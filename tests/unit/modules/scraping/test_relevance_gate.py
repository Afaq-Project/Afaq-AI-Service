# Focused tests for Level 0 page_role explicitness (relevance_gate).

import pytest
from pydantic import ValidationError

from src.modules.scraping.services.discovery_service.relevance_gate import (
    PlatformDiscoveryOutput,
)


def _base(**overrides):
    data = {
        "is_opportunity_portal": True,
        "site_name": "Example",
        "domain": "example.edu",
    }
    data.update(overrides)
    return data


def test_legacy_catalog_true_infers_catalog() -> None:
    out = PlatformDiscoveryOutput.model_validate(
        _base(is_catalog_page=True)
    )
    assert out.page_role == "catalog"
    assert out.is_catalog_page is True


def test_legacy_catalog_false_requires_explicit_role() -> None:
    with pytest.raises(ValidationError) as exc:
        PlatformDiscoveryOutput.model_validate(_base(is_catalog_page=False))
    assert "page_role is required" in str(exc.value)


def test_missing_catalog_and_role_requires_explicit_role() -> None:
    with pytest.raises(ValidationError) as exc:
        PlatformDiscoveryOutput.model_validate(_base())
    assert "page_role is required" in str(exc.value)


def test_explicit_homepage_not_guessed() -> None:
    out = PlatformDiscoveryOutput.model_validate(
        _base(page_role="homepage", is_catalog_page=False)
    )
    assert out.page_role == "homepage"
    assert out.is_catalog_page is False


def test_explicit_detail_not_guessed() -> None:
    out = PlatformDiscoveryOutput.model_validate(
        _base(page_role="detail", is_catalog_page=False)
    )
    assert out.page_role == "detail"
    assert out.is_catalog_page is False


def test_explicit_catalog_overrides_legacy_false() -> None:
    out = PlatformDiscoveryOutput.model_validate(
        _base(page_role="catalog", is_catalog_page=False)
    )
    assert out.page_role == "catalog"
    assert out.is_catalog_page is True


def test_role_aliases_normalize() -> None:
    cases = {
        "home": "homepage",
        "landing": "homepage",
        "listing": "catalog",
        "detail_page": "detail",
    }
    for raw, expected in cases.items():
        out = PlatformDiscoveryOutput.model_validate(_base(page_role=raw))
        assert out.page_role == expected


def test_invalid_role_rejected() -> None:
    with pytest.raises(ValidationError):
        PlatformDiscoveryOutput.model_validate(_base(page_role="unknown_role"))


def test_validation_alias_entry_page_type() -> None:
    out = PlatformDiscoveryOutput.model_validate(
        _base(entry_page_type="catalog")
    )
    assert out.page_role == "catalog"
