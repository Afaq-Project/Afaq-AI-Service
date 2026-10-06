"""
Template Contract and Validation Framework for Afaq GenericTemplateAdapter.

Defines the declarative JSON template specification, static schema validation,
and runtime execution validation against HTML samples.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# Valid extraction modes supported by GenericTemplateAdapter
SUPPORTED_BASE_EXTRACTION_MODES = {"text", "html", "href", "src"}
SUPPORTED_SECTION_EXTRACTION_MODES = {"section_text", "list_items"}


class ValidationErrorDetail(BaseModel):
    """Detailed information for a single validation error."""

    model_config = ConfigDict(extra="forbid")

    field: str | None = None
    type: str  # e.g. "missing_field", "invalid_selector", "unsupported_mode", "invalid_regex", "structural_error"
    message: str
    location: str | None = None


class ValidationWarningDetail(BaseModel):
    """Detailed information for a single validation warning."""

    model_config = ConfigDict(extra="forbid")

    field: str | None = None
    type: str  # e.g. "missing_optional_field", "empty_match", "empty_taxonomy"
    message: str
    location: str | None = None


class TemplateValidationResult(BaseModel):
    """Encapsulates the complete result of static or runtime template validation."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[ValidationErrorDetail] = Field(default_factory=list)
    warnings: list[ValidationWarningDetail] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_error(
        self,
        message: str,
        type_: str = "validation_error",
        field: str | None = None,
        location: str | None = None,
    ) -> None:
        self.valid = False
        self.errors.append(
            ValidationErrorDetail(
                field=field,
                type=type_,
                message=message,
                location=location,
            )
        )

    def add_warning(
        self,
        message: str,
        type_: str = "validation_warning",
        field: str | None = None,
        location: str | None = None,
    ) -> None:
        self.warnings.append(
            ValidationWarningDetail(
                field=field,
                type=type_,
                message=message,
                location=location,
            )
        )


