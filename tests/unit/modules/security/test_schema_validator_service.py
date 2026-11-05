# [OMA-W001-T006] Unit tests for SchemaValidatorService

import pytest

from src.modules.security.exceptions import (
    ERR_SCHEMA_SHAPE_INVALID,
    ERR_SELECTOR_SYNTAX_INVALID,
    SchemaShapeInvalidError,
    SelectorSyntaxInvalidError,
)
from src.modules.security.models import TemplateSchemaValidationResult
from src.modules.security.services.schema_validator_service import (
    SchemaValidator,
    SchemaValidatorService,
)


# [OMA-W001-T006] UC-02: AI Extraction Template Schema Dry-Run Verification
@pytest.mark.asyncio
async def test_validate_template_schema_success():
    """UC-02: Verifies valid AI extraction template schema and dry-runs selectors against sample HTML."""
    schema = {
        "schema_name": "scholarship_details",
        "selectors": {
            "title": "h1.grant-title",
            "apply_link": "a.btn-apply",
        },
    }
    sample_html = """
    <html>
        <body>
            <h1 class="grant-title">Global Excellence Scholarship 2026</h1>
            <a class="btn-apply" href="https://example.edu/apply">Apply Now</a>
        </body>
    </html>
    """

    result = await SchemaValidatorService.validate_template_schema(
        schema_dict=schema,
        sample_html=sample_html,
    )

    assert isinstance(result, TemplateSchemaValidationResult)
    assert result.is_valid is True
    assert result.schema_name == "scholarship_details"
    assert result.selector_count == 2
    assert result.selectors_validated == ["h1.grant-title", "a.btn-apply"]
    assert result.error_code is None
    assert result.rejection_reason is None
    assert result.failing_selector is None


# [OMA-W001-T006] Test non-dict input rejection
@pytest.mark.asyncio
async def test_non_dict_schema_rejected():
    """Protects schema shape invariants: non-dictionary input raises SchemaShapeInvalidError."""
    with pytest.raises(SchemaShapeInvalidError) as exc_info:
        await SchemaValidatorService.validate_template_schema("not_a_dictionary")  # type: ignore[arg-type]

    assert exc_info.value.error_code == ERR_SCHEMA_SHAPE_INVALID
    assert "must be a dictionary" in str(exc_info.value)


# [OMA-W001-T006] Test extra forbidden fields rejection
@pytest.mark.asyncio
async def test_extra_forbidden_fields_rejected():
    """Protects strict Pydantic shape invariants: extra root keys raise SchemaShapeInvalidError."""
    schema = {
        "schema_name": "test_schema",
        "selectors": {"a": "div.title", "b": "span.date"},
        "injected_untrusted_field": "dangerous_payload",
    }
    with pytest.raises(SchemaShapeInvalidError) as exc_info:
        await SchemaValidatorService.validate_template_schema(schema)

    assert exc_info.value.error_code == ERR_SCHEMA_SHAPE_INVALID
    assert "Extra forbidden field(s)" in str(exc_info.value)


# [OMA-W001-T006] Test schema name presence and validation
@pytest.mark.asyncio
async def test_schema_name_validation():
    """Protects schema identity: schema must provide valid non-empty schema_name or name."""
    # Missing name
    with pytest.raises(SchemaShapeInvalidError):
        await SchemaValidatorService.validate_template_schema(
            {"selectors": {"a": "div", "b": "span"}}
        )

    # Empty whitespace name
    with pytest.raises(SchemaShapeInvalidError):
        await SchemaValidatorService.validate_template_schema(
            {"schema_name": "   ", "selectors": {"a": "div", "b": "span"}}
        )

    # Alternate allowed key 'name' is accepted
    res = await SchemaValidatorService.validate_template_schema(
        {"name": "alternate_name", "selectors": {"a": "div.one", "b": "div.two"}}
    )
    assert res.schema_name == "alternate_name"


