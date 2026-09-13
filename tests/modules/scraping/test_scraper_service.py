from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.infrastructure.webhook.webhook_client import ScrapeCompletePayload
from src.modules.scraping.services.cleaning_service import CleaningService
from src.modules.scraping.services.deduplication_service import DeduplicationService
from src.modules.scraping.services.normalization_service import NormalizationService
from src.modules.scraping.services.scraper_service import ScraperService


@pytest.mark.asyncio
async def test_scraper_service_complete_end_to_end_pipeline():
    """
    اختبار تكاملي حقيقي لدورة الـ Pipeline الكاملة بدون Mock للـ business logic:
    SourceRepository -> AdapterFactory -> Adapter.fetch() -> Adapter.is_opportunity()
    -> Adapter.parse() -> CleaningService -> NormalizationService -> DeduplicationService
    -> OpportunityRepository (create_raw + create_cleaned) -> WebhookClient.
    """
    # 1. Source Mock
    mock_source = MagicMock()
    mock_source.id = "src-001"
    mock_source.name = "grabscholarship"
    mock_source.base_url = "https://grabscholarships.com"
    mock_source.api_endpoint = "/wp-json/wp/v2/posts"
    mock_source.method = "wordpress_api"
    mock_source.pagination_config = {"limit": 10}
    mock_source.field_mapping = {}

    mock_source_repo = MagicMock()
    mock_source_repo.get_by_ids = AsyncMock(return_value=[mock_source])
    mock_source_repo.mark_scraped = AsyncMock()

    # 2. Opportunity Repository Tracking
    created_raw_records = []
    created_cleaned_records = []

    async def mock_create_raw(source_id, raw_payload, status, source_url):
        raw_rec = MagicMock()
        raw_rec.id = f"raw-{len(created_raw_records) + 1}"
        raw_rec.source_id = source_id
        raw_rec.raw_payload = raw_payload
        raw_rec.source_url = source_url
        raw_rec.status = status
        created_raw_records.append(raw_rec)
        return raw_rec

    async def mock_create_cleaned(cleaned_data):
        created_cleaned_records.append(cleaned_data)
        return MagicMock()

    mock_opp_repo = MagicMock()
    mock_opp_repo.create_raw = AsyncMock(side_effect=mock_create_raw)
    mock_opp_repo.create_cleaned = AsyncMock(side_effect=mock_create_cleaned)
    mock_opp_repo.mark_raw_status = AsyncMock()
    mock_opp_repo.exists_by_content_hash = AsyncMock(return_value=False)

    # 3. Webhook Mock
    mock_webhook = MagicMock()
    mock_webhook.notify_scrape_complete = AsyncMock(return_value=True)

    # 4. HTTP client mock with raw data:
    # Item 1: Real scholarship (University of Alberta) -> should be processed & saved
    # Item 2: Guide to choosing courses -> should be filtered out by is_opportunity
    mock_raw_posts = [
        {
            "title": {
                "rendered": "University of Alberta International Undergraduate Scholarships"
            },
            "content": {
                "rendered": "<p>One in five students receives a scholarship. Full tuition coverage. Deadline: 10 January 2027</p>"
            },
            "excerpt": {"rendered": "Scholarship in Canada"},
            "categories": ["Scholarships", "Undergraduate Scholarships", "Canada"],
            "link": "https://grabscholarships.com/alberta-scholarship/",
            "date": "2026-09-01T12:00:00",
        },
        {
            "title": {"rendered": "A Guide to Choosing University Courses"},
            "content": {
                "rendered": "<p>General informational article about choosing a major.</p>"
            },
            "categories": ["University Courses"],
            "link": "https://grabscholarships.com/guide-courses/",
            "date": "2026-09-01T12:00:00",
        },
    ]

    mock_http_response = MagicMock()
    mock_http_response.json.return_value = mock_raw_posts
    mock_http_response.is_success = True

    mock_http_client = MagicMock()
    mock_http_client.get = AsyncMock(return_value=mock_http_response)
    mock_http_client.close = AsyncMock()

    # 5. Build Real Services Pipeline
    cleaning_service = CleaningService()
    normalization_service = NormalizationService()
    deduplication_service = DeduplicationService(opportunity_repo=mock_opp_repo)

    service = ScraperService(
        source_repo=mock_source_repo,
        opportunity_repo=mock_opp_repo,
        cleaning_service=cleaning_service,
        normalization_service=normalization_service,
        deduplication_service=deduplication_service,
        webhook_client=mock_webhook,
    )

    with patch(
        "src.modules.scraping.adapters.base_adapter.BaseHttpClient",
        return_value=mock_http_client,
    ):
        result = await service.run(
            source_ids=["src-001"], batch_id="batch-pipeline-test"
        )

    # 6. Verify Results
    assert result.batch_id == "batch-pipeline-test"
    assert result.total_opportunities == 1
    assert "grabscholarship" in result.succeeded_sources
    assert len(result.failed_sources) == 0

    # Verify raw opportunity was created for the processed opportunity
    assert len(created_raw_records) == 1
    assert (
        created_raw_records[0].source_url
        == "https://grabscholarships.com/alberta-scholarship/"
    )

    # Verify cleaned opportunity was saved with normalized fields
    assert len(created_cleaned_records) == 1
    saved_clean = created_cleaned_records[0]
    assert (
        saved_clean["title"]
        == "University of Alberta International Undergraduate Scholarships"
    )
    assert saved_clean["opportunity_type"] == "scholarship"
    assert saved_clean["country"] == "Canada"
    assert "Bachelor" in saved_clean["study_levels"]
    assert saved_clean["funding_type"] == "fully_funded"
    assert saved_clean["content_hash"] is not None

    # Verify Webhook payload
    mock_webhook.notify_scrape_complete.assert_called_once()
    payload: ScrapeCompletePayload = mock_webhook.notify_scrape_complete.call_args[0][0]
    assert payload.batch_id == "batch-pipeline-test"
    assert payload.total_opportunities == 1
    assert payload.succeeded_sources == ["grabscholarship"]


