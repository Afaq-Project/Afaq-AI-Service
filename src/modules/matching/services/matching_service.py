import asyncio
import logging
from typing import Any
from uuid import UUID, uuid4

from src.modules.core.database.repositories.match_score_repository import (
    MatchScoreRepository,
)
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)
from src.modules.infrastructure.webhook.webhook_client import (
    MatchingCompletePayload,
    WebhookClient,
)
from src.modules.matching.services.feed_ranker import FeedRanker
from src.modules.matching.services.hard_filter_service import HardFilterService
from src.modules.matching.services.lifecycle_service import is_within_visibility_window
from src.modules.matching.services.match_calculator import MatchCalculator
from src.modules.matching.services.user_profile_reader import UserProfileReader

logger = logging.getLogger(__name__)


class UserNotFoundError(Exception):
    """Raised when a specified user profile does not exist."""


class OpportunityNotFoundError(Exception):
    """Raised when a specified opportunity does not exist."""


class RematchAlreadyRunningError(Exception):
    """Raised when a full rematch operation is already in progress."""


def _to_opportunity_dict(opp: Any) -> dict[str, Any]:
    """Converts a database model or dictionary opportunity to a standard dict."""
    if isinstance(opp, dict):
        return opp
    if hasattr(opp, "model_dump") and callable(opp.model_dump):
        return opp.model_dump()
    if hasattr(opp, "dict") and callable(opp.dict):
        return opp.dict()
    if hasattr(opp, "__dict__"):
        return {k: v for k, v in opp.__dict__.items() if not k.startswith("_")}
    return dict(opp)


