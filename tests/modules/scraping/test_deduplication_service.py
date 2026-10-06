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
async def test_deduplication_test1_title_changed_same_source_url():
    """Test 1: Same source URL with changed title must be detected as duplicate."""
    service = DeduplicationService()

    opp1 = {
        "title": "ETH Excellence Scholarships",
        "source_url": "https://scholars4dev.com/9763/eth-zurich-excellence-masters-scholarship-program",
    }

    opp2 = {
        "title": "ETH Zurich Excellence Masters Scholarship Program",
        "source_url": "https://scholars4dev.com/9763/eth-zurich-excellence-masters-scholarship-program",
    }

    h1 = service.generate_content_hash(opp1)
    service.mark_as_seen(h1, opp1["source_url"])

    h2 = service.generate_content_hash(opp2)
    is_dup = await service.is_duplicate(opp2, h2)

    assert (
        is_dup is True
    ), "Same source URL with different titles must be flagged as duplicate"


@pytest.mark.asyncio
async def test_deduplication_test2_same_application_url_different_source_urls():
    """Test 2: Same application URL but different source URLs must NOT be automatically merged as duplicates."""
    service = DeduplicationService()

    opp1 = {
        "title": "OAS Scholarships in Argentina",
        "organization": "Organization of American States",
        "country": "Argentina",
        "source_url": "https://almin7.com/scholarship/oas-scholarships-in-argentina/",
        "application_url": "https://www.oas.org/en/scholarships/",
    }

    opp2 = {
        "title": "OAS Scholarships in Mexico",
        "organization": "Organization of American States",
        "country": "Mexico",
        "source_url": "https://almin7.com/scholarship/oas-scholarships-in-mexico/",
        "application_url": "https://www.oas.org/en/scholarships/",
    }

    h1 = service.generate_content_hash(opp1)
    service.mark_as_seen(h1, opp1["source_url"])

    h2 = service.generate_content_hash(opp2)
    is_dup = await service.is_duplicate(opp2, h2)

    assert (
        is_dup is False
    ), "Distinct opportunities sharing the same application portal URL must NOT be duplicates"


@pytest.mark.asyncio
async def test_deduplication_test3_exact_same_opportunity():
    """Test 3: Exact same opportunity fields must be detected as duplicate."""
    service = DeduplicationService()

    opp = {
        "title": "Chevening Scholarships UK",
        "organization": "UK Foreign Office",
        "country": "United Kingdom",
        "source_url": "https://scholars4dev.com/3299/british-chevening-scholarships/",
    }

    h = service.generate_content_hash(opp)
    assert await service.is_duplicate(opp, h) is False

    service.mark_as_seen(h, opp["source_url"])
    assert await service.is_duplicate(opp, h) is True


@pytest.mark.asyncio
async def test_deduplication_test4_fallback_without_source_url():
    """Test 4: Fallback deduplication without source_url using composite title+org+country."""
    service = DeduplicationService()

    opp1 = {
        "title": "Fulbright Foreign Student Program",
        "organization": "US Department of State",
        "country": "USA",
    }

    opp2 = {
        "title": "Fulbright Foreign Student Program",
        "organization": "US Department of State",
        "country": "USA",
    }

    h1 = service.generate_content_hash(opp1)
    service.mark_as_seen(h1)

    h2 = service.generate_content_hash(opp2)
    assert await service.is_duplicate(opp2, h2) is True


@pytest.mark.asyncio
async def test_deduplication_test5_url_normalization():
    """Test 5: URL normalization resilient to trailing slashes."""
    service = DeduplicationService()

    opp1 = {
        "title": "Gates Cambridge Scholarships",
        "source_url": "https://scholars4dev.com/2043/gates-scholarships/",
    }

    opp2 = {
        "title": "Gates Cambridge Scholarships Program",
        "source_url": "https://scholars4dev.com/2043/gates-scholarships",
    }

    h1 = service.generate_content_hash(opp1)
    service.mark_as_seen(h1, opp1["source_url"])

    h2 = service.generate_content_hash(opp2)
    assert await service.is_duplicate(opp2, h2) is True


@pytest.mark.asyncio
async def test_deduplication_batch_cache_and_db():
    mock_repo = MagicMock()
    mock_repo.exists_by_content_hash = AsyncMock(return_value=False)
    mock_repo.exists_by_source_url = AsyncMock(return_value=False)

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
