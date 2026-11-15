# [OMA-W001-T006] Unit tests for LinkValidatorService

import socket
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.modules.security.exceptions import (
    CircularRedirectError,
    HomographAttackError,
    InvalidUrlPortError,
    InvalidUrlSchemeError,
    InvalidUrlSyntaxError,
    MaxRedirectsExceededError,
    PathTraversalError,
    RateLimitedCooldownError,
    SSRFAttemptBlockedError,
)
from src.modules.security.models import ValidatedUrl
from src.modules.security.services.link_validator_service import (
    LinkValidator,
    LinkValidatorService,
)


# [OMA-W001-T006] UC-01: Standard Public Educational Link Validation
@pytest.mark.asyncio
async def test_valid_public_https_url_resolves():
    """UC-01: Standard Public Educational Link Validation."""
    raw_url = "https://scholarships.example.edu/programs/2026"

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        # Transport returns 200 OK directly
        transport = httpx.MockTransport(lambda req: httpx.Response(200))
        async with httpx.AsyncClient(transport=transport) as client:
            result = await LinkValidatorService.validate_url(raw_url, client=client)

    assert isinstance(result, ValidatedUrl)
    assert result.original_url == raw_url
    assert result.canonical_url == "https://scholarships.example.edu/programs/2026"
    assert result.scheme == "https"
    assert result.host == "scholarships.example.edu"
    assert result.port == 443
    assert result.resolved_ip == "93.184.216.34"
    assert result.is_https is True
    assert result.redirect_hops == 0
    assert result.redirect_chain == []
    assert (
        result.dns_pinned_rule
        == "--host-resolver-rules=MAP scholarships.example.edu 93.184.216.34"
    )


# [OMA-W001-T006] UC-04: Relative URL Reference Resolution (FR-013)
@pytest.mark.asyncio
async def test_relative_url_resolves_with_base_url():
    """UC-04: Resolves relative path against base_url per RFC 3986."""
    relative_url = "/scholarships/detail/491"
    base_url = "https://example.edu/catalog/page/2"

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        transport = httpx.MockTransport(lambda req: httpx.Response(200))
        async with httpx.AsyncClient(transport=transport) as client:
            result = await LinkValidatorService.validate_url(
                relative_url, base_url=base_url, client=client
            )

    assert result.canonical_url == "https://example.edu/scholarships/detail/491"
    assert result.host == "example.edu"
    assert result.scheme == "https"


# [OMA-W001-T006] UC-05: IDN Homograph Cyrillic Domain Spoofing
@pytest.mark.asyncio
async def test_homograph_cyrillic_spoofing_rejected():
    """UC-05: Detects mixed-script Cyrillic spoofing in domain and rejects with HomographAttackError."""
    # 'о' is Cyrillic U+043E
    spoofed_url = "https://oxf\u043erd.edu/grant"

    with pytest.raises(HomographAttackError) as exc_info:
        await LinkValidatorService.validate_url(spoofed_url)

    assert "IDN homograph attack detected" in str(exc_info.value)
    assert exc_info.value.error_code == "ERR_HOMOGRAPH_ATTACK"


# [OMA-W001-T006] UC-09: Circular Redirect Loop Trap
@pytest.mark.asyncio
async def test_circular_redirect_loop_detected():
    """UC-09: Detects redirect cycle (/a -> /b -> /a) and raises CircularRedirectError."""
    url = "https://example.edu/a"

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/a":
            return httpx.Response(302, headers={"Location": "/b"})
        if path == "/b":
            return httpx.Response(302, headers={"Location": "https://example.edu/a"})
        return httpx.Response(200)

    transport = httpx.MockTransport(redirect_handler)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(CircularRedirectError) as exc_info:
                await LinkValidatorService.validate_url(url, client=client)

    assert exc_info.value.error_code == "ERR_CIRCULAR_REDIRECT"
    assert "Circular redirect detected" in str(exc_info.value)


