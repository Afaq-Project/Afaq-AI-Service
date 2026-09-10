from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.scraping.services.deduplication_service import DeduplicationService


def test_deduplication_hash_normalization_resilience():
    service = DeduplicationService()

    opp1 = {
        "title": "Türkiye Bursları Scholarship 2026",
        "organization": "YTB Turkey",
        "opportunity_type": "scholarship",
        "country": "Turkey",
    }

    # Same opportunity with casing, punctuation, and whitespace variations
    opp2 = {
        "title": "  türkiye bursları scholarship 2026!  ",
        "organization": "ytb turkey...",
        "opportunity_type": "scholarship",
        "country": "Turkey",
    }

    hash1 = service.generate_content_hash(opp1)
    hash2 = service.generate_content_hash(opp2)
    assert hash1 == hash2, "Formatting differences must produce identical content_hash"


def test_deduplication_scenario_a_identical_across_sources():
    """Scenario A: Same scholarship reported by two different sources must produce identical hash."""
    service = DeduplicationService()

    source1_opp = {
        "title": "DAAD Scholarship 2026",
        "organization": "DAAD",
        "opportunity_type": "scholarship",
        "country": "Germany",
        "source_url": "https://almin7.com/daad-2026",
    }

    source2_opp = {
        "title": "DAAD Scholarship 2026",
        "organization": "DAAD",
        "opportunity_type": "scholarship",
        "country": "Germany",
        "source_url": "https://grabscholarships.com/daad-scholarship-2026",
    }

    assert service.generate_content_hash(source1_opp) == service.generate_content_hash(
        source2_opp
    )


def test_deduplication_scenario_b_different_scholarships_same_org_and_app_url():
    """
    Scenario B: Different scholarships at the same university sharing the same application_url
    MUST NOT be merged as duplicates.
    """
    service = DeduplicationService()

    opp_a = {
        "title": "University of Oxford Rhodes Scholarship",
        "organization": "University of Oxford",
        "opportunity_type": "scholarship",
        "country": "United Kingdom",
        "application_url": "https://ox.ac.uk/apply",
    }

    opp_b = {
        "title": "University of Oxford Clarendon Fund Scholarship",
        "organization": "University of Oxford",
        "opportunity_type": "scholarship",
        "country": "United Kingdom",
        "application_url": "https://ox.ac.uk/apply",
    }

    hash_a = service.generate_content_hash(opp_a)
    hash_b = service.generate_content_hash(opp_b)

    assert (
        hash_a != hash_b
    ), "Different scholarships sharing the same application URL must have distinct hashes"


@pytest.mark.asyncio
async def test_deduplication_batch_cache_and_db():
    mock_repo = MagicMock()
    mock_repo.exists_by_content_hash = AsyncMock(return_value=False)

    service = DeduplicationService(opportunity_repo=mock_repo)

    opp = {
        "title": "DAAD Scholarship",
        "organization": "DAAD",
        "opportunity_type": "scholarship",
        "country": "Germany",
    }
    content_hash = service.generate_content_hash(opp)

    # First time: not duplicate
    assert await service.is_duplicate(opp, content_hash) is False

    # Mark seen in current batch
    service.mark_as_seen(content_hash)

    # Second time: duplicate in-memory
    assert await service.is_duplicate(opp, content_hash) is True

    # Reset batch: clear in-memory cache
    service.reset_batch()
    assert await service.is_duplicate(opp, content_hash) is False
