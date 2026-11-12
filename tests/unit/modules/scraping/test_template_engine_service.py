# [OMA-W005-T028] [OMA-W005-T029] [OMA-W005-T032] [OMA-W008-T007] Unit tests for TemplateEngineService

from unittest.mock import AsyncMock, MagicMock

import pytest
from prisma.models import ScrapingTemplate

from src.modules.infrastructure.llm.base import (
    StructuredCompletion,
    StructuredGenerator,
)
from src.modules.scraping.exceptions import ERR_EXTRACTION_FAILED
from src.modules.scraping.models import ExtractionResult
from src.modules.scraping.services.template_engine_service import (
    FieldMetrics,
    MicroRepairResponse,
    TemplateEngineService,
)
from src.modules.scraping.services.template_engine_service.matcher import (
    evaluate_gate_3_text_bounds,
)
from src.modules.security.exceptions import (
    ERR_SELECTOR_SYNTAX_INVALID,
    SelectorSyntaxInvalidError,
)


# [OMA-W005-T028] Test 3-gate deterministic template matching without AI calls
def test_match_template_deterministic_3_gates():
    """Protects UC-03 & TEST-03: Verifies 3-gate deterministic evaluation matches template with 0 AI calls."""
    sample_html = """
    <html><body>
        <div class="card-container">
            <div class="opportunity-card">
                <h2 class="card-title">Erasmus Fellowship 2026</h2>
                <a class="card-link" href="/scholarships/erasmus-2026">View</a>
                <p class="card-snippet">Fully funded masters program in Europe.</p>
                <img class="card-image" src="https://example.edu/erasmus.jpg" />
            </div>
        </div>
    </body></html>
    """

    # Template 1: Gate 1 failure (container selector does not exist in DOM)
    t1_schema = {
        "schema_name": "t1_missing_container",
        "selectors": {
            "card_container": ".non-existent-table",
            "card_title": ".card-title",
            "card_link": ".card-link",
        },
    }
    t1 = ScrapingTemplate.model_construct(
        id="t1",
        level=1,
        version=1,
        hit_count=100,
        template_schema=t1_schema,
    )

    # Template 2: Gate 2 failure (container exists, but coverage < 80%)
    t2_schema = {
        "schema_name": "t2_low_coverage",
        "selectors": {
            "card_container": ".opportunity-card",
            "card_title": ".card-title",  # matches (1/5)
            "salary": ".salary-amount",  # missing
            "location": ".location-tag",  # missing
            "department": ".dept-name",  # missing
            "supervisor": ".prof-name",  # missing
        },
    }
    t2 = ScrapingTemplate.model_construct(
        id="t2",
        level=1,
        version=1,
        hit_count=80,
        template_schema=t2_schema,
    )

    # Template 3: Gate 3 failure (container exists, coverage >= 80%, but extracted text is whitespace)
    sample_html_empty_text = """
    <html><body>
        <div class="opportunity-card">
            <h2 class="card-title">   </h2>
        </div>
    </body></html>
    """
    t3_schema = {
        "schema_name": "t3_empty_text",
        "selectors": {
            "card_container": ".opportunity-card",
            "card_title": ".card-title",
        },
    }
    t3 = ScrapingTemplate.model_construct(
        id="t3",
        level=1,
        version=1,
        hit_count=50,
        template_schema=t3_schema,
    )

    # Template 4: Passes all 3 gates!
    t4_schema = {
        "schema_name": "t4_perfect_match",
        "selectors": {
            "card_container": ".opportunity-card",
            "card_title": ".card-title",
            "card_link": ".card-link",
            "card_snippet": ".card-snippet",
            "card_image": ".card-image",
        },
    }
    t4 = ScrapingTemplate.model_construct(
        id="t4",
        level=1,
        version=1,
        hit_count=20,
        template_schema=t4_schema,
    )

    mock_llm = MagicMock(spec=StructuredGenerator)
    engine = TemplateEngineService(llm_client=mock_llm)

    # Candidate list: t1 and t2 fail gates, t4 passes
    matched = engine.match_template_deterministic(sample_html, [t1, t2, t4])

    assert matched is not None
    assert matched.id == "t4"
    # Invariant: Zero AI invocations for deterministic hit
    mock_llm.generate.assert_not_called()

    # t3 fails Gate 3 (empty whitespace text)
    matched_t3 = engine.match_template_deterministic(sample_html_empty_text, [t3])
    assert matched_t3 is None


