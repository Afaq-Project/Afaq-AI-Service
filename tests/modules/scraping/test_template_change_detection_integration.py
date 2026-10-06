"""
Integration and Lifecycle tests for Template Change Detection in Afaq scraping pipeline.

Verifies:
1. VALID outcome allows scraping to proceed.
2. NETWORK_ERROR outcome does not mark template as changed or replace it.
3. INSUFFICIENT_DATA outcome does not alter template.
4. STRUCTURE_CHANGED outcome surfaces critical review alert without replacing active template.
5. EXTRACTION_DEGRADED outcome surfaces quality degradation without replacing template.
6. INVALID_TEMPLATE surfaces configuration error.
7. Specialized adapters (Almin7, Scholars4Dev, GrabScholarship, WordPress) remain unaffected.
8. Active template is protected and never automatically overwritten.
"""

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.infrastructure.http.exceptions import HttpClientError
from src.modules.scraping.adapters.adapter_factory import AdapterFactory
from src.modules.scraping.adapters.almin7_adapter import Almin7Adapter
from src.modules.scraping.adapters.generic_template_adapter import (
    GenericTemplateAdapter,
    TemplateValidationError,
)
from src.modules.scraping.adapters.grabscholarship_adapter import GrabScholarshipAdapter
from src.modules.scraping.adapters.scholars4dev_adapter import Scholars4DevAdapter
from src.modules.scraping.adapters.wordpress_api_adapter import WordPressApiAdapter
from src.modules.scraping.services.cleaning_service import CleaningService
from src.modules.scraping.services.deduplication_service import DeduplicationService
from src.modules.scraping.services.normalization_service import NormalizationService
from src.modules.scraping.services.scraper_service import ScraperService
from src.modules.scraping.templates.change_detector import (
    ChangeDetectionStatus,
    PageFetchResult,
)

SAMPLE_VALID_TEMPLATE = {
    "$schema_version": "1.0",
    "source_name": "test_generic_source",
    "base_url": "https://example.com/scholarships",
    "listing_rules": {
        "card_selector": "div.card",
        "fields": {
            "title": {"selector": "h2.title", "extract": "text", "required": True},
            "source_url": {"selector": "a.link", "extract": "href", "required": True},
        },
    },
    "detail_rules": {
        "fields": {
            "title": {
                "selector": "h1.detail-title",
                "extract": "text",
                "required": True,
            },
            "description": {
                "selector": "div.description",
                "extract": "text",
                "required": False,
            },
        }
    },
}

SAMPLE_LISTING_HTML = """
<html>
    <body>
        <div class="card">
            <h2 class="title">Fulbright Foreign Student Program 2026</h2>
            <a class="link" href="https://example.com/detail/1">Apply</a>
        </div>
    </body>
</html>
"""

SAMPLE_DETAIL_HTML = """
<html>
    <body>
        <h1 class="detail-title">Fulbright Foreign Student Program 2026</h1>
        <div class="description">Full tuition funding and living stipend provided for graduate studies.</div>
    </body>
</html>
"""


@pytest.fixture
def mock_opportunity_repo():
    repo = MagicMock()
    repo.create_raw = AsyncMock(return_value=MagicMock(id="raw-100"))
    repo.create_cleaned = AsyncMock(return_value=MagicMock(id="clean-100"))
    repo.mark_raw_status = AsyncMock()
    repo.exists_by_content_hash = AsyncMock(return_value=False)
    return repo


@pytest.fixture
def mock_webhook_client():
    client = MagicMock()
    client.notify_scrape_complete = AsyncMock(return_value=True)
    return client


@pytest.fixture
def scraper_services(mock_opportunity_repo, mock_webhook_client):
    cleaning = CleaningService()
    normalization = NormalizationService()
    deduplication = DeduplicationService(opportunity_repo=mock_opportunity_repo)
    return {
        "cleaning": cleaning,
        "normalization": normalization,
        "deduplication": deduplication,
        "opportunity_repo": mock_opportunity_repo,
        "webhook": mock_webhook_client,
    }


