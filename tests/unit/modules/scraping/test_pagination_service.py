# [OMA-W005-T008] [OMA-W005-T010] [OMA-W005-T014] Unit tests for PaginationService

import pytest

from src.modules.scraping.exceptions import (
    ERR_PAGINATION_LOOP_DETECTED,
    PaginationLoopDetectedError,
)
from src.modules.scraping.models import PaginationType
from src.modules.scraping.services.pagination_service import PaginationService


# [OMA-W005-T008] Test query parameter pagination URL builder
def test_build_query_param_url():
    """Protects UC-06 & TEST-06: Verifies query parameter pagination increments and preserves existing params."""
    # Simple query param addition
    url = "https://scholarships.example.edu/programs"
    next_url = PaginationService.build_query_param_url(
        url, param_name="page", current_page=1, step=1
    )
    assert next_url == "https://scholarships.example.edu/programs?page=2"

    # Preserves existing parameters and increments existing page param
    complex_url = (
        "https://scholarships.example.edu/search?category=stem&page=3&sort=desc"
    )
    next_url_2 = PaginationService.build_query_param_url(
        complex_url, param_name="page", current_page=3, step=1
    )
    assert "category=stem" in next_url_2
    assert "page=4" in next_url_2
    assert "sort=desc" in next_url_2

    # Custom parameter name (e.g. ?p=2 or ?offset=20)
    custom_url = "https://scholarships.example.edu/grants?p=5"
    next_url_3 = PaginationService.build_query_param_url(
        custom_url, param_name="p", current_page=5, step=1
    )
    assert next_url_3 == "https://scholarships.example.edu/grants?p=6"


# [OMA-W005-T008] Test path segment pagination URL builder
def test_build_path_segment_url():
    """Protects UC-06: Verifies path segment pagination handles /page/N/, /p/N/, and custom patterns."""
    # Common WordPress /page/N/ format
    url_wp = "https://scholarships.example.edu/scholarships/page/1/"
    next_wp = PaginationService.build_path_segment_url(url_wp, current_page=1, step=1)
    assert next_wp == "https://scholarships.example.edu/scholarships/page/2/"

    # /p/N/ format
    url_p = "https://scholarships.example.edu/programs/p/4"
    next_p = PaginationService.build_path_segment_url(url_p, current_page=4, step=1)
    assert next_p == "https://scholarships.example.edu/programs/p/5"

    # Custom pattern template with {page}
    url_custom = "https://scholarships.example.edu/opportunities"
    next_custom = PaginationService.build_path_segment_url(
        url_custom, current_page=2, step=1, pattern="index-{page}.html"
    )
    assert next_custom == "https://scholarships.example.edu/opportunities/index-3.html"

    # Fallback when no pattern or match exists: appends /page/N/
    url_plain = "https://scholarships.example.edu/portal"
    next_fallback = PaginationService.build_path_segment_url(
        url_plain, current_page=1, step=1
    )
    assert next_fallback == "https://scholarships.example.edu/portal/page/2/"


# [OMA-W005-T008] Test next button selector pagination URL builder
def test_build_next_button_url():
    """Protects UC-06: Verifies next button href resolution and rejection of invalid / anchor hrefs."""
    base_url = "https://scholarships.example.edu/catalog/list"

    # Valid relative link
    next_rel = PaginationService.build_next_button_url(base_url, "page2.html?ref=btn")
    assert next_rel == "https://scholarships.example.edu/catalog/page2.html?ref=btn"

    # Valid root-relative link
    next_root = PaginationService.build_next_button_url(base_url, "/catalog?page=2")
    assert next_root == "https://scholarships.example.edu/catalog?page=2"

    # Valid absolute link
    next_abs = PaginationService.build_next_button_url(
        base_url, "https://scholarships.example.edu/catalog?page=2"
    )
    assert next_abs == "https://scholarships.example.edu/catalog?page=2"

    # Invalid / empty hrefs must return None
    assert PaginationService.build_next_button_url(base_url, None) is None
    assert PaginationService.build_next_button_url(base_url, "") is None
    assert PaginationService.build_next_button_url(base_url, "   ") is None
    assert PaginationService.build_next_button_url(base_url, "#") is None
    assert (
        PaginationService.build_next_button_url(base_url, "javascript:void(0)") is None
    )