# [OMA-W005-T028] Test Level 1 catalog card extraction with discovered URLs
def test_extract_level_1_catalog():
    """Protects UC-01 & TEST-01: Extracts opportunity card records and discovered URLs for Level 1 catalog."""
    html = """
    <html><body>
        <div class="catalog-list">
            <div class="card">
                <a class="item-title" href="/grants/101">DAAD Scholarship 2026</a>
                <span class="desc">Monthly stipend for graduates.</span>
                <img class="thumb" src="/images/daad.png" />
            </div>
            <div class="card">
                <a class="item-title" href="/grants/102">Fulbright Fellowship</a>
                <span class="desc">Full tuition exchange.</span>
                <img class="thumb" src="/images/fulbright.png" />
            </div>
        </div>
    </body></html>
    """

    schema = {
        "schema_name": "catalog_v1",
        "selectors": {
            "card_container": ".card",
            "card_title": ".item-title",
            "card_link": ".item-title",
            "card_snippet": ".desc",
            "card_image": ".thumb",
        },
    }
    template = ScrapingTemplate.model_construct(
        id="tpl_catalog",
        level=1,
        version=1,
        template_schema=schema,
    )

    engine = TemplateEngineService()
    result = engine.extract_with_template(html, template)

    assert isinstance(result, ExtractionResult)
    assert result.level == 1
    assert result.success is True
    assert result.status == "success"
    assert len(result.discovered_urls) == 2
    assert "/grants/101" in result.discovered_urls
    assert "/grants/102" in result.discovered_urls

    cards = result.data.get("cards", [])
    assert len(cards) == 2
    assert cards[0]["card_title_preview"] == "DAAD Scholarship 2026"
    assert cards[0]["card_snippet_preview"] == "Monthly stipend for graduates."
    assert cards[0]["card_image_url"] == "/images/daad.png"


# [OMA-W005-T028] Test Level 2 detail scholarship extraction and field results telemetry
def test_extract_level_2_detail():
    """Protects UC-01 & TEST-01: Extracts structured educational and grant detail fields for Level 2."""
    html = """
    <html><body>
        <article class="grant-detail">
            <h1 class="scholarship-title">Chevening Masters Scholarship 2026</h1>
            <div class="host-uni">University of Oxford</div>
            <span class="coverage-type">Fully Funded</span>
            <span class="deadline-date">November 5, 2026</span>
            <a class="apply-btn" href="https://chevening.org/apply">Apply Now</a>
        </article>
    </body></html>
    """

    schema = {
        "schema_name": "detail_v1",
        "selectors": {
            "title": ".scholarship-title",
            "host_institution": ".host-uni",
            "financial_coverage": ".coverage-type",
            "deadline": ".deadline-date",
            "application_link": ".apply-btn",
            "missing_field": ".non-existent-box",
        },
    }
    template = ScrapingTemplate.model_construct(
        id="tpl_detail",
        level=2,
        version=1,
        template_schema=schema,
    )

    engine = TemplateEngineService()
    result = engine.extract_with_template(html, template)

    assert result.level == 2
    assert result.success is True
    assert result.data["title"] == "Chevening Masters Scholarship 2026"
    assert result.data["host_institution"] == "University of Oxford"
    assert result.data["financial_coverage"] == "Fully Funded"
    assert result.data["deadline"] == "November 5, 2026"
    assert result.data["application_link"] == "https://chevening.org/apply"

    # Field results telemetry tracking
    field_results = result.data.get("field_results", {})
    assert field_results["title"] is True
    assert field_results["deadline"] is True
    assert field_results["missing_field"] is False


