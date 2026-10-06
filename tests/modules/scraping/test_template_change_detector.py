"""
Unit test suite for TemplateChangeDetector.

Tests all six classification outcomes (VALID, INVALID_TEMPLATE, NETWORK_ERROR,
INSUFFICIENT_DATA, STRUCTURE_CHANGED, EXTRACTION_DEGRADED), metric calculations,
baseline comparison, and active template protection safeguards.
"""

from pathlib import Path

import pytest

from src.modules.scraping.templates.change_detector import (
    ChangeDetectionStatus,
    PageFetchResult,
    TemplateChangeDetector,
)


@pytest.fixture
def sample_valid_template():
    return {
        "$schema_version": "1.0",
        "source_name": "test_source",
        "base_url": "https://example.org",
        "detail_rules": {
            "fields": {
                "title": {
                    "selector": "h1.title",
                    "extract": "text",
                    "required": True,
                },
                "deadline": {
                    "selector": "span.deadline",
                    "extract": "text",
                    "required": False,
                },
                "country": {
                    "selector": "span.country",
                    "extract": "text",
                    "required": False,
                },
                "application_url": {
                    "selector": "a.apply",
                    "extract": "href",
                    "required": False,
                },
            }
        },
    }


@pytest.fixture
def sample_valid_html():
    return """
    <html>
      <body>
        <h1 class="title">Global Excellence Scholarship 2026</h1>
        <span class="deadline">Deadline: 2026-11-30</span>
        <span class="country">Germany</span>
        <a class="apply" href="https://example.org/apply">Apply Now</a>
      </body>
    </html>
    """


# =========================================================================
# 1. Classification Status: INVALID_TEMPLATE
# =========================================================================


def test_detection_invalid_template():
    """Static schema validation failure must classify outcome as INVALID_TEMPLATE."""
    detector = TemplateChangeDetector()
    invalid_template = {
        "$schema_version": "1.0",
        # Missing source_name and missing listing/detail_rules
    }
    fetch = PageFetchResult(
        url="https://example.org/test", success=True, html="<html></html>"
    )
    res = detector.evaluate(invalid_template, detail_fetches=[fetch])

    assert res.status == ChangeDetectionStatus.INVALID_TEMPLATE
    assert res.valid is False
    assert res.quality_score == 0.0
    assert len(res.errors) > 0


# =========================================================================
# 2. Classification Status: NETWORK_ERROR
# =========================================================================


def test_detection_network_error():
    """Network failure or HTTP timeout must classify outcome as NETWORK_ERROR, not STRUCTURE_CHANGED."""
    detector = TemplateChangeDetector()
    template = {
        "$schema_version": "1.0",
        "source_name": "test_net",
        "detail_rules": {
            "fields": {"title": {"selector": "h1", "extract": "text", "required": True}}
        },
    }
    failed_fetch = PageFetchResult(
        url="https://example.org/test",
        success=False,
        status_code=504,
        error_type="timeout",
        error_message="Gateway Timeout 504",
        html=None,
    )

    res = detector.evaluate(template, detail_fetches=[failed_fetch])

    assert res.status == ChangeDetectionStatus.NETWORK_ERROR
    assert res.valid is False
    assert res.quality_score == 0.0
    assert any("Timeout" in e or "fetch failed" in e.lower() for e in res.errors)


# =========================================================================
# 3. Classification Status: INSUFFICIENT_DATA
# =========================================================================


def test_detection_insufficient_data(sample_valid_template):
    """When number of valid HTML samples is less than min_detail_samples, return INSUFFICIENT_DATA."""
    detector = TemplateChangeDetector(min_detail_samples=2)
    single_fetch = PageFetchResult(
        url="https://example.org/1",
        success=True,
        html="<html><body><h1 class='title'>T</h1></body></html>",
    )

    res = detector.evaluate(sample_valid_template, detail_fetches=[single_fetch])

    assert res.status == ChangeDetectionStatus.INSUFFICIENT_DATA
    assert res.valid is False
    assert res.detail_samples_evaluated == 1


# =========================================================================
# 4. Classification Status: STRUCTURE_CHANGED
# =========================================================================


def test_detection_structure_changed_required_field_missing(sample_valid_template):
    """When a required field selector matches no elements, classify as STRUCTURE_CHANGED."""
    detector = TemplateChangeDetector()
    changed_html = """
    <html>
      <body>
        <!-- Website changed h1.title tag to div.header-main -->
        <div class="header-main">Global Excellence Scholarship 2026</div>
        <span class="deadline">Deadline: 2026-11-30</span>
      </body>
    </html>
    """
    fetch = PageFetchResult(
        url="https://example.org/changed", success=True, html=changed_html
    )
    res = detector.evaluate(sample_valid_template, detail_fetches=[fetch])

    assert res.status == ChangeDetectionStatus.STRUCTURE_CHANGED
    assert res.valid is False
    assert res.metrics.required_field_success_rate == 0.0
    assert any("title" in e for e in res.errors)


# =========================================================================
# 5. Classification Status: EXTRACTION_DEGRADED
# =========================================================================


