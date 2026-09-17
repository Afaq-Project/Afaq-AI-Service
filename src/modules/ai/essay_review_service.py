import logging
import re

from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)
from src.modules.infrastructure.llm.anthropic_client import StructuredGenerator

from .constants import Locale
from .exceptions import OpportunityNotFoundError
from .models import EssayPoint, EssayReview, EssayType
from .prompts import build_essay_review_prompt, build_essay_review_system_prompt

logger = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().casefold()


def _verified(points: list[EssayPoint], essay: str) -> list[EssayPoint]:
    return [
        (
            point
            if point.evidence and _normalize(point.evidence) in essay
            else point.model_copy(update={"evidence": None})
        )
        for point in points
    ]


def drop_unverified_evidence(review: EssayReview, essay_text: str) -> EssayReview:
    essay = _normalize(essay_text)
    return review.model_copy(
        update={
            "strengths": _verified(review.strengths, essay),
            "weaknesses": _verified(review.weaknesses, essay),
        }
    )


class EssayReviewService:

    def __init__(
        self,
        llm: StructuredGenerator,
        opportunities: OpportunityRepository,
    ) -> None:
        self._llm = llm
        self._opportunities = opportunities

    async def review(
        self,
        *,
        user_id: str,
        essay_text: str,
        essay_type: EssayType,
        locale: Locale = "ar",
        opportunity_id: str | None = None,
    ) -> EssayReview:
        opportunity = None
        if opportunity_id is not None:
            opportunity = await self._opportunities.get_cleaned_by_id(opportunity_id)
            if opportunity is None:
                raise OpportunityNotFoundError(opportunity_id)

        completion = await self._llm.generate(
            system=build_essay_review_system_prompt(locale),
            prompt=build_essay_review_prompt(essay_text, essay_type, opportunity),
            output_type=EssayReview,
        )
        logger.info(
            "Essay review for user %s: type=%s chars=%d model=%s in=%d out=%d latency=%dms",
            user_id,
            essay_type,
            len(essay_text),
            completion.model,
            completion.input_tokens,
            completion.output_tokens,
            completion.latency_ms,
        )

        review = drop_unverified_evidence(completion.output, essay_text)
        if opportunity is None:
            review = review.model_copy(update={"fit_with_opportunity": None})
        return review