@pytest.mark.asyncio
async def test_scraper_service_in_batch_deduplication():
    """
    اختبار التحقق من كشف التكرار داخل نفس الدفعة:
    عنصران متطابقان في نفس المصدر يجب أن يحفظ الأول ويوسم الثاني كـ duplicate.
    """
    mock_source = MagicMock()
    mock_source.id = "src-dedup"
    mock_source.name = "grabscholarship"
    mock_source.base_url = "https://grabscholarships.com"
    mock_source.api_endpoint = "/wp-json/wp/v2/posts"
    mock_source.method = "wordpress_api"
    mock_source.pagination_config = {"limit": 10}
    mock_source.field_mapping = {}

    mock_source_repo = MagicMock()
    mock_source_repo.get_by_ids = AsyncMock(return_value=[mock_source])
    mock_source_repo.mark_scraped = AsyncMock()

    raw_counter = 0

    async def mock_create_raw(source_id, raw_payload, status, source_url):
        nonlocal raw_counter
        raw_counter += 1
        return MagicMock(id=f"raw-{raw_counter}")

    mock_opp_repo = MagicMock()
    mock_opp_repo.create_raw = AsyncMock(side_effect=mock_create_raw)
    mock_opp_repo.create_cleaned = AsyncMock()
    mock_opp_repo.mark_raw_status = AsyncMock()
    mock_opp_repo.exists_by_content_hash = AsyncMock(return_value=False)

    mock_webhook = MagicMock()
    mock_webhook.notify_scrape_complete = AsyncMock(return_value=True)

    # Two duplicate items in the same batch
    duplicate_posts = [
        {
            "title": {"rendered": "DAAD Master Scholarship in Germany 2026"},
            "content": {"rendered": "<p>Fully funded master program in Germany.</p>"},
            "categories": ["Scholarships", "Germany"],
            "link": "https://grabscholarships.com/daad-1/",
        },
        {
            "title": {"rendered": "  DAAD Master Scholarship in Germany 2026  "},
            "content": {"rendered": "<p>Fully funded master program in Germany.</p>"},
            "categories": ["Scholarships", "Germany"],
            "link": "https://grabscholarships.com/daad-2/",
        },
    ]

    mock_http_response = MagicMock()
    mock_http_response.json.return_value = duplicate_posts
    mock_http_response.is_success = True

    mock_http_client = MagicMock()
    mock_http_client.get = AsyncMock(return_value=mock_http_response)
    mock_http_client.close = AsyncMock()

    cleaning_service = CleaningService()
    normalization_service = NormalizationService()
    deduplication_service = DeduplicationService(opportunity_repo=mock_opp_repo)

    service = ScraperService(
        source_repo=mock_source_repo,
        opportunity_repo=mock_opp_repo,
        cleaning_service=cleaning_service,
        normalization_service=normalization_service,
        deduplication_service=deduplication_service,
        webhook_client=mock_webhook,
    )

    with patch(
        "src.modules.scraping.adapters.base_adapter.BaseHttpClient",
        return_value=mock_http_client,
    ):
        result = await service.run(
            source_ids=["src-dedup"], batch_id="batch-dedup-test"
        )

    # Only 1 unique opportunity should be counted and saved
    assert result.total_opportunities == 1
    assert mock_opp_repo.create_cleaned.call_count == 1

    # The second raw record must be marked as 'duplicate'
    mock_opp_repo.mark_raw_status.assert_any_call("raw-2", status="duplicate")


