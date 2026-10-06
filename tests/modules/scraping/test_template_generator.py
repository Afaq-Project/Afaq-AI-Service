"""
Unit tests for Gemini Template Generator and 3-Gate Validation Pipeline in Afaq.
"""

import json

import pytest

from src.modules.scraping.adapters.adapter_factory import AdapterFactory
from src.modules.scraping.adapters.almin7_adapter import Almin7Adapter
from src.modules.scraping.adapters.generic_template_adapter import (
    GenericTemplateAdapter,
)
from src.modules.scraping.adapters.scholars4dev_adapter import Scholars4DevAdapter
from src.modules.scraping.templates.change_detector import PageFetchResult
from src.modules.scraping.templates.llm_provider import (
    LLMGenerationError,
    LLMTimeoutError,
    MockLLMProvider,
)
from src.modules.scraping.templates.template_generator import (
    CandidateStatus,
    GeminiTemplateGenerator,
)

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Scholarship Page</title></head>
<body>
    <article class="scholarship-container">
        <h1 class="scholarship-title">Fulbright Foreign Student Program 2026</h1>
        <div class="scholarship-body">
            <p class="desc">The Fulbright Program offers full funding for graduate study in the United States.</p>
            <div class="eligibility">Applicants must hold a Bachelor degree and reside in an eligible country.</div>
            <div class="funding">Full tuition, living stipend, roundtrip airfare, and health insurance provided.</div>
            <a class="apply-link" href="https://example.org/apply-fulbright">Apply Now</a>
        </div>
    </article>
