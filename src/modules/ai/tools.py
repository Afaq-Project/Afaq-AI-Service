import asyncio
import json
import logging
from asyncio import AbstractEventLoop
from collections.abc import Callable, Coroutine
from typing import Any

from src.modules.core.database.repositories.match_score_repository import (
    MatchScoreRepository,
)
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)

from .context import build_opportunity_context

logger = logging.getLogger(__name__)

NOT_FOUND = "No matching record was found."
NO_RESULTS = "No opportunities matched this search."
TOOL_FAILED = "This lookup is unavailable right now."


def _summarize(opportunity: Any) -> str:
    deadline = getattr(opportunity, "deadline", None)
    parts = [
        str(getattr(opportunity, "title", "")).strip(),
        f"type={getattr(opportunity, 'opportunity_type', None) or '-'}",
        f"country={getattr(opportunity, 'country', None) or '-'}",
        f"funding={getattr(opportunity, 'funding_type', None) or '-'}",
        f"deadline={deadline.date().isoformat() if deadline else '-'}",
        f"id={getattr(opportunity, 'id', '')}",
    ]
    return " | ".join(parts)


def _breakdown(score: Any) -> str:
    raw = getattr(score, "score_breakdown", None)
    if not raw:
        return "-"
    try:
        return json.dumps(raw, ensure_ascii=False, sort_keys=True)[:600]
    except (TypeError, ValueError):
        return str(raw)[:600]


def build_chat_tools(
    *,
    user_id: str,
    opportunities: OpportunityRepository,
    matches: MatchScoreRepository,
    loop: AbstractEventLoop,
    timeout: float = 20.0,
) -> list[Callable[..., str]]:
    def run(coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)

    def search_opportunities(
        query: str = "",
        opportunity_type: str = "",
        country: str = "",
        funding_type: str = "",
        study_level: str = "",
        limit: int = 5,
    ) -> str:
        """Search the opportunities catalogue by keyword and optional filters.

        Only opportunities that are still open, or whose deadline passed within the
        last 30 days, are returned. Use it when the student asks about opportunities
        other than the one being discussed.

        Args:
            query: Free text matched against title, description and organization.
            opportunity_type: scholarship, internship, fellowship, training, grant, …
            country: Country name, for example Turkey.
            funding_type: fully_funded, partially_funded or unfunded.
            study_level: Bachelor, Master, PhD, Diploma, …
            limit: Maximum number of results, at most 20.
        """
        try:
            found = run(
                opportunities.search_visible(
                    query=query,
                    opportunity_type=opportunity_type or None,
                    country=country or None,
                    funding_type=funding_type or None,
                    study_level=study_level or None,
                    limit=limit,
                )
            )
        except Exception as exc:
            logger.warning("search_opportunities failed: %s", exc)
            return TOOL_FAILED

        if not found:
            return NO_RESULTS
        return "\n".join(
            f"{index}. {_summarize(item)}" for index, item in enumerate(found, start=1)
        )

    def get_opportunity_details(opportunity_id: str) -> str:
        """Return the full stored details of one opportunity by its id.

        Use it after search_opportunities when the student asks about a specific
        result, or to check a field of the opportunity under discussion.

        Args:
            opportunity_id: The opportunity id as returned by search_opportunities.
        """
        try:
            record = run(opportunities.get_cleaned_by_id(opportunity_id))
        except Exception as exc:
            logger.warning("get_opportunity_details failed: %s", exc)
            return TOOL_FAILED

        if record is None or getattr(record, "status", None) != "cleaned":
            return NOT_FOUND
        return build_opportunity_context(record)

    def get_my_match_score(opportunity_id: str) -> str:
        """Return the match score of the student you are serving for one opportunity.

        The score belongs to the current student only; it is not possible to read
        another person's scores.

        Args:
            opportunity_id: The opportunity id to look up.
        """
        try:
            score = run(matches.get_for_user(user_id, opportunity_id))
        except Exception as exc:
            logger.warning("get_my_match_score failed: %s", exc)
            return TOOL_FAILED

        if score is None:
            return "No match score has been calculated for this opportunity yet."
        return (
            f"score={getattr(score, 'score_pct', '-')}% | "
            f"calculated_at={getattr(score, 'calculated_at', '-')} | "
            f"breakdown={_breakdown(score)}"
        )

    def get_my_top_matches(limit: int = 5) -> str:
        """Return the best matching opportunities for the student you are serving.

        The list is personal to the current student and ordered by score.

        Args:
            limit: Maximum number of results, at most 20.
        """
        try:
            scores = run(matches.top_for_user(user_id, limit))
        except Exception as exc:
            logger.warning("get_my_top_matches failed: %s", exc)
            return TOOL_FAILED

        if not scores:
            return "No match scores have been calculated for this student yet."

        lines = []
        for index, score in enumerate(scores, start=1):
            opportunity = getattr(score, "opportunity", None)
            title = getattr(opportunity, "title", None) or getattr(
                score, "opportunity_id", ""
            )
            lines.append(
                f"{index}. {title} | score={getattr(score, 'score_pct', '-')}% | "
                f"id={getattr(score, 'opportunity_id', '')}"
            )
        return "\n".join(lines)

    return [
        search_opportunities,
        get_opportunity_details,
        get_my_match_score,
        get_my_top_matches,
    ]
