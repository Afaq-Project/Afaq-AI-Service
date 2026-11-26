from src.modules.scraping.extraction_contract import (
    LEVEL2_ALLOWED_FIELDS,
    Level1TemplateContract,
    Level2TemplateContract,
    RawOpportunityPayload,
)


def test_raw_payload_defaults_and_forbid_unknown():
    payload = RawOpportunityPayload(source_url="https://example.com")
    assert payload.title is None
    assert payload.eligible_countries == []
    assert payload.source_url == "https://example.com"

    try:
        RawOpportunityPayload(source_url="https://example.com", unknown_field="x")
        raised = False
    except Exception:
        raised = True
    assert raised


def test_level2_allowed_fields_matches_payload():
    assert LEVEL2_ALLOWED_FIELDS == set(RawOpportunityPayload.model_fields.keys())


def test_level2_template_rejects_unknown_field():
    try:
        Level2TemplateContract(fields={"foo": {"selector": "h1", "extraction": "text"}})
        raised = False
    except Exception:
        raised = True
    assert raised


def test_level1_template_round_trip():
    tpl = Level1TemplateContract(
        container_selector=".card",
        title={"selector": "h2", "extraction": "text", "required": True},
        detail_url={"selector": "a", "extraction": "href", "required": True},
    )
    assert tpl.container_selector == ".card"
    assert tpl.title.required is True
