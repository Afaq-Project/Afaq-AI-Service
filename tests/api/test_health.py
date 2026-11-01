from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check_healthy(client: AsyncClient):
    with patch("src.api.routes.v1.health.get_client") as mock_get_client:
        mock_prisma = AsyncMock()
        mock_prisma.query_raw = AsyncMock(return_value=[{"?column?": 1}])
        mock_get_client.return_value = mock_prisma

        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_health_check_degraded(client: AsyncClient):
    with patch("src.api.routes.v1.health.get_client") as mock_get_client:
        mock_prisma = AsyncMock()
        mock_prisma.query_raw = AsyncMock(side_effect=Exception("DB Down"))
        mock_get_client.return_value = mock_prisma

        response = await client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unavailable"