# [OMA-W001-T006] UC-10: Deep Redirect Chain Exceeding 5 Hops
@pytest.mark.asyncio
async def test_max_redirects_exceeded_error():
    """UC-10: Detects redirect chain exceeding threshold of 5 hops."""
    url = "https://example.edu/hop0"

    def chain_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/hop"):
            hop_num = int(path.replace("/hop", ""))
            return httpx.Response(302, headers={"Location": f"/hop{hop_num + 1}"})
        return httpx.Response(200)

    transport = httpx.MockTransport(chain_handler)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(MaxRedirectsExceededError) as exc_info:
                await LinkValidatorService.validate_url(url, client=client)

    assert exc_info.value.error_code == "ERR_MAX_REDIRECTS_EXCEEDED"
    assert "Maximum redirect hops (5) exceeded" in str(exc_info.value)


# [OMA-W001-T006] UC-15: Non-Standard Internal Port Querying
@pytest.mark.asyncio
async def test_non_standard_ports_rejected():
    """UC-15: Rejects ports outside 80 and 443 with InvalidUrlPortError."""
    disallowed_urls = [
        "http://victim.org:6379/eval",
        "https://victim.org:8080/admin",
        "http://victim.org:22/ssh",
        "http://victim.org:8443/dash",
    ]

    for url in disallowed_urls:
        with pytest.raises(InvalidUrlPortError) as exc_info:
            await LinkValidatorService.validate_url(url)
        assert exc_info.value.error_code == "ERR_INVALID_PORT"
        assert "Only ports 80 and 443 are allowed" in str(exc_info.value)


# [OMA-W001-T006] UC-16: Disallowed Schemes (file:, gopher:, data:, etc.)
@pytest.mark.asyncio
async def test_disallowed_schemes_rejected():
    """UC-16: Rejects unsafe schemes with InvalidUrlSchemeError."""
    disallowed_schemes = [
        "file:///etc/passwd",
        "gopher://127.0.0.1:70/",
        "data:text/html,<html>alert(1)</html>",
        "ftp://mirror.example.edu/pub/",
        "javascript:alert(1)",
    ]

    for url in disallowed_schemes:
        with pytest.raises(InvalidUrlSchemeError) as exc_info:
            await LinkValidatorService.validate_url(url)
        assert exc_info.value.error_code == "ERR_INVALID_SCHEME"


# [OMA-W001-T006] UC-17: HTTP 429 Rate Limiting with High Retry-After
@pytest.mark.asyncio
async def test_http_429_retry_after_cooldown():
    """UC-17: Parses Retry-After header; raises RateLimitedCooldownError if > 300 seconds."""
    url = "https://example.edu/rate-limited"

    def rate_limit_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1200"})

    transport = httpx.MockTransport(rate_limit_handler)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(RateLimitedCooldownError) as exc_info:
                await LinkValidatorService.validate_url(url, client=client)

    assert exc_info.value.error_code == "ERR_RATE_LIMITED_COOLDOWN"
    assert exc_info.value.retry_after == 1200.0
    assert "exceeding 300s threshold" in str(exc_info.value)


# [OMA-W001-T006] Test empty and invalid URL syntax
@pytest.mark.asyncio
async def test_empty_and_invalid_syntax_rejected():
    """Protects input syntax invariants: empty, whitespace, or missing hostname."""
    with pytest.raises(InvalidUrlSyntaxError) as exc_1:
        await LinkValidatorService.validate_url("")
    assert exc_1.value.error_code == "ERR_INVALID_URL_SYNTAX"

    with pytest.raises(InvalidUrlSyntaxError) as exc_2:
        await LinkValidatorService.validate_url("   ")
    assert exc_2.value.error_code == "ERR_INVALID_URL_SYNTAX"

    with pytest.raises(InvalidUrlSyntaxError) as exc_3:
        await LinkValidatorService.validate_url("https:///no-host-path")
    assert exc_3.value.error_code == "ERR_INVALID_URL_SYNTAX"