@pytest.mark.asyncio
async def test_scraper_service_malformed_raw_item_resilience():
    """
    اختبار صمود المعالجة عند وجود عنصر تالف (بدون عنوان):
    يتم تسجيل العنصر التالف كـ failed ومتابعة حفظ باقي العناصر الصالحة.
    """
    mock_source = MagicMock()
    mock_source.id = "src-malformed"
    mock_source.name = "grabscholarship"
    mock_source.base_url = "https://grabscholarships.com"
    mock_source.api_endpoint = "/wp-json/wp/v2/posts"
    mock_source.method = "wordpress_api"
    mock_source.pagination_config = {"limit": 10}
    mock_source.field_mapping = {}

    mock_source_repo = MagicMock()
    mock_source_repo.get_by_ids = AsyncMock(return_value=[mock_source])
    mock_source_repo.mark_scraped = AsyncMock()

    raw_counter = 0

    async def mock_create_raw(source_id, raw_payload, status, source_url):
        nonlocal raw_counter
        raw_counter += 1
        return MagicMock(id=f"raw-{raw_counter}")

    mock_opp_repo = MagicMock()
    mock_opp_repo.create_raw = AsyncMock(side_effect=mock_create_raw)
    mock_opp_repo.create_cleaned = AsyncMock()
    mock_opp_repo.mark_raw_status = AsyncMock()
    mock_opp_repo.exists_by_content_hash = AsyncMock(return_value=False)

    mock_webhook = MagicMock()
    mock_webhook.notify_scrape_complete = AsyncMock(return_value=True)

    # 1 malformed post (no title but marked as scholarship) + 1 valid post
    posts = [
        {
            "title": {"rendered": ""},
            "content": {
                "rendered": "<p>Apply now for scholarship. Full funding available.</p>"
            },
            "categories": ["Scholarships"],
            "link": "https://grabscholarships.com/broken-post/",
        },
        {
            "title": {"rendered": "Oxford Clarendon Scholarship in UK"},
            "content": {"rendered": "<p>Fully funded postgraduate scholarship.</p>"},
            "categories": ["Scholarships", "UK"],
            "link": "https://grabscholarships.com/oxford-clarendon/",
        },
    ]

    mock_http_response = MagicMock()
    mock_http_response.json.return_value = posts
    mock_http_response.is_success = True

    mock_http_client = MagicMock()
    mock_http_client.get = AsyncMock(return_value=mock_http_response)
    mock_http_client.close = AsyncMock()

    cleaning_service = CleaningService()
    normalization_service = NormalizationService()
    deduplication_service = DeduplicationService(opportunity_repo=mock_opp_repo)

    service = ScraperService(
        source_repo=mock_source_repo,
        opportunity_repo=mock_opp_repo,
        cleaning_service=cleaning_service,
        normalization_service=normalization_service,
        deduplication_service=deduplication_service,
        webhook_client=mock_webhook,
    )

    with patch(
        "src.modules.scraping.adapters.base_adapter.BaseHttpClient",
        return_value=mock_http_client,
    ):
        result = await service.run(
            source_ids=["src-malformed"], batch_id="batch-malformed-test"
        )

    # The valid opportunity is processed successfully
    assert result.total_opportunities == 1
    assert mock_opp_repo.create_cleaned.call_count == 1

    # The broken item (raw-1) is marked failed with error_message
    call_args_list = mock_opp_repo.mark_raw_status.call_args_list
    failed_calls = [
        c
        for c in call_args_list
        if c[0][0] == "raw-1" and c[1].get("status") == "failed"
    ]
    assert len(failed_calls) == 1
    assert "error_message" in failed_calls[0][1]
    assert failed_calls[0][1]["error_message"] is not None


