"""
Unit test suite for Template Contract and Validation Framework.

Tests static schema validation, runtime extraction validation,
negative error cases, and field-level error reporting.
"""

from pathlib import Path

import pytest

from src.modules.scraping.adapters.generic_template_adapter import (
    GenericTemplateAdapter,
    TemplateValidationError,
)
from src.modules.scraping.templates.template_contract import (
    TemplateRuntimeValidator,
    TemplateSchemaValidator,
)


@pytest.fixture
def minimal_valid_template():
    return {
        "$schema_version": "1.0",
        "source_name": "valid_source",
        "base_url": "https://example.com",
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
                    "pattern": r"(?i)Deadline:\s*(\d{4}-\d{2}-\d{2})",
                    "required": False,
                },
                "apply_link": {
                    "selector": "a.apply",
                    "extract": "href",
                    "required": False,
                },
                "custom_data": {
                    "selector": "div.data",
                    "extract": "attr:data-id",
                    "required": False,
                },
            }
        },
    }


# =========================================================================
# 1. Static Schema Validation Positive Tests
# =========================================================================


def test_static_validation_valid_minimal(minimal_valid_template):
    """A structurally valid template must pass static validation with zero errors."""
    res = TemplateSchemaValidator.validate(minimal_valid_template)
    assert res.valid is True
    assert len(res.errors) == 0
    assert res.metadata["source_name"] == "valid_source"


def test_static_validation_almin7_template():
    """Production almin7.json template must pass strict static validation."""
    almin7_path = Path("src/modules/scraping/templates/almin7.json")
    res = TemplateSchemaValidator.validate(almin7_path)
    assert res.valid is True
    assert len(res.errors) == 0
    assert res.metadata["source_name"] == "almin7"


def test_static_validation_scholars4dev_template():
    """Experimental scholars4dev template must pass static validation."""
    s4d_path = Path(
        r"C:\Users\msi\.gemini\antigravity\brain\768d7fb2-4232-4db4-93cf-66e07eadd7af\scratch\scholars4dev_template.json"
    )
    if s4d_path.exists():
        res = TemplateSchemaValidator.validate(s4d_path)
        assert res.valid is True
        assert len(res.errors) == 0


# =========================================================================
# 2. Static Schema Validation Negative Tests (Reject Invalid Templates)
# =========================================================================


def test_reject_missing_source_name():
    """Missing or empty source_name must fail static validation."""
    template = {
        "$schema_version": "1.0",
        "detail_rules": {"fields": {"title": {"selector": "h1", "extract": "text"}}},
    }
    res = TemplateSchemaValidator.validate(template)
    assert res.valid is False
    assert any(
        "source_name" in e.message.lower() or e.field == "source_name"
        for e in res.errors
    )

    with pytest.raises(TemplateValidationError):
        GenericTemplateAdapter(template=template)


def test_reject_empty_source_name():
    """Whitespace-only or non-alphanumeric source_name must fail validation."""
    template = {
        "$schema_version": "1.0",
        "source_name": "   ",
        "detail_rules": {"fields": {"title": {"selector": "h1", "extract": "text"}}},
    }
    res = TemplateSchemaValidator.validate(template)
    assert res.valid is False


def test_reject_missing_both_listing_and_detail_rules():
    """Template with neither listing_rules nor detail_rules must fail."""
    template = {
        "$schema_version": "1.0",
        "source_name": "empty_rules",
    }
    res = TemplateSchemaValidator.validate(template)
    assert res.valid is False
    assert any("listing_rules" in e.message for e in res.errors)


def test_reject_empty_card_selector_in_listing_rules():
    """listing_rules with empty card_selector must fail static validation."""
    template = {
        "$schema_version": "1.0",
        "source_name": "invalid_listing",
        "listing_rules": {
            "card_selector": "   ",
            "fields": {"title": {"selector": "h2", "extract": "text"}},
        },
    }
    res = TemplateSchemaValidator.validate(template)
    assert res.valid is False
    assert any("card_selector" in e.message for e in res.errors)


def test_reject_empty_field_selector(minimal_valid_template):
    """Field rule with empty selector string must fail static validation."""
    minimal_valid_template["detail_rules"]["fields"]["title"]["selector"] = ""
    res = TemplateSchemaValidator.validate(minimal_valid_template)
    assert res.valid is False
    assert any("selector" in e.message.lower() for e in res.errors)


def test_reject_malformed_selector_syntax(minimal_valid_template):
    """Malformed selector with unbalanced brackets must fail validation."""
    minimal_valid_template["detail_rules"]["fields"]["title"][
        "selector"
    ] = "div[unclosed-bracket"
    res = TemplateSchemaValidator.validate(minimal_valid_template)
    assert res.valid is False
    assert any("selector" in e.message.lower() for e in res.errors)


def test_reject_unsupported_extraction_mode(minimal_valid_template):
    """Unsupported extraction mode (e.g. 'something_unsupported') must be rejected."""
    minimal_valid_template["detail_rules"]["fields"]["title"][
        "extract"
    ] = "something_unsupported"
    res = TemplateSchemaValidator.validate(minimal_valid_template)
    assert res.valid is False
    assert any("unsupported extraction mode" in e.message.lower() for e in res.errors)

    with pytest.raises(TemplateValidationError):
        GenericTemplateAdapter(template=minimal_valid_template)


def test_reject_empty_attribute_extraction_mode(minimal_valid_template):
    """Attribute extraction mode 'attr:' without attribute name must fail."""
    minimal_valid_template["detail_rules"]["fields"]["title"]["extract"] = "attr:"
    res = TemplateSchemaValidator.validate(minimal_valid_template)
    assert res.valid is False
    assert any("attr:" in e.message for e in res.errors)


