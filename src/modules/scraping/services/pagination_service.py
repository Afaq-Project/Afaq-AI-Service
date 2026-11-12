# [OMA-W005-T011] PaginationService: dynamic catalog pagination, fingerprinting, and termination controls

import hashlib
import logging
import re
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.modules.scraping.exceptions import (
    ERR_PAGINATION_LOOP_DETECTED,
    PaginationLoopDetectedError,
)
from src.modules.scraping.models import PaginationType

logger = logging.getLogger(__name__)


# [OMA-W005-T011] Data structure capturing evaluation result of a pagination step
@dataclass
class PaginationStepResult:
    """Outcome of evaluating a single catalog pagination step."""

    current_url: str
    next_url: str | None
    is_terminated: bool
    termination_signal: str | None
    page_fingerprint: str
    card_count: int
    new_card_count: int
    consecutive_existing_pages: int
    details: dict[str, Any] = field(default_factory=dict)


# [OMA-W005-T011] Stateful tracker for catalog pagination traversal across pages
@dataclass
class PaginationState:
    """Stateful container tracking progress, visited URLs, and fingerprints."""

    initial_url: str
    current_page: int = 1
    visited_urls: set[str] = field(default_factory=set)
    seen_fingerprints: list[str] = field(default_factory=list)
    consecutive_existing_pages: int = 0
    is_terminated: bool = False
    termination_signal: str | None = None
    known_card_ids: set[str] = field(default_factory=set)
    history: list[PaginationStepResult] = field(default_factory=list)


# [OMA-W007-T004] Data structure for pagination step options (Sonar Rule S107)
@dataclass
class PaginationStepOptions:
    current_url: str = ""
    status_code: int = 200
    card_identifiers: list[str] | None = None
    pagination_type: str = "auto"
    pagination_config: dict[str, Any] | None = None
    incremental_cutoff_enabled: bool = True
    custom_selector: str | None = None
    query_param: str | None = None
    path_template: str | None = None
    page_num: int = 1
    page_size: int = 10
    max_lookahead_steps: int = 2
    lookahead_consecutive_zero_threshold: int = 2
    same_domain_only: bool = True
    max_pages: int = 100


def _build_step_options_from_kwargs(kwargs: dict[str, Any]) -> PaginationStepOptions:
    raw_cards = kwargs.get("cards")
    raw_card_ids = kwargs.get("card_identifiers")
    if raw_card_ids is not None:
        parsed_card_ids = list(raw_card_ids)
    elif raw_cards is not None:
        parsed_card_ids = list(raw_cards)
    else:
        parsed_card_ids = None

    raw_pag_type = kwargs.get("pagination_type")
    if raw_pag_type is None:
        effective_pag_type = "url_param"
    elif hasattr(raw_pag_type, "value"):
        effective_pag_type = str(raw_pag_type.value)
    else:
        effective_pag_type = str(raw_pag_type)

    if (
        "incremental_cutoff_enabled" in kwargs
        and kwargs["incremental_cutoff_enabled"] is not None
    ):
        inc_cutoff = bool(kwargs["incremental_cutoff_enabled"])
    elif "is_chronological" in kwargs and kwargs["is_chronological"] is not None:
        inc_cutoff = bool(kwargs["is_chronological"])
    else:
        inc_cutoff = True

    return PaginationStepOptions(
        current_url=kwargs.get("current_url") or kwargs.get("page_url") or "",
        status_code=kwargs.get("status_code", 200),
        card_identifiers=parsed_card_ids,
        pagination_type=effective_pag_type,
        pagination_config=kwargs.get("pagination_config"),
        incremental_cutoff_enabled=inc_cutoff,
        custom_selector=kwargs.get("custom_selector")
        or kwargs.get("next_button_selector"),
        query_param=kwargs.get("query_param"),
        path_template=kwargs.get("path_template"),
        page_num=kwargs.get("page_num", 1),
        page_size=kwargs.get("page_size", 10),
        max_lookahead_steps=kwargs.get("max_lookahead_steps", 2),
        lookahead_consecutive_zero_threshold=kwargs.get(
            "lookahead_consecutive_zero_threshold", 2
        ),
        same_domain_only=kwargs.get("same_domain_only", True),
        max_pages=kwargs.get("max_pages", 100),
    )


