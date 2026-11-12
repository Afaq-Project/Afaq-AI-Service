# [OMA-W005-T018] PrioritizationService: Multi-source dynamic scoring and domain interleaving

import logging
import urllib.parse
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# [OMA-W005-T018] Scoring weight constants for priority calculation formula
# [OMA-W006-T003] Correct priority scoring weights to match FR-007
DEFAULT_BASE_PRIORITY_WEIGHT: float = 100.0
DEFAULT_DAYS_SINCE_SCRAPE_WEIGHT: float = 1.0
DEFAULT_CONSECUTIVE_FAILURES_PENALTY: float = 10.0
DEFAULT_UNSCRAPED_DAYS: float = 30.0
MANUAL_OVERRIDE_PRIORITY_BONUS: float = 10000.0


# [OMA-W005-T018] Dynamic multi-source prioritization and domain interleaving engine
class PrioritizationService:
    """Prioritizes scraping candidate sources and interleaves domains.

    Enforces:
      - Dynamic scoring formula (FR-007):
          priority_score = (base_priority * 100.0) + (days_since_last_scrape * 1.0) - (consecutive_failures * 10.0)
      - P0 administrative manual overrides ("Scrape Now")
      - Domain interleaving: round-robin selection ensuring adjacent queued items never target the same domain
    """

    def __init__(
        self,
        base_priority_weight: float = DEFAULT_BASE_PRIORITY_WEIGHT,
        days_since_scrape_weight: float = DEFAULT_DAYS_SINCE_SCRAPE_WEIGHT,
        consecutive_failures_penalty: float = DEFAULT_CONSECUTIVE_FAILURES_PENALTY,
        unscraped_days_default: float = DEFAULT_UNSCRAPED_DAYS,
    ) -> None:
        self.base_priority_weight = base_priority_weight
        self.days_since_scrape_weight = days_since_scrape_weight
        self.consecutive_failures_penalty = consecutive_failures_penalty
        self.unscraped_days_default = unscraped_days_default

    # [OMA-W005-T018] Primary priority score calculation formula
    # [OMA-W006-T003] Calculate priority score matching FR-007
    @classmethod
    def calculate_priority_score(
        cls,
        base_priority: float = 1.0,
        days_since_last_scrape: float = 0.0,
        consecutive_failures: int = 0,
        *,
        base_weight: float = DEFAULT_BASE_PRIORITY_WEIGHT,
        days_weight: float = DEFAULT_DAYS_SINCE_SCRAPE_WEIGHT,
        failures_penalty: float = DEFAULT_CONSECUTIVE_FAILURES_PENALTY,
    ) -> float:
        """Calculates dynamic priority score for a target source.

        Formula (FR-007):
            priority_score = (base_priority * 100.0) + (days_since_last_scrape * 1.0) - (consecutive_failures * 10.0)
        """
        score = (
            (float(base_priority) * base_weight)
            + (float(days_since_last_scrape) * days_weight)
            - (float(consecutive_failures) * failures_penalty)
        )
        return score

    # [OMA-W005-T018] Extract normalized domain name from source object, dict, or URL
    @classmethod
    def extract_domain(cls, source: Any) -> str:
        """Extracts and normalizes the target hostname/domain from a source item.

        Handles:
          - Prisma Source model (with optional .config)
          - SourceConfig model
          - Dict containing 'domain', 'url', or nested 'config'
          - Raw URL string
        """
        if not source:
            return "unknown_domain"

        # If source is raw string (URL or domain)
        if isinstance(source, str):
            raw_str = source.strip()
            if "://" in raw_str:
                hostname = urllib.parse.urlsplit(raw_str).hostname or ""
            else:
                hostname = raw_str.split("/")[0].split(":")[0]
            norm = hostname.lower()
            if norm.startswith("www."):
                norm = norm[4:]
            return norm or "unknown_domain"

        # If source is a dictionary
        if isinstance(source, dict):
            if source.get("domain"):
                return cls.extract_domain(str(source["domain"]))
            if source.get("config") and isinstance(source["config"], dict):
                cfg_domain = source["config"].get("domain")
                if cfg_domain:
                    return cls.extract_domain(str(cfg_domain))
            if source.get("url"):
                return cls.extract_domain(str(source["url"]))
            return "unknown_domain"

        # If source is an object (Prisma model or Pydantic model)
        domain_attr = getattr(source, "domain", None)
        if domain_attr:
            return cls.extract_domain(str(domain_attr))

        config_attr = getattr(source, "config", None)
        if config_attr:
            cfg_domain = getattr(config_attr, "domain", None)
            if cfg_domain:
                return cls.extract_domain(str(cfg_domain))

        url_attr = getattr(source, "url", None)
        if url_attr:
            return cls.extract_domain(str(url_attr))

        return "unknown_domain"

    # [OMA-W005-T018] Calculate source score based on operational attributes
    def score_source(
        self,
        source: Any,
        now: datetime | None = None,
        is_manual_override: bool = False,
    ) -> float:
        """Computes priority score for a given source object or dict."""
        current_time = now or datetime.now(UTC)

        # [OMA-W006-T003] Remove unused default assignment to base_priority
        consecutive_failures = 0
        last_scraped_at: datetime | None = None

        if isinstance(source, dict):
            base_priority = float(source.get("base_priority", 1.0))
            consecutive_failures = int(source.get("consecutive_failures", 0))
            last_scraped_at = source.get("last_scraped_at")
            if source.get("config") and isinstance(source["config"], dict):
                cfg = source["config"]
                consecutive_failures = int(
                    cfg.get("consecutive_failures", consecutive_failures)
                )
                last_scraped_at = cfg.get("last_scraped_at", last_scraped_at)
        else:
            base_priority = float(getattr(source, "base_priority", 1.0))
            config = getattr(source, "config", None)
            if config:
                consecutive_failures = int(
                    getattr(config, "consecutive_failures", 0) or 0
                )
                last_scraped_at = getattr(config, "last_scraped_at", None)
            else:
                consecutive_failures = int(
                    getattr(source, "consecutive_failures", 0) or 0
                )
                last_scraped_at = getattr(source, "last_scraped_at", None)

        if last_scraped_at is None:
            days_since_scrape = self.unscraped_days_default
        else:
            if last_scraped_at.tzinfo is None:
                last_scraped_at = last_scraped_at.replace(tzinfo=UTC)
            elapsed_seconds = (current_time - last_scraped_at).total_seconds()
            days_since_scrape = max(0.0, elapsed_seconds / 86400.0)

        raw_score = self.calculate_priority_score(
            base_priority=base_priority,
            days_since_last_scrape=days_since_scrape,
            consecutive_failures=consecutive_failures,
            base_weight=self.base_priority_weight,
            days_weight=self.days_since_scrape_weight,
            failures_penalty=self.consecutive_failures_penalty,
        )

        if is_manual_override:
            raw_score += MANUAL_OVERRIDE_PRIORITY_BONUS

        return raw_score

    # [OMA-W005-T018] Interleave items across domains round-robin without adjacent duplicates
    @classmethod
    def interleave_domains(
        cls,
        items: Sequence[T],
        domain_extractor: Callable[[T], str] | None = None,
    ) -> list[T]:
        """Interleaves items round-robin by domain so adjacent queued items never target the same domain.

        Maintains priority order within each domain while ensuring host politeness.
        """
        if not items:
            return []

        if len(items) <= 1:
            return list(items)

        extractor = domain_extractor or cls.extract_domain

        # Group items preserving order
        domain_queues: dict[str, deque[T]] = defaultdict(deque)
        for item in items:
            domain = extractor(item)
            domain_queues[domain].append(item)

        # If only one domain exists, no interleaving is possible
        if len(domain_queues) == 1:
            return list(items)

        interleaved: list[T] = []
        last_domain: str | None = None

        total_items = len(items)
        while len(interleaved) < total_items:
            # Find eligible domains (domains with items remaining, excluding last_domain if alternatives exist)
            eligible_domains = [
                d for d, q in domain_queues.items() if len(q) > 0 and d != last_domain
            ]

            if not eligible_domains:
                # If only the last_domain has items left, we must pick it
                eligible_domains = [d for d, q in domain_queues.items() if len(q) > 0]

            if not eligible_domains:
                break

            # Pick the domain with the largest remaining queue or first in rotation
            chosen_domain = max(eligible_domains, key=lambda d: len(domain_queues[d]))

            item = domain_queues[chosen_domain].popleft()
            interleaved.append(item)
            last_domain = chosen_domain

        return interleaved

    # [OMA-W005-T018] Master prioritization method: score, sort, and interleave candidate sources
    def prioritize_sources(
        self,
        sources: Sequence[Any],
        manual_source_ids: Sequence[str] | None = None,
        now: datetime | None = None,
    ) -> list[Any]:
        """Calculates dynamic scores, sorts, and interleaves candidate sources.

        Manual source IDs are treated as P0 overrides and guaranteed top priority.
        """
        if not sources:
            return []

        manual_set = set(str(s) for s in (manual_source_ids or []))

        # Helper to extract source ID
        def get_id(src: Any) -> str:
            if isinstance(src, dict):
                return str(src.get("id") or src.get("source_id", ""))
            return str(getattr(src, "id", "") or getattr(src, "source_id", ""))

        scored_sources: list[tuple[float, Any]] = []
        for src in sources:
            src_id = get_id(src)
            is_manual = src_id in manual_set if manual_set else False
            score = self.score_source(src, now=now, is_manual_override=is_manual)
            scored_sources.append((score, src))

        # Sort descending by priority score
        scored_sources.sort(key=lambda pair: pair[0], reverse=True)
        sorted_sources = [pair[1] for pair in scored_sources]

        # Interleave domains round-robin
        return self.interleave_domains(
            sorted_sources, domain_extractor=self.extract_domain
        )