# [OMA-W005-T008] Test build_next_url dispatcher across all pagination mechanics
def test_build_next_url_dispatcher():
    """Protects UC-06: Verifies unified build_next_url dispatches appropriately per configured type."""
    base_url = "https://scholarships.example.edu/catalog"

    # URL query param
    q_url = PaginationService.build_next_url(
        current_url=base_url,
        pagination_type=PaginationType.URL_PARAM,
        pagination_config={"param_name": "p"},
        current_page=1,
    )
    assert q_url == "https://scholarships.example.edu/catalog?p=2"

    # Path segment
    p_url = PaginationService.build_next_url(
        current_url=base_url,
        pagination_type="path_segment",
        current_page=2,
    )
    assert p_url == "https://scholarships.example.edu/catalog/page/3/"

    # Next button
    b_url = PaginationService.build_next_url(
        current_url=base_url,
        pagination_type=PaginationType.NEXT_BUTTON,
        next_button_href="?page=3",
    )
    assert b_url == "https://scholarships.example.edu/catalog?page=3"

    # Unsupported / None type
    none_url = PaginationService.build_next_url(
        current_url=base_url,
        pagination_type=PaginationType.NONE,
    )
    assert none_url is None


# [OMA-W005-T010] Test SHA-256 card fingerprinting and normalization
def test_calculate_page_fingerprint():
    """Protects UC-07 & TEST-07: Verifies SHA256 fingerprinting normalizes casing and whitespace."""
    cards_1 = ["Erasmus Mundus Scholarship", "Fulbright Fellowship 2026"]
    cards_2 = ["  erasmus mundus scholarship  ", "fulbright fellowship 2026\n"]
    cards_diff = ["DAAD Study Grant 2026", "Chevening Award"]

    fp1 = PaginationService.calculate_page_fingerprint(cards_1)
    fp2 = PaginationService.calculate_page_fingerprint(cards_2)
    fp_diff = PaginationService.calculate_page_fingerprint(cards_diff)

    assert fp1 == fp2  # Normalization produces exact same fingerprint
    assert fp1 != fp_diff
    assert len(fp1) == 64  # SHA-256 64-char hex string

    # Empty card list returns constant empty SHA-256
    fp_empty = PaginationService.calculate_page_fingerprint([])
    assert len(fp_empty) == 64
    assert PaginationService.calculate_page_fingerprint(["", "   "]) == fp_empty


# [OMA-W005-T010] Test stagnant and circular loop detection via fingerprints
def test_detect_fingerprint_loop():
    """Protects UC-07 & TEST-07: Verifies stagnant loop and circular loop detection with optional exception."""
    seen_history = ["fp_page_1", "fp_page_2", "fp_page_3"]

    # 1. Stagnant loop (identical to immediate preceding page)
    is_loop, reason = PaginationService.detect_fingerprint_loop(
        "fp_page_3", seen_history, raise_on_loop=False
    )
    assert is_loop is True
    assert reason == "stagnant"

    # 2. Circular loop (matches page 1 or non-adjacent page in history)
    is_loop, reason = PaginationService.detect_fingerprint_loop(
        "fp_page_1", seen_history, raise_on_loop=False
    )
    assert is_loop is True
    assert reason == "circular"

    # 3. New unique page (no loop)
    is_loop, reason = PaginationService.detect_fingerprint_loop(
        "fp_page_4_new", seen_history, raise_on_loop=False
    )
    assert is_loop is False
    assert reason is None

    # 4. raise_on_loop triggers PaginationLoopDetectedError
    with pytest.raises(PaginationLoopDetectedError) as exc_info:
        PaginationService.detect_fingerprint_loop(
            "fp_page_3", seen_history, raise_on_loop=True
        )
    assert exc_info.value.code == ERR_PAGINATION_LOOP_DETECTED
    assert exc_info.value.details["loop_type"] == "stagnant"