def _resolve_next_button_href(
    next_button_href: str | None, selector: str | None, html: str | None
) -> str | None:
    if next_button_href or not selector or not html:
        return next_button_href
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        el = soup.select_one(selector)
        if el and el.name == "a" and el.get("href"):
            return str(el["href"])
    except Exception:
        pass
    return None


# [OMA-W005-T011] PaginationService dynamic catalog traversal engine
class PaginationService:
    """Dynamic catalog pagination engine handling query params, path segments, and next-button selectors.

    Enforces 5 termination signals:
      1. Empty page (0 cards found)
      2. HTTP error status (404/410/500/etc.)
      3. Same-URL redirect loop
      4. Content duplicate loop (identical SHA-256 card fingerprint)
      5. 2-page lookahead cutoff (2 consecutive pages yielding 0 new unvisited cards)
    """

    # [OMA-W005-T011] Calculate SHA-256 fingerprint from card identifiers
    @classmethod
    def calculate_page_fingerprint(cls, card_identifiers: Sequence[str]) -> str:
        """Computes a SHA-256 fingerprint of normalized card titles or URLs.

        Normalizes strings by stripping whitespace and lowercasing to avoid
        spurious differences caused by formatting or casing.
        """
        if not card_identifiers:
            return hashlib.sha256(b"").hexdigest()

        normalized = [c.strip().lower() for c in card_identifiers if c and c.strip()]
        if not normalized:
            return hashlib.sha256(b"").hexdigest()

        joined_payload = "|".join(normalized)
        return hashlib.sha256(joined_payload.encode("utf-8")).hexdigest()

    # [OMA-W005-T011] Detect duplicate or circular pagination loops via card fingerprints
    @classmethod
    def detect_fingerprint_loop(
        cls,
        current_fingerprint: str,
        seen_fingerprints: Sequence[str],
        raise_on_loop: bool = False,
    ) -> tuple[bool, str | None]:
        """Detects circular or stagnant card content loops.

        - Stagnant loop: current fingerprint matches the immediately previous page.
        - Circular loop: current fingerprint matches the first page or any seen page.
        """
        if not seen_fingerprints or not current_fingerprint:
            return False, None

        # Stagnant loop check (matches immediately preceding page)
        if current_fingerprint == seen_fingerprints[-1]:
            reason = "stagnant"
            logger.warning(
                "Stagnant pagination loop detected: fingerprint %s identical to previous page",
                current_fingerprint,
            )
            if raise_on_loop:
                raise PaginationLoopDetectedError(
                    f"Stagnant pagination loop detected (fingerprint {current_fingerprint})",
                    code=ERR_PAGINATION_LOOP_DETECTED,
                    details={
                        "loop_type": reason,
                        "fingerprint": current_fingerprint,
                    },
                )
            return True, reason

        # Circular loop check (matches first page or previously seen page in history)
        if current_fingerprint in seen_fingerprints:
            reason = "circular"
            logger.warning(
                "Circular pagination loop detected: fingerprint %s matches previous page in history",
                current_fingerprint,
            )
            if raise_on_loop:
                raise PaginationLoopDetectedError(
                    f"Circular pagination loop detected (fingerprint {current_fingerprint})",
                    code=ERR_PAGINATION_LOOP_DETECTED,
                    details={
                        "loop_type": reason,
                        "fingerprint": current_fingerprint,
                    },
                )
            return True, reason

        return False, None

    # [OMA-W005-T011] Update lookahead counter based on newly discovered cards
    @classmethod
    def advance_lookahead(
        cls,
        current_cards: Sequence[str],
        known_card_ids: set[str] | Sequence[str],
        consecutive_existing_pages: int = 0,
        cutoff_threshold: int = 2,
    ) -> tuple[int, int, bool]:
        """Evaluates lookahead progression.

        Returns (new_cards_count, new_consecutive_existing_pages, is_cutoff_reached).
        """
        known_set = (
            set(known_card_ids)
            if not isinstance(known_card_ids, set)
            else known_card_ids
        )
        total_cards = len(current_cards)
        if total_cards == 0:
            return 0, consecutive_existing_pages, False

        new_cards_count = sum(1 for c in current_cards if c.strip() not in known_set)

        if new_cards_count == 0:
            new_consecutive = consecutive_existing_pages + 1
            is_cutoff = new_consecutive >= cutoff_threshold
            if is_cutoff:
                logger.info(
                    "Lookahead cutoff reached: %d consecutive pages with 0 new cards",
                    new_consecutive,
                )
            return new_cards_count, new_consecutive, is_cutoff

        # Found at least one new card, reset counter
        return new_cards_count, 0, False

    # [OMA-W005-T011] Query parameter pagination builder (?page=N, ?p=N)
    @classmethod
    def build_query_param_url(
        cls,
        current_url: str,
        param_name: str = "page",
        current_page: int = 1,
        step: int = 1,
    ) -> str:
        """Constructs next URL by incrementing or adding a pagination query parameter."""
        parsed = urllib.parse.urlsplit(current_url)
        query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)

        found = False
        new_params: list[tuple[str, str]] = []
        for k, v in query_params:
            if k.lower() == param_name.lower():
                found = True
                try:
                    val = int(v)
                    next_val = val + step
                except ValueError:
                    next_val = current_page + step
                new_params.append((k, str(next_val)))
            else:
                new_params.append((k, v))

        if not found:
            next_val = current_page + step
            new_params.append((param_name, str(next_val)))

        new_query = urllib.parse.urlencode(new_params)
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
        )

    # [OMA-W005-T011] Path segment pagination builder (/page/N/)
    @classmethod
    def build_path_segment_url(
        cls,
        current_url: str,
        current_page: int = 1,
        step: int = 1,
        pattern: str | None = None,
    ) -> str:
        """Constructs next URL by incrementing or inserting a path segment (e.g. /page/2/)."""
        parsed = urllib.parse.urlsplit(current_url)
        path = parsed.path or "/"

        next_page = current_page + step

        # Check common patterns in path: /page/N/, /p/N/, /page/N
        match = re.search(r"/(page|p)/(\d+)(/)?", path, flags=re.IGNORECASE)
        if match:
            seg_name = match.group(1)
            trailing_slash = match.group(3) or ""
            try:
                found_page = int(match.group(2))
                next_val = found_page + step
            except ValueError:
                next_val = next_page
            replacement = f"/{seg_name}/{next_val}{trailing_slash}"
            new_path = path[: match.start()] + replacement + path[match.end() :]
        elif pattern and "{page}" in pattern:
            formatted_segment = pattern.replace("{page}", str(next_page))
            if not formatted_segment.startswith("/"):
                formatted_segment = "/" + formatted_segment
            # Strip trailing slash from path before appending if segment has leading slash
            base_path = path.rstrip("/")
            new_path = f"{base_path}{formatted_segment}"
        else:
            # Default fallback: append /page/{next_page}/
            base_path = path.rstrip("/")
            new_path = f"{base_path}/page/{next_page}/"

        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment)
        )

    # [OMA-W005-T011] Next-button selector pagination URL resolver
    @classmethod
    def build_next_button_url(
        cls,
        current_url: str,
        next_button_href: str | None,
    ) -> str | None:
        """Resolves next button href against current URL, returning None if absent or invalid."""
        if not next_button_href:
            return None

        clean_href = next_button_href.strip()
        if not clean_href or clean_href.startswith("javascript:") or clean_href == "#":
            return None

        return urllib.parse.urljoin(current_url, clean_href)

    # [OMA-W005-T011] Unified next URL dispatcher across all pagination mechanisms
    @classmethod
    def build_next_url(
        cls,
        current_url: str,
        pagination_type: str | PaginationType = "url_param",
        pagination_config: dict[str, Any] | None = None,
        current_page: int = 1,
        next_button_href: str | None = None,
        step: int = 1,
    ) -> str | None:
        """Computes next page URL based on configured pagination mechanism."""
        config = pagination_config or {}
        p_type = (
            pagination_type.value
            if isinstance(pagination_type, PaginationType)
            else str(pagination_type).lower()
        )

        if p_type in ("url_param", "query_param", "query"):
            param_name = config.get("param_name") or config.get("param") or "page"
            return cls.build_query_param_url(
                current_url=current_url,
                param_name=param_name,
                current_page=current_page,
                step=step,
            )

        if p_type in ("path_segment", "path", "url_path"):
            pattern = config.get("path_pattern") or config.get("pattern")
            return cls.build_path_segment_url(
                current_url=current_url,
                current_page=current_page,
                step=step,
                pattern=pattern,
            )

        if p_type in ("next_button", "next_link", "button"):
            return cls.build_next_button_url(
                current_url=current_url,
                next_button_href=next_button_href,
            )

        # None or unsupported pagination mechanism
        return None

    # [OMA-W005-T011] Enforce the 5 termination signals
    @classmethod
    def evaluate_termination(
        cls,
        cards: Sequence[str],
        current_url: str,
        next_url: str | None = None,
        status_code: int = 200,
        seen_fingerprints: Sequence[str] | None = None,
        visited_urls: set[str] | Sequence[str] | None = None,
        consecutive_existing_pages: int = 0,
        cutoff_threshold: int = 2,
        raise_on_loop: bool = False,
    ) -> tuple[bool, str | None]:
        """Evaluates whether catalog traversal must terminate.

        Enforces the 5 termination signals:
          1. Empty page (0 cards found)
          2. HTTP error status (status_code >= 400, e.g. 404, 410)
          3. Same-URL redirect loop (next_url == current_url or next_url in visited_urls)
          4. Content duplicate loop (identical card fingerprint)
          5. 2-page lookahead cutoff (2 consecutive pages yielding 0 new cards)
        """
        # Signal 1: Empty page (0 cards found)
        if len(cards) == 0:
            return True, "empty_page"

        # Signal 2: HTTP error status
        if status_code >= 400:
            return True, f"http_error_{status_code}"

        # Signal 4: Content duplicate loop
        current_fp = cls.calculate_page_fingerprint(cards)
        if seen_fingerprints:
            is_loop, loop_type = cls.detect_fingerprint_loop(
                current_fingerprint=current_fp,
                seen_fingerprints=seen_fingerprints,
                raise_on_loop=raise_on_loop,
            )
            if is_loop:
                return True, f"duplicate_content_{loop_type}_loop"

        # Signal 5: 2-page lookahead cutoff
        if consecutive_existing_pages >= cutoff_threshold:
            return True, "lookahead_cutoff"

        # Signal 3: Same-URL redirect loop
        if next_url:
            visited_set = set(visited_urls) if visited_urls else set()
            if next_url == current_url or next_url in visited_set:
                return True, "same_url_loop"

        return False, None

    # [OMA-W005-T011] Create a stateful tracking session for a catalog crawl
    @classmethod
    def create_state(
        cls,
        initial_url: str,
        known_card_ids: set[str] | None = None,
    ) -> PaginationState:
        """Instantiates a new PaginationState session container."""
        return PaginationState(
            initial_url=initial_url,
            known_card_ids=set(known_card_ids or set()),
        )

    # [OMA-W005-T011] Process a single catalog page in a stateful session
    @classmethod
    def process_page(
        cls,
        state: PaginationState,
        page_url: str,
        cards: Sequence[str],
        status_code: int = 200,
        pagination_type: str | PaginationType = "url_param",
        pagination_config: dict[str, Any] | None = None,
        next_button_href: str | None = None,
        is_chronological: bool = True,
        cutoff_threshold: int = 2,
        raise_on_loop: bool = False,
    ) -> PaginationStepResult:
        """Evaluates a crawled catalog page, updates state, and yields the next target URL.

        Applies SHA-256 fingerprinting, lookahead tracking, loop detection,
        and termination signal evaluation.
        """
        # Mark current URL as visited
        state.visited_urls.add(page_url)
        card_count = len(cards)
        current_fp = cls.calculate_page_fingerprint(cards)

        # Evaluate lookahead counter if catalog is chronological
        new_card_count = 0
        if is_chronological and card_count > 0:
            new_card_count, new_consec, is_cutoff = cls.advance_lookahead(
                current_cards=cards,
                known_card_ids=state.known_card_ids,
                consecutive_existing_pages=state.consecutive_existing_pages,
                cutoff_threshold=cutoff_threshold,
            )
            state.consecutive_existing_pages = new_consec
        else:
            new_card_count = card_count
            state.consecutive_existing_pages = 0

        # Build candidate next URL
        candidate_next_url = cls.build_next_url(
            current_url=page_url,
            pagination_type=pagination_type,
            pagination_config=pagination_config,
            current_page=state.current_page,
            next_button_href=next_button_href,
        )

        # Check termination signals
        is_terminated, termination_reason = cls.evaluate_termination(
            cards=cards,
            current_url=page_url,
            next_url=candidate_next_url,
            status_code=status_code,
            seen_fingerprints=state.seen_fingerprints,
            visited_urls=state.visited_urls,
            consecutive_existing_pages=state.consecutive_existing_pages,
            cutoff_threshold=cutoff_threshold,
            raise_on_loop=raise_on_loop,
        )

        # If next button pagination was specified but candidate_next_url is None
        p_type = (
            pagination_type.value
            if isinstance(pagination_type, PaginationType)
            else str(pagination_type).lower()
        )
        if not is_terminated and p_type in ("next_button", "next_link", "button"):
            if not candidate_next_url:
                is_terminated = True
                termination_reason = "no_next_button"

        final_next_url = None if is_terminated else candidate_next_url

        # Update state
        state.seen_fingerprints.append(current_fp)
        for c in cards:
            if c and c.strip():
                state.known_card_ids.add(c.strip())

        if is_terminated:
            state.is_terminated = True
            state.termination_signal = termination_reason
        else:
            state.current_page += 1

        step_result = PaginationStepResult(
            current_url=page_url,
            next_url=final_next_url,
            is_terminated=is_terminated,
            termination_signal=termination_reason,
            page_fingerprint=current_fp,
            card_count=card_count,
            new_card_count=new_card_count,
            consecutive_existing_pages=state.consecutive_existing_pages,
            details={
                "pagination_type": p_type,
                "current_page": (
                    state.current_page - 1 if not is_terminated else state.current_page
                ),
            },
        )
        state.history.append(step_result)
        return step_result

    # [OMA-W007-T004] Unified evaluate_step options parameter satisfying Sonar S107
    @classmethod
    def evaluate_step(
        cls,
        state: PaginationState | None = None,
        options: PaginationStepOptions | None = None,
        **kwargs: Any,
    ) -> PaginationStepResult:
        """Evaluates a pagination step with support for PaginationStepOptions and backward compatibility."""
        if isinstance(state, PaginationStepOptions):
            options = state
            state = kwargs.get("state")
        elif state is None:
            state = kwargs.get("state")

        step_options = options or _build_step_options_from_kwargs(kwargs)

        effective_page_url = (
            step_options.current_url
            or kwargs.get("page_url")
            or (state.initial_url if state else "")
        )

        effective_cards: list[str] = (
            step_options.card_identifiers
            if step_options.card_identifiers is not None
            else list(kwargs.get("cards") or [])
        )

        effective_next_button_href = _resolve_next_button_href(
            kwargs.get("next_button_href"),
            step_options.custom_selector or kwargs.get("next_button_selector"),
            kwargs.get("html"),
        )

        return cls.process_page(
            state=state,  # type: ignore[arg-type]
            page_url=effective_page_url,
            cards=effective_cards,
            status_code=step_options.status_code,
            pagination_type=step_options.pagination_type,
            pagination_config=step_options.pagination_config,
            next_button_href=effective_next_button_href,
            is_chronological=step_options.incremental_cutoff_enabled,
            cutoff_threshold=kwargs.get("cutoff_threshold", 2),
            raise_on_loop=kwargs.get("raise_on_loop", False),
        )