def test_reject_invalid_regex_pattern(minimal_valid_template):
    """Uncompilable regex pattern in field rule must fail static validation."""
    minimal_valid_template["detail_rules"]["fields"]["deadline"][
        "pattern"
    ] = "(?i)[unclosed_regex"
    res = TemplateSchemaValidator.validate(minimal_valid_template)
    assert res.valid is False
    assert any("invalid regex pattern" in e.message.lower() for e in res.errors)


def test_reject_malformed_field_definition_not_an_object(minimal_valid_template):
    """A field definition that is a string or list instead of a dict must fail."""
    minimal_valid_template["detail_rules"]["fields"]["title"] = "h1.title"
    res = TemplateSchemaValidator.validate(minimal_valid_template)
    assert res.valid is False


def test_reject_invalid_section_rule_extract_mode(minimal_valid_template):
    """section_rules with invalid extract mode must fail validation."""
    minimal_valid_template["detail_rules"]["section_rules"] = {
        "eligibility": {
            "heading_keywords": ["Eligibility"],
            "extract": "unsupported_section_mode",
        }
    }
    res = TemplateSchemaValidator.validate(minimal_valid_template)
    assert res.valid is False


# =========================================================================
# 3. Runtime Validation Tests (Valid vs Missing vs Required Failures)
# =========================================================================


def test_runtime_validation_success_detail(minimal_valid_template):
    """Runtime validation succeeds when all required and optional fields match."""
    html = """
    <html>
      <body>
        <h1 class="title">Global Masters Scholarship</h1>
        <span class="deadline">Deadline: 2026-12-31</span>
        <a class="apply" href="/apply-now">Apply Here</a>
        <div class="data" data-id="opp-999">Metadata</div>
      </body>
    </html>
    """
    res = TemplateRuntimeValidator.validate_detail(minimal_valid_template, html)
    assert res.valid is True
    assert len(res.errors) == 0
    extracted = res.metadata.get("extracted_fields", {})
    assert extracted["title"] == "Global Masters Scholarship"
    assert extracted["deadline"] == "2026-12-31"
    assert extracted["apply_link"] == "https://example.com/apply-now"
    assert extracted["custom_data"] == "opp-999"


def test_runtime_validation_optional_field_missing_produces_warning(
    minimal_valid_template,
):
    """Missing optional fields produce warnings but do NOT invalidate runtime validation."""
    html = """
    <html>
      <body>
        <h1 class="title">Global Masters Scholarship</h1>
      </body>
    </html>
    """
    res = TemplateRuntimeValidator.validate_detail(minimal_valid_template, html)
    assert res.valid is True
    assert len(res.errors) == 0
    # Should contain warnings for missing deadline and apply_link
    assert len(res.warnings) > 0
    warning_fields = [w.field for w in res.warnings]
    assert "deadline" in warning_fields
    assert "apply_link" in warning_fields


def test_runtime_validation_required_field_missing_fails(minimal_valid_template):
    """When a required field selector matches no elements, runtime validation fails with error."""
    html = """
    <html>
      <body>
        <div class="content">No title tag here</div>
      </body>
    </html>
    """
    res = TemplateRuntimeValidator.validate_detail(minimal_valid_template, html)
    assert res.valid is False
    assert len(res.errors) > 0
    assert any(
        e.field == "title" and e.type == "required_field_missing" for e in res.errors
    )


def test_runtime_validation_empty_html_fails(minimal_valid_template):
    """Empty HTML content must fail runtime validation immediately."""
    res = TemplateRuntimeValidator.validate_detail(minimal_valid_template, "   ")
    assert res.valid is False
    assert any(e.type == "empty_html" for e in res.errors)


def test_runtime_validation_listing_success():
    """Listing runtime validation succeeds when cards and card fields are found."""
    template = {
        "$schema_version": "1.0",
        "source_name": "listing_source",
        "base_url": "https://example.com",
        "listing_rules": {
            "card_selector": "article.card",
            "fields": {
                "title": {
                    "selector": "h2.card-title",
                    "extract": "text",
                    "required": True,
                },
                "source_url": {
                    "selector": "a.card-link",
                    "extract": "href",
                    "required": True,
                },
            },
        },
    }
    html = """
    <html>
      <body>
        <article class="card">
          <h2 class="card-title">Opportunity 1</h2>
          <a class="card-link" href="/opp/1">View</a>
        </article>
        <article class="card">
          <h2 class="card-title">Opportunity 2</h2>
          <a class="card-link" href="/opp/2">View</a>
        </article>
      </body>
    </html>
    """
    res = TemplateRuntimeValidator.validate_listing(template, html)
    assert res.valid is True
    assert res.metadata["cards_found_count"] == 2
    assert res.metadata["extracted_items_count"] == 2


def test_runtime_validation_listing_no_cards_error():
    """Listing runtime validation reports error when card_selector matches 0 cards."""
    template = {
        "$schema_version": "1.0",
        "source_name": "listing_source",
        "base_url": "https://example.com",
        "listing_rules": {
            "card_selector": "article.card",
            "fields": {
                "title": {"selector": "h2", "extract": "text"},
            },
        },
    }
    html = "<html><body><div>Empty listing</div></body></html>"
    res = TemplateRuntimeValidator.validate_listing(template, html)
    assert res.valid is False
    assert any(e.type == "no_cards_found" for e in res.errors)
