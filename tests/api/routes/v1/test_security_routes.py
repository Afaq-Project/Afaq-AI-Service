# [OMA-W001-T006] API route integration tests for POST /api/v1/security/inspect-url

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.api.dependencies import get_api_key_service, require_api_key
from src.main import app
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.security.services.link_validator_service import LinkValidatorService


# [OMA-W001-T006] Test successful URL inspection via diagnostic REST API (200 OK)
@pytest.mark.asyncio
async def test_inspect_url_success(client: AsyncClient):
    """Protects POST /api/v1/security/inspect-url: returns 200 OK with ValidatedUrl payload."""
    mock_key = ApiKeyInfo(id="key_1", name="test_partner", is_active=True)
    app.dependency_overrides[require_api_key] = lambda: mock_key

    try:
        with patch.object(
            LinkValidatorService,
            "_resolve_host",
            new_callable=AsyncMock,
            return_value="93.184.216.34",
        ):
            payload = {"url": "https://scholarships.example.edu/programs/2026"}
            response = await client.post("/api/v1/security/inspect-url", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["message"] == "URL verified as safe."
        assert (
            body["data"]["original_url"]
            == "https://scholarships.example.edu/programs/2026"
        )
        assert (
            body["data"]["canonical_url"]
            == "https://scholarships.example.edu/programs/2026"
        )
        assert body["data"]["resolved_ip"] == "93.184.216.34"
        assert body["data"]["port"] == 443
        assert body["data"]["is_https"] is True
        assert "--host-resolver-rules=" in body["data"]["dns_pinned_rule"]
    finally:
        app.dependency_overrides.pop(require_api_key, None)


# [OMA-W001-T006] Test inspect-url with relative path and base_url
@pytest.mark.asyncio
async def test_inspect_url_relative_with_base_url(client: AsyncClient):
    """Protects relative URL resolution through the REST API endpoint."""
    mock_key = ApiKeyInfo(id="key_1", name="test_partner", is_active=True)
    app.dependency_overrides[require_api_key] = lambda: mock_key

    try:
        with patch.object(
            LinkValidatorService,
            "_resolve_host",
            new_callable=AsyncMock,
            return_value="93.184.216.34",
        ):
            payload = {
                "url": "/catalog/2026",
                "base_url": "https://scholarships.example.edu",
            }
            response = await client.post("/api/v1/security/inspect-url", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["canonical_url"] == "https://scholarships.example.edu/catalog/2026"
    finally:
        app.dependency_overrides.pop(require_api_key, None)


# [OMA-W001-T006] Test inspect-url with allow_redirects=False
@pytest.mark.asyncio
async def test_inspect_url_no_redirects(client: AsyncClient):
    """Protects allow_redirects flag passed in request payload."""
    mock_key = ApiKeyInfo(id="key_1", name="test_partner", is_active=True)
    app.dependency_overrides[require_api_key] = lambda: mock_key

    try:
        with patch.object(
            LinkValidatorService,
            "_resolve_host",
            new_callable=AsyncMock,
            return_value="93.184.216.34",
        ):
            payload = {
                "url": "https://scholarships.example.edu",
                "allow_redirects": False,
            }
            response = await client.post("/api/v1/security/inspect-url", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["redirect_hops"] == 0
    finally:
        app.dependency_overrides.pop(require_api_key, None)


# [OMA-W001-T006] Test security validation failure returns HTTP 400 Bad Request
@pytest.mark.asyncio
async def test_inspect_url_security_failure_400(client: AsyncClient):
    """Protects API error mapping: SecurityValidationError maps to 400 Bad Request with detail."""
    mock_key = ApiKeyInfo(id="key_1", name="test_partner", is_active=True)
    app.dependency_overrides[require_api_key] = lambda: mock_key

    try:
        # SSRF target to AWS IMDS
        ssrf_payload = {"url": "http://169.254.169.254/latest/meta-data/"}
        response = await client.post("/api/v1/security/inspect-url", json=ssrf_payload)

        assert response.status_code == 400
        assert "detail" in response.json()
        assert (
            "destination" in response.json()["detail"]
            or "SSRF" in response.json()["detail"]
        )

        # Path traversal target
        trav_payload = {"url": "https://example.edu/static/../../etc/passwd"}
        trav_response = await client.post(
            "/api/v1/security/inspect-url", json=trav_payload
        )

        assert trav_response.status_code == 400
        assert "Path traversal token detected" in trav_response.json()["detail"]
    finally:
        app.dependency_overrides.pop(require_api_key, None)


# [OMA-W001-T006] Test schema validation failure returns HTTP 422 Unprocessable Entity
@pytest.mark.asyncio
async def test_inspect_url_validation_failure_422(client: AsyncClient):
    """Protects schema validation: malformed request bodies return 422."""
    mock_key = ApiKeyInfo(id="key_1", name="test_partner", is_active=True)
    app.dependency_overrides[require_api_key] = lambda: mock_key

    try:
        # Missing required field 'url'
        response = await client.post("/api/v1/security/inspect-url", json={})
        assert response.status_code == 422

        # Extra forbidden field
        response_extra = await client.post(
            "/api/v1/security/inspect-url",
            json={"url": "https://example.edu", "extra_bad_key": "val"},
        )
        assert response_extra.status_code == 422
    finally:
        app.dependency_overrides.pop(require_api_key, None)


# [OMA-W001-T006] Test unauthorized access returns HTTP 401 Unauthorized
@pytest.mark.asyncio
async def test_inspect_url_unauthorized_401(client: AsyncClient):
    """Protects authentication boundary: missing or invalid API key returns 401."""
    app.dependency_overrides.pop(require_api_key, None)

    mock_auth_service = AsyncMock()
    mock_auth_service.validate = AsyncMock(return_value=None)
    app.dependency_overrides[get_api_key_service] = lambda: mock_auth_service

    try:
        response = await client.post(
            "/api/v1/security/inspect-url",
            json={"url": "https://example.edu"},
            headers={"X-API-Key": "invalid_or_missing"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid or missing API key"
    finally:
        app.dependency_overrides.pop(get_api_key_service, None)
