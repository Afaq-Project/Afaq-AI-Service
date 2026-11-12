# [OMA-W005-T015] [OMA-W005-T017] [OMA-W005-T021] [OMA-W006-T004] Unit tests for PrioritizationService

from datetime import UTC, datetime, timedelta

import pytest

from src.modules.scraping.services.prioritization_service import (
    PrioritizationService,
)


# [OMA-W006-T004] Test priority scoring formula with FR-007 dynamic weights: (Admin Tier * 100) + Days - (Failures * 10)
def test_calculate_priority_score_formula():
    """Protects FR-007: priority_score = (base_priority * 100.0) + (days_since_scrape * 1.0) - (consecutive_failures * 10.0)."""
    # Case 1: Fresh high-tier source scraped today (0 days), 0 failures
    # score = (3.0 * 100.0) + (0.0 * 1.0) - (0 * 10.0) = 300.0
    score1 = PrioritizationService.calculate_priority_score(
        base_priority=3.0,
        days_since_last_scrape=0.0,
        consecutive_failures=0,
    )
    assert score1 == 300.0

    # Case 2: Stale normal-tier source (10 days since scrape), 2 failures
    # score = (1.0 * 100.0) + (10.0 * 1.0) - (2 * 10.0) = 100 + 10 - 20 = 90.0
    score2 = PrioritizationService.calculate_priority_score(
        base_priority=1.0,
        days_since_last_scrape=10.0,
        consecutive_failures=2,
    )
    assert score2 == 90.0

    # Case 3: Flaky source with many failures (5 failures)
    # score = (1.0 * 100.0) + (1.0 * 1.0) - (5 * 10.0) = 100 + 1 - 50 = 51.0
    score3 = PrioritizationService.calculate_priority_score(
        base_priority=1.0,
        days_since_last_scrape=1.0,
        consecutive_failures=5,
    )
    assert score3 == 51.0

    # Case 4: Severe failure penalty resulting in negative priority score
    # score = (1.0 * 100.0) + (2.0 * 1.0) - (15 * 10.0) = 100 + 2 - 150 = -48.0
    score4 = PrioritizationService.calculate_priority_score(
        base_priority=1.0,
        days_since_last_scrape=2.0,
        consecutive_failures=15,
    )
    assert score4 == -48.0


# [OMA-W006-T004] Test score_source with objects, dictionaries, and unscraped defaults matching FR-007
def test_score_source_unscraped_default():
    """Protects FR-007 & UC-02: Unscraped source defaults to 30 days staleness."""
    service = PrioritizationService(unscraped_days_default=30.0)

    # Source never scraped before (last_scraped_at = None)
    # score = (1.0 * 100.0) + (30.0 * 1.0) - (0 * 10.0) = 130.0
    source_dict = {
        "id": "src_new",
        "base_priority": 1.0,
        "last_scraped_at": None,
        "consecutive_failures": 0,
    }
    score = service.score_source(source_dict)
    assert score == 130.0

    # Source scraped 5 days ago
    now = datetime.now(UTC)
    five_days_ago = now - timedelta(days=5)
    source_scraped = {
        "id": "src_scraped",
        "base_priority": 2.0,
        "last_scraped_at": five_days_ago,
        "consecutive_failures": 1,
    }
    # score = (2.0 * 100.0) + (5.0 * 1.0) - (1 * 10.0) = 200 + 5 - 10 = 195.0
    score_scraped = service.score_source(source_scraped, now=now)
    assert pytest.approx(score_scraped, rel=1e-2) == 195.0


# [OMA-W005-T017] Test domain extraction across varied input types
def test_extract_domain():
    """Protects domain isolation: Normalizes domains across strings, dicts, models, and URLs."""
    # Raw strings
    assert (
        PrioritizationService.extract_domain(
            "https://scholarships.example.edu/programs"
        )
        == "scholarships.example.edu"
    )
    assert (
        PrioritizationService.extract_domain("http://www.mit.edu/admissions")
        == "mit.edu"
    )
    assert PrioritizationService.extract_domain("www.ox.ac.uk:443/grants") == "ox.ac.uk"
    assert PrioritizationService.extract_domain("stanford.edu") == "stanford.edu"

    # Dictionaries
    dict_domain = {"domain": "www.harvard.edu"}
    assert PrioritizationService.extract_domain(dict_domain) == "harvard.edu"

    dict_url = {"url": "https://daad.de/scholarships"}
    assert PrioritizationService.extract_domain(dict_url) == "daad.de"

    dict_config = {"config": {"domain": "chevening.org"}}
    assert PrioritizationService.extract_domain(dict_config) == "chevening.org"

    # Objects / Mock Models
    class MockSource:

        def __init__(self, domain: str):
            self.domain = domain

    assert (
        PrioritizationService.extract_domain(MockSource("cambridge.ac.uk"))
        == "cambridge.ac.uk"
    )

    # Empty / None fallback
    assert PrioritizationService.extract_domain(None) == "unknown_domain"
    assert PrioritizationService.extract_domain("") == "unknown_domain"