# [OMA-W001-T006] Test path traversal patterns in URL
@pytest.mark.asyncio
async def test_path_traversal_tokens_rejected():
    """Protects path traversal invariants: rejects raw and encoded path traversal tokens."""
    traversal_inputs = [
        "https://example.edu/static/../../etc/passwd",
        "https://example.edu/static/..\\..\\windows\\win.ini",
        "https://example.edu/static/%2e%2e/secret",
        "https://example.edu/static/..%2fprivate",
        "https://example.edu/static/%2e%2e%2fprivate",
        "https://example.edu/static/..%5cprivate",
        "https://example.edu/static/%2e%2e%5cprivate",
    ]

    for trav_url in traversal_inputs:
        with pytest.raises(PathTraversalError) as exc_info:
            await LinkValidatorService.validate_url(trav_url)
        assert exc_info.value.error_code == "ERR_PATH_TRAVERSAL"


# [OMA-W001-T006] Test relative URL validation errors with missing or invalid base_url
@pytest.mark.asyncio
async def test_relative_url_error_cases():
    """Protects FR-013 invariants: relative URLs require valid base_url."""
    # Relative URL without base_url
    with pytest.raises(InvalidUrlSchemeError) as exc_1:
        await LinkValidatorService.validate_url("/path/to/doc")
    assert exc_1.value.error_code == "ERR_INVALID_SCHEME"
    assert "Relative URL requires base_url" in str(exc_1.value)

    # Relative URL with invalid base_url scheme
    with pytest.raises(InvalidUrlSchemeError) as exc_2:
        await LinkValidatorService.validate_url(
            "/path/to/doc", base_url="ftp://ftp.example.com"
        )
    assert exc_2.value.error_code == "ERR_INVALID_SCHEME"

    # Relative URL with base_url lacking hostname
    with pytest.raises(InvalidUrlSchemeError) as exc_3:
        await LinkValidatorService.validate_url(
            "/path/to/doc", base_url="https:///missing-host"
        )
    assert exc_3.value.error_code == "ERR_INVALID_SCHEME"

    # Relative URL that resolves to path traversal
    with pytest.raises(PathTraversalError) as exc_4:
        await LinkValidatorService.validate_url(
            "../../secret", base_url="https://example.edu/sub/"
        )
    assert exc_4.value.error_code == "ERR_PATH_TRAVERSAL"


# [OMA-W001-T006] Test IDN Greek homograph and IDNA decode error handling
@pytest.mark.asyncio
async def test_homograph_greek_and_encoding():
    """Protects UC-05 invariants: Greek mixed-script and invalid IDNA encoding."""
    # Greek omicron \u03bf mixed with Latin
    greek_mixed_url = "https://\u03bfxford.edu/scholarship"
    with pytest.raises(HomographAttackError) as exc_info:
        await LinkValidatorService.validate_url(greek_mixed_url)
    assert exc_info.value.error_code == "ERR_HOMOGRAPH_ATTACK"

    # Label exceeding 63 characters fails idna encoding
    long_label_url = f"https://{'a' * 64}.example.edu/path"
    with pytest.raises(InvalidUrlSyntaxError) as enc_exc:
        await LinkValidatorService.validate_url(long_label_url)
    assert enc_exc.value.error_code == "ERR_INVALID_URL_SYNTAX"

    # Punycode with cyrillic
    with patch(
        "src.modules.security.services.link_validator_service.unicodedata.name",
        return_value="CYRILLIC SMALL LETTER O",
    ):
        with pytest.raises(HomographAttackError):
            LinkValidatorService._check_homograph("xn--something.com")