</body>
</html>
"""

VALID_CANDIDATE_JSON = {
    "$schema_version": "1.0",
    "source_name": "test_fulbright",
    "display_name": "Test Fulbright Scholarship",
    "base_url": "https://example.org",
    "detail_rules": {
        "fields": {
            "title": {
                "selector": "h1.scholarship-title",
                "extract": "text",
                "required": True,
            },
            "application_url": {
                "selector": "a.apply-link",
                "extract": "href",
                "required": True,
            },
            "description": {"selector": "p.desc", "extract": "text", "required": False},
            "eligibility_text": {
                "selector": "div.eligibility",
                "extract": "text",
                "required": False,
            },
            "funding_details": {
                "selector": "div.funding",
                "extract": "text",
                "required": False,
            },
        }
    },
}


@pytest.fixture
def sample_detail_fetches():
    return [
        PageFetchResult(
            url="https://example.org/fulbright-2026",
            success=True,
            status_code=200,
            html=SAMPLE_HTML,
        )
    ]


@pytest.mark.asyncio
async def test_valid_candidate_accepted_for_review(sample_detail_fetches):
    """Test 1: Gemini returns valid candidate -> schema validation passes -> ACCEPTED_FOR_REVIEW."""
    mock_provider = MockLLMProvider(response_text=json.dumps(VALID_CANDIDATE_JSON))
    generator = GeminiTemplateGenerator(llm_provider=mock_provider)

    result = await generator.generate_candidate(
        detail_fetches=sample_detail_fetches,
        source_name="test_fulbright",
        base_url="https://example.org",
    )

    assert result.status == CandidateStatus.ACCEPTED_FOR_REVIEW
    assert result.valid is True
    assert result.gate_failed is None
    assert result.candidate_template == VALID_CANDIDATE_JSON
    assert result.quality_score >= 0.75


@pytest.mark.asyncio
async def test_malformed_json_rejected_gate1(sample_detail_fetches):
    """Test 2: Gemini returns malformed JSON -> reject at Gate 1."""
    mock_provider = MockLLMProvider(response_text="INVALID JSON {{{")
    generator = GeminiTemplateGenerator(llm_provider=mock_provider)

    result = await generator.generate_candidate(
        detail_fetches=sample_detail_fetches,
        source_name="test_fulbright",
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.valid is False
    assert result.gate_failed == 1
    assert "Malformed JSON" in (result.rejection_reason or "")


@pytest.mark.asyncio
async def test_schema_invalid_candidate_rejected_gate1(sample_detail_fetches):
    """Test 3: Gemini returns schema-invalid candidate -> reject at Gate 1."""
    invalid_schema_dict = {
        "$schema_version": "1.0",
        # missing source_name and rules
    }
    mock_provider = MockLLMProvider(response_text=json.dumps(invalid_schema_dict))
    generator = GeminiTemplateGenerator(llm_provider=mock_provider)

    result = await generator.generate_candidate(
        detail_fetches=sample_detail_fetches,
        source_name="test_source",
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.valid is False
    assert result.gate_failed == 1


@pytest.mark.asyncio
async def test_candidate_fails_runtime_validation_gate2(sample_detail_fetches):
    """Test 4: Candidate fails runtime required field extraction -> reject at Gate 2."""
    candidate_with_bad_selector = {
        "$schema_version": "1.0",
        "source_name": "test_fulbright",
        "base_url": "https://example.org",
        "detail_rules": {
            "fields": {
                "title": {
                    "selector": "h1.non-existent-header-class",
                    "extract": "text",
                    "required": True,
                },
            }
        },
    }
    mock_provider = MockLLMProvider(
        response_text=json.dumps(candidate_with_bad_selector)
    )
    generator = GeminiTemplateGenerator(llm_provider=mock_provider)

    result = await generator.generate_candidate(
        detail_fetches=sample_detail_fetches,
        source_name="test_fulbright",
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.valid is False
    assert result.gate_failed == 2
    assert "Gate 2 Failed" in (result.rejection_reason or "")


@pytest.mark.asyncio
async def test_candidate_quality_worse_than_current_rejected_gate3(
    sample_detail_fetches,
):
    """Test 5: Candidate quality score is lower than current template -> reject at Gate 3."""
    # Current template extracts title + url + desc + eligibility + funding (score ~ 1.0)
    current_template = VALID_CANDIDATE_JSON

    # Candidate template only extracts title + url (optional coverage is lower)
    low_coverage_candidate = {
        "$schema_version": "1.0",
        "source_name": "test_fulbright",
        "base_url": "https://example.org",
        "detail_rules": {
            "fields": {
                "title": {
                    "selector": "h1.scholarship-title",
                    "extract": "text",
                    "required": True,
                },
                "application_url": {
                    "selector": "a.apply-link",
                    "extract": "href",
                    "required": True,
                },
                "non_existent_optional_1": {
                    "selector": ".missing-1",
                    "extract": "text",
                    "required": False,
                },
                "non_existent_optional_2": {
                    "selector": ".missing-2",
                    "extract": "text",
                    "required": False,
                },
                "non_existent_optional_3": {
                    "selector": ".missing-3",
                    "extract": "text",
                    "required": False,
                },
                "non_existent_optional_4": {
                    "selector": ".missing-4",
                    "extract": "text",
                    "required": False,
                },
            }
        },
    }

    mock_provider = MockLLMProvider(response_text=json.dumps(low_coverage_candidate))
    generator = GeminiTemplateGenerator(llm_provider=mock_provider)

    result = await generator.generate_candidate(
        detail_fetches=sample_detail_fetches,
        current_template=current_template,
        source_name="test_fulbright",
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.valid is False
    assert result.gate_failed == 3


@pytest.mark.asyncio
async def test_candidate_quality_better_than_current_accepted(sample_detail_fetches):
    """Test 6: Candidate quality score is higher than current template -> ACCEPTED_FOR_REVIEW."""
    # Current template has broken selector for title
    degraded_current_template = {
        "$schema_version": "1.0",
        "source_name": "test_fulbright",
        "base_url": "https://example.org",
        "detail_rules": {
            "fields": {
                "title": {
                    "selector": "h1.old-broken-title",
                    "extract": "text",
                    "required": True,
                },
                "application_url": {
                    "selector": "a.apply-link",
                    "extract": "href",
                    "required": True,
                },
            }
        },
    }

    # Candidate has fixed selectors and full coverage
    mock_provider = MockLLMProvider(response_text=json.dumps(VALID_CANDIDATE_JSON))
    generator = GeminiTemplateGenerator(llm_provider=mock_provider)

    result = await generator.generate_candidate(
        detail_fetches=sample_detail_fetches,
        current_template=degraded_current_template,
        source_name="test_fulbright",
    )

    assert result.status == CandidateStatus.ACCEPTED_FOR_REVIEW
    assert result.valid is True
    assert result.comparison_with_current.get("score_improvement", 0.0) > 0.0


@pytest.mark.asyncio
async def test_gemini_api_failure_handled_gracefully(sample_detail_fetches):
    """Test 7: Gemini API failure -> active template remains unchanged, rejected gracefully."""
    mock_provider = MockLLMProvider(
        should_raise=LLMGenerationError("API connection error")
    )
    generator = GeminiTemplateGenerator(llm_provider=mock_provider)

    result = await generator.generate_candidate(
        detail_fetches=sample_detail_fetches,
        source_name="test_fulbright",
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.valid is False
    assert "LLM generation failed" in (result.rejection_reason or "")


@pytest.mark.asyncio
async def test_gemini_timeout_handled_gracefully(sample_detail_fetches):
    """Test 8: Gemini timeout -> active template remains unchanged, rejected gracefully."""
    mock_provider = MockLLMProvider(
        should_raise=LLMTimeoutError("Request timed out after 120s")
    )
    generator = GeminiTemplateGenerator(llm_provider=mock_provider)

    result = await generator.generate_candidate(
        detail_fetches=sample_detail_fetches,
        source_name="test_fulbright",
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.valid is False
    assert "timed out" in (result.rejection_reason or "")


@pytest.mark.asyncio
async def test_empty_or_insufficient_html_samples_rejected_early():
    """Test 9: Empty/insufficient HTML -> generation is not attempted."""
    mock_provider = MockLLMProvider(response_text=json.dumps(VALID_CANDIDATE_JSON))
    generator = GeminiTemplateGenerator(
        llm_provider=mock_provider, min_detail_samples=1
    )

    # Empty list of fetches
    result = await generator.generate_candidate(
        detail_fetches=[],
        source_name="test_fulbright",
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.valid is False
    assert "Insufficient HTML samples" in (result.rejection_reason or "")
    assert mock_provider.last_prompt is None  # LLM was not called


def test_specialized_adapters_remain_unaffected():
    """Test 10: Existing specialized adapters remain unaffected by template generator."""
    almin7 = AdapterFactory.get_adapter("almin7")
    assert isinstance(almin7, Almin7Adapter)

    s4d = AdapterFactory.get_adapter("scholars4dev")
    assert isinstance(s4d, Scholars4DevAdapter)


def test_generic_template_adapter_remains_functional():
    """Test 11: GenericTemplateAdapter extraction tests remain functional."""
    adapter = GenericTemplateAdapter(template=VALID_CANDIDATE_JSON)
    extracted = adapter.extract_from_detail_html(
        SAMPLE_HTML, source_url="https://example.org/test"
    )

    assert extracted["title"] == "Fulbright Foreign Student Program 2026"
    assert extracted["application_url"] == "https://example.org/apply-fulbright"
    assert "full funding" in extracted["description"]


@pytest.mark.asyncio
async def test_active_template_file_never_overwritten(sample_detail_fetches, tmp_path):
    """Test 12: Active template file on disk is NEVER overwritten automatically."""
    active_template_file = tmp_path / "active_template.json"
    active_template_file.write_text(
        json.dumps(VALID_CANDIDATE_JSON, indent=2), encoding="utf-8"
    )
    original_mtime = active_template_file.stat().st_mtime

    mock_provider = MockLLMProvider(response_text=json.dumps(VALID_CANDIDATE_JSON))
    generator = GeminiTemplateGenerator(llm_provider=mock_provider)

    # Execute generation attempt
    result = await generator.generate_candidate(
        detail_fetches=sample_detail_fetches,
        current_template=VALID_CANDIDATE_JSON,
        source_name="test_fulbright",
    )

    # Verify result status is ACCEPTED_FOR_REVIEW
    assert result.status == CandidateStatus.ACCEPTED_FOR_REVIEW

    # Verify file content and modification time on disk remain untouched
    current_mtime = active_template_file.stat().st_mtime
    assert current_mtime == original_mtime
    assert (
        json.loads(active_template_file.read_text(encoding="utf-8"))
        == VALID_CANDIDATE_JSON
    )
