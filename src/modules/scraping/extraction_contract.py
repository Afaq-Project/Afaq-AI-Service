# [OMA-SCRAPING-T1] Versioned extraction contract for template-driven scraping

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RawOpportunityPayload(BaseModel):
    """Versioned raw payload contract consumed by the cleaning stage.

    Publisher-original values are preserved verbatim; no FK ids or
    canonical classifications are produced here.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    provider_institution_name: str | None = None
    opportunity_type_raw: str | None = None
    eligibility_text: str | None = None
    application_url_candidate: str | None = None
    source_url: str
    funding_amount_raw: str | None = None
    funding_currency_raw: str | None = None
    funding_description: str | None = None
    deadline_raw: str | None = None
    is_remote: bool | None = None
    eligible_countries: list[str] = Field(default_factory=list)
    study_locations: list[str] = Field(default_factory=list)
    education_levels: list[str] = Field(default_factory=list)
    majors: list[str] = Field(default_factory=list)
    special_statuses: list[str] = Field(default_factory=list)


RAW_OPPORTUNITY_PAYLOAD_VERSION: str = "1.0"


class Level1FieldSpec(BaseModel):
    """Extraction specification for a single Level 1 (catalog) field."""

    model_config = ConfigDict(extra="forbid")

    selector: str
    extraction: Literal["text", "href", "src", "list"] = "text"
    required: bool = False
    multiple: bool = False


class Level1TemplateContract(BaseModel):
    """Contract for a Level 1 catalog template."""

    model_config = ConfigDict(extra="forbid")

    container_selector: str
    title: Level1FieldSpec
    detail_url: Level1FieldSpec
    summary: Level1FieldSpec | None = None
    image: Level1FieldSpec | None = None
    next_page: Level1FieldSpec | None = None


class Level2FieldSpec(BaseModel):
    """Extraction specification for a single Level 2 (detail) field."""

    model_config = ConfigDict(extra="forbid")

    selector: str
    extraction: Literal["text", "href", "src", "list"] = "text"
    required: bool = False
    multiple: bool = False


# Field names allowed in a Level 2 template must map to RawOpportunityPayload.
LEVEL2_ALLOWED_FIELDS: frozenset[str] = frozenset(RawOpportunityPayload.model_fields.keys())


class Level2TemplateContract(BaseModel):
    """Contract for a Level 2 detail template."""

    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Level2FieldSpec]

    @model_validator(mode="after")
    def _check_field_names(self) -> "Level2TemplateContract":
        unknown = set(self.fields) - LEVEL2_ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"Unknown Level 2 fields: {sorted(unknown)}")
        return self

    def validate_field_names(self) -> None:
        unknown = set(self.fields) - LEVEL2_ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"Unknown Level 2 fields: {sorted(unknown)}")