# [OMA-W001-T006] Test selectors variations: dictionary, list, and invalid types
@pytest.mark.asyncio
async def test_selectors_structure_validation():
    """Protects 'selectors' property validation: dict of strings or list of strings."""
    # Valid selectors list
    res = await SchemaValidatorService.validate_template_schema(
        {"schema_name": "list_selectors", "selectors": ["div.card", "span.author"]}
    )
    assert res.selector_count == 2

    # Selectors dict with non-string value
    with pytest.raises(SchemaShapeInvalidError) as exc_1:
        await SchemaValidatorService.validate_template_schema(
            {"schema_name": "bad_dict", "selectors": {"title": 12345, "body": "p"}}
        )
    assert exc_1.value.error_code == ERR_SCHEMA_SHAPE_INVALID

    # Selectors list with non-string item
    with pytest.raises(SchemaShapeInvalidError) as exc_2:
        await SchemaValidatorService.validate_template_schema(
            {"schema_name": "bad_list", "selectors": ["div.card", {"invalid": 1}]}
        )
    assert exc_2.value.error_code == ERR_SCHEMA_SHAPE_INVALID

    # Selectors not dict or list
    with pytest.raises(SchemaShapeInvalidError) as exc_3:
        await SchemaValidatorService.validate_template_schema(
            {"schema_name": "bad_type", "selectors": 12345}
        )
    assert exc_3.value.error_code == ERR_SCHEMA_SHAPE_INVALID


# [OMA-W001-T006] Test fields structure: dict and list variations
@pytest.mark.asyncio
async def test_fields_structure_validation():
    """Protects 'fields' property validation: dict of strings/objects or list of strings/objects."""
    # Valid fields dict with strings
    res_str = await SchemaValidatorService.validate_template_schema(
        {"schema_name": "fields_str", "fields": {"title": "h1", "date": "time"}}
    )
    assert res_str.selector_count == 2

    # Valid fields dict with object containing 'selector'
    res_obj = await SchemaValidatorService.validate_template_schema(
        {
            "schema_name": "fields_obj",
            "fields": {
                "title": {"selector": "h1.title", "type": "text"},
                "link": {"selector": "a.apply", "type": "url"},
            },
        }
    )
    assert res_obj.selector_count == 2

    # Fields dict with invalid item (missing selector)
    with pytest.raises(SchemaShapeInvalidError):
        await SchemaValidatorService.validate_template_schema(
            {
                "schema_name": "fields_bad_dict",
                "fields": {"title": {"invalid_key": "h1"}, "date": "span"},
            }
        )

    # Valid fields list
    res_list = await SchemaValidatorService.validate_template_schema(
        {
            "schema_name": "fields_list",
            "fields": [{"selector": "h1.title"}, "a.link"],
        }
    )
    assert res_list.selector_count == 2

    # Fields list with invalid item
    with pytest.raises(SchemaShapeInvalidError):
        await SchemaValidatorService.validate_template_schema(
            {
                "schema_name": "fields_bad_list",
                "fields": [{"missing_selector": 1}, "a.link"],
            }
        )

    # Fields list with non-dict non-str
    with pytest.raises(SchemaShapeInvalidError):
        await SchemaValidatorService.validate_template_schema(
            {"schema_name": "fields_bad_item", "fields": [123, "a.link"]}
        )

    # Fields of invalid root type
    with pytest.raises(SchemaShapeInvalidError):
        await SchemaValidatorService.validate_template_schema(
            {"schema_name": "bad_fields_type", "fields": "invalid_string"}
        )


# [OMA-W001-T006] Test minimum 2 selectors requirement (FR-008)
@pytest.mark.asyncio
async def test_minimum_selectors_requirement():
    """Protects FR-008 requirement: extraction templates must contain at least 2 selectors."""
    # Only 1 selector
    with pytest.raises(SchemaShapeInvalidError) as exc_info:
        await SchemaValidatorService.validate_template_schema(
            {"schema_name": "single_selector", "selectors": ["h1.title"]}
        )
    assert exc_info.value.error_code == ERR_SCHEMA_SHAPE_INVALID
    assert "must contain at least 2 selectors/fields" in str(exc_info.value)