# [OMA-W005-T028] Test extraction failure when HTML content is empty
def test_extract_with_template_empty_html():
    """Protects defensive boundary: Empty HTML returns failed ExtractionResult with ERR_EXTRACTION_FAILED."""
    schema = {"schema_name": "test", "selectors": {"title": "h1"}}
    template = ScrapingTemplate.model_construct(
        id="tpl_test", level=2, version=1, template_schema=schema
    )

    engine = TemplateEngineService()
    result = engine.extract_with_template("", template)

    assert result.success is False
    assert result.status == "failed"
    assert result.error_code == ERR_EXTRACTION_FAILED


# [OMA-W005-T029] Test rolling fill-rate metrics calculation and persistence
@pytest.mark.asyncio
async def test_update_field_metrics():
    """Protects UC-10: Updates rolling fill-rate metrics across consecutive extraction runs."""
    mock_repo = MagicMock()

    # Existing template in DB with 9 runs (8 successful for title, 9 for host)
    existing_template = ScrapingTemplate.model_construct(
        id="tpl_metrics",
        level=2,
        version=1,
        field_metrics={
            "title": {
                "field_name": "title",
                "total_runs": 9,
                "successful_runs": 8,
                "fill_rate": 0.8889,
                "baseline_fill_rate": 1.0,
            }
        },
    )
    mock_repo.get_template_by_id = AsyncMock(return_value=existing_template)
    mock_repo.update_field_metrics = AsyncMock()

    engine = TemplateEngineService(repository=mock_repo)

    # 10th run: title succeeded
    await engine.update_field_metrics(
        source_id="src_1",
        template_id="tpl_metrics",
        field_results={"title": True},
    )

    mock_repo.update_field_metrics.assert_awaited_once()
    call_args = mock_repo.update_field_metrics.call_args[0]
    updated_metrics = call_args[1]

    # After 10th run (9/10 successful): fill_rate = 0.9000
    assert updated_metrics["title"]["total_runs"] == 10
    assert updated_metrics["title"]["successful_runs"] == 9
    assert updated_metrics["title"]["fill_rate"] == 0.9


# [OMA-W005-T029] Test soft-drift detection flagging fields dropped > 40% below baseline
def test_detect_soft_drift():
    """Protects UC-10 & TEST-10: Detects soft-drift degradation where fill rate drops > 40% from baseline."""
    engine = TemplateEngineService()

    # Field 1: baseline 1.0, current fill_rate 0.55 -> drop 0.45 (> 0.40) -> FLAGGED
    # Field 2: baseline 1.0, current fill_rate 0.85 -> drop 0.15 (<= 0.40) -> NOT FLAGGED
    # Field 3: baseline 0.9, current fill_rate 0.40 -> drop 0.50 (> 0.40) -> FLAGGED
    metrics_list = [
        FieldMetrics(
            field_name="deadline",
            fill_rate=0.55,
            baseline_fill_rate=1.0,
            total_runs=20,
            successful_runs=11,
        ),
        FieldMetrics(
            field_name="title",
            fill_rate=0.85,
            baseline_fill_rate=1.0,
            total_runs=20,
            successful_runs=17,
        ),
        FieldMetrics(
            field_name="host_institution",
            fill_rate=0.40,
            baseline_fill_rate=0.90,
            total_runs=20,
            successful_runs=8,
        ),
    ]

    flagged = engine.detect_soft_drift(metrics_list)

    assert "deadline" in flagged
    assert "host_institution" in flagged
    assert "title" not in flagged


# [OMA-W005-T032] Test minimal DOM snippet extraction and minor version increment helper
def test_dom_snippet_and_version_increment():
    """Protects UC-10: Verifies token-efficient DOM snippet extraction and semver minor increments."""
    html = """
    <html><body>
        <div class="main-content">
            <header><h1>University Header</h1></header>
            <div class="application-deadline" id="app_deadline">
                <span>Closing: December 31, 2026</span>
            </div>
            <footer>Contact</footer>
        </div>
    </body></html>
    """

    snippet = TemplateEngineService._extract_dom_snippet(
        html, "application_deadline", max_chars=500
    )
    assert "Closing: December 31, 2026" in snippet
    assert len(snippet) <= 500

    # Minor version increments (v1.0 -> v1.1, v1.9 -> v1.10, 1 -> v1.1)
    assert TemplateEngineService._increment_minor_version("v1.0") == "v1.1"
    assert TemplateEngineService._increment_minor_version("v1.9") == "v1.10"
    assert TemplateEngineService._increment_minor_version("1") == "v1.1"
    assert TemplateEngineService._increment_minor_version("v2.3") == "v2.4"