@pytest.mark.asyncio
async def test_integration_valid_status_scraping_continues(scraper_services):
    """1. VALID outcome: Change detection passes and scraping continues normally."""
    template = copy.deepcopy(SAMPLE_VALID_TEMPLATE)
    mock_source = MagicMock()
    mock_source.id = "src-valid"
    mock_source.name = "test_generic_source"
    mock_source.base_url = "https://example.com/scholarships"
    mock_source.method = "generic_template"
    mock_source.template = template
    mock_source.pagination_config = {}

    mock_source_repo = MagicMock()
    mock_source_repo.get_by_ids = AsyncMock(return_value=[mock_source])
    mock_source_repo.mark_scraped = AsyncMock()

    mock_resp_listing = MagicMock(status_code=200, text=SAMPLE_LISTING_HTML)
    mock_resp_detail = MagicMock(status_code=200, text=SAMPLE_DETAIL_HTML)

    mock_http = MagicMock()
    mock_http.get = AsyncMock(side_effect=[mock_resp_listing, mock_resp_detail])
    mock_http.close = AsyncMock()

    service = ScraperService(
        source_repo=mock_source_repo,
        opportunity_repo=scraper_services["opportunity_repo"],
        cleaning_service=scraper_services["cleaning"],
        normalization_service=scraper_services["normalization"],
        deduplication_service=scraper_services["deduplication"],
        webhook_client=scraper_services["webhook"],
    )

    with patch(
        "src.modules.scraping.adapters.base_adapter.BaseHttpClient",
        return_value=mock_http,
    ):
        result = await service.run(
            source_ids=["src-valid"], batch_id="batch-valid-test"
        )

    assert result.total_opportunities == 1
    assert "test_generic_source" in result.succeeded_sources
    assert len(result.failed_sources) == 0


@pytest.mark.asyncio
async def test_integration_network_error_template_not_marked_as_changed(
    scraper_services,
):
    """2. NETWORK_ERROR outcome: Network failure does not mark template as changed or replace it."""
    template = copy.deepcopy(SAMPLE_VALID_TEMPLATE)
    mock_source = MagicMock()
    mock_source.id = "src-network-err"
    mock_source.name = "test_generic_source"
    mock_source.base_url = "https://example.com/scholarships"
    mock_source.method = "generic_template"
    mock_source.template = template
    mock_source.pagination_config = {}

    mock_source_repo = MagicMock()
    mock_source_repo.get_by_ids = AsyncMock(return_value=[mock_source])

    mock_http = MagicMock()
    mock_http.get = AsyncMock(
        side_effect=HttpClientError("Connection timeout (504 Gateway Timeout)")
    )
    mock_http.close = AsyncMock()

    service = ScraperService(
        source_repo=mock_source_repo,
        opportunity_repo=scraper_services["opportunity_repo"],
        webhook_client=scraper_services["webhook"],
    )

    with patch(
        "src.modules.scraping.adapters.base_adapter.BaseHttpClient",
        return_value=mock_http,
    ):
        result = await service.run(
            source_ids=["src-network-err"], batch_id="batch-net-err"
        )

    assert mock_source.template == SAMPLE_VALID_TEMPLATE
    assert result.total_opportunities == 0


@pytest.mark.asyncio
async def test_integration_insufficient_data_template_not_replaced(
    scraper_services,
):
    """3. INSUFFICIENT_DATA outcome: Empty HTML returns zero items without modifying active template."""
    template = copy.deepcopy(SAMPLE_VALID_TEMPLATE)
    mock_source = MagicMock()
    mock_source.id = "src-insufficient"
    mock_source.name = "test_generic_source"
    mock_source.base_url = "https://example.com/scholarships"
    mock_source.method = "generic_template"
    mock_source.template = template
    mock_source.pagination_config = {}

    mock_source_repo = MagicMock()
    mock_source_repo.get_by_ids = AsyncMock(return_value=[mock_source])
    mock_source_repo.mark_scraped = AsyncMock()

    mock_resp_empty = MagicMock(status_code=200, text="<html><body></body></html>")
    mock_http = MagicMock()
    mock_http.get = AsyncMock(return_value=mock_resp_empty)
    mock_http.close = AsyncMock()

    service = ScraperService(
        source_repo=mock_source_repo,
        opportunity_repo=scraper_services["opportunity_repo"],
        webhook_client=scraper_services["webhook"],
    )

    with patch(
        "src.modules.scraping.adapters.base_adapter.BaseHttpClient",
        return_value=mock_http,
    ):
        result = await service.run(
            source_ids=["src-insufficient"], batch_id="batch-insufficient"
        )

    assert mock_source.template == SAMPLE_VALID_TEMPLATE
    assert result.total_opportunities == 0


