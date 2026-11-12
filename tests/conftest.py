import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


# [OMA-W006-TEST-02] Filter StarletteDeprecationWarning for HTTP_422 deprecation in test runner
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "filterwarnings",
        "ignore::starlette.exceptions.StarletteDeprecationWarning",
    )


@pytest.fixture
async def client():
    """Async test client for FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
