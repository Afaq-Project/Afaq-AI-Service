import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.api.dependencies import require_api_key
from src.api.protocols import get_discovery_service, get_scraper_service
from src.main import app
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.security.models import ValidatedUrl
from src.modules.security.services.link_validator_service import LinkValidatorService
from src.modules.scraping.models import (
    OperationAbortData,
    SourceAbortData,
    SourceOnboardData,
    SourceOnboardResponse,
)

PACT_FILE = (
    Path(__file__).parents[2]
    / "pacts"
    / "afaq-ai-service-contract-guard-afaq-ai-service.json"
)
OPERATION_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_ID = "22222222-2222-4222-8222-222222222222"
FIXED_TIME = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _assert_contract_subset(actual, expected, location: str = "response.body") -> None:
    """Assert every pact-declared value while allowing provider-added fields."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{location} must be an object"
        for key, expected_value in expected.items():
            assert key in actual, f"{location}.{key} is missing"
            _assert_contract_subset(
                actual[key], expected_value, f"{location}.{key}"
            )
    elif isinstance(expected, list):
        assert actual == expected, f"{location} differs from the pact"
    else:
        assert actual == expected, (
            f"{location}: expected {expected!r}, got {actual!r}"
        )


def _operation(status: str = "completed"):
    return SimpleNamespace(
        id=OPERATION_ID,
        status=status,
        triggered_by="admin_api",
        sources_attempted=[SOURCE_ID],
        sources_succeeded=[SOURCE_ID] if status == "completed" else [],
        sources_failed=[],
        total_listings_found=2,
        total_details_extracted=2,
        total_files_downloaded=1,
        error_summary={},
        started_at=FIXED_TIME,
        completed_at=FIXED_TIME if status == "completed" else None,
    )


def _route_method_path(route):
    return route.path, route.methods or set()


def _concrete_path(path: str) -> str:
    values = {
        "operation_id": OPERATION_ID,
        "source_id": SOURCE_ID,
    }
    return re.sub(
        r"\{([^}:]+)(?::[^}]+)?\}",
        lambda match: values[match.group(1)],
        path,
    )


def test_pact_contract_covers_every_application_api_route():
    contract = json.loads(PACT_FILE.read_text(encoding="utf-8"))
    pact_routes = {
        (interaction["request"]["method"], interaction["request"]["path"])
        for interaction in contract["interactions"]
    }

    app_routes = set()
    for route in app.routes:
        path, methods = _route_method_path(route)
        # FastAPI's OpenAPI and interactive documentation endpoints are framework
        # utilities, not application API contracts.
        if path in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}:
            continue
        for method in methods & {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            app_routes.add((method, _concrete_path(path)))

    assert app_routes == pact_routes, (
        f"Pact route mismatch. Missing: {sorted(app_routes - pact_routes)}; "
        f"stale: {sorted(pact_routes - app_routes)}"
    )


@pytest.mark.asyncio
async def test_provider_matches_all_internal_pact_interactions(client: AsyncClient):
    """Run each internal endpoint contract against the FastAPI provider."""
    contract = json.loads(PACT_FILE.read_text(encoding="utf-8"))
    assert contract["provider"]["name"] == "afaq-ai-service"
    assert contract["consumer"]["name"] == "afaq-ai-service-contract-guard"

    source_abort = SourceAbortData(source_id=SOURCE_ID, is_locked=False)
    scraper = SimpleNamespace(
        prepare_scrape_operation=AsyncMock(
            return_value=(_operation("running"), False, 1, 0)
        ),
        run_scrape_operation=AsyncMock(),
        get_operations_log=AsyncMock(return_value=([], 0)),
        get_latest_operation=AsyncMock(return_value=None),
        get_operation_by_id=AsyncMock(return_value=_operation()),
        abort_operation=AsyncMock(
            return_value=OperationAbortData(
                operation_id=OPERATION_ID,
                status="aborted",
                aborted_at=FIXED_TIME,
                sources_released=1,
            )
        ),
        abort_source=AsyncMock(return_value=source_abort),
        get_dead_letter_records=AsyncMock(return_value=([], 0)),
    )
    discovery = SimpleNamespace(
        onboard_source=AsyncMock(
            return_value=SourceOnboardResponse(
                data=SourceOnboardData(
                    source_id=SOURCE_ID,
                    domain="example.edu",
                    site_name="Example Scholarships",
                    supported_languages=["en"],
                    pagination_type="url_param",
                    pagination_config={"param": "page", "step": 1},
                    ordering_strategy="chronological_descending",
                    rate_limit_delay_sec=1.0,
                    is_active=True,
                )
            )
        )
    )
    key_info = ApiKeyInfo(
        id="00000000-0000-4000-8000-000000000001",
        name="Internal Pact Guard",
        is_active=True,
    )
    validated_url = ValidatedUrl(
        original_url="https://example.edu/scholarships",
        canonical_url="https://example.edu/scholarships",
        scheme="https",
        host="example.edu",
        port=443,
        resolved_ip="203.0.113.10",
        is_https=True,
        redirect_hops=0,
        redirect_chain=[],
        dns_pinned_rule="MAP example.edu 203.0.113.10",
        validated_at=FIXED_TIME,
    )

    app.dependency_overrides[require_api_key] = lambda: key_info
    app.dependency_overrides[get_scraper_service] = lambda: scraper
    app.dependency_overrides[get_discovery_service] = lambda: discovery
    try:
        for interaction in contract["interactions"]:
            request = interaction["request"]
            response_contract = interaction["response"]
            method = request["method"]
            path = request["path"]
            headers = request.get("headers", {})
            params = request.get("query", {})
            body = request.get("body")

            with patch(
                "src.api.routes.v1.health.get_client",
                return_value=SimpleNamespace(
                    query_raw=AsyncMock(return_value=[{"?column?": 1}])
                ),
            ), patch.object(
                LinkValidatorService,
                "validate_url",
                new_callable=AsyncMock,
                return_value=validated_url,
            ):
                response = await client.request(
                    method,
                    path,
                    headers=headers,
                    params=params,
                    json=body if body is not None else None,
                )

            assert response.status_code == response_contract["status"], (
                f"{interaction['description']}: expected status "
                f"{response_contract['status']}, got {response.status_code}: "
                f"{response.text}"
            )
            for name, expected_value in response_contract.get("headers", {}).items():
                assert response.headers.get(name.lower()) == expected_value
            if "body" in response_contract:
                _assert_contract_subset(response.json(), response_contract["body"])
    finally:
        app.dependency_overrides.pop(require_api_key, None)
        app.dependency_overrides.pop(get_scraper_service, None)
        app.dependency_overrides.pop(get_discovery_service, None)