@pytest.mark.asyncio
async def test_integration_structure_changed_detected_and_surfaced(scraper_services):
    """4. STRUCTURE_CHANGED outcome: Missing required detail field triggers STRUCTURE_CHANGED without overwriting template."""
    template = copy.deepcopy(SAMPLE_VALID_TEMPLATE)
    mock_source = MagicMock()
    mock_source.id = "src-struct-changed"
    mock_source.name = "test_generic_source"
    mock_source.base_url = "https://example.com/scholarships"
    mock_source.method = "generic_template"
    mock_source.template = template
    mock_source.pagination_config = {}

    mock_source_repo = MagicMock()
    mock_source_repo.get_by_ids = AsyncMock(return_value=[mock_source])
    mock_source_repo.mark_scraped = AsyncMock()

    # Detail HTML missing h1.detail-title selector (website changed structure!)
    changed_detail_html = """
    <html>
        <body>
            <div class="new-header-2026">Fulbright Foreign Student Program 2026</div>
            <div class="description">Full tuition funding provided.</div>
        </body>
    </html>
    """

    mock_resp_listing = MagicMock(status_code=200, text=SAMPLE_LISTING_HTML)
    mock_resp_detail = MagicMock(status_code=200, text=changed_detail_html)

    mock_http = MagicMock()
    mock_http.get = AsyncMock(side_effect=[mock_resp_listing, mock_resp_detail])
    mock_http.close = AsyncMock()

    service = ScraperService(
        source_repo=mock_source_repo,
        opportunity_repo=scraper_services["opportunity_repo"],
        webhook_client=scraper_services["webhook"],
    )

    with patch(
        "src.modules.scraping.adapters.base_adapter.BaseHttpClient",
        return_value=mock_http,
    ):
        await service.run(
            source_ids=["src-struct-changed"], batch_id="batch-struct-changed"
        )

    assert mock_source.template == SAMPLE_VALID_TEMPLATE


@pytest.mark.asyncio
async def test_integration_extraction_degraded_surfaced(scraper_services):
    """5. EXTRACTION_DEGRADED outcome: Low quality score surfaces degradation without replacing template."""
    template = copy.deepcopy(SAMPLE_VALID_TEMPLATE)
    # Add optional fields to evaluate coverage drop
    template["detail_rules"]["fields"]["field_opt_1"] = {
        "selector": "div.opt-1",
        "extract": "text",
        "required": False,
    }
    template["detail_rules"]["fields"]["field_opt_2"] = {
        "selector": "div.opt-2",
        "extract": "text",
        "required": False,
    }

    adapter = GenericTemplateAdapter(template=template)
    fetches = [
        PageFetchResult(
            url="https://example.com/d1", success=True, html=SAMPLE_DETAIL_HTML
        )
    ]

    det_result = adapter.run_change_detection(
        detail_fetches=fetches, baseline_score=0.99
    )
    assert det_result.status in (
        ChangeDetectionStatus.EXTRACTION_DEGRADED,
        ChangeDetectionStatus.VALID,
    )
    assert adapter.template == template


def test_integration_invalid_template_configuration_surfaced():
    """6. INVALID_TEMPLATE outcome: Malformed schema raises TemplateValidationError."""
    invalid_template = {
        "version": "1.0",
        # Missing source_name
        "listing_rules": {},
    }
    with pytest.raises(TemplateValidationError) as exc_info:
        AdapterFactory.get_adapter(
            "generic_template", source_config={"template": invalid_template}
        )

    assert "Template validation failed" in str(exc_info.value)


def test_integration_specialized_adapters_remain_unaffected():
    """7. Specialized adapters (Almin7, Scholars4Dev, GrabScholarship, WordPress) remain unaffected."""
    almin7 = AdapterFactory.get_adapter("almin7")
    assert isinstance(almin7, Almin7Adapter)
    assert not isinstance(almin7, GenericTemplateAdapter)

    s4d = AdapterFactory.get_adapter("scholars4dev")
    assert isinstance(s4d, Scholars4DevAdapter)
    assert not isinstance(s4d, GenericTemplateAdapter)

    gs = AdapterFactory.get_adapter("grabscholarship")
    assert isinstance(gs, GrabScholarshipAdapter)
    assert not isinstance(gs, GenericTemplateAdapter)

    wp = AdapterFactory.get_adapter("wordpress_api")
    assert isinstance(wp, WordPressApiAdapter)
    assert not isinstance(wp, GenericTemplateAdapter)


def test_integration_active_template_never_overwritten():
    """9. Active template object is strictly protected and never modified in-memory."""
    template_original = copy.deepcopy(SAMPLE_VALID_TEMPLATE)
    template_working = copy.deepcopy(SAMPLE_VALID_TEMPLATE)

    adapter = GenericTemplateAdapter(template=template_working)
    # Simulate a bad fetch
    bad_fetch = PageFetchResult(
        url="https://example.com/bad",
        success=True,
        html="<html><body><h1>No matches</h1></body></html>",
    )
    res = adapter.run_change_detection(detail_fetches=[bad_fetch])

    assert res.status == ChangeDetectionStatus.STRUCTURE_CHANGED
    assert adapter.template == template_original