# [OMA-W001-T006] Test pinned_ip parameter behavior
@pytest.mark.asyncio
async def test_pinned_ip_parameter():
    """Protects DNS pinning feature: valid public pinned_ip is accepted, blocked pinned_ip is rejected."""
    url = "https://example.edu/page"

    # Blocked private pinned_ip
    with pytest.raises(SSRFAttemptBlockedError) as exc_info:
        await LinkValidatorService.validate_url(url, pinned_ip="192.168.1.1")
    assert exc_info.value.error_code == "ERR_SSRF_ATTEMPT_BLOCKED"

    # Valid public pinned_ip bypasses DNS resolution
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await LinkValidatorService.validate_url(
            url, pinned_ip="93.184.216.34", client=client
        )
    assert result.resolved_ip == "93.184.216.34"
    assert (
        result.dns_pinned_rule == "--host-resolver-rules=MAP example.edu 93.184.216.34"
    )


# [OMA-W001-T006] Test allow_redirects=False disables redirect probing
@pytest.mark.asyncio
async def test_allow_redirects_false():
    """Protects allow_redirects=False flag: immediately returns without HTTP probing."""
    url = "https://example.edu/redirect-me"

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        result = await LinkValidatorService.validate_url(url, allow_redirects=False)

    assert result.redirect_hops == 0
    assert result.redirect_chain == []
    assert result.canonical_url == "https://example.edu/redirect-me"


# [OMA-W001-T006] Test Retry-After header parsing edge cases
def test_parse_retry_after_parser():
    """Protects _parse_retry_after parsing: integer seconds, HTTP-date, past date, and invalid strings."""
    # Integer string
    assert LinkValidatorService._parse_retry_after("120") == 120.0
    assert LinkValidatorService._parse_retry_after("  300  ") == 300.0

    # Valid future HTTP-date (RFC 2822)
    future_time = datetime.now(UTC) + timedelta(seconds=600)
    http_date = future_time.strftime("%a, %d %b %Y %H:%M:%S GMT")
    parsed_sec = LinkValidatorService._parse_retry_after(http_date)
    assert parsed_sec is not None
    assert 580 <= parsed_sec <= 620

    # Past HTTP-date returns 0.0
    past_time = datetime.now(UTC) - timedelta(seconds=100)
    past_http_date = past_time.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert LinkValidatorService._parse_retry_after(past_http_date) == 0.0

    # Invalid header string returns None
    assert LinkValidatorService._parse_retry_after("not-a-valid-date") is None


# [OMA-W001-T006] Test rate limit 429 and 503 response conditions
@pytest.mark.asyncio
async def test_rate_limiting_responses():
    """Protects rate limiting checks: 429 with small Retry-After, 503 with high Retry-After, and 429 without header."""
    url = "https://example.edu/probe"

    # 429 with Retry-After <= 300 does not raise RateLimitedCooldownError
    transport_small = httpx.MockTransport(
        lambda req: httpx.Response(429, headers={"Retry-After": "60"})
    )
    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=transport_small) as client:
            res = await LinkValidatorService.validate_url(url, client=client)
            assert res.canonical_url == "https://example.edu/probe"

    # 503 with Retry-After > 300 raises RateLimitedCooldownError
    transport_503 = httpx.MockTransport(
        lambda req: httpx.Response(503, headers={"Retry-After": "500"})
    )
    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=transport_503) as client:
            with pytest.raises(RateLimitedCooldownError) as exc_503:
                await LinkValidatorService.validate_url(url, client=client)
            assert exc_503.value.retry_after == 500.0

    # 429 with no Retry-After header breaks loop cleanly
    transport_no_hdr = httpx.MockTransport(lambda req: httpx.Response(429))
    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=transport_no_hdr) as client:
            res_no_hdr = await LinkValidatorService.validate_url(url, client=client)
            assert res_no_hdr.canonical_url == "https://example.edu/probe"