def test_detection_extraction_degraded_low_optional_coverage(sample_valid_template):
    """Required fields pass, but missing optional fields drop coverage < threshold -> EXTRACTION_DEGRADED."""
    detector = TemplateChangeDetector(optional_coverage_threshold=0.50)
    # HTML contains title (required), but lacks deadline, country, application_url (0 of 3 optional fields)
    degraded_html = """
    <html>
      <body>
        <h1 class="title">Global Excellence Scholarship 2026</h1>
      </body>
    </html>
    """
    fetch = PageFetchResult(
        url="https://example.org/degraded", success=True, html=degraded_html
    )
    res = detector.evaluate(sample_valid_template, detail_fetches=[fetch])

    assert res.status == ChangeDetectionStatus.EXTRACTION_DEGRADED
    assert res.valid is False
    assert res.metrics.required_field_success_rate == 1.0
    assert res.metrics.optional_field_coverage_rate == 0.0


def test_detection_extraction_degraded_baseline_drop(
    sample_valid_template, sample_valid_html
):
    """Relative drop > 20% compared to previous baseline score triggers EXTRACTION_DEGRADED."""
    detector = TemplateChangeDetector(degradation_threshold=0.20)
    # Baseline score was perfect 1.0. If current HTML only has title, score drops below 0.80 -> degraded
    partial_html = """
    <html>
      <body>
        <h1 class="title">Global Excellence Scholarship 2026</h1>
      </body>
    </html>
    """
    fetch = PageFetchResult(
        url="https://example.org/partial", success=True, html=partial_html
    )
    res = detector.evaluate(
        sample_valid_template, detail_fetches=[fetch], baseline_score=1.0
    )

    assert res.status == ChangeDetectionStatus.EXTRACTION_DEGRADED
    assert res.valid is False
    assert res.metrics.baseline_degradation is not None
    assert res.metrics.baseline_degradation > 0.20


# =========================================================================
# 6. Classification Status: VALID
# =========================================================================


def test_detection_valid_success(sample_valid_template, sample_valid_html):
    """When required fields match and quality metrics meet thresholds, return status VALID."""
    detector = TemplateChangeDetector()
    fetch = PageFetchResult(
        url="https://example.org/valid", success=True, html=sample_valid_html
    )
    res = detector.evaluate(sample_valid_template, detail_fetches=[fetch])

    assert res.status == ChangeDetectionStatus.VALID
    assert res.valid is True
    assert res.quality_score >= 0.75
    assert res.metrics.required_field_success_rate == 1.0
    assert res.metrics.optional_field_coverage_rate == 1.0


# =========================================================================
# 7. Real Fixture Evaluation (almin7 & Scholars4Dev)
# =========================================================================


def test_detection_real_almin7_detail_file():
    """Evaluating production almin7.json template against real almin7_detail.html must return VALID."""
    almin7_template = Path("src/modules/scraping/templates/almin7.json")
    detail_file = Path("almin7_detail.html")

    if not detail_file.exists():
        pytest.skip("almin7_detail.html fixture not present in root")

    html = open(detail_file, encoding="utf-8").read()
    fetch = PageFetchResult(
        url="https://almin7.com/scholarship/romanian-american-university/",
        success=True,
        html=html,
    )

    detector = TemplateChangeDetector()
    res = detector.evaluate(almin7_template, detail_fetches=[fetch])

    assert res.status == ChangeDetectionStatus.VALID
    assert res.valid is True
    assert res.metrics.required_field_success_rate == 1.0


def test_detection_real_scholars4dev_fixtures():
    """Evaluating scholars4dev template against local HTML samples must return VALID."""
    s4d_template = Path(
        r"C:\Users\msi\.gemini\antigravity\brain\768d7fb2-4232-4db4-93cf-66e07eadd7af\scratch\scholars4dev_template.json"
    )
    if not s4d_template.exists():
        pytest.skip("scholars4dev_template.json fixture not present in scratch")

    detector = TemplateChangeDetector(min_detail_samples=3)
    fetches = []
    for fname in ("fulbright_page.html", "vlir_page.html", "warwick_page.html"):
        p = Path(fname)
        if p.exists():
            html = open(p, encoding="utf-8").read()
            fetches.append(
                PageFetchResult(
                    url=f"https://scholars4dev.com/{fname}", success=True, html=html
                )
            )

    if len(fetches) == 3:
        res = detector.evaluate(s4d_template, detail_fetches=fetches)
        assert res.status == ChangeDetectionStatus.VALID
        assert res.valid is True
        assert res.detail_samples_evaluated == 3


# =========================================================================
# 8. Active Template Protection Safeguard
# =========================================================================


def test_active_template_protection_safeguard(sample_valid_template):
    """Detector evaluation must never mutate active template input dictionary or file."""
    import copy

    original_dict = copy.deepcopy(sample_valid_template)

    detector = TemplateChangeDetector()
    changed_html = "<html><body><div>Broken</div></body></html>"
    fetch = PageFetchResult(
        url="https://example.org/broken", success=True, html=changed_html
    )

    # Evaluate against broken page
    res = detector.evaluate(sample_valid_template, detail_fetches=[fetch])
    assert res.status == ChangeDetectionStatus.STRUCTURE_CHANGED

    # Verify original template dict is completely unmutated
    assert sample_valid_template == original_dict
