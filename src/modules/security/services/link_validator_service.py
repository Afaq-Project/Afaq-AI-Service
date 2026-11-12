# [OMA-W004-T001] Streamlined LinkValidatorService using safe-web-access

import asyncio
import email.utils
import ipaddress
import socket
import unicodedata
import urllib.parse
from datetime import UTC, datetime

import httpx
from safe_web_access.exceptions import (
    InvalidUrlError,
    UnsupportedSchemeError,
)
from safe_web_access.networks import _is_public_address
from safe_web_access.urls import validate_and_normalize_url

from src.modules.security.exceptions import (
    ERR_CIRCULAR_REDIRECT,
    ERR_HOMOGRAPH_ATTACK,
    ERR_INVALID_PORT,
    ERR_INVALID_SCHEME,
    ERR_INVALID_URL_SYNTAX,
    ERR_MAX_REDIRECTS_EXCEEDED,
    ERR_PATH_TRAVERSAL,
    ERR_RATE_LIMITED_COOLDOWN,
    ERR_SSRF_ATTEMPT_BLOCKED,
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


# [OMA-W004-T001] Streamlined LinkValidatorService using safe-web-access
class LinkValidatorService:
    """Pure, non-mutating URL inspection and security gatekeeper.

    Enforces RFC 3986 canonicalization, port/scheme filtering, Anti-SSRF
    pre-request DNS verification, Chromium DNS pinning, and safe redirect
    traversal using safe-web-access.
    """

    # [OMA-W004-T001] Path traversal and relative URL resolver
    @classmethod
    def _parse_and_check_traversal(
        cls, raw_url: str, base_url: str | None
    ) -> tuple[str, urllib.parse.SplitResult]:
        """Parses target URL, resolves relative paths using base_url, and checks traversal."""
        if not raw_url or not isinstance(raw_url, str) or not raw_url.strip():
            raise InvalidUrlSyntaxError(
                "URL cannot be empty", error_code=ERR_INVALID_URL_SYNTAX
            )

        target_url = raw_url.strip()
        cls._check_path_traversal(target_url)

        parsed = urllib.parse.urlsplit(target_url)
        if not parsed.scheme:
            if not base_url:
                raise InvalidUrlSchemeError(
                    "Relative URL requires base_url",
                    error_code=ERR_INVALID_SCHEME,
                )
            base_parsed = urllib.parse.urlsplit(base_url)
            if (
                base_parsed.scheme.lower() not in ("http", "https")
                or not base_parsed.hostname
            ):
                raise InvalidUrlSchemeError(
                    "Invalid base_url scheme. Only http and https are allowed.",
                    error_code=ERR_INVALID_SCHEME,
                )
            target_url = urllib.parse.urljoin(base_url, target_url)
            parsed = urllib.parse.urlsplit(target_url)

        cls._check_path_traversal(target_url)
        return target_url, parsed

    # [OMA-W004-T001] Loopback and IP literal Anti-SSRF check using safe-web-access
    @classmethod
    def _check_loopback_and_ip_ssrf(cls, host: str) -> None:
        """Blocks loopback domain names and disallowed IP literal addresses."""
        lower_host = host.lower()
        if (
            lower_host in ("localhost", "127.0.0.1", "::1")
            or lower_host.endswith(".localhost")
            or lower_host.endswith(".local")
        ):
            raise SSRFAttemptBlockedError(
                f"Blocked SSRF attempt to loopback host: {host}",
                error_code=ERR_SSRF_ATTEMPT_BLOCKED,
            )

        try:
            ip_obj = ipaddress.ip_address(host)
            if not _is_public_address(ip_obj):
                raise SSRFAttemptBlockedError(
                    f"Blocked SSRF attempt to non-public destination: {host}",
                    error_code=ERR_SSRF_ATTEMPT_BLOCKED,
                )
        except ValueError:
            pass

    # [OMA-W004-T001] URL syntax, scheme, host, and port verification
    @classmethod
    def _verify_url_target(
        cls, parsed: urllib.parse.SplitResult
    ) -> tuple[str, str, int]:
        """Validates scheme, hostname, homograph safety, port, and IP literals."""
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise InvalidUrlSchemeError(
                f"Unsupported scheme '{scheme}'. Only http and https are allowed.",
                error_code=ERR_INVALID_SCHEME,
            )

        host = parsed.hostname
        if not host:
            raise InvalidUrlSyntaxError(
                "URL missing hostname", error_code=ERR_INVALID_URL_SYNTAX
            )

        cls._check_homograph(host)
        cls._check_loopback_and_ip_ssrf(host)

        port = parsed.port
        if port is not None:
            if port not in (80, 443):
                raise InvalidUrlPortError(
                    f"Port {port} is not permitted. Only ports 80 and 443 are allowed.",
                    error_code=ERR_INVALID_PORT,
                )
        else:
            port = 443 if scheme == "https" else 80

        return scheme, host, port

    # [OMA-W004-T001] Initial IP resolution and pinned IP verification
    @classmethod
    async def _resolve_and_verify_ip(
        cls, host: str, port: int, pinned_ip: str | None
    ) -> str:
        """Resolves target hostname to IP or verifies pinned IP against SSRF blocklist."""
        if pinned_ip:
            if cls._is_blocked_ip(pinned_ip):
                raise SSRFAttemptBlockedError(
                    f"Blocked SSRF attempt to non-public destination: {pinned_ip}",
                    error_code=ERR_SSRF_ATTEMPT_BLOCKED,
                )
            return pinned_ip
        return await cls._resolve_host(host, port)

    # [OMA-W004-T001] Canonical URL constructor
    @classmethod
    def _build_canonical_url(
        cls, scheme: str, host: str, port: int, parsed: urllib.parse.SplitResult
    ) -> str:
        """Builds RFC 3986 normalized canonical URL string."""
        netloc = (
            host
            if (port == 443 and scheme == "https") or (port == 80 and scheme == "http")
            else f"{host}:{port}"
        )
        return urllib.parse.urlunsplit(
            (scheme, netloc, parsed.path or "/", parsed.query, parsed.fragment)
        )

    # [OMA-W004-T001] Safe redirect probe execution wrapper
    @classmethod
    async def _run_redirect_probe(
        cls,
        client: httpx.AsyncClient | None,
        current_url: str,
        current_host: str,
        current_ip: str,
        current_scheme: str,
        current_port: int,
        visited: set[str],
        redirect_chain: list[str],
        redirect_hops: int,
    ) -> tuple[str, str, str, str, int, int, list[str]]:
        """Executes safe redirect traversal using provided or ephemeral httpx client."""
        if client is not None:
            return await cls._probe_redirects(
                client=client,
                current_url=current_url,
                current_host=current_host,
                current_ip=current_ip,
                current_scheme=current_scheme,
                current_port=current_port,
                visited=visited,
                redirect_chain=redirect_chain,
                redirect_hops=redirect_hops,
            )

        async with httpx.AsyncClient(
            timeout=10.0, follow_redirects=False
        ) as internal_client:
            return await cls._probe_redirects(
                client=internal_client,
                current_url=current_url,
                current_host=current_host,
                current_ip=current_ip,
                current_scheme=current_scheme,
                current_port=current_port,
                visited=visited,
                redirect_chain=redirect_chain,
                redirect_hops=redirect_hops,
            )

    # [OMA-W004-T001] Main URL validator orchestrator
    @classmethod
    async def validate_url(
        cls,
        raw_url: str,
        base_url: str | None = None,
        allow_redirects: bool = True,
        pinned_ip: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> ValidatedUrl:
        """Inspect, normalize, and verify a target URL for security invariants."""
        target_url, parsed = cls._parse_and_check_traversal(raw_url, base_url)
        scheme, host, port = cls._verify_url_target(parsed)
        resolved_ip = await cls._resolve_and_verify_ip(host, port, pinned_ip)
        canonical_url = cls._build_canonical_url(scheme, host, port, parsed)

        if not allow_redirects:
            dns_pinned_rule = f"--host-resolver-rules=MAP {host} {resolved_ip}"
            return ValidatedUrl(
                original_url=raw_url,
                canonical_url=canonical_url,
                scheme=scheme,  # type: ignore[arg-type]
                host=host,
                port=port,
                resolved_ip=resolved_ip,
                is_https=(scheme == "https"),
                redirect_hops=0,
                redirect_chain=[],
                dns_pinned_rule=dns_pinned_rule,
            )

        visited = {target_url, canonical_url}
        redirect_chain: list[str] = []
        final_state = await cls._run_redirect_probe(
            client=client,
            current_url=canonical_url,
            current_host=host,
            current_ip=resolved_ip,
            current_scheme=scheme,
            current_port=port,
            visited=visited,
            redirect_chain=redirect_chain,
            redirect_hops=0,
        )

        (
            final_url,
            final_host,
            final_ip,
            final_scheme,
            final_port,
            final_hops,
            final_chain,
        ) = final_state

        dns_pinned_rule = f"--host-resolver-rules=MAP {final_host} {final_ip}"
        return ValidatedUrl(
            original_url=raw_url,
            canonical_url=final_url,
            scheme=final_scheme,  # type: ignore[arg-type]
            host=final_host,
            port=final_port,
            resolved_ip=final_ip,
            is_https=(final_scheme == "https"),
            redirect_hops=final_hops,
            redirect_chain=final_chain,
            dns_pinned_rule=dns_pinned_rule,
        )

    # [OMA-W004-T001] Single HTTP request probe with HEAD/GET fallback
    @classmethod
    async def _fetch_redirect_response(
        cls, client: httpx.AsyncClient, current_url: str
    ) -> httpx.Response | None:
        """Attempts HEAD request followed by GET fallback if method 405 Method Not Allowed."""
        try:
            response = await client.head(current_url)
            if response.status_code == 405:
                response = await client.get(current_url)
            return response
        except httpx.HTTPError:
            return None

    # [OMA-W004-T001] Redirect and rate limiting status evaluator
    @classmethod
    def _handle_redirect_status(cls, response: httpx.Response) -> bool:
        """Inspects status codes for rate-limiting or non-redirect termination. Returns True to stop traversal."""
        if response.status_code in (429, 503):
            retry_after_hdr = response.headers.get("retry-after")
            if retry_after_hdr:
                retry_seconds = cls._parse_retry_after(retry_after_hdr)
                if retry_seconds is not None and retry_seconds > 300:
                    raise RateLimitedCooldownError(
                        f"Rate limited with Retry-After {retry_seconds}s exceeding 300s threshold",
                        error_code=ERR_RATE_LIMITED_COOLDOWN,
                        retry_after=retry_seconds,
                        details={
                            "retry_after": retry_seconds,
                            "status_code": response.status_code,
                        },
                    )
            return True

        return response.status_code not in (301, 302, 303, 307, 308)

    # [OMA-W004-T001] Single redirect hop follower with safe-web-access
    @classmethod
    def _follow_single_redirect_hop(
        cls,
        current_url: str,
        location: str,
        visited: set[str],
        redirect_hops: int,
    ) -> tuple[str, str, int, str, int]:
        """Validates next hop location for circular loops, traversal, scheme, and port bounds."""
        redirect_hops += 1
        if redirect_hops > 5:
            raise MaxRedirectsExceededError(
                "Maximum redirect hops (5) exceeded",
                error_code=ERR_MAX_REDIRECTS_EXCEEDED,
            )

        next_url = urllib.parse.urljoin(current_url, location).strip()
        if next_url in visited:
            raise CircularRedirectError(
                f"Circular redirect detected: {next_url}",
                error_code=ERR_CIRCULAR_REDIRECT,
            )
        visited.add(next_url)

        cls._check_path_traversal(next_url)

        try:
            val = validate_and_normalize_url(next_url)
        except UnsupportedSchemeError as err:
            raise InvalidUrlSchemeError(
                f"Invalid redirect scheme: {err}",
                error_code=ERR_INVALID_SCHEME,
            ) from err
        except InvalidUrlError as err:
            raise InvalidUrlSyntaxError(
                f"Redirect URL missing hostname: {err}",
                error_code=ERR_INVALID_URL_SYNTAX,
            ) from err

        next_scheme = val.scheme
        next_host = val.hostname
        if not next_host:
            raise InvalidUrlSyntaxError(
                "Redirect URL missing hostname",
                error_code=ERR_INVALID_URL_SYNTAX,
            )

        cls._check_homograph(next_host)
        cls._check_loopback_and_ip_ssrf(next_host)

        next_port = val.port or (443 if next_scheme == "https" else 80)
        if next_port not in (80, 443):
            raise InvalidUrlPortError(
                f"Invalid redirect port: {next_port}",
                error_code=ERR_INVALID_PORT,
            )

        return next_url, next_host, next_port, next_scheme, redirect_hops

    # [OMA-W004-T001] Safe redirect traversal loop
    @classmethod
    async def _probe_redirects(
        cls,
        client: httpx.AsyncClient,
        current_url: str,
        current_host: str,
        current_ip: str,
        current_scheme: str,
        current_port: int,
        visited: set[str],
        redirect_chain: list[str],
        redirect_hops: int,
    ) -> tuple[str, str, str, str, int, int, list[str]]:
        """Safely traverses HTTP redirect hops with per-hop SSRF validation."""
        while True:
            response = await cls._fetch_redirect_response(client, current_url)
            if response is None or cls._handle_redirect_status(response):
                break

            location = response.headers.get("location")
            if not location:
                break

            (
                next_url,
                next_host,
                next_port,
                next_scheme,
                redirect_hops,
            ) = cls._follow_single_redirect_hop(
                current_url=current_url,
                location=location,
                visited=visited,
                redirect_hops=redirect_hops,
            )
            redirect_chain.append(next_url)
            next_ip = await cls._resolve_host(next_host, next_port)

            current_url = next_url
            current_host = next_host
            current_ip = next_ip
            current_scheme = next_scheme
            current_port = next_port

        return (
            current_url,
            current_host,
            current_ip,
            current_scheme,
            current_port,
            redirect_hops,
            redirect_chain,
        )

    # [OMA-W004-T001] Path traversal detector
    @classmethod
    def _check_path_traversal(cls, url: str) -> None:
        """Detects path traversal sequences in raw or encoded URL strings."""
        lower_raw = url.lower()
        unquoted = urllib.parse.unquote(url).lower()

        traversal_patterns = (
            "../",
            "..\\",
            "%2e%2e",
            "..%2f",
            "%2e%2e%2f",
            "..%5c",
            "%2e%2e%5c",
        )
        if any(tok in lower_raw for tok in traversal_patterns):
            raise PathTraversalError(
                "Path traversal token detected in URL",
                error_code=ERR_PATH_TRAVERSAL,
            )

        if "../" in unquoted or "..\\" in unquoted:
            raise PathTraversalError(
                "Path traversal token detected in URL",
                error_code=ERR_PATH_TRAVERSAL,
            )

    # [OMA-W004-T001] IDN homograph detector
    @classmethod
    def _check_homograph(cls, host: str) -> None:
        """Detects IDN homograph attacks and deceptive mixed-script hostnames."""
        try:
            punycode = host.encode("idna").decode("ascii")
        except Exception as e:
            raise InvalidUrlSyntaxError(
                f"Invalid host encoding: {e}",
                error_code=ERR_INVALID_URL_SYNTAX,
            ) from e

        has_latin = False
        has_cyrillic = False
        has_greek = False

        for ch in host:
            if ch in ".-_0123456789":
                continue
            try:
                name = unicodedata.name(ch)
                if "LATIN" in name:
                    has_latin = True
                elif "CYRILLIC" in name:
                    has_cyrillic = True
                elif "GREEK" in name:
                    has_greek = True
            except ValueError:
                continue

        if (
            (has_latin and has_cyrillic)
            or (has_latin and has_greek)
            or (punycode.startswith("xn--") and has_cyrillic)
        ):
            raise HomographAttackError(
                f"IDN homograph attack detected in domain: {host}",
                error_code=ERR_HOMOGRAPH_ATTACK,
            )

    # [OMA-W006-T005] Public helper to verify if an IP address is blocked against SSRF
    @classmethod
    def is_ip_blocked(cls, ip_str: str) -> bool:
        """Returns True if the IP address belongs to private, loopback, or cloud metadata CIDRs."""
        return cls._is_blocked_ip(ip_str)

    # [OMA-W004-T001] Blocked IP detector using safe-web-access
    @classmethod
    def _is_blocked_ip(cls, ip_str: str) -> bool:
        """Returns True if the IP address belongs to private, loopback, or cloud metadata CIDRs."""
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return True

        return not _is_public_address(ip)

    # [OMA-W004-T001] DNS resolution and Anti-SSRF using safe-web-access
    @classmethod
    async def _resolve_host(cls, host: str, port: int) -> str:
        """Asynchronously resolves a hostname to an IP and verifies Anti-SSRF constraints via safe-web-access."""
        lower_host = host.lower()
        if (
            lower_host in ("localhost", "127.0.0.1", "::1")
            or lower_host.endswith(".localhost")
            or lower_host.endswith(".local")
        ):
            raise SSRFAttemptBlockedError(
                f"Blocked SSRF attempt to loopback host: {host}",
                error_code=ERR_SSRF_ATTEMPT_BLOCKED,
            )

        # Check if host is already an IP address
        try:
            ip_obj = ipaddress.ip_address(host)
            if not _is_public_address(ip_obj):
                raise SSRFAttemptBlockedError(
                    f"Blocked SSRF attempt to non-public destination: {host}",
                    error_code=ERR_SSRF_ATTEMPT_BLOCKED,
                )
            return str(ip_obj)
        except ValueError:
            pass

        # Perform asynchronous DNS resolution
        loop = asyncio.get_running_loop()
        try:
            addr_info = await loop.getaddrinfo(
                host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
            )
        except socket.gaierror as e:
            raise InvalidUrlSyntaxError(
                f"Failed to resolve host '{host}': {e}",
                error_code=ERR_INVALID_URL_SYNTAX,
            ) from e

        if not addr_info:
            raise InvalidUrlSyntaxError(
                f"Failed to resolve host '{host}': no addresses returned",
                error_code=ERR_INVALID_URL_SYNTAX,
            )

        verified_ip: str | None = None
        for item in addr_info:
            ip_str = item[4][0]
            if cls._is_blocked_ip(ip_str):
                raise SSRFAttemptBlockedError(
                    f"Blocked SSRF attempt to non-public destination: {ip_str}",
                    error_code=ERR_SSRF_ATTEMPT_BLOCKED,
                )
            if verified_ip is None:
                verified_ip = ip_str

        if not verified_ip:
            raise InvalidUrlSyntaxError(
                f"Failed to resolve host '{host}' to a valid IP",
                error_code=ERR_INVALID_URL_SYNTAX,
            )

        return verified_ip

    # [OMA-W004-T001] Retry-After parser
    @classmethod
    def _parse_retry_after(cls, value: str) -> float | None:
        """Parses Retry-After header as integer seconds or HTTP-date."""
        val = value.strip()
        try:
            return float(val)
        except ValueError:
            pass

        try:
            parsed_dt = email.utils.parsedate_to_datetime(val)
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=UTC)
            delta = (parsed_dt - datetime.now(UTC)).total_seconds()
            return max(0.0, delta)
        except Exception:
            return None


# [OMA-W004-T001] Backward-compatible alias
LinkValidator = LinkValidatorService