class MatchingService:
    """Orchestrates matching calculations, database persistence, and webhook notifications."""

    def __init__(
        self,
        profile_reader: UserProfileReader,
        opportunity_repo: OpportunityRepository,
        match_score_repo: MatchScoreRepository,
        webhook_client: WebhookClient | None = None,
        feed_ranker: FeedRanker | None = None,
        match_calculator: MatchCalculator | None = None,
        hard_filter_service: HardFilterService | None = None,
    ) -> None:
        self._profile_reader = profile_reader
        self._opportunity_repo = opportunity_repo
        self._match_score_repo = match_score_repo
        self._webhook_client = webhook_client
        self._calc = match_calculator or MatchCalculator()
        self._filter = hard_filter_service or HardFilterService()
        self._ranker = feed_ranker or FeedRanker(
            match_calculator=self._calc, hard_filter_service=self._filter
        )
        self._rematch_lock = asyncio.Lock()

    @property
    def is_rematch_running(self) -> bool:
        """Returns True if a full rematch job is currently executing."""
        return self._rematch_lock.locked()

    async def match_user(self, user_id: str | UUID) -> dict[str, Any]:
        """Matches a single user against all active/visible opportunities and persists results."""
        user_uuid_str = str(user_id)

        # 1. Retrieve user profile
        profile = await self._profile_reader.get_profile_by_user_id(user_uuid_str)
        if profile is None:
            logger.warning("User profile not found for user_id: %s", user_uuid_str)
            raise UserNotFoundError(
                f"User profile not found for user_id: {user_uuid_str}"
            )

        # 2. Retrieve active opportunities within visibility window
        raw_opps = await self._opportunity_repo.find_within_visibility_window()
        opportunities = [_to_opportunity_dict(opp) for opp in raw_opps]

        # 3. Evaluate and rank opportunities using existing FeedRanker
        ranking_result = self._ranker.rank_opportunities(
            user_profile=profile,
            opportunities=opportunities,
            filter_hard_eligibility=True,
            enable_relaxation=True,
        )

        # 4. Prepare and persist match scores
        scores_to_persist: list[dict[str, Any]] = []
        for ranked in ranking_result.ranked_opportunities:
            opp_dict = ranked.opportunity
            opp_id = str(opp_dict.get("id") or opp_dict.get("opportunity_id") or "")
            if not opp_id:
                continue

            scores_to_persist.append(
                {
                    "user_id": user_uuid_str,
                    "opportunity_id": opp_id,
                    "score_pct": int(round(ranked.match_score.total_score)),
                    "score_breakdown": ranked.match_score.model_dump(),
                    "calculation_version": 1,
                }
            )

        persisted_count = 0
        if scores_to_persist:
            persisted_count = await self._match_score_repo.upsert_many_scores(
                scores_to_persist
            )

        # 5. Dispatch Webhook Notification
        operation_id = str(uuid4())
        if self._webhook_client:
            payload = MatchingCompletePayload(
                operation_type="user_matching",
                operation_id=operation_id,
                user_id=user_uuid_str,
                matches_count=persisted_count,
                status="success",
                metadata={
                    "total_evaluated": ranking_result.total_evaluated,
                    "total_eligible": ranking_result.total_eligible,
                    "is_preliminary": ranking_result.is_preliminary,
                    "is_relaxed": ranking_result.is_relaxed,
                },
            )
            await self._webhook_client.notify_matching_complete(payload)

        return {
            "status": "success",
            "operation_id": operation_id,
            "user_id": user_uuid_str,
            "matches_count": persisted_count,
            "total_evaluated": ranking_result.total_evaluated,
            "total_eligible": ranking_result.total_eligible,
            "is_preliminary": ranking_result.is_preliminary,
        }

    async def match_opportunity(self, opportunity_id: str | UUID) -> dict[str, Any]:
        """Matches a single newly discovered opportunity against all relevant users and persists results."""
        opp_uuid_str = str(opportunity_id)

        # 1. Retrieve the opportunity
        raw_opp = await self._opportunity_repo.get_cleaned_by_id(opp_uuid_str)
        if raw_opp is None:
            logger.warning("Opportunity not found for opportunity_id: %s", opp_uuid_str)
            raise OpportunityNotFoundError(
                f"Opportunity not found for opportunity_id: {opp_uuid_str}"
            )

        opp_dict = _to_opportunity_dict(raw_opp)

        # Verify visibility window
        deadline = opp_dict.get("deadline")
        if not is_within_visibility_window(deadline=deadline):
            logger.info(
                "Opportunity %s is outside active visibility window; skipping matching",
                opp_uuid_str,
            )
            return {
                "status": "skipped",
                "opportunity_id": opp_uuid_str,
                "reason": "outside_visibility_window",
                "users_evaluated": 0,
                "matches_persisted": 0,
            }

        # 2. Iterate through user profiles in batches to avoid high memory consumption
        batch_size = 100
        offset = 0
        total_users_evaluated = 0
        scores_to_persist: list[dict[str, Any]] = []

        while True:
            users_batch = await self._profile_reader.get_all_profiles(
                limit=batch_size, offset=offset
            )
            if not users_batch:
                break

            for user_profile in users_batch:
                user_id_str = (
                    str(user_profile.user_id) if user_profile.user_id else None
                )
                if not user_id_str:
                    continue

                total_users_evaluated += 1

                # Evaluate hard filter eligibility
                is_eligible = self._filter.evaluate(user_profile, opp_dict)
                if not is_eligible:
                    continue

                # Calculate match score
                score_result = self._calc.calculate_match_score(user_profile, opp_dict)
                scores_to_persist.append(
                    {
                        "user_id": user_id_str,
                        "opportunity_id": opp_uuid_str,
                        "score_pct": int(round(score_result.total_score)),
                        "score_breakdown": score_result.model_dump(),
                        "calculation_version": 1,
                    }
                )

            offset += batch_size

        # 3. Persist matching scores
        persisted_count = 0
        if scores_to_persist:
            persisted_count = await self._match_score_repo.upsert_many_scores(
                scores_to_persist
            )

        # 4. Dispatch Webhook Notification
        operation_id = str(uuid4())
        if self._webhook_client:
            payload = MatchingCompletePayload(
                operation_type="opportunity_matching",
                operation_id=operation_id,
                opportunity_id=opp_uuid_str,
                matches_count=persisted_count,
                status="success",
                metadata={"users_evaluated": total_users_evaluated},
            )
            await self._webhook_client.notify_matching_complete(payload)

        return {
            "status": "success",
            "operation_id": operation_id,
            "opportunity_id": opp_uuid_str,
            "users_evaluated": total_users_evaluated,
            "matches_persisted": persisted_count,
        }

    async def full_rematch(self, batch_size: int = 100) -> dict[str, Any]:
        """Performs full rematching across all users and active opportunities in batches."""
        if self._rematch_lock.locked():
            logger.warning("Full rematch operation is already in progress.")
            raise RematchAlreadyRunningError(
                "A full rematch operation is already running."
            )

        async with self._rematch_lock:
            operation_id = str(uuid4())
            logger.info("Starting full rematch operation %s", operation_id)

            # 1. Fetch all active opportunities within visibility window
            raw_opps = await self._opportunity_repo.find_within_visibility_window()
            opportunities = [_to_opportunity_dict(opp) for opp in raw_opps]

            offset = 0
            total_users_processed = 0
            total_matches_persisted = 0

            while True:
                users_batch = await self._profile_reader.get_all_profiles(
                    limit=batch_size, offset=offset
                )
                if not users_batch:
                    break

                batch_scores: list[dict[str, Any]] = []
                for user_profile in users_batch:
                    user_id_str = (
                        str(user_profile.user_id) if user_profile.user_id else None
                    )
                    if not user_id_str:
                        continue

                    total_users_processed += 1
                    ranking = self._ranker.rank_opportunities(
                        user_profile=user_profile,
                        opportunities=opportunities,
                        filter_hard_eligibility=True,
                        enable_relaxation=True,
                    )

                    for ranked in ranking.ranked_opportunities:
                        opp_dict = ranked.opportunity
                        opp_id = str(
                            opp_dict.get("id") or opp_dict.get("opportunity_id") or ""
                        )
                        if not opp_id:
                            continue

                        batch_scores.append(
                            {
                                "user_id": user_id_str,
                                "opportunity_id": opp_id,
                                "score_pct": int(round(ranked.match_score.total_score)),
                                "score_breakdown": ranked.match_score.model_dump(),
                                "calculation_version": 1,
                            }
                        )

                if batch_scores:
                    count = await self._match_score_repo.upsert_many_scores(
                        batch_scores
                    )
                    total_matches_persisted += count

                offset += batch_size

            # 2. Dispatch Webhook Notification
            if self._webhook_client:
                payload = MatchingCompletePayload(
                    operation_type="full_rematch",
                    operation_id=operation_id,
                    matches_count=total_matches_persisted,
                    status="success",
                    metadata={
                        "users_processed": total_users_processed,
                        "opportunities_processed": len(opportunities),
                    },
                )
                await self._webhook_client.notify_matching_complete(payload)

            logger.info(
                "Full rematch operation %s completed: %d users, %d opportunities, %d matches persisted",
                operation_id,
                total_users_processed,
                len(opportunities),
                total_matches_persisted,
            )

            return {
                "status": "success",
                "operation_id": operation_id,
                "users_processed": total_users_processed,
                "opportunities_processed": len(opportunities),
                "matches_persisted": total_matches_persisted,
            }