# [OMA-W005-T032] Test 4-stage validation pipeline on synthesized micro-repair selector
@pytest.mark.asyncio
async def test_validate_synthesized_selector_pipeline():
    """Protects UC-10 & Section 3.3: Verifies 4-stage validation pipeline rejects invalid, bloated, or unsafe selectors."""
    valid_schema = {
        "schema_name": "detail_test",
        "selectors": {"title": "h1.title", "deadline": "span.date"},
    }
    sample_html = "<html><body><h1 class='title'>Test</h1><span class='date'>Tomorrow</span></body></html>"

    # Stage 1a: Empty selector rejected
    with pytest.raises(SelectorSyntaxInvalidError) as exc_info:
        await TemplateEngineService._validate_synthesized_selector(
            replacement_selector="",
            degraded_field="deadline",
            candidate_schema=valid_schema,
            html=sample_html,
        )
    assert exc_info.value.error_code == ERR_SELECTOR_SYNTAX_INVALID

    # Stage 1b: Bloated selector (> 300 chars) rejected
    bloated_sel = "div > " * 60 + "span"
    with pytest.raises(SelectorSyntaxInvalidError) as exc_info2:
        await TemplateEngineService._validate_synthesized_selector(
            replacement_selector=bloated_sel,
            degraded_field="deadline",
            candidate_schema=valid_schema,
            html=sample_html,
        )
    assert exc_info2.value.error_code == ERR_SELECTOR_SYNTAX_INVALID

    # Stage 1c: Malformed CSS syntax rejected
    with pytest.raises(SelectorSyntaxInvalidError) as exc_info3:
        await TemplateEngineService._validate_synthesized_selector(
            replacement_selector="div[unclosed-attribute",
            degraded_field="deadline",
            candidate_schema=valid_schema,
            html=sample_html,
        )
    assert exc_info3.value.error_code == ERR_SELECTOR_SYNTAX_INVALID

    # Valid, clean selector passes all 4 stages without error
    await TemplateEngineService._validate_synthesized_selector(
        replacement_selector="span.date",
        degraded_field="deadline",
        candidate_schema=valid_schema,
        html=sample_html,
    )


# [OMA-W005-T032] Test targeted micro-repair ensuring other selectors remain immutable
@pytest.mark.asyncio
async def test_micro_repair_field_immutability_and_versioning():
    """Protects UC-10 & TEST-10: Micro-repair updates ONLY degraded selector; others remain strictly immutable."""
    html_sample = """
    <html><body>
        <h1 class="post-title">Oxford Rhodes Scholarship</h1>
        <div class="info-box">
            <span class="closing-deadline">October 15, 2026</span>
        </div>
        <p class="summary-body">Prestigious postgraduate award.</p>
    </body></html>
    """

    initial_schema = {
        "schema_name": "rhodes_template",
        "version": "v1.0",
        "selectors": {
            "title": ".post-title",
            "body": ".summary-body",
            "deadline": ".old-dead-selector",  # degraded field
        },
    }

    template = ScrapingTemplate.model_construct(
        id="tpl_rhodes",
        level=2,
        version=1,
        template_schema=initial_schema,
    )

    # Mock structured LLM completion returning replacement selector for deadline
    mock_llm_response = MicroRepairResponse(
        field_name="deadline",
        replacement_selector=".closing-deadline",
        explanation="Updated selector to target .closing-deadline inside .info-box",
    )
    mock_completion = StructuredCompletion(
        output=mock_llm_response,
        model="gemini-2.5-flash",
        input_tokens=150,
        output_tokens=30,
        latency_ms=250,
    )

    mock_llm = MagicMock(spec=StructuredGenerator)
    mock_llm.generate = AsyncMock(return_value=mock_completion)

    async def mock_update_template(t_id, template_schema):
        return ScrapingTemplate.model_construct(
            id=t_id, level=2, version=1, template_schema=template_schema
        )

    mock_repo = MagicMock()
    mock_repo._db = None
    mock_repo.get_template_by_id = AsyncMock(return_value=template)
    mock_repo.update_template = AsyncMock(side_effect=mock_update_template)

    engine = TemplateEngineService(repository=mock_repo, llm_client=mock_llm)

    repaired_template = await engine.micro_repair_field(
        html=html_sample,
        template=template,
        degraded_field="deadline",
    )

    repaired_schema = repaired_template.template_schema
    if hasattr(repaired_schema, "data"):
        repaired_schema = repaired_schema.data

    # Invariant: ONLY 'deadline' selector was modified
    assert repaired_schema["selectors"]["deadline"] == ".closing-deadline"

    # Invariant: Other selectors remain strictly immutable!
    assert repaired_schema["selectors"]["title"] == ".post-title"
    assert repaired_schema["selectors"]["body"] == ".summary-body"

    # Invariant: Minor version incremented (v1.0 -> v1.1)
    assert repaired_schema["version"] == "v1.1"


