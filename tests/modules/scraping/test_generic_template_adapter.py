import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.modules.scraping.adapters.generic_template_adapter import (
    ExtractionError,
    GenericTemplateAdapter,
    TemplateValidationError,
)
from src.modules.scraping.models.cleaned_opportunity import (
    CleanedOpportunityBase,
    CleanedOpportunityDTO,
)
from src.modules.scraping.services.cleaning_service import CleaningService
from src.modules.scraping.services.normalization_service import NormalizationService


@pytest.fixture
def template_path() -> Path:
    return (
        Path(__file__).parent.parent.parent.parent
        / "src"
        / "modules"
        / "scraping"
        / "templates"
        / "almin7.json"
    )


@pytest.fixture
def almin7_template_dict(template_path: Path) -> dict:
    with open(template_path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_listing_html() -> str:
    return """
    <html>
      <body>
        <div class="posts">
          <article class="al7-scholarship-page-card post-1 scholarship type-scholarship location-turkey">
            <h2 class="al7-archive-posttitle">
              <a href="/scholarship/turkey-1/">منحة الحكومة التركية 2026</a>
            </h2>
            <div class="al7-archive-meta">
              <span class="al7-archive-type">منحة</span>
            </div>
            <p class="al7-archive-excerpt">منحة ممولة بالكامل لدراسة البكالوريوس والماجستير.</p>
            <div class="al7-archive-taxline">
              <a href="/location/turkey/">تركيا</a>
            </div>
            <div class="al7-archive-cardfoot">
              <span>20 مارس، 2026</span>
              <a class="al7-archive-action" href="https://turkiye.gov.tr/apply">التقديم الرسمي</a>
            </div>
          </article>
          <article class="al7-scholarship-page-card post-2 post type-post category-articles">
            <h2 class="al7-archive-posttitle">
              <a href="/article-2/">نصائح وإرشادات عامة للدراسة في الخارج</a>
            </h2>
            <div class="al7-archive-meta">
              <span class="al7-archive-type">مقال</span>
            </div>
            <p class="al7-archive-excerpt">مقال عام غير مرتبط بمنحة.</p>
          </article>
        </div>
      </body>
    </html>
    """


@pytest.fixture
def sample_detail_html() -> str:
    return """
    <html>
      <body>
        <h1 class="al7-single-title">منحة جامعة ميونخ في ألمانيا 2026</h1>
        <div class="al7-single-tax-panel">
          <a href="https://almin7.com/location/germany/" class="al7-single-tax-pill">ألمانيا</a>
          <a href="https://almin7.com/university/tum/" class="al7-single-tax-pill">جامعة ميونخ التقنية</a>
          <a href="https://almin7.com/nationality/palestine/" class="al7-single-tax-pill">فلسطين</a>
          <a href="https://almin7.com/nationality/jordan/" class="al7-single-tax-pill">الأردن</a>
        </div>
        <a href="https://tum.de/apply" class="al7-single-apply-beam">التقديم الرسمي</a>
        <div class="al7-single-content">
          <p>تفاصيل المنحة لدراسة ماجستير أو دكتوراه Master PhD في ألمانيا.</p>
          <h2>شروط التقديم</h2>
          <p>الحصول على معدل جيد جداً وإتقان اللغة الإنجليزية بمستوى B2 على الأقل.</p>
          <h2>التخصصات المتاحة</h2>
          <ul>
            <li>علوم الحاسب، الذكاء الاصطناعي، الأمن السيبراني</li>
            <li>الهندسة الميكانيكية، الهندسة الكهربائية</li>
          </ul>
          <h2>ما الذي تقدمه</h2>
          <p>تمويل كامل للرسوم الدراسية مع راتب شهري قدره 1200 يورو وتأمين صحي.</p>
          <h2>المواعيد النهائية</h2>
          <p>آخر موعد للتقديم: 15 يونيو 2026.</p>
        </div>
      </body>
    </html>
    """


# ==========================================
# Base Template Loading & Structure Tests
# ==========================================


def test_load_valid_template(template_path: Path, almin7_template_dict: dict):
    adapter1 = GenericTemplateAdapter(template=template_path)
    assert adapter1.source_name == "almin7"
    assert adapter1.base_url == "https://almin7.com"

    adapter2 = GenericTemplateAdapter(template=almin7_template_dict)
    assert adapter2.source_name == "almin7"

    adapter3 = GenericTemplateAdapter(template=json.dumps(almin7_template_dict))
    assert adapter3.source_name == "almin7"


def test_reject_invalid_template():
    with pytest.raises(TemplateValidationError):
        GenericTemplateAdapter(template={"detail_rules": {}})

    with pytest.raises(TemplateValidationError):
        GenericTemplateAdapter(template={"source_name": "test"})

    with pytest.raises(TemplateValidationError):
        GenericTemplateAdapter(
            template={"source_name": "test", "listing_rules": {"fields": {}}}
        )

    with pytest.raises(TemplateValidationError):
        GenericTemplateAdapter(template=123)  # type: ignore


# ==========================================
# Issue 1: Generic Selector Tests (No Almin7 Defaults in Code)
# ==========================================


def test_generic_adapter_without_almin7_selectors():
    """A completely generic template with custom non-Almin7 selectors."""
    custom_template = {
        "source_name": "custom_portal",
        "base_url": "https://example.org",
        "detail_rules": {
            "fields": {
                "title": {
                    "selector": "h1.grant-title",
                    "extract": "text",
                    "required": True,
                },
            },
            "taxonomy_rules": {
                "container_selector": "div.meta-badges",
                "item_selector": "span.badge-pill",
                "mapping": {
                    "country": {"class_markers": ["country-tag"]},
                    "organization": {"class_markers": ["sponsor-tag"]},
                    "nationalities": {"class_markers": ["nat-tag"]},
                },
            },
        },
    }

    custom_html = """
    <html>
      <body>
        <h1 class="grant-title">European Research Fellowship</h1>
        <div class="meta-badges">
          <span class="badge-pill country-tag">France</span>
          <span class="badge-pill sponsor-tag">Sorbonne University</span>
          <span class="badge-pill nat-tag">Egypt</span>
        </div>
      </body>
    </html>
    """

    adapter = GenericTemplateAdapter(template=custom_template)
    detail = adapter.extract_from_detail_html(custom_html)

    assert detail["title"] == "European Research Fellowship"
    assert detail["country"] == "France"
    assert detail["organization"] == "Sorbonne University"
    assert detail["eligible_nationalities"] == ["Egypt"]


def test_generic_adapter_taxonomy_missing_container():
    """When taxonomy container is missing in HTML, returns empty taxonomy dictionary safely."""
    custom_template = {
        "source_name": "test_missing",
        "base_url": "https://example.org",
        "detail_rules": {
            "fields": {
                "title": {"selector": "h1", "extract": "text", "required": True},
            },
            "taxonomy_rules": {
                "container_selector": "div.non-existent-tags",
                "item_selector": "span.tag",
                "mapping": {
                    "country": {"class_markers": ["country"]},
                },
            },
        },
    }

    html = "<html><body><h1>Simple Title</h1></body></html>"
    adapter = GenericTemplateAdapter(template=custom_template)
    detail = adapter.extract_from_detail_html(html)

    assert detail["title"] == "Simple Title"
    assert detail.get("country") is None
    assert detail.get("eligible_nationalities") is None


# ==========================================
# Issue 2: Safe Nationality Handling Tests
# ==========================================


def test_nationalities_generic_dump_filtered(almin7_template_dict: dict):
    """Generic 27-country default dump without specific text should be safely cleared."""
    generic_27_pills = "".join(
        [
            f'<a href="https://almin7.com/nationality/{i}/" class="al7-single-tax-pill">{nat}</a>'
            for i, nat in enumerate(
                [
                    "إريتريا",
                    "الأردن",
                    "الإمارات",
                    "البحرين",
                    "الجزائر",
                    "السعودية",
                    "السودان",
                    "الصومال",
                    "العراق",
                    "الكويت",
                    "المغرب",
                    "النيجر",
                    "اليمن",
                    "تشاد",
                    "تونس",
                    "جزر القمر",
                    "جنوب السودان",
                    "جيبوتي",
                    "سوريا",
                    "عُمان",
                    "فلسطين",
                    "قطر",
                    "لبنان",
                    "ليبيا",
                    "مالي",
                    "مصر",
                    "موريتانيا",
                ]
            )
        ]
    )

    html = f"""
    <html>
      <body>
        <h1 class="al7-single-title">منحة الجامعة الرومانية الأمريكية</h1>
        <div class="al7-single-tax-panel">
          <a href="https://almin7.com/location/romania/" class="al7-single-tax-pill">رومانيا</a>
          {generic_27_pills}
        </div>
        <div class="al7-single-content">
          <p>شروط عامة دون تحديد جنسية معينة.</p>
        </div>
      </body>
    </html>
    """

    adapter = GenericTemplateAdapter(template=almin7_template_dict)
    detail = adapter.extract_from_detail_html(html)

    assert detail["country"] == "رومانيا"
    # Generic dump must be filtered out
    assert detail.get("eligible_nationalities") == []


def test_nationalities_single_specific_country_preserved(almin7_template_dict: dict):
    """A specific single country (e.g. Saudi Arabia) must be preserved."""
    html = """
    <html>
      <body>
        <h1 class="al7-single-title">منحة برنامج الابتعاث</h1>
        <div class="al7-single-tax-panel">
          <a href="https://almin7.com/nationality/saudi/" class="al7-single-tax-pill">السعودية</a>
        </div>
        <div class="al7-single-content">
          <p>شروط التقديم للأكاديميين.</p>
        </div>
      </body>
    </html>
    """

    adapter = GenericTemplateAdapter(template=almin7_template_dict)
    detail = adapter.extract_from_detail_html(html)

    assert detail.get("eligible_nationalities") == ["السعودية"]


def test_nationalities_specific_small_list_preserved(almin7_template_dict: dict):
    """A specific targeted list (e.g. Palestine and Jordan) is preserved."""
    html = """
    <html>
      <body>
        <h1 class="al7-single-title">منحة دراسات عليا</h1>
        <div class="al7-single-tax-panel">
          <a href="https://almin7.com/nationality/palestine/" class="al7-single-tax-pill">فلسطين</a>
          <a href="https://almin7.com/nationality/jordan/" class="al7-single-tax-pill">الأردن</a>
          <a href="https://almin7.com/nationality/egypt/" class="al7-single-tax-pill">مصر</a>
        </div>
        <div class="al7-single-content">
          <p>التقديم متاح للطلاب من الدول المحددة.</p>
        </div>
      </body>
    </html>
    """

    adapter = GenericTemplateAdapter(template=almin7_template_dict)
    detail = adapter.extract_from_detail_html(html)

    assert set(detail.get("eligible_nationalities", [])) == {"فلسطين", "الأردن", "مصر"}


def test_nationalities_generic_dump_with_explicit_text_match(
    almin7_template_dict: dict,
):
    """When generic dump exists but text says 'مخصصة للطلاب السعوديين فقط', extracts Saudi Arabia."""
    generic_27_pills = "".join(
        [
            f'<a href="https://almin7.com/nationality/{i}/" class="al7-single-tax-pill">{nat}</a>'
            for i, nat in enumerate(
                [
                    "إريتريا",
                    "الأردن",
                    "الإمارات",
                    "البحرين",
                    "الجزائر",
                    "السعودية",
                    "السودان",
                    "الصومال",
                    "العراق",
                    "الكويت",
                    "المغرب",
                    "النيجر",
                    "اليمن",
                    "تشاد",
                    "تونس",
                    "جزر القمر",
                    "جنوب السودان",
                    "جيبوتي",
                    "سوريا",
                    "عُمان",
                    "فلسطين",
                    "قطر",
                    "لبنان",
                    "ليبيا",
                    "مالي",
                    "مصر",
                    "موريتانيا",
                ]
            )
        ]
    )

    html = f"""
    <html>
      <body>
        <h1 class="al7-single-title">منحة التميز الأكاديمي</h1>
        <div class="al7-single-tax-panel">
          {generic_27_pills}
        </div>
        <div class="al7-single-content">
          <p>المنحة مخصصة للطلاب السعوديين فقط وفقاً لتعليمات الوزارة.</p>
        </div>
      </body>
    </html>
    """

    adapter = GenericTemplateAdapter(template=almin7_template_dict)
    detail = adapter.extract_from_detail_html(html)

    assert detail.get("eligible_nationalities") == ["السعودية"]


def test_nationalities_unfiltered_template_behavior():
    """A template without filter_generic_dumps set to true keeps all extracted items."""
    unfiltered_template = {
        "source_name": "unfiltered_source",
        "base_url": "https://example.org",
        "detail_rules": {
            "fields": {
                "title": {"selector": "h1", "extract": "text", "required": True},
            },
            "taxonomy_rules": {
                "container_selector": "div.tags",
                "item_selector": "span.tag",
                "mapping": {
                    "nationalities": {
                        "class_markers": ["nat"],
                        "filter_generic_dumps": False,
                    }
                },
            },
        },
    }

    tags = "".join([f'<span class="tag nat">Country-{i}</span>' for i in range(30)])
    html = f"<html><body><h1>Title</h1><div class='tags'>{tags}</div></body></html>"

    adapter = GenericTemplateAdapter(template=unfiltered_template)
    detail = adapter.extract_from_detail_html(html)

    assert len(detail.get("eligible_nationalities", [])) == 30


# ==========================================
# Issue 3: Safe Relative and Absolute URL Resolution Tests
# ==========================================


def test_resolve_url_variations():
    adapter = GenericTemplateAdapter(
        template={
            "source_name": "test_url",
            "base_url": "https://almin7.com",
            "listing_rules": {
                "card_selector": "article",
                "fields": {
                    "title": {"selector": "h2", "extract": "text"},
                    "source_url": {"selector": "a", "extract": "href"},
                },
            },
        }
    )

    # 1. Relative with leading slash
    assert (
        adapter._resolve_url("/scholarship/123/")
        == "https://almin7.com/scholarship/123/"
    )

    # 2. Relative without leading slash
    assert (
        adapter._resolve_url("scholarship/456/")
        == "https://almin7.com/scholarship/456/"
    )

    # 3. Absolute HTTPS URL
    assert (
        adapter._resolve_url("https://scholarships.univ.edu/post/789")
        == "https://scholarships.univ.edu/post/789"
    )

    # 4. Absolute HTTP URL
    assert adapter._resolve_url("http://example.org/page") == "http://example.org/page"

    # 5. Empty or None
    assert adapter._resolve_url("") is None
    assert adapter._resolve_url(None) is None
    assert adapter._resolve_url("   ") is None

    # 6. Disallowed / unsafe protocols
    assert adapter._resolve_url("javascript:void(0)") is None
    assert adapter._resolve_url("mailto:info@almin7.com") is None
    assert adapter._resolve_url("#content") is None
    assert adapter._resolve_url("data:text/html;base64,abc") is None
    assert adapter._resolve_url("tel:+123456789") is None


@pytest.mark.asyncio
async def test_fetch_with_details_resolves_relative_urls():
    """Verify that fetch_with_details properly resolves relative URLs before calling HTTP client."""
    mock_http = MagicMock()
    mock_response = MagicMock()
    mock_response.text = (
        "<html><body><h1 class='al7-single-title'>Detail Title</h1></body></html>"
    )
    mock_http.get = AsyncMock(return_value=mock_response)

    adapter = GenericTemplateAdapter(
        template={
            "source_name": "test_fetch",
            "base_url": "https://almin7.com",
            "listing_rules": {
                "card_selector": "article",
                "fields": {
                    "title": {"selector": "h2", "extract": "text"},
                    "source_url": {"selector": "a", "extract": "href"},
                },
            },
            "detail_rules": {
                "fields": {
                    "title": {
                        "selector": "h1.al7-single-title",
                        "extract": "text",
                        "required": True,
                    },
                }
            },
        },
        http_client=mock_http,
    )

    # Simulate fetch() returning an item with a relative URL
    adapter.fetch = AsyncMock(
        return_value=[
            {"title": "Card 1", "source_url": "/scholarship/item-1/"},
            {"title": "Card 2", "source_url": "https://external.org/item-2/"},
            {"title": "Card 3", "source_url": "javascript:void(0)"},
        ]
    )

    results = await adapter.fetch_with_details(limit=3)

    assert len(results) == 3
    # First item resolved relative to base_url
    assert results[0]["source_url"] == "https://almin7.com/scholarship/item-1/"
    # Second item kept absolute
    assert results[1]["source_url"] == "https://external.org/item-2/"
    # Third item unsafe URL ignored for details
    assert results[2]["source_url"] == "javascript:void(0)"

    # Verify HTTP GET was called with resolved URLs
    called_urls = [call.args[0] for call in mock_http.get.call_args_list]
    assert "https://almin7.com/scholarship/item-1/" in called_urls
    assert "https://external.org/item-2/" in called_urls
    assert "javascript:void(0)" not in called_urls


# ==========================================
# Extraction & Pipeline Integration Tests
# ==========================================


def test_extract_items_from_listing_html(
    almin7_template_dict: dict, sample_listing_html: str
):
    adapter = GenericTemplateAdapter(template=almin7_template_dict)
    items = adapter.extract_items_from_listing_html(sample_listing_html)

    assert len(items) == 2

    first_item = items[0]
    assert first_item["title"] == "منحة الحكومة التركية 2026"
    assert first_item["source_url"] == "https://almin7.com/scholarship/turkey-1/"
    assert first_item["badge"] == "منحة"
    assert first_item[
        "country"
    ] == "https://almin7.com/location/turkey/" or "تركيا" in first_item.get(
        "country", ""
    )
    assert first_item["application_url"] == "https://turkiye.gov.tr/apply"
    assert adapter.is_opportunity(first_item) is True

    second_item = items[1]
    assert second_item["badge"] == "مقال"
    assert adapter.is_opportunity(second_item) is False


def test_extract_from_detail_html(almin7_template_dict: dict, sample_detail_html: str):
    adapter = GenericTemplateAdapter(template=almin7_template_dict)
    detail = adapter.extract_from_detail_html(
        sample_detail_html,
        source_url="https://almin7.com/scholarship/tum-2026/",
    )

    assert detail["title"] == "منحة جامعة ميونخ في ألمانيا 2026"
    assert detail["country"] == "ألمانيا"
    assert detail["organization"] == "جامعة ميونخ التقنية"
    assert detail["application_url"] == "https://tum.de/apply"
    assert "فلسطين" in detail["eligible_nationalities"]
    assert "الأردن" in detail["eligible_nationalities"]
    assert "معدل جيد جداً" in detail["eligibility_text"]
    assert "علوم الحاسب" in detail["fields_of_study"]
    assert "تمويل كامل" in detail["funding_details"]
    assert "15 يونيو 2026" in detail["deadline"]


def test_real_almin7_detail_file(almin7_template_dict: dict):
    real_file = Path(__file__).parent.parent.parent.parent / "almin7_detail.html"
    if not real_file.exists():
        pytest.skip("almin7_detail.html not found in repository root")

    with open(real_file, encoding="utf-8") as f:
        html = f.read()

    adapter = GenericTemplateAdapter(template=almin7_template_dict)
    detail = adapter.extract_from_detail_html(
        html,
        source_url="https://almin7.com/scholarship/romanian-american-university/",
    )

    assert "الجامعة الرومانية الأمريكية" in detail["title"]
    assert detail["country"] == "رومانيا"
    assert detail["organization"] == "الجامعة الرومانية الأمريكية"
    assert (
        detail["application_url"]
        == "https://www.rau.ro/scholarship-regulations/?lang=en"
    )
    assert detail.get("eligibility_text") is not None
    assert len(detail.get("fields_of_study", [])) > 0
    # In the real file, there are 27 generic Arab nationality pills, so generic dump filtering clears them safely
    assert detail.get("eligible_nationalities") == []


def test_missing_optional_fields_handling(almin7_template_dict: dict):
    minimal_html = (
        "<html><body><h1 class='al7-single-title'>منحة بسيطة</h1></body></html>"
    )
    adapter = GenericTemplateAdapter(template=almin7_template_dict)
    detail = adapter.extract_from_detail_html(minimal_html)

    assert detail["title"] == "منحة بسيطة"
    assert detail.get("country") is None
    assert detail.get("application_url") is None
    assert detail.get("eligibility_text") is None
    assert detail.get("fields_of_study") is None


def test_empty_or_mismatched_html(almin7_template_dict: dict):
    adapter = GenericTemplateAdapter(template=almin7_template_dict)

    assert adapter.extract_items_from_listing_html("") == []
    assert adapter.extract_from_detail_html("") == {}

    mismatched_html = "<html><body><div>Random text</div></body></html>"
    with pytest.raises(ExtractionError):
        adapter.extract_from_detail_html(mismatched_html)


def test_pipeline_and_pydantic_compatibility(
    almin7_template_dict: dict, sample_detail_html: str
):
    adapter = GenericTemplateAdapter(template=almin7_template_dict)
    detail = adapter.extract_from_detail_html(
        sample_detail_html,
        source_url="https://almin7.com/scholarship/tum-2026/",
    )

    # Parse through adapter
    parsed = adapter.parse(detail)
    assert parsed["title"] == "منحة جامعة ميونخ في ألمانيا 2026"
    assert parsed["source_url"] == "https://almin7.com/scholarship/tum-2026/"

    # Pass through CleaningService
    cleaner = CleaningService()
    cleaned = cleaner.clean(parsed)
    assert cleaned["title"] == "منحة جامعة ميونخ في ألمانيا 2026"
    assert cleaned["application_url"] == "https://tum.de/apply"

    # Pass through NormalizationService
    normalizer = NormalizationService()
    normalized = normalizer.normalize(cleaned)
    assert normalized["opportunity_type"] == "scholarship"
    assert normalized["funding_type"] == "fully_funded"
    assert "Master" in normalized["study_levels"]
    assert "PhD" in normalized["study_levels"]
    assert normalized["country"] == "Germany"

    # Validate against CleanedOpportunityBase
    base_model = CleanedOpportunityBase(**normalized)
    assert base_model.title == "منحة جامعة ميونخ في ألمانيا 2026"
    assert base_model.country == "Germany"

    # Validate against CleanedOpportunityDTO
    source_id = uuid4()
    dto = CleanedOpportunityDTO(source_id=source_id, **normalized)
    assert dto.title == "منحة جامعة ميونخ في ألمانيا 2026"
    assert dto.funding_type == "fully_funded"
    assert dto.source_id == source_id


def test_no_dynamic_code_execution(almin7_template_dict: dict):
    template_str = json.dumps(almin7_template_dict)
    assert "__import__" not in template_str
    assert "eval(" not in template_str
    assert "exec(" not in template_str
    assert "os.system" not in template_str