@pytest.mark.asyncio
async def test_scraper_service_source_failure_resilience():
    """اختبار صمود خدمة الجلب عند فشل مصدر واستمرار باقي المصادر."""
    mock_source_repo = MagicMock()
    source_a = MagicMock()
    source_a.id = "src-a"
    source_a.name = "source_failing"
    source_a.base_url = "https://failing.com"
    source_a.api_endpoint = "/wp-json/wp/v2/posts"
    source_a.method = "wordpress_api"
    source_a.pagination_config = {}
    source_a.field_mapping = {}

    source_b = MagicMock()
    source_b.id = "src-b"
    source_b.name = "source_succeeding"
    source_b.base_url = "https://succeeding.com"
    source_b.api_endpoint = "/wp-json/wp/v2/posts"
    source_b.method = "wordpress_api"
    source_b.pagination_config = {}
    source_b.field_mapping = {}

    mock_source_repo.get_by_ids = AsyncMock(return_value=[source_a, source_b])
    mock_source_repo.mark_scraped = AsyncMock()

    mock_opp_repo = MagicMock()
    mock_opp_repo.create_raw = AsyncMock(return_value=MagicMock(id="raw-1"))
    mock_opp_repo.create_cleaned = AsyncMock()
    mock_opp_repo.mark_raw_status = AsyncMock()
    mock_opp_repo.exists_by_content_hash = AsyncMock(return_value=False)

    mock_webhook = MagicMock()
    mock_webhook.notify_scrape_complete = AsyncMock(return_value=True)

    service = ScraperService(
        source_repo=mock_source_repo,
        opportunity_repo=mock_opp_repo,
        webhook_client=mock_webhook,
    )

    async def mock_process(source):
        if source.name == "source_failing":
            raise RuntimeError("Connection timed out on source A")
        return 2

    service._process_source = AsyncMock(side_effect=mock_process)

    result = await service.run(
        source_ids=["src-a", "src-b"], batch_id="batch-resilience"
    )

    assert result.total_opportunities == 2
    assert result.succeeded_sources == ["source_succeeding"]
    assert result.failed_sources == ["source_failing"]

    # Verify webhook received the partial success status
    mock_webhook.notify_scrape_complete.assert_called_once()
    payload = mock_webhook.notify_scrape_complete.call_args[0][0]
    assert payload.total_opportunities == 2
    assert payload.succeeded_sources == ["source_succeeding"]
    assert payload.failed_sources == ["source_failing"]


@pytest.mark.asyncio
async def test_scraper_service_webhook_failure_does_not_fail_scrape():
    """Explicit business requirement: Webhook delivery failure MUST NOT fail the scraping run."""
    mock_source = MagicMock()
    mock_source.id = "src-webhook-fail"
    mock_source.name = "almin7"
    mock_source.base_url = "https://almin7.com"
    mock_source.api_endpoint = "/wp-json/wp/v2/posts"
    mock_source.method = "wordpress_api"
    mock_source.pagination_config = {}
    mock_source.field_mapping = {}

    mock_source_repo = MagicMock()
    mock_source_repo.get_by_ids = AsyncMock(return_value=[mock_source])
    mock_source_repo.mark_scraped = AsyncMock()

    mock_opp_repo = MagicMock()
    mock_opp_repo.create_raw = AsyncMock(return_value=MagicMock(id="raw-1"))
    mock_opp_repo.create_cleaned = AsyncMock()
    mock_opp_repo.mark_raw_status = AsyncMock()
    mock_opp_repo.exists_by_content_hash = AsyncMock(return_value=False)

    # Webhook client raises an exception
    failing_webhook = MagicMock()
    failing_webhook.notify_scrape_complete = AsyncMock(
        side_effect=RuntimeError(
            "Main Service Webhook Connection Refused (port 3000 down)"
        )
    )

    service = ScraperService(
        source_repo=mock_source_repo,
        opportunity_repo=mock_opp_repo,
        webhook_client=failing_webhook,
    )
    service._process_source = AsyncMock(return_value=5)

    result = await service.run(
        source_ids=["src-webhook-fail"], batch_id="batch-webhook-fail"
    )

    # Scrape run must still succeed with total_opportunities == 5
    assert result.total_opportunities == 5
    assert result.succeeded_sources == ["almin7"]
    assert len(result.failed_sources) == 0