# [OMA-W005-T014] Test advance_lookahead progression and counter reset
def test_advance_lookahead():
    """Protects UC-06 & TEST-06: Verifies lookahead advances on existing cards and resets on new cards."""
    known_cards = {"card_1", "card_2", "card_3"}

    # Page with 100% existing cards -> counter increments to 1, cutoff not yet reached (threshold 2)
    new_count, consec, is_cutoff = PaginationService.advance_lookahead(
        current_cards=["card_1", "card_2"],
        known_card_ids=known_cards,
        consecutive_existing_pages=0,
        cutoff_threshold=2,
    )
    assert new_count == 0
    assert consec == 1
    assert is_cutoff is False

    # Second consecutive page of 100% existing cards -> counter increments to 2, cutoff REACHED
    new_count_2, consec_2, is_cutoff_2 = PaginationService.advance_lookahead(
        current_cards=["card_2", "card_3"],
        known_card_ids=known_cards,
        consecutive_existing_pages=1,
        cutoff_threshold=2,
    )
    assert new_count_2 == 0
    assert consec_2 == 2
    assert is_cutoff_2 is True

    # Page with at least 1 new card -> counter resets back to 0
    new_count_3, consec_3, is_cutoff_3 = PaginationService.advance_lookahead(
        current_cards=["card_1", "card_new_99"],
        known_card_ids=known_cards,
        consecutive_existing_pages=1,
        cutoff_threshold=2,
    )
    assert new_count_3 == 1
    assert consec_3 == 0
    assert is_cutoff_3 is False


# [OMA-W005-T014] Test 5 termination signals evaluation
def test_evaluate_termination_signals():
    """Protects UC-06 & UC-07: Verifies all 5 termination signals are accurately evaluated."""
    # Signal 1: Empty page (0 cards found)
    is_term, sig = PaginationService.evaluate_termination(
        cards=[],
        current_url="https://example.edu/page/10",
        next_url="https://example.edu/page/11",
        status_code=200,
    )
    assert is_term is True
    assert sig == "empty_page"

    # Signal 2: HTTP error status (404/500)
    is_term, sig = PaginationService.evaluate_termination(
        cards=["card_1"],
        current_url="https://example.edu/page/10",
        status_code=404,
    )
    assert is_term is True
    assert sig == "http_error_404"

    # Signal 3: Same-URL redirect loop
    is_term, sig = PaginationService.evaluate_termination(
        cards=["card_1"],
        current_url="https://example.edu/catalog",
        next_url="https://example.edu/catalog",
        status_code=200,
    )
    assert is_term is True
    assert sig == "same_url_loop"

    # Signal 3b: Visited URL loop
    is_term, sig = PaginationService.evaluate_termination(
        cards=["card_1"],
        current_url="https://example.edu/catalog/page/3",
        next_url="https://example.edu/catalog/page/1",
        visited_urls={
            "https://example.edu/catalog/page/1",
            "https://example.edu/catalog/page/2",
        },
    )
    assert is_term is True
    assert sig == "same_url_loop"

    # Signal 4: Content duplicate loop
    card_set = ["Scholarship A", "Scholarship B"]
    fp = PaginationService.calculate_page_fingerprint(card_set)
    is_term, sig = PaginationService.evaluate_termination(
        cards=card_set,
        current_url="https://example.edu/catalog/page/2",
        next_url="https://example.edu/catalog/page/3",
        seen_fingerprints=[fp],  # Stagnant loop
    )
    assert is_term is True
    assert sig == "duplicate_content_stagnant_loop"

    # Signal 5: 2-page lookahead cutoff
    is_term, sig = PaginationService.evaluate_termination(
        cards=["card_existing_1"],
        current_url="https://example.edu/catalog/page/5",
        next_url="https://example.edu/catalog/page/6",
        consecutive_existing_pages=2,
        cutoff_threshold=2,
    )
    assert is_term is True
    assert sig == "lookahead_cutoff"

    # Healthy case: no termination
    is_term, sig = PaginationService.evaluate_termination(
        cards=["card_new_1"],
        current_url="https://example.edu/catalog/page/1",
        next_url="https://example.edu/catalog/page/2",
        seen_fingerprints=["different_fp"],
        visited_urls={"https://example.edu/catalog/page/1"},
        consecutive_existing_pages=0,
    )
    assert is_term is False
    assert sig is None


