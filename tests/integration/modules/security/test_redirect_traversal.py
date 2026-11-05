# [OMA-W001-T006] Integration tests for multi-hop redirect chain traversal

from unittest.mock import patch

import httpx
import pytest

from src.modules.security.models import ValidatedUrl
from src.modules.security.services.link_validator_service import LinkValidatorService


# [OMA-W001-T006] UC-07: Multi-Hop Safe Redirect Chain (<= 5 Hops)
@pytest.mark.asyncio
async def test_safe_redirect_chain_traversal():
    """UC-07: Multi-Hop Safe Redirect Chain Traversal using MockTransport.

    Verifies hop 1 (301 Moved Permanently) and hop 2 (302 Found) leading to final 200 OK,
    recording full chain, hop count, and deriving final DNS pinning rules.
    """
    initial_url = "http://short.edu/1"

    # Map domains to verified public IPs
    dns_records = {
        "short.edu": "93.184.216.34",
        "middle.edu": "93.184.216.35",
        "final.edu": "93.184.216.36",
    }

    async def mock_resolve_host(host: str, port: int) -> str:
        if host in dns_records:
            return dns_records[host]
        return "93.184.216.100"

    # MockTransport routing requests along the redirect chain
    def redirect_router(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str == "http://short.edu/1":
            return httpx.Response(301, headers={"Location": "https://middle.edu/2"})
        if url_str == "https://middle.edu/2":
            return httpx.Response(302, headers={"Location": "https://final.edu/target"})
        if url_str == "https://final.edu/target":
            return httpx.Response(
                200, html="<html><body>Final Scholarship Page</body></html>"
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(redirect_router)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        side_effect=mock_resolve_host,
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            result = await LinkValidatorService.validate_url(
                raw_url=initial_url,
                allow_redirects=True,
                client=client,
            )

    assert isinstance(result, ValidatedUrl)
    assert result.original_url == "http://short.edu/1"
    assert result.canonical_url == "https://final.edu/target"
    assert result.scheme == "https"
    assert result.host == "final.edu"
    assert result.port == 443
    assert result.resolved_ip == "93.184.216.36"
    assert result.is_https is True
    assert result.redirect_hops == 2
    assert result.redirect_chain == [
        "https://middle.edu/2",
        "https://final.edu/target",
    ]
    assert result.dns_pinned_rule == "--host-resolver-rules=MAP final.edu 93.184.216.36"


# [OMA-W001-T006] Test relative redirect paths in multi-hop traversal
@pytest.mark.asyncio
async def test_relative_redirect_chain():
    """Protects RFC 3986 relative location resolution across multiple redirect hops."""
    start_url = "https://university.edu/admissions"

    def relative_router(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str == "https://university.edu/admissions":
            return httpx.Response(302, headers={"Location": "scholarships/"})
        if url_str == "https://university.edu/scholarships/":
            return httpx.Response(307, headers={"Location": "undergraduate/2026"})
        if url_str == "https://university.edu/scholarships/undergraduate/2026":
            return httpx.Response(200)
        return httpx.Response(404)

    transport = httpx.MockTransport(relative_router)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        return_value="93.184.216.50",
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            result = await LinkValidatorService.validate_url(
                start_url, allow_redirects=True, client=client
            )

    assert (
        result.canonical_url == "https://university.edu/scholarships/undergraduate/2026"
    )
    assert result.redirect_hops == 2
    assert result.redirect_chain == [
        "https://university.edu/scholarships/",
        "https://university.edu/scholarships/undergraduate/2026",
    ]


# [OMA-W001-T006] Test boundary redirect chain of exactly 5 hops (allowed ceiling)
@pytest.mark.asyncio
async def test_exact_five_hops_allowed():
    """Protects threshold boundary: exactly 5 hops must succeed without raising MaxRedirectsExceededError."""
    start_url = "https://chain.edu/step0"

    def five_hops_router(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/step0":
            return httpx.Response(302, headers={"Location": "/step1"})
        if path == "/step1":
            return httpx.Response(302, headers={"Location": "/step2"})
        if path == "/step2":
            return httpx.Response(302, headers={"Location": "/step3"})
        if path == "/step3":
            return httpx.Response(302, headers={"Location": "/step4"})
        if path == "/step4":
            return httpx.Response(302, headers={"Location": "/step5"})
        if path == "/step5":
            return httpx.Response(200)
        return httpx.Response(404)

    transport = httpx.MockTransport(five_hops_router)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        return_value="93.184.216.50",
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            result = await LinkValidatorService.validate_url(
                start_url, allow_redirects=True, client=client
            )

    assert result.redirect_hops == 5
    assert len(result.redirect_chain) == 5
    assert result.canonical_url == "https://chain.edu/step5"


# [OMA-W001-T006] Test HTTP to HTTPS scheme upgrade via redirect
@pytest.mark.asyncio
async def test_http_to_https_upgrade_redirect():
    """Protects scheme transition: traverses port 80 to port 443 with updated netloc and is_https flag."""
    start_url = "http://portal.edu:80/home"

    def upgrade_router(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "http://portal.edu/home":
            return httpx.Response(301, headers={"Location": "https://portal.edu/home"})
        return httpx.Response(200)

    transport = httpx.MockTransport(upgrade_router)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        return_value="93.184.216.70",
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            result = await LinkValidatorService.validate_url(
                start_url, allow_redirects=True, client=client
            )

    assert result.canonical_url == "https://portal.edu/home"
    assert result.scheme == "https"
    assert result.port == 443
    assert result.is_https is True
    assert result.redirect_hops == 1
    assert result.redirect_chain == ["https://portal.edu/home"]