# [OMA-W008-T007] Test Gate 3 text bounds check: < 3 chars or non-printable content fails Gate 3, substantive passes
def test_gate_3_text_bounds_check():
    """Protects UC-03 & FR-012: Verifies Gate 3 text bounds rejects text < 3 chars or non-printable, while accepting substantive text."""
    # 1. Direct function boundaries verification
    # Empty list fails
    assert evaluate_gate_3_text_bounds([]) is False

    # Text < 3 characters fails
    assert evaluate_gate_3_text_bounds([""]) is False
    assert evaluate_gate_3_text_bounds(["a"]) is False
    assert evaluate_gate_3_text_bounds(["12"]) is False
    assert evaluate_gate_3_text_bounds(["  ok  "]) is False  # stripped length is 2 < 3
    assert evaluate_gate_3_text_bounds(["   "]) is False

    # Non-printable content (< 80% printable characters) fails
    assert evaluate_gate_3_text_bounds(["\x00\x01\x02\x03\x04\x05\x06bad"]) is False
    assert evaluate_gate_3_text_bounds(["\x00\x00\x00test"]) is False

    # Text exceeding 500k characters fails
    assert evaluate_gate_3_text_bounds(["a" * 500_001]) is False

    # Substantive printable text passes
    assert (
        evaluate_gate_3_text_bounds(["abc"]) is True
    )  # boundary: exactly 3 printable chars
    assert evaluate_gate_3_text_bounds(["Fully Funded Masters 2026"]) is True
    assert (
        evaluate_gate_3_text_bounds(
            ["Scholarship Title", "Oxford University", "https://oxford.edu"]
        )
        is True
    )

    # 2. End-to-end integration through TemplateEngineService.match_template_deterministic
    engine = TemplateEngineService()
    template_schema = {
        "schema_name": "gate3_test_schema",
        "selectors": {
            "card_container": ".opportunity-card",
            "card_title": ".card-title",
        },
    }
    template = ScrapingTemplate.model_construct(
        id="t_gate3",
        level=1,
        version=1,
        hit_count=50,
        template_schema=template_schema,
    )

    # DOM with text < 3 characters: fails Gate 3
    html_short_text = """
    <html><body>
        <div class="opportunity-card">
            <h2 class="card-title">hi</h2>
        </div>
    </body></html>
    """
    assert engine.match_template_deterministic(html_short_text, [template]) is None

    # DOM with non-printable content: fails Gate 3
    html_non_printable = """
    <html><body>
        <div class="opportunity-card">
            <h2 class="card-title">\x00\x01\x02\x03\x04\x05\x06broken</h2>
        </div>
    </body></html>
    """
    assert engine.match_template_deterministic(html_non_printable, [template]) is None

    # DOM with substantive text: passes Gate 3
    html_substantive = """
    <html><body>
        <div class="opportunity-card">
            <h2 class="card-title">Erasmus Mundus Scholarship 2026</h2>
        </div>
    </body></html>
    """
    matched = engine.match_template_deterministic(html_substantive, [template])
    assert matched is not None
    assert matched.id == "t_gate3"