# [OMA-W005-T014] Test stateful multi-step crawl execution with healthy progression
def test_stateful_pagination_process():
    """Protects UC-06 & TEST-06: Verifies healthy multi-step stateful crawl advances across pages."""
    state = PaginationService.create_state(
        initial_url="https://example.edu/catalog",
        known_card_ids={"old_grant_1", "old_grant_2"},
    )
    assert state.current_page == 1
    assert len(state.known_card_ids) == 2

    # Step 1: Page 1 with new cards -> healthy advance
    step1 = PaginationService.process_page(
        state=state,
        page_url="https://example.edu/catalog?page=1",
        cards=["new_grant_10", "new_grant_11"],
        pagination_type=PaginationType.URL_PARAM,
    )
    assert step1.is_terminated is False
    assert step1.new_card_count == 2
    assert step1.consecutive_existing_pages == 0
    assert step1.next_url == "https://example.edu/catalog?page=2"
    assert state.current_page == 2

    # Step 2: Page 2 with further new cards -> healthy advance
    step2 = PaginationService.process_page(
        state=state,
        page_url="https://example.edu/catalog?page=2",
        cards=["new_grant_20", "new_grant_21"],
        pagination_type=PaginationType.URL_PARAM,
    )
    assert step2.is_terminated is False
    assert step2.new_card_count == 2
    assert step2.consecutive_existing_pages == 0
    assert step2.next_url == "https://example.edu/catalog?page=3"
    assert state.current_page == 3


# [OMA-W005-T014] Test multi-step lookahead termination with distinct known cards
def test_stateful_pagination_lookahead_termination():
    """Protects UC-06 & TEST-06: Verifies lookahead cutoff terminates after 2 consecutive pages of known cards."""
    # Pre-populate known cards
    initial_known = {"grant_p2_a", "grant_p2_b", "grant_p3_a", "grant_p3_b"}
    state = PaginationService.create_state(
        initial_url="https://example.edu/catalog?page=1",
        known_card_ids=initial_known,
    )

    # Page 1: Brand new grants
    step1 = PaginationService.process_page(
        state=state,
        page_url="https://example.edu/catalog?page=1",
        cards=["grant_p1_brand_new"],
        pagination_type=PaginationType.URL_PARAM,
        cutoff_threshold=2,
    )
    assert step1.is_terminated is False
    assert step1.new_card_count == 1
    assert step1.consecutive_existing_pages == 0
    assert step1.next_url == "https://example.edu/catalog?page=2"

    # Page 2: Grants already in known set (consecutive_existing_pages -> 1)
    step2 = PaginationService.process_page(
        state=state,
        page_url="https://example.edu/catalog?page=2",
        cards=["grant_p2_a", "grant_p2_b"],
        pagination_type=PaginationType.URL_PARAM,
        cutoff_threshold=2,
    )
    assert step2.is_terminated is False
    assert step2.new_card_count == 0
    assert step2.consecutive_existing_pages == 1
    assert step2.next_url == "https://example.edu/catalog?page=3"

    # Page 3: Different grants, but also already in known set (consecutive_existing_pages -> 2 => CUTOFF)
    step3 = PaginationService.process_page(
        state=state,
        page_url="https://example.edu/catalog?page=3",
        cards=["grant_p3_a", "grant_p3_b"],
        pagination_type=PaginationType.URL_PARAM,
        cutoff_threshold=2,
    )
    assert step3.is_terminated is True
    assert step3.termination_signal == "lookahead_cutoff"
    assert step3.next_url is None
    assert state.is_terminated is True


# [OMA-W005-T014] Test next-button pagination terminating when button is absent
def test_next_button_termination_when_absent():
    """Protects UC-06: Verifies next button pagination cleanly terminates with 'no_next_button' when href is None."""
    state = PaginationService.create_state(initial_url="https://example.edu/catalog")

    step = PaginationService.process_page(
        state=state,
        page_url="https://example.edu/catalog",
        cards=["grant_1", "grant_2"],
        pagination_type=PaginationType.NEXT_BUTTON,
        next_button_href=None,  # No next button present on last page
    )
    assert step.is_terminated is True
    assert step.termination_signal == "no_next_button"
    assert step.next_url is None
    assert state.is_terminated is True
