"""Live API HTTP smoke tests for Afaq-AI-Service.

Tests all registered API routes against the ASGI application or live server,
validating HTTP status codes, response envelopes, authentication enforcement,
and error handling.
"""

import os

import httpx
import pytest

from src.main import app
from src.modules.core.database.prisma_client import connect, disconnect

LIVE_SERVER_URL = os.environ.get("TEST_API_URL", "http://127.0.0.1:8000")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "k6-test-key-secret-12345")
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


@pytest.fixture(autouse=True)
async def manage_database_connection():
    """Ensure Prisma client is connected to current test's event loop."""
    await connect()
    yield
    await disconnect()


@pytest.fixture
async def api_client():
    """Returns an async HTTP client configured for live server or in-process ASGI fallback."""
    is_live = False
    try:
        async with httpx.AsyncClient(timeout=1.0) as check_client:
            res = await check_client.get(f"{LIVE_SERVER_URL}/health")
            if res.status_code == 200:
                is_live = True
    except Exception:
        is_live = False

    if is_live:
        async with httpx.AsyncClient(base_url=LIVE_SERVER_URL, timeout=10.0) as client:
            yield client
    else:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=10.0) as client:
            yield client


@pytest.mark.asyncio
async def test_health_check_endpoint(api_client: httpx.AsyncClient):
    """GET /health must return 200 OK with status and database connection status."""
    response = await api_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "database" in data


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(api_client: httpx.AsyncClient):
    """Protected endpoints must reject requests lacking X-API-Key with 401."""
    response = await api_client.post("/api/v1/security/inspect-url", json={"url": "https://example.edu"})
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_invalid_api_key_rejected(api_client: httpx.AsyncClient):
    """Protected endpoints must reject requests with invalid X-API-Key."""
    response = await api_client.get("/api/v1/scrape/operations", headers={"X-API-Key": "invalid-secret-key"})
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_inspect_url_valid(api_client: httpx.AsyncClient):
    """POST /api/v1/security/inspect-url validates safe public URLs."""
    response = await api_client.post(
        "/api/v1/security/inspect-url",
        headers=AUTH_HEADERS,
        json={"url": "https://example.edu/scholarships", "allow_redirects": True},
    )
    # 200 on success or 400 on SSRF / blocked IP
    assert response.status_code in {200, 400}
    if response.status_code == 200:
        data = response.json()
        assert data["status"] == "success"
        assert "canonical_url" in data["data"]


@pytest.mark.asyncio
async def test_operations_log_pagination(api_client: httpx.AsyncClient):
    """GET /api/v1/scrape/operations returns paginated operations list."""
    response = await api_client.get(
        "/api/v1/scrape/operations?limit=5&offset=0",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "operations" in body["data"]
    assert "total_count" in body["data"]
    assert isinstance(body["data"]["operations"], list)


@pytest.mark.asyncio
async def test_operations_latest(api_client: httpx.AsyncClient):
    """GET /api/v1/scrape/operations/latest returns latest operation or null."""
    response = await api_client.get(
        "/api/v1/scrape/operations/latest",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    # data is either an operation object or null
    assert body["data"] is None or isinstance(body["data"], dict)


@pytest.mark.asyncio
async def test_operation_by_id_validation(api_client: httpx.AsyncClient):
    """GET /api/v1/scrape/operations/{id} rejects malformed UUID with 422 and missing UUID with 404."""
    # Malformed UUID
    res_malformed = await api_client.get(
        "/api/v1/scrape/operations/not-a-uuid",
        headers=AUTH_HEADERS,
    )
    assert res_malformed.status_code == 422

    # Non-existent UUID
    res_missing = await api_client.get(
        "/api/v1/scrape/operations/00000000-0000-0000-0000-000000000000",
        headers=AUTH_HEADERS,
    )
    assert res_missing.status_code == 404


@pytest.mark.asyncio
async def test_dead_letter_queue_query(api_client: httpx.AsyncClient):
    """GET /api/v1/scrape/dead-letter returns dead letter records with limit/offset."""
    response = await api_client.get(
        "/api/v1/scrape/dead-letter?limit=10&offset=0",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "items" in body["data"]
    assert "total_count" in body["data"]


@pytest.mark.asyncio
async def test_webhook_scrape_complete_delivery(api_client: httpx.AsyncClient):
    """POST /api/v1/webhook/scrape-complete validates and accepts incoming webhook."""
    payload = {
        "event": "scrape.completed",
        "operation_id": "11111111-1111-4111-8111-111111111111",
        "batch_id": "batch-smoke-001",
        "status": "completed",
        "total_opportunities": 5,
        "succeeded_count": 5,
        "failed_count": 0,
    }
    response = await api_client.post(
        "/api/v1/webhook/scrape-complete",
        headers=AUTH_HEADERS,
        json=payload,
    )
    assert response.status_code in {200, 202}
    body = response.json()
    assert body["status"] in {"success", "received"}