class FieldRuleSchema(BaseModel):
    """Contract for extracting a single field from a DOM node."""

    model_config = ConfigDict(extra="forbid")

    selector: str
    extract: str = "text"
    pattern: str | None = None
    required: bool = False

    @field_validator("selector")
    @classmethod
    def validate_selector(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field selector cannot be empty.")
        if v.count("[") != v.count("]") or v.count("(") != v.count(")"):
            raise ValueError(f"Malformed CSS selector syntax: '{v}'")
        return v.strip()

    @field_validator("extract")
    @classmethod
    def validate_extract_mode(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean in SUPPORTED_BASE_EXTRACTION_MODES:
            return clean
        if clean.startswith("attr:"):
            attr_name = clean.split(":", 1)[1].strip()
            if not attr_name:
                raise ValueError(
                    "Attribute extraction mode 'attr:' must specify an attribute name (e.g. 'attr:data-id')."
                )
            return f"attr:{attr_name}"
        raise ValueError(
            f"Unsupported extraction mode '{v}'. Supported modes are: {sorted(SUPPORTED_BASE_EXTRACTION_MODES)} or 'attr:<attribute_name>'."
        )

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str | None) -> str | None:
        if v is not None:
            if not v.strip():
                raise ValueError("Regex pattern cannot be an empty string.")
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern '{v}': {exc}") from exc
        return v


class OpportunityFilterSchema(BaseModel):
    """Contract for filtering listing cards by badge, classes, or url."""

    model_config = ConfigDict(extra="forbid")

    exclude_badge_keywords: list[str] = Field(default_factory=list)
    exclude_classes: list[str] = Field(default_factory=list)
    exclude_url_patterns: list[str] = Field(default_factory=list)


class ListingRulesSchema(BaseModel):
    """Contract for extracting opportunity cards from listing/archive HTML."""

    model_config = ConfigDict(extra="forbid")

    card_selector: str
    fields: dict[str, FieldRuleSchema] = Field(default_factory=dict)
    opportunity_filter: OpportunityFilterSchema | None = None

    @field_validator("card_selector")
    @classmethod
    def validate_card_selector(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("card_selector cannot be empty.")
        if v.count("[") != v.count("]") or v.count("(") != v.count(")"):
            raise ValueError(f"Malformed CSS selector in card_selector: '{v}'")
        return v.strip()


class SpecificTextPatternSchema(BaseModel):
    """Specific nationality pattern mapping."""

    model_config = ConfigDict(extra="forbid")

    pattern: str
    value: str

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Pattern cannot be empty.")
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern '{v}': {exc}") from exc
        return v

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Pattern value cannot be empty.")
        return v.strip()


class TaxonomyMappingItemSchema(BaseModel):
    """Mapping configuration for a taxonomy category."""

    model_config = ConfigDict(extra="forbid")

    url_markers: list[str] = Field(default_factory=list)
    class_markers: list[str] = Field(default_factory=list)
    filter_generic_dumps: bool = False
    generic_threshold: int = 15
    generic_list: list[str] = Field(default_factory=list)
    exclude_text_patterns: list[str] = Field(default_factory=list)
    specific_text_patterns: list[SpecificTextPatternSchema] = Field(
        default_factory=list
    )

    @field_validator("exclude_text_patterns")
    @classmethod
    def validate_exclude_patterns(cls, patterns: list[str]) -> list[str]:
        for pat in patterns:
            try:
                re.compile(pat)
            except re.error as exc:
                raise ValueError(
                    f"Invalid regex in exclude_text_patterns '{pat}': {exc}"
                ) from exc
        return patterns


class TaxonomyRulesSchema(BaseModel):
    """Contract for extracting taxonomies (country, organization, nationalities)."""

    model_config = ConfigDict(extra="forbid")

    container_selector: str | None = None
    item_selector: str | None = None
    mapping: dict[str, TaxonomyMappingItemSchema] = Field(default_factory=dict)

    @field_validator("container_selector", "item_selector")
    @classmethod
    def validate_optional_selector(cls, v: str | None) -> str | None:
        if v is not None:
            if not v.strip():
                raise ValueError("Selector string cannot be empty if provided.")
            if v.count("[") != v.count("]") or v.count("(") != v.count(")"):
                raise ValueError(f"Malformed CSS selector syntax: '{v}'")
            return v.strip()
        return None


class SectionRuleSchema(BaseModel):
    """Contract for heading-based section text extraction."""

    model_config = ConfigDict(extra="forbid")

    heading_keywords: list[str]
    extract: Literal["section_text", "list_items"] = "section_text"

    @field_validator("heading_keywords")
    @classmethod
    def validate_keywords(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("heading_keywords list cannot be empty.")
        cleaned = [k.strip() for k in v if k and k.strip()]
        if not cleaned:
            raise ValueError(
                "heading_keywords must contain at least one non-empty keyword."
            )
        return cleaned


class DetailRulesSchema(BaseModel):
    """Contract for extracting structured fields from a single detail page HTML."""

    model_config = ConfigDict(extra="forbid")

    fields: dict[str, FieldRuleSchema] = Field(default_factory=dict)
    taxonomy_rules: TaxonomyRulesSchema | None = None
    section_rules: dict[str, SectionRuleSchema] = Field(default_factory=dict)


class ExtractionTemplateSchema(BaseModel):
    """Root contract for a declarative scraping extraction template."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(alias="$schema_version", default="1.0")
    source_name: str
    display_name: str | None = None
    base_url: str | None = None
    description: str | None = None
    listing_rules: ListingRulesSchema | None = None
    detail_rules: DetailRulesSchema | None = None

    @field_validator("source_name")
    @classmethod
    def validate_source_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("source_name cannot be empty.")
        clean = v.strip()
        if not re.match(r"^[a-zA-Z0-9_\-]+$", clean):
            raise ValueError(
                f"Invalid source_name '{clean}'. Must contain only alphanumeric characters, underscores, or hyphens."
            )
        return clean

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str | None) -> str | None:
        if v is not None:
            clean = v.strip()
            if not clean:
                return None
            parsed = urlparse(clean)
            if not parsed.scheme or parsed.scheme not in {"http", "https"}:
                raise ValueError(
                    f"Invalid base_url '{clean}'. Must start with http:// or https://"
                )
            return clean
        return None

    @model_validator(mode="after")
    def validate_at_least_one_rule_set(self) -> ExtractionTemplateSchema:
        if not self.listing_rules and not self.detail_rules:
            raise ValueError(
                "Template must define at least 'listing_rules' or 'detail_rules'."
            )
        return self


class TemplateSchemaValidator:
    """Performs strict static schema validation against the template contract."""

    @classmethod
    def validate(
        cls, template_input: dict[str, Any] | str | Path
    ) -> TemplateValidationResult:
        result = TemplateValidationResult(valid=True)

        # 1. Parse JSON if string or Path
        raw_dict: dict[str, Any]
        if isinstance(template_input, (str, Path)):
            raw_path = Path(template_input)
            if raw_path.is_file():
                try:
                    with open(raw_path, encoding="utf-8") as f:
                        raw_dict = json.load(f)
                except Exception as exc:
                    result.add_error(
                        message=f"Failed to read template file '{raw_path}': {exc}",
                        type_="file_read_error",
                        location=str(raw_path),
                    )
                    return result
            else:
                try:
                    raw_dict = json.loads(str(template_input))
                except Exception as exc:
                    result.add_error(
                        message=f"Invalid template JSON string: {exc}",
                        type_="json_parse_error",
                    )
                    return result
        elif isinstance(template_input, dict):
            raw_dict = template_input
        else:
            result.add_error(
                message=f"Unsupported template input type: {type(template_input)}. Expected dict, str, or Path.",
                type_="invalid_input_type",
            )
            return result

        if not isinstance(raw_dict, dict):
            result.add_error(
                message="Template root must be a JSON object (dictionary).",
                type_="structural_error",
                location="root",
            )
            return result

        # 2. Validate via Pydantic model
        try:
            parsed_template = ExtractionTemplateSchema.model_validate(raw_dict)
            result.metadata["source_name"] = parsed_template.source_name
            result.metadata["schema_version"] = parsed_template.schema_version
            result.metadata["has_listing_rules"] = (
                parsed_template.listing_rules is not None
            )
            result.metadata["has_detail_rules"] = (
                parsed_template.detail_rules is not None
            )
        except Exception as exc:
            # Extract detailed error list from Pydantic ValidationError
            if hasattr(exc, "errors"):
                for err in exc.errors():
                    loc = " -> ".join(str(x) for x in err.get("loc", []))
                    msg = err.get("msg", str(err))
                    err_type = err.get("type", "schema_error")
                    result.add_error(
                        message=msg,
                        type_=err_type,
                        field=loc.split(" -> ")[-1] if loc else None,
                        location=loc or "root",
                    )
            else:
                result.add_error(
                    message=str(exc), type_="schema_error", location="root"
                )

        # 3. Check recommended metadata warnings
        if result.valid:
            if not raw_dict.get("base_url"):
                result.add_warning(
                    message="Template has no 'base_url'. Relative URLs will not be resolved automatically.",
                    type_="missing_base_url",
                    location="base_url",
                )
            if not raw_dict.get("display_name"):
                result.add_warning(
                    message="Template has no 'display_name'. It is recommended to provide a human-readable name.",
                    type_="missing_display_name",
                    location="display_name",
                )

        return result


class TemplateRuntimeValidator:
    """
    Validates a template against actual HTML content in runtime.

    Distinguishes between:
    - Critical Errors: Required fields missing, required selectors not matching.
    - Quality Warnings: Optional fields missing or empty.
    - Valid extractions: Extracted values meeting expectations.
    """

    @classmethod
    def validate_detail(
        cls,
        template_input: dict[str, Any] | str | Path,
        html: str,
        source_url: str = "",
    ) -> TemplateValidationResult:
        # First ensure static validity
        static_result = TemplateSchemaValidator.validate(template_input)
        if not static_result.valid:
            return static_result

        result = TemplateValidationResult(valid=True)
        if not html or not html.strip():
            result.add_error(
                message="HTML content is empty or whitespace only.",
                type_="empty_html",
                location="runtime_input",
            )
            return result

        # Load template dictionary
        if isinstance(template_input, (str, Path)):
            raw_path = Path(template_input)
            if raw_path.is_file():
                with open(raw_path, encoding="utf-8") as f:
                    template_dict = json.load(f)
            else:
                template_dict = json.loads(str(template_input))
        else:
            template_dict = template_input

        from src.modules.scraping.adapters.generic_template_adapter import (
            GenericTemplateAdapter,
        )

        adapter = GenericTemplateAdapter(template=template_dict)
        soup = BeautifulSoup(html, "html.parser")

        detail_rules = template_dict.get("detail_rules", {})
        field_rules = detail_rules.get("fields", {})

        extracted_data: dict[str, Any] = {}

        # 1. Validate fields
        for field_name, rule in field_rules.items():
            selector = rule.get("selector", "")
            is_required = rule.get("required", False)
            node = soup.select_one(selector) if selector else None

            if not node:
                if is_required:
                    result.add_error(
                        message=f"Required field '{field_name}' not found. Selector '{selector}' matched no DOM elements.",
                        type_="required_field_missing",
                        field=field_name,
                        location=f"detail_rules.fields.{field_name}",
                    )
                else:
                    result.add_warning(
                        message=f"Optional field '{field_name}' selector '{selector}' matched no DOM elements.",
                        type_="optional_field_missing",
                        field=field_name,
                        location=f"detail_rules.fields.{field_name}",
                    )
                continue

            val = adapter._extract_field_value(soup, rule)
            if val is None or (isinstance(val, str) and not val.strip()):
                if is_required:
                    result.add_error(
                        message=f"Required field '{field_name}' extracted empty value using rule {rule}.",
                        type_="required_field_empty",
                        field=field_name,
                        location=f"detail_rules.fields.{field_name}",
                    )
                else:
                    result.add_warning(
                        message=f"Optional field '{field_name}' extracted empty value.",
                        type_="optional_field_empty",
                        field=field_name,
                        location=f"detail_rules.fields.{field_name}",
                    )
            else:
                extracted_data[field_name] = val

        # 2. Run full adapter extraction
        try:
            full_extracted = adapter.extract_from_detail_html(
                html, source_url=source_url
            )
            result.metadata["extracted_fields"] = full_extracted
        except Exception as exc:
            result.add_error(
                message=f"Adapter execution failed during extract_from_detail_html: {exc}",
                type_="extraction_exception",
                location="extract_from_detail_html",
            )

        return result

    @classmethod
    def validate_listing(
        cls,
        template_input: dict[str, Any] | str | Path,
        html: str,
    ) -> TemplateValidationResult:
        static_result = TemplateSchemaValidator.validate(template_input)
        if not static_result.valid:
            return static_result

        result = TemplateValidationResult(valid=True)
        if not html or not html.strip():
            result.add_error(
                message="Listing HTML content is empty.",
                type_="empty_html",
                location="runtime_input",
            )
            return result

        if isinstance(template_input, (str, Path)):
            raw_path = Path(template_input)
            if raw_path.is_file():
                with open(raw_path, encoding="utf-8") as f:
                    template_dict = json.load(f)
            else:
                template_dict = json.loads(str(template_input))
        else:
            template_dict = template_input

        from src.modules.scraping.adapters.generic_template_adapter import (
            GenericTemplateAdapter,
        )

        adapter = GenericTemplateAdapter(template=template_dict)
        listing_rules = template_dict.get("listing_rules", {})
        card_selector = listing_rules.get("card_selector", "")

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(card_selector) if card_selector else []

        if not cards:
            result.add_error(
                message=f"Listing card_selector '{card_selector}' matched 0 cards in HTML.",
                type_="no_cards_found",
                location="listing_rules.card_selector",
            )
            return result

        result.metadata["cards_found_count"] = len(cards)
        try:
            items = adapter.extract_items_from_listing_html(html)
            result.metadata["extracted_items_count"] = len(items)
            if items:
                result.metadata["sample_item"] = items[0]
        except Exception as exc:
            result.add_error(
                message=f"Failed to extract listing items: {exc}",
                type_="listing_extraction_exception",
                location="extract_items_from_listing_html",
            )

        return result