# [OMA-W001-T006] Test selector length limit (300 characters)
@pytest.mark.asyncio
async def test_selector_length_limit():
    """Protects selector complexity: selector exceeding 300 characters raises SelectorSyntaxInvalidError."""
    long_selector = "div." + ("a" * 305)
    schema = {
        "schema_name": "long_sel",
        "selectors": [long_selector, "span.date"],
    }
    with pytest.raises(SelectorSyntaxInvalidError) as exc_info:
        await SchemaValidatorService.validate_template_schema(schema)

    assert exc_info.value.error_code == ERR_SELECTOR_SYNTAX_INVALID
    assert "exceeds maximum length of 300 characters" in str(exc_info.value)


# [OMA-W001-T006] Test invalid CSS selector syntax compilation failure
@pytest.mark.asyncio
async def test_invalid_css_syntax_rejected():
    """Protects selector safety: syntax errors in CSS selectors raise SelectorSyntaxInvalidError."""
    schema = {
        "schema_name": "broken_syntax",
        "selectors": ["div[[[malformed::syntax", "span.date"],
    }
    with pytest.raises(SelectorSyntaxInvalidError) as exc_info:
        await SchemaValidatorService.validate_template_schema(schema)

    assert exc_info.value.error_code == ERR_SELECTOR_SYNTAX_INVALID
    assert "Invalid CSS selector syntax" in str(exc_info.value)


# [OMA-W001-T006] Test dry run without sample HTML
@pytest.mark.asyncio
async def test_validation_without_sample_html():
    """Protects dry-run optional evaluation: compiles selectors without execution when sample_html is None."""
    schema = {
        "schema_name": "no_html",
        "selectors": ["h1.title", "p.content"],
    }
    res = await SchemaValidatorService.validate_template_schema(
        schema, sample_html=None
    )
    assert res.is_valid is True
    assert res.selector_count == 2
    assert res.dry_run_latency_ms == 0.0


# [OMA-W001-T006] Test raise_on_error=False flag
@pytest.mark.asyncio
async def test_raise_on_error_false():
    """Protects non-throwing validation mode: returns TemplateSchemaValidationResult with is_valid=False."""
    bad_schema = {
        "schema_name": "syntax_error_schema",
        "selectors": ["div[[[bad", "p.normal"],
    }
    result = await SchemaValidatorService.validate_template_schema(
        bad_schema, raise_on_error=False
    )
    assert isinstance(result, TemplateSchemaValidationResult)
    assert result.is_valid is False
    assert result.error_code == ERR_SELECTOR_SYNTAX_INVALID
    assert result.failing_selector == "div[[[bad"


# [OMA-W001-T006] Test field definition with non-string selector value
@pytest.mark.asyncio
async def test_fields_dict_non_string_selector():
    """Protects fields validation when dict contains selector with non-string value."""
    schema = {
        "schema_name": "bad_field_selector",
        "fields": {
            "title": {"selector": 12345},
            "desc": "p.text",
        },
    }
    with pytest.raises(SchemaShapeInvalidError) as exc_info:
        await SchemaValidatorService.validate_template_schema(schema)
    assert exc_info.value.error_code == ERR_SCHEMA_SHAPE_INVALID
    assert "Field selector must be a string" in str(exc_info.value)


# [OMA-W001-T006] Test calculate_has_depth helper directly
def test_calculate_has_depth_helper():
    """Protects internal ReDoS complexity helper _calculate_has_depth."""
    assert SchemaValidatorService._calculate_has_depth("div:has(p)") == 1
    assert SchemaValidatorService._calculate_has_depth("div:has(p:has(span))") == 2
    assert SchemaValidatorService._calculate_has_depth("div > p") == 0


# [OMA-W001-T006] Test backward compatibility alias
def test_schema_validator_alias():
    """Protects public API backward-compatibility alias SchemaValidator."""
    assert SchemaValidator is SchemaValidatorService
