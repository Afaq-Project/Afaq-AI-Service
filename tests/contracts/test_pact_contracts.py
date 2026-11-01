import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.api.dependencies import require_api_key
from src.main import app
from src.modules.core.auth.models import ApiKeyInfo


@pytest.mark.asyncio
async def test_verify_pact_contracts(client: AsyncClient):
    """Verifies that the application fulfills the published Pact contract."""
    pact_file = (
        Path(__file__).parents[2] / "pacts" / "afaq-main-service-afaq-ai-service.json"
    )
    assert pact_file.exists(), f"Pact contract file not found at {pact_file}"

    contract = json.loads(pact_file.read_text(encoding="utf-8"))
    assert contract["provider"]["name"] == "afaq-ai-service"

    for interaction in contract["interactions"]:
        req = interaction["request"]
        expected_res = interaction["response"]
        method = req["method"]
        path = req["path"]
        headers = req.get("headers", {})
        body = req.get("body")

        if path == "/health":
            with patch("src.api.routes.v1.health.get_client") as mock_get_client:
                mock_prisma = AsyncMock()
                mock_prisma.query_raw = AsyncMock(return_value=[{"?column?": 1}])
                mock_get_client.return_value = mock_prisma

                response = await client.request(method, path, headers=headers)
                assert (
                    response.status_code == expected_res["status"]
                ), f"Mismatch on {path}: expected {expected_res['status']}, got {response.status_code}"
                assert response.json() == expected_res["body"]

        elif path == "/api/v1/webhook/scrape-complete":
            mock_key_info = ApiKeyInfo(
                id="00000000-0000-0000-0000-000000000001",
                key="test-key",
                name="Afaq Main Service",
                is_active=True,
            )
            app.dependency_overrides[require_api_key] = lambda k=mock_key_info: k
            try:
                response = await client.request(
                    method, path, headers=headers, json=body
                )
                assert (
                    response.status_code == expected_res["status"]
                ), f"Mismatch on {path}: expected {expected_res['status']}, got {response.status_code}"
                assert response.json() == expected_res["body"]
            finally:
                app.dependency_overrides.pop(require_api_key, None)