# [OMA-W001-T006] Test redirect chain edge cases: 405 fallback, HTTP error, missing Location, and validation errors
@pytest.mark.asyncio
async def test_redirect_edge_cases():
    """Protects redirect traversal robustness: 405 HEAD fallback, connection error handling, missing location."""
    url = "https://example.edu/start"

    # Case 1: 405 on HEAD falls back to GET
    def handler_405(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(200)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler_405)
        ) as client:
            res = await LinkValidatorService.validate_url(url, client=client)
            assert res.canonical_url == "https://example.edu/start"

    # Case 2: httpx.HTTPError during probe breaks cleanly
    def handler_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler_error)
        ) as client:
            res_err = await LinkValidatorService.validate_url(url, client=client)
            assert res_err.canonical_url == "https://example.edu/start"

    # Case 3: Redirect with 302 but missing Location header breaks cleanly
    handler_missing_loc = httpx.MockTransport(lambda req: httpx.Response(302))
    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=handler_missing_loc) as client:
            res_missing = await LinkValidatorService.validate_url(url, client=client)
            assert res_missing.canonical_url == "https://example.edu/start"


# [OMA-W001-T006] Test redirect validation errors: path traversal, scheme, port, missing host, and homograph in redirect
@pytest.mark.asyncio
async def test_redirect_validation_rejections():
    """Protects redirect safety gates: redirect targets must adhere to all URL safety constraints."""
    url = "https://example.edu/start"

    # Redirect to encoded path traversal (%2e%2e)
    def h_trav(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/static/%2e%2e/passwd"})
        return httpx.Response(200)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=httpx.MockTransport(h_trav)) as client:
            with pytest.raises(PathTraversalError):
                await LinkValidatorService.validate_url(url, client=client)

    # Redirect to disallowed scheme (ftp://)
    def h_scheme(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/start":
            return httpx.Response(302, headers={"Location": "ftp://example.com/file"})
        return httpx.Response(200)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=httpx.MockTransport(h_scheme)) as client:
            with pytest.raises(InvalidUrlSchemeError):
                await LinkValidatorService.validate_url(url, client=client)

    # Redirect to invalid port (8080)
    def h_port(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/start":
            return httpx.Response(
                302, headers={"Location": "https://example.com:8080/dest"}
            )
        return httpx.Response(200)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=httpx.MockTransport(h_port)) as client:
            with pytest.raises(InvalidUrlPortError):
                await LinkValidatorService.validate_url(url, client=client)

    # Redirect missing hostname
    def h_nohost(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/start":
            return httpx.Response(302, headers={"Location": "http:///missing-host"})
        return httpx.Response(200)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=httpx.MockTransport(h_nohost)) as client:
            with pytest.raises(InvalidUrlSyntaxError):
                await LinkValidatorService.validate_url(url, client=client)

    # Redirect to homograph domain
    def h_homograph(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/start":
            return httpx.Response(
                302,
                headers=[
                    (b"Location", "https://oxf\u043erd.edu/target".encode("utf-8"))
                ],
            )
        return httpx.Response(200)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(h_homograph)
        ) as client:
            with pytest.raises(HomographAttackError):
                await LinkValidatorService.validate_url(url, client=client)


# [OMA-W001-T006] Test DNS resolution errors in _resolve_host
@pytest.mark.asyncio
async def test_resolve_host_dns_failures():
    """Protects DNS resolution error handling: socket.gaierror and empty addrinfo."""
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = AsyncMock()
        mock_loop.getaddrinfo = AsyncMock(
            side_effect=socket.gaierror("Name or service not known")
        )
        mock_get_loop.return_value = mock_loop

        with pytest.raises(InvalidUrlSyntaxError) as exc_info:
            await LinkValidatorService._resolve_host("unresolvable.example", 443)
        assert exc_info.value.error_code == "ERR_INVALID_URL_SYNTAX"

    with patch("asyncio.get_running_loop") as mock_get_loop_2:
        mock_loop_2 = AsyncMock()
        mock_loop_2.getaddrinfo = AsyncMock(return_value=[])
        mock_get_loop_2.return_value = mock_loop_2

        with pytest.raises(InvalidUrlSyntaxError) as exc_empty:
            await LinkValidatorService._resolve_host("empty.example", 443)
        assert exc_empty.value.error_code == "ERR_INVALID_URL_SYNTAX"