# [OMA-W005-T017] Test domain interleaving round-robin without adjacent duplicates
def test_interleave_domains():
    """Protects UC-02 & Section 3.1: Enforces that adjacent queued jobs never target the same domain."""
    items = [
        {"id": "mit_1", "domain": "mit.edu"},
        {"id": "mit_2", "domain": "mit.edu"},
        {"id": "mit_3", "domain": "mit.edu"},
        {"id": "harvard_1", "domain": "harvard.edu"},
        {"id": "harvard_2", "domain": "harvard.edu"},
        {"id": "stanford_1", "domain": "stanford.edu"},
    ]

    interleaved = PrioritizationService.interleave_domains(items)

    assert len(interleaved) == len(items)

    # Verify no two adjacent items share the same domain (whenever multiple domains are remaining)
    for i in range(len(interleaved) - 1):
        curr_domain = interleaved[i]["domain"]
        next_domain = interleaved[i + 1]["domain"]
        # Only at the very tail when only 1 domain has remaining items can adjacent match
        # But here total: mit(3), harvard(2), stanford(1) -> perfectly interleavable without adjacent matches!
        assert (
            curr_domain != next_domain
        ), f"Adjacent duplicate domain '{curr_domain}' found at index {i} and {i+1}"


# [OMA-W005-T017] Test single domain queue edge case in interleaving
def test_interleave_domains_single_domain():
    """Protects edge-case: If all items belong to a single domain, preserves order without error."""
    items = [
        {"id": "mit_1", "domain": "mit.edu"},
        {"id": "mit_2", "domain": "mit.edu"},
    ]
    interleaved = PrioritizationService.interleave_domains(items)
    assert interleaved == items

    # Empty and single-item inputs
    assert PrioritizationService.interleave_domains([]) == []
    assert PrioritizationService.interleave_domains([items[0]]) == [items[0]]


# [OMA-W005-T021] Test manual P0 override ("Scrape Now") bonus
def test_manual_p0_override():
    """Protects UC-02 & Section 3.1: Manual 'Scrape Now' sources jump to the head of the queue."""
    service = PrioritizationService()
    now = datetime.now(UTC)

    sources = [
        {
            "id": "src_regular_stale",
            "domain": "mit.edu",
            "base_priority": 10.0,
            "last_scraped_at": now - timedelta(days=20),
            "consecutive_failures": 0,
        },
        {
            "id": "src_manual_fresh",
            "domain": "harvard.edu",
            "base_priority": 1.0,
            "last_scraped_at": now,  # 0 days stale
            "consecutive_failures": 3,
        },
    ]

    # Without manual override, src_regular_stale wins on staleness
    ordered_normal = service.prioritize_sources(sources, now=now)
    assert ordered_normal[0]["id"] == "src_regular_stale"

    # With manual override on src_manual_fresh, it jumps to the head (+10000.0 bonus)
    ordered_manual = service.prioritize_sources(
        sources, manual_source_ids=["src_manual_fresh"], now=now
    )
    assert ordered_manual[0]["id"] == "src_manual_fresh"
    assert ordered_manual[1]["id"] == "src_regular_stale"


# [OMA-W005-T021] Test master prioritize_sources with combined scoring, override, and interleaving
def test_prioritize_sources_master_pipeline():
    """Protects UC-02 & Section 3.1: Verifies end-to-end prioritization, sorting, and interleaving."""
    service = PrioritizationService()
    now = datetime.now(UTC)

    candidates = [
        {
            "id": "mit_low",
            "domain": "mit.edu",
            "base_priority": 1.0,
            "last_scraped_at": now,
        },
        {
            "id": "mit_high",
            "domain": "mit.edu",
            "base_priority": 50.0,
            "last_scraped_at": now,
        },
        {
            "id": "oxford_mid",
            "domain": "ox.ac.uk",
            "base_priority": 25.0,
            "last_scraped_at": now,
        },
        {
            "id": "cambridge_mid",
            "domain": "cambridge.ac.uk",
            "base_priority": 20.0,
            "last_scraped_at": now,
        },
    ]

    result = service.prioritize_sources(candidates, now=now)
    assert len(result) == 4

    # Top item should be mit_high (score 5000.0)
    assert result[0]["id"] == "mit_high"
    # Second item should be from a different domain (ox.ac.uk or cambridge.ac.uk), not mit_low!
    assert result[1]["domain"] != "mit.edu"