# [OMA-W001-T006] Test public IP literal in validate_url and _resolve_host
@pytest.mark.asyncio
async def test_public_ip_literal_validation():
    """Protects direct IP literal handling when the IP is public."""
    url = "http://93.184.216.34/"
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await LinkValidatorService.validate_url(url, client=client)

    assert result.host == "93.184.216.34"
    assert result.resolved_ip == "93.184.216.34"
    assert result.port == 80
    assert result.is_https is False


# [OMA-W001-T006] Test internal _is_blocked_ip edge cases
def test_is_blocked_ip_edge_cases():
    """Protects IP filtering edge cases: invalid strings, IPv4-mapped IPv6, AWS IMDS."""
    # Invalid string is treated as blocked (fail-closed)
    assert LinkValidatorService._is_blocked_ip("not-an-ip-string") is True

    # Public IPv6 address is allowed
    assert LinkValidatorService._is_blocked_ip("2606:4700:4700::1111") is False

    # IPv4-mapped IPv6 addresses inherit the policy of their embedded IPv4.
    assert LinkValidatorService._is_blocked_ip("::ffff:93.184.216.34") is False
    assert LinkValidatorService._is_blocked_ip("::ffff:10.0.0.1") is True

    # AWS IMDS explicit string
    assert LinkValidatorService._is_blocked_ip("169.254.169.254") is True


# [OMA-W001-T006] Test _resolve_host edge cases: loopback hostnames, direct public IP, and multi-record DNS
@pytest.mark.asyncio
async def test_resolve_host_edge_cases():
    """Protects _resolve_host branches: direct IP resolution, loopback blocking, and multi-address checking."""
    # Direct public IP
    res_ip = await LinkValidatorService._resolve_host("93.184.216.34", 80)
    assert res_ip == "93.184.216.34"

    # Loopback hostname passed to _resolve_host
    with pytest.raises(SSRFAttemptBlockedError):
        await LinkValidatorService._resolve_host("localhost", 80)

    # Multi-address DNS response with one private IP raises SSRFAttemptBlockedError
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = AsyncMock()
        mock_loop.getaddrinfo = AsyncMock(
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
            ]
        )
        mock_get_loop.return_value = mock_loop

        with pytest.raises(SSRFAttemptBlockedError):
            await LinkValidatorService._resolve_host("multi-homed.example", 443)

    # Multi-address DNS response with all public IPs returns verified IP
    with patch("asyncio.get_running_loop") as mock_get_loop_2:
        mock_loop_2 = AsyncMock()
        mock_loop_2.getaddrinfo = AsyncMock(
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.35", 443)),
            ]
        )
        mock_get_loop_2.return_value = mock_loop_2

        verified = await LinkValidatorService._resolve_host("multi-public.example", 443)
        assert verified == "93.184.216.34"


# [OMA-W001-T006] Test _parse_retry_after with naive datetime
def test_parse_retry_after_naive_datetime():
    """Protects _parse_retry_after with date string converted to naive datetime."""
    with patch("email.utils.parsedate_to_datetime") as mock_parse:
        mock_parse.return_value = datetime.now().replace(tzinfo=None) + timedelta(
            seconds=120
        )
        res = LinkValidatorService._parse_retry_after("Tue, 15 Nov 2030 12:45:26 GMT")
        assert res is not None
        assert res > 0


# [OMA-W001-T006] Test _check_homograph character raising ValueError
def test_check_homograph_unknown_unicode_char():
    """Protects _check_homograph when a character has no standard unicode name."""
    with patch("unicodedata.name", side_effect=ValueError("no such character")):
        # Pure ASCII-equivalent punycode should not raise homograph error
        LinkValidatorService._check_homograph("standard.edu")


# [OMA-W001-T006] Test backward compatibility alias
def test_link_validator_alias():
    """Protects public API backward-compatibility alias LinkValidator."""
    assert LinkValidator is LinkValidatorService
