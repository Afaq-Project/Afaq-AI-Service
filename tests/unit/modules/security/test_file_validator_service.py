# [OMA-W001-T006] Unit tests for FileValidatorService

import hashlib
import io
import zipfile

import pytest
from PIL import Image

from src.modules.security.exceptions import (
    ERR_FILE_SIZE_EXCEEDED,
    ERR_MALICIOUS_FILE_TYPE,
    FileSizeExceededError,
    MaliciousFileTypeError,
)
from src.modules.security.models import FileValidationResult
from src.modules.security.services.file_validator_service import (
    FileValidator,
    FileValidatorService,
)


def _make_minimal_pdf(version: str = "1.4") -> bytes:
    """Constructs a structurally valid minimal PDF with xref table and /Root catalog."""
    header = f"%PDF-{version}\n".encode("ascii")
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
    return header + obj1 + obj2 + xref + trailer


def _make_minimal_image(fmt: str) -> bytes:
    """Constructs a structurally valid minimal 2x2 image using PIL."""
    buf = io.BytesIO()
    img = Image.new("RGB", (2, 2), color=(255, 0, 0))
    img.save(buf, format=fmt)
    return buf.getvalue()


# [OMA-W001-T006] UC-03: Official Scholarship PDF Attachment Inspection
def test_valid_pdf_magic_bytes_and_s3_key():
    """UC-03: Inspects valid PDF stream, checks %PDF- magic bytes, computes SHA256, and generates S3 key."""
    pdf_content = _make_minimal_pdf("1.7")
    stream = io.BytesIO(pdf_content)

    result = FileValidatorService.validate_stream(
        stream=stream,
        filename="guidelines.pdf",
        source_id="src_99",
        source_url="https://scholarships.example.edu/guidelines.pdf",
    )

    expected_sha256 = hashlib.sha256(pdf_content).hexdigest()
    assert isinstance(result, FileValidationResult)
    assert result.is_valid is True
    assert result.mime_type == "application/pdf"
    assert result.file_extension == "pdf"
    assert result.file_size_bytes == len(pdf_content)
    assert result.sha256_checksum == expected_sha256
    assert (
        result.suggested_s3_key
        == f"documents/src_99/{expected_sha256[:16]}_guidelines.pdf"
    )
    assert result.magic_bytes_hex.startswith("255044462D")
    assert result.error_code is None
    assert result.rejection_reason is None


# [OMA-W001-T006] UC-06: S3 Naming with Content-Disposition Fallback (FR-014)
def test_content_disposition_s3_naming_fallback():
    """UC-06: Extracts and sanitizes filename from Content-Disposition header when URL path filename is missing."""
    pdf_content = _make_minimal_pdf("1.4")
    stream = io.BytesIO(pdf_content)
    header = 'attachment; filename="application_guide_2026.pdf"'

    result = FileValidatorService.validate_stream(
        stream=stream,
        filename=None,
        content_disposition=header,
        source_id="portal_42",
    )

    sha16 = hashlib.sha256(pdf_content).hexdigest()[:16]
    assert (
        result.suggested_s3_key
        == f"documents/portal_42/{sha16}_application_guide_2026.pdf"
    )

    # RFC 5987 / 6266 filename*=UTF-8'' encoded format
    stream_rfc = io.BytesIO(pdf_content)
    header_rfc = "attachment; filename*=UTF-8''official%20scholarship.pdf"
    result_rfc = FileValidatorService.validate_stream(
        stream=stream_rfc,
        filename=None,
        content_disposition=header_rfc,
        source_id="portal_42",
    )
    assert (
        result_rfc.suggested_s3_key
        == f"documents/portal_42/{sha16}_official_scholarship.pdf"
    )

    # Traversal in Content-Disposition is sanitized
    stream_trav = io.BytesIO(pdf_content)
    header_trav = 'attachment; filename="../../malicious_escape.pdf"'
    result_trav = FileValidatorService.validate_stream(
        stream=stream_trav,
        filename=None,
        content_disposition=header_trav,
        source_id="portal_42",
    )
    assert (
        result_trav.suggested_s3_key
        == f"documents/portal_42/{sha16}_malicious_escape.pdf"
    )

    # Neither filename nor Content-Disposition provided: hash fallback
    stream_fallback = io.BytesIO(pdf_content)
    result_fallback = FileValidatorService.validate_stream(
        stream=stream_fallback,
        filename=None,
        content_disposition=None,
        source_id="portal_42",
    )
    assert result_fallback.suggested_s3_key == f"documents/portal_42/{sha16}.pdf"


# [OMA-W001-T006] Test stream size ceiling (25 MB limit)
def test_file_size_exceeded_25mb():
    """Protects FR-010 invariants: file streams exceeding 25 MB ceiling are aborted."""

    class OversizedStream:
        def __init__(self, size: int):
            self.remaining = size

        def read(self, chunk_size: int = 64 * 1024) -> bytes:
            if self.remaining <= 0:
                return b""
            chunk_len = min(chunk_size, self.remaining)
            self.remaining -= chunk_len
            return b"%PDF-" + b"0" * (chunk_len - 5)

        def seek(self, pos: int):
            pass

    # Stream exceeds 25 MB limit by 1024 bytes
    oversized = OversizedStream(25 * 1024 * 1024 + 1024)
    with pytest.raises(FileSizeExceededError) as exc_info:
        FileValidatorService.validate_stream(oversized, filename="huge.pdf")  # type: ignore[arg-type]

    assert exc_info.value.error_code == ERR_FILE_SIZE_EXCEEDED
    assert "exceeds 25 MB stream ceiling" in str(exc_info.value)


# [OMA-W001-T006] Test empty stream rejection
def test_empty_file_stream_rejected():
    """Protects against empty payloads: zero-byte stream raises MaliciousFileTypeError."""
    empty_stream = io.BytesIO(b"")

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(empty_stream, filename="empty.pdf")

    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File stream is empty" in str(exc_info.value)


# [OMA-W001-T006] Test allowed image types: JPEG, PNG, WEBP, GIF
def test_allowed_image_types():
    """Protects image attachment magic bytes: JPEG, PNG, WEBP, and GIF signatures."""
    # JPEG magic bytes \xFF\xD8\xFF
    jpeg_bytes = _make_minimal_image("JPEG")
    jpeg_res = FileValidatorService.validate_stream(
        io.BytesIO(jpeg_bytes), filename="photo.jpg"
    )
    assert jpeg_res.mime_type == "image/jpeg"
    assert jpeg_res.file_extension == "jpg"

    # PNG magic bytes \x89PNG\r\n\x1a\n
    png_bytes = _make_minimal_image("PNG")
    png_res = FileValidatorService.validate_stream(
        io.BytesIO(png_bytes), filename="badge.png"
    )
    assert png_res.mime_type == "image/png"
    assert png_res.file_extension == "png"

    # WEBP magic bytes RIFF....WEBP
    webp_bytes = _make_minimal_image("WEBP")
    webp_res = FileValidatorService.validate_stream(
        io.BytesIO(webp_bytes), filename="banner.webp"
    )
    assert webp_res.mime_type == "image/webp"
    assert webp_res.file_extension == "webp"

    # GIF magic bytes GIF87a/GIF89a
    gif_bytes = _make_minimal_image("GIF")
    gif_res = FileValidatorService.validate_stream(
        io.BytesIO(gif_bytes), filename="graphic.gif"
    )
    assert gif_res.mime_type == "image/gif"
    assert gif_res.file_extension == "gif"


# [OMA-W001-T006] Test allowed Office documents (DOCX, XLSX) and standard ZIP archives
def test_allowed_office_and_zip_archives():
    """Protects Office container inspection: distinguishes DOCX, XLSX, and standard ZIP."""
    # 1. DOCX: contains word/document.xml and [Content_Types].xml
    docx_buf = io.BytesIO()
    with zipfile.ZipFile(docx_buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        zf.writestr(
            "word/document.xml", "<w:document><w:body><w:p/></w:body></w:document>"
        )
    docx_buf.seek(0)
    docx_res = FileValidatorService.validate_stream(docx_buf, filename="essay.docx")
    assert docx_res.file_extension == "docx"
    assert "wordprocessingml" in docx_res.mime_type

    # 2. XLSX: contains xl/workbook.xml and [Content_Types].xml
    xlsx_buf = io.BytesIO()
    with zipfile.ZipFile(xlsx_buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        zf.writestr("xl/workbook.xml", "<workbook><sheets/></workbook>")
    xlsx_buf.seek(0)
    xlsx_res = FileValidatorService.validate_stream(xlsx_buf, filename="budget.xlsx")
    assert xlsx_res.file_extension == "xlsx"
    assert "spreadsheetml" in xlsx_res.mime_type

    # 3. Standard ZIP: contains generic file
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("notes.txt", "Scholarship notes and references.")
    zip_buf.seek(0)
    zip_res = FileValidatorService.validate_stream(zip_buf, filename="bundle.zip")
    assert zip_res.file_extension == "zip"
    assert zip_res.mime_type == "application/zip"

    # 4. Corrupted ZIP archive starting with PK\x03\x04 but corrupted bytes
    corrupted_buf = io.BytesIO(
        b"PK\x03\x04corrupted_garbage_bytes_that_are_not_valid_zip"
    )
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(corrupted_buf, filename="corrupted.zip")
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Corrupted or invalid ZIP archive" in str(exc_info.value)


# [OMA-W001-T006] Test unrecognized file type rejection
def test_unrecognized_file_type():
    """Protects file type allowlist: unrecognized headers are rejected."""
    random_bytes = b"UNKNOWN_BINARY_DATA\x01\x02\x03\x04" * 10
    stream = io.BytesIO(random_bytes)
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(stream, filename="data.bin")

    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File magic bytes do not match any permitted attachment type" in str(
        exc_info.value
    )


# [OMA-W001-T006] Test raise_on_error=False flag
def test_raise_on_error_false():
    """Protects non-throwing inspection mode: returns FileValidationResult with is_valid=False."""
    empty_stream = io.BytesIO(b"")
    result = FileValidatorService.validate_stream(
        empty_stream,
        filename="empty.pdf",
        raise_on_error=False,
    )

    assert isinstance(result, FileValidationResult)
    assert result.is_valid is False
    assert result.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File stream is empty" in str(result.rejection_reason)


# [OMA-W001-T006] Test non-seekable stream handling
def test_non_seekable_stream():
    """Protects stream compatibility: streams without seek support validate without error."""

    class NonSeekableStream:
        def __init__(self, data: bytes):
            self.stream = io.BytesIO(data)

        def read(self, size: int = -1) -> bytes:
            return self.stream.read(size)

    pdf_data = _make_minimal_pdf("1.4")
    non_seek = NonSeekableStream(pdf_data)
    result = FileValidatorService.validate_stream(non_seek, filename="stream.pdf")  # type: ignore[arg-type]
    assert result.is_valid is True
    assert result.mime_type == "application/pdf"


# [OMA-W001-T006] Test stream seek raising OSError or UnsupportedOperation
def test_stream_seek_raises_unsupported_operation():
    """Protects seek error handling when seek(0) raises OSError or UnsupportedOperation."""

    class BrokenSeekStream:
        def __init__(self, data: bytes):
            self.stream = io.BytesIO(data)

        def read(self, size: int = -1) -> bytes:
            return self.stream.read(size)

        def seek(self, pos: int):
            raise io.UnsupportedOperation("Seek not allowed")

    pdf_data = _make_minimal_pdf("1.4")
    broken_stream = BrokenSeekStream(pdf_data)
    result = FileValidatorService.validate_stream(
        broken_stream, filename="seek_err.pdf"
    )  # type: ignore[arg-type]
    assert result.is_valid is True
    assert result.mime_type == "application/pdf"


# [OMA-W001-T006] Test check_zip_bomb with corrupted zip bytes
def test_check_zip_bomb_bad_zip_file():
    """Protects _check_zip_bomb error handling when zipfile raises BadZipFile."""
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService._check_zip_bomb(b"PK\x03\x04invalid_bytes")
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Invalid ZIP container" in str(exc_info.value)


# [OMA-W001-T006] Test S3 key derivation with unquoted Content-Disposition and mismatched extension
def test_s3_key_unquoted_and_mismatched_ext():
    """Protects S3 key filename extraction with unquoted filename and alternative extension stripping."""
    pdf_content = _make_minimal_pdf("1.4")

    # Unquoted filename: filename=sample.pdf
    res1 = FileValidatorService.validate_stream(
        io.BytesIO(pdf_content),
        content_disposition="attachment; filename=plain_sample.pdf",
    )
    assert "plain_sample.pdf" in res1.suggested_s3_key

    # Mismatched extension in filename argument: filename="document.doc" detected as pdf
    res2 = FileValidatorService.validate_stream(
        io.BytesIO(pdf_content),
        filename="document.doc",
    )
    assert "document.pdf" in res2.suggested_s3_key


# [OMA-W001-T006] Test backward compatibility alias
def test_file_validator_alias():
    """Protects public API backward-compatibility alias FileValidator."""
    assert FileValidator is FileValidatorService


# ==============================================================================
# [OMA-W002-T002] Dedicated unit tests for stream offset & rewind enforcement
# ==============================================================================


# [OMA-W002-T002] Test 1: Partially consumed unseekable stream raises MaliciousFileTypeError
@pytest.mark.parametrize(
    "seek_exc",
    [OSError("Stream seek failed"), io.UnsupportedOperation("Stream is not seekable")],
)
def test_partially_consumed_unseekable_stream_raises(seek_exc: Exception):
    """Protects stream pointer integrity: partially consumed unseekable stream raises MaliciousFileTypeError."""

    class PartiallyConsumedUnseekableStream:
        def __init__(self, data: bytes, pos: int = 16):
            self._data = data
            self._pos = pos

        def read(self, size: int = -1) -> bytes:
            return self._data[self._pos :]

        def tell(self) -> int:
            return self._pos

        def seek(self, pos: int) -> int:
            raise seek_exc

    stream = PartiallyConsumedUnseekableStream(_make_minimal_pdf("1.4"), pos=10)
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(stream, filename="test.pdf")  # type: ignore[arg-type]

    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "partially consumed" in str(exc_info.value)


# [OMA-W002-T002] Test 2: Partially consumed stream lacking seek method raises MaliciousFileTypeError
def test_partially_consumed_stream_without_seek_method_raises():
    """Protects stream pointer integrity: partially consumed stream lacking seek method raises MaliciousFileTypeError."""

    class PartiallyConsumedNoSeekStream:
        def __init__(self, data: bytes, pos: int = 8):
            self._data = data
            self._pos = pos

        def read(self, size: int = -1) -> bytes:
            return self._data[self._pos :]

        def tell(self) -> int:
            return self._pos

    stream = PartiallyConsumedNoSeekStream(_make_minimal_pdf("1.4"), pos=8)
    assert not hasattr(stream, "seek")
    assert stream.tell() > 0

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(stream, filename="test.pdf")  # type: ignore[arg-type]

    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "partially consumed" in str(exc_info.value)


# [OMA-W002-T002] Test 3: Unseekable stream starting cleanly at offset 0 succeeds
@pytest.mark.parametrize("tell_raises", [False, True])
def test_unseekable_stream_starting_at_offset_zero_succeeds(tell_raises: bool):
    """Protects operational compatibility: unseekable stream starting at offset 0 is validated cleanly."""
    pdf_content = _make_minimal_pdf("1.5")

    class CleanUnseekableStream:
        def __init__(self, data: bytes):
            self._bio = io.BytesIO(data)

        def read(self, size: int = -1) -> bytes:
            return self._bio.read(size)

        def tell(self) -> int:
            if tell_raises:
                raise OSError("ESPIPE: Illegal seek on tell")
            return self._bio.tell()

        def seek(self, pos: int) -> int:
            raise OSError("ESPIPE: Illegal seek on seek")

    stream = CleanUnseekableStream(pdf_content)
    result = FileValidatorService.validate_stream(stream, filename="clean.pdf")  # type: ignore[arg-type]

    assert isinstance(result, FileValidationResult)
    assert result.is_valid is True
    assert result.mime_type == "application/pdf"
    assert result.file_extension == "pdf"
    assert result.file_size_bytes == len(pdf_content)
    assert result.sha256_checksum == hashlib.sha256(pdf_content).hexdigest()


# [OMA-W002-T002] Test 4: Partially consumed seekable stream rewinds and succeeds
def test_partially_consumed_seekable_stream_rewinds_properly():
    """Protects stream pointer integrity: partially consumed seekable stream rewinds to 0 and validates."""
    pdf_content = _make_minimal_pdf("1.6")
    stream = io.BytesIO(pdf_content)

    # Simulate caller partially consuming stream before passing to validator
    partial_bytes = stream.read(20)
    assert len(partial_bytes) == 20
    assert stream.tell() == 20

    # Execute validation on the partially consumed seekable stream
    result = FileValidatorService.validate_stream(
        stream=stream,
        filename="grant_guidelines.pdf",
        source_id="grant_univ",
    )

    expected_sha256 = hashlib.sha256(pdf_content).hexdigest()
    assert isinstance(result, FileValidationResult)
    assert result.is_valid is True
    assert result.mime_type == "application/pdf"
    assert result.file_extension == "pdf"
    assert result.file_size_bytes == len(pdf_content)
    assert result.sha256_checksum == expected_sha256
    assert (
        result.suggested_s3_key
        == f"documents/grant_univ/{expected_sha256[:16]}_grant_guidelines.pdf"
    )

    # Invariant: stream must be rewound to position 0 after validation completes
    assert stream.tell() == 0
    # Reading full stream produces original content
    assert stream.read() == pdf_content


# ==============================================================================
# [OMA-W003-T002] File footer and structural integrity unit & threat tests
# ==============================================================================


# [OMA-W003-T002] File footer & trailing overlay injection rejection: JPEG
def test_jpeg_trailing_overlay_payload_raises():
    """Protects against JPEG trailing overlay payloads (e.g. PHP webshell or shellcode after EOI)."""
    valid_jpeg = _make_minimal_image("JPEG")

    # Case A: PHP webshell injected after JPEG EOI marker (\xFF\xD9)
    php_webshell = b"<?php system($_GET['cmd']); ?>"
    tainted_jpeg_php = valid_jpeg + php_webshell
    with pytest.raises(MaliciousFileTypeError) as exc_php:
        FileValidatorService.validate_stream(
            io.BytesIO(tainted_jpeg_php), filename="profile.jpg"
        )
    assert exc_php.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_php.value
    )

    # Case B: Binary shellcode injected after JPEG EOI marker
    shellcode = b"\x90\x90\x90\x31\xc0\x50\x68\x2f\x2f\x73\x68"
    tainted_jpeg_sh = valid_jpeg + shellcode
    with pytest.raises(MaliciousFileTypeError) as exc_sh:
        FileValidatorService.validate_stream(
            io.BytesIO(tainted_jpeg_sh), filename="avatar.jpeg"
        )
    assert exc_sh.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(exc_sh.value)


# [OMA-W003-T002] File footer & trailing overlay injection rejection: PNG
def test_png_trailing_overlay_injection_raises():
    """Protects against PNG trailing overlay injection after IEND chunk."""
    valid_png = _make_minimal_image("PNG")
    tainted_png = valid_png + b"\xde\xad\xbe\xef\x00\x01\x02\x03malicious_overlay"

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(tainted_png), filename="badge.png"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] File footer & trailing overlay injection rejection: GIF
def test_gif_trailing_overlay_injection_raises():
    """Protects against GIF trailing overlay injection after ';' trailer byte."""
    valid_gif = _make_minimal_image("GIF")
    tainted_gif = valid_gif + b"TRAILING_INJECTED_OVERLAY_BYTES"

    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(tainted_gif), filename="anim.gif"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] File footer & trailing overlay injection rejection: PDF
def test_pdf_trailing_overlay_injection_raises():
    """Protects against PDF trailing foreign script or binary overlay after %%EOF."""
    valid_pdf = _make_minimal_pdf("1.4")

    # Case A: Appended foreign script after %%EOF
    tainted_pdf_script = valid_pdf + b"\n<script>alert('pwned')</script>\n"
    with pytest.raises(MaliciousFileTypeError) as exc_script:
        FileValidatorService.validate_stream(
            io.BytesIO(tainted_pdf_script), filename="document.pdf"
        )
    assert exc_script.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_script.value
    )

    # Case B: Appended executable binary overlay after %%EOF
    tainted_pdf_bin = valid_pdf + b"\n\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00"
    with pytest.raises(MaliciousFileTypeError) as exc_bin:
        FileValidatorService.validate_stream(
            io.BytesIO(tainted_pdf_bin), filename="guide.pdf"
        )
    assert exc_bin.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_bin.value
    )


# [OMA-W003-T002] File footer & trailing overlay injection rejection: ZIP & Office
def test_zip_office_trailing_overlay_injection_raises():
    """Protects against ZIP and Office archives with trailing data injected after EOCD record."""
    # Case A: Standard ZIP with trailing overlay data
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("test.txt", "safe zip content")
    tainted_zip = zip_buf.getvalue() + b"MALICIOUS_EOCD_OVERLAY_BYTES"

    with pytest.raises(MaliciousFileTypeError) as exc_zip:
        FileValidatorService.validate_stream(
            io.BytesIO(tainted_zip), filename="archive.zip"
        )
    assert exc_zip.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_zip.value
    )

    # Case B: DOCX with trailing injected data after EOCD record
    docx_buf = io.BytesIO()
    with zipfile.ZipFile(docx_buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        zf.writestr("word/document.xml", "<w:document><w:body/></w:document>")
    tainted_docx = docx_buf.getvalue() + b"INJECTED_DOCX_PAYLOAD"

    with pytest.raises(MaliciousFileTypeError) as exc_docx:
        FileValidatorService.validate_stream(
            io.BytesIO(tainted_docx), filename="application.docx"
        )
    assert exc_docx.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_docx.value
    )


# [OMA-W003-T002] Deep structural parsing: PNG chunk corruption or bad CRC
def test_png_corrupted_chunk_or_bad_crc_raises():
    """Protects against corrupted or truncated PNG chunk header or bad CRC."""
    corrupt_png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\xff\xff\xff\xff"  # Bad CRC
        b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
    )
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(corrupt_png), filename="corrupt.png"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Corrupt or malformed image structure" in str(exc_info.value)


# [OMA-W003-T002] Deep structural parsing: Malformed JPEG missing image markers
def test_jpeg_corrupted_missing_markers_raises():
    """Protects against malformed or corrupted JPEG missing required image markers."""
    malformed_jpeg = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x00\x00\x00"
        + b"\x00" * 30
        + b"\xff\xd9"
    )
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(malformed_jpeg), filename="corrupt.jpg"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Corrupt or malformed image structure" in str(exc_info.value)


# [OMA-W003-T002] Deep structural parsing: Corrupted PDF cross-reference / catalog
def test_pdf_corrupted_cross_reference_or_catalog_raises():
    """Protects against corrupted PDF cross-reference table or missing /Root catalog object."""
    # Case A: startxref pointing out of bounds
    bad_xref_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"startxref\n9999\n%%EOF"
    )
    with pytest.raises(MaliciousFileTypeError) as exc_xref:
        FileValidatorService.validate_stream(
            io.BytesIO(bad_xref_pdf), filename="bad_xref.pdf"
        )
    assert exc_xref.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Corrupt or malformed PDF structure" in str(exc_xref.value)

    # Case B: Trailer missing /Root catalog reference
    no_root_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        b"xref\n0 1\n0000000000 65535 f \n"
        b"trailer\n<< /Size 1 >>\n"
        b"startxref\n41\n%%EOF"
    )
    with pytest.raises(MaliciousFileTypeError) as exc_root:
        FileValidatorService.validate_stream(
            io.BytesIO(no_root_pdf), filename="no_root.pdf"
        )
    assert exc_root.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Corrupt or malformed PDF structure" in str(exc_root.value)

    # Case C: /Root references an object that is not a Catalog
    not_catalog_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /NotCatalog /Info (malformed) >>\nendobj\n"
        b"xref\n0 2\n0000000000 65535 f \n0000000009 00000 n \n"
        b"trailer\n<< /Size 2 /Root 1 0 R >>\n"
        b"startxref\n59\n%%EOF"
    )
    with pytest.raises(MaliciousFileTypeError) as exc_cat:
        FileValidatorService.validate_stream(
            io.BytesIO(not_catalog_pdf), filename="not_catalog.pdf"
        )
    assert exc_cat.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Corrupt or malformed PDF structure" in str(exc_cat.value)


# [OMA-W003-T002] Deep structural parsing: Corrupted ZIP archive bad CRC or missing [Content_Types].xml
def test_zip_corrupted_archive_bad_crc_or_missing_content_types_raises():
    """Protects against corrupted ZIP CRC or DOCX archive missing [Content_Types].xml."""
    # Case A: ZIP archive with stored data tampered causing CRC failure in testzip()
    valid_zip_buf = io.BytesIO()
    with zipfile.ZipFile(valid_zip_buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("critical.txt", b"ABCDEFGHIJ")
    tampered_bytes = bytearray(valid_zip_buf.getvalue())
    tampered_bytes[42] = ord("Z")  # Corrupt stored payload byte causing CRC mismatch

    with pytest.raises(MaliciousFileTypeError) as exc_crc:
        FileValidatorService.validate_stream(
            io.BytesIO(tampered_bytes), filename="tampered.zip"
        )
    assert exc_crc.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Corrupt or malformed archive/office document structure" in str(
        exc_crc.value
    )

    # Case B: DOCX missing required [Content_Types].xml
    docx_no_ct = io.BytesIO()
    with zipfile.ZipFile(docx_no_ct, "w") as zf:
        zf.writestr("word/document.xml", "<w:document><w:body/></w:document>")
    docx_no_ct.seek(0)

    with pytest.raises(MaliciousFileTypeError) as exc_no_ct:
        FileValidatorService.validate_stream(
            docx_no_ct, filename="no_content_types.docx"
        )
    assert exc_no_ct.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Corrupt or malformed archive/office document structure" in str(
        exc_no_ct.value
    )

    # Case C: DOCX with malformed XML in [Content_Types].xml
    docx_bad_xml = io.BytesIO()
    with zipfile.ZipFile(docx_bad_xml, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types><unclosed_tag>")
        zf.writestr("word/document.xml", "<w:document><w:body/></w:body></w:document>")
    docx_bad_xml.seek(0)

    with pytest.raises(MaliciousFileTypeError) as exc_bad_xml:
        FileValidatorService.validate_stream(docx_bad_xml, filename="bad_xml.docx")
    assert exc_bad_xml.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Corrupt or malformed archive/office document structure" in str(
        exc_bad_xml.value
    )


# [OMA-W003-T002] Fake-terminator bypass regression: JPEG with embedded webshell and fake EOI
def test_jpeg_fake_terminator_bypass_rejected():
    """Protects against fake-terminator bypass where PHP webshell is followed by fake JPEG EOI (\xff\xd9)."""
    # Arrange: Valid JPEG image followed by PHP webshell payload and fake EOI marker
    valid_jpeg = _make_minimal_image("JPEG")
    php_payload = b"<?php system($_GET['cmd']); ?>"
    fake_eoi = b"\xff\xd9"
    crafted_payload = valid_jpeg + php_payload + fake_eoi

    # Act & Assert
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(crafted_payload), filename="fake_terminator.jpg"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Fake-terminator bypass regression: PNG with embedded webshell and duplicate fake IEND
def test_png_fake_terminator_bypass_rejected():
    """Protects against fake-terminator bypass where PHP webshell is followed by duplicate fake PNG IEND chunk."""
    # Arrange: Valid PNG image followed by PHP webshell and fake 12-byte IEND chunk
    valid_png = _make_minimal_image("PNG")
    php_payload = b"<?php phpinfo(); ?>"
    fake_iend = b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
    crafted_payload = valid_png + php_payload + fake_iend

    # Act & Assert
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(crafted_payload), filename="fake_terminator.png"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Fake-terminator bypass regression: GIF with embedded webshell and fake trailer byte
def test_gif_fake_terminator_bypass_rejected():
    """Protects against fake-terminator bypass where PHP webshell is followed by fake GIF trailer byte (b';')."""
    # Arrange: Valid GIF image followed by PHP webshell and fake trailer byte ';'
    valid_gif = _make_minimal_image("GIF")
    php_payload = b"<?php passthru($_POST['c']); ?>"
    fake_trailer = b";"
    crafted_payload = valid_gif + php_payload + fake_trailer

    # Act & Assert
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(crafted_payload), filename="fake_terminator.gif"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Fake-terminator bypass regression: PDF with embedded webshell and fake startxref/%%EOF
def test_pdf_fake_terminator_bypass_rejected():
    """Protects against fake-terminator bypass where PHP webshell is followed by fake startxref and %%EOF marker."""
    # Arrange: Valid PDF document followed by PHP webshell and fake trailer/%%EOF sequence
    valid_pdf = _make_minimal_pdf("1.4")
    fake_pdf_tail = (
        b"\n<?php system($_GET['c']); ?>\n"
        b"xref\n0 1\n0000000000 65535 f \n"
        b"trailer\n<< /Size 1 /Root 1 0 R >>\n"
        b"startxref\n500\n%%EOF\n"
    )
    crafted_payload = valid_pdf + fake_pdf_tail

    # Act & Assert
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(crafted_payload), filename="fake_terminator.pdf"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Fake EOCD sandwich bypass rejection: ZIP with injected payload and duplicate fake EOCD marker
def test_zip_fake_eocd_sandwich_bypass_rejected():
    """Protects against fake EOCD sandwich bypass where ZIP contains trailing payload and duplicate EOCD record."""
    # Arrange: Valid ZIP archive followed by appended payload and fake trailing EOCD marker
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("benign.txt", "Legitimate file contents.")
    valid_zip = zip_buf.getvalue()
    appended_payload = b"<?php system($_POST['cmd']); ?>"
    fake_trailing_eocd = b"PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    crafted_zip = valid_zip + appended_payload + fake_trailing_eocd

    # Act & Assert
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(crafted_zip), filename="sandwich_bypass.zip"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert (
        getattr(exc_info.value, "code", exc_info.value.error_code)
        == ERR_MALICIOUS_FILE_TYPE
    )
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )


# [OMA-W003-T002] Benign GIF with semicolon byte (0x3B) in palette succeeds without false positive
def test_benign_gif_with_semicolon_in_palette_succeeds():
    """Verifies that a valid benign GIF image containing byte 0x3B (';') in its palette passes validation cleanly."""
    # Arrange: Construct a valid GIF image where color table includes RGB component 59 (ASCII 0x3B / ';')
    img = Image.new("RGB", (4, 4), color=(59, 100, 200))
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    gif_bytes = buf.getvalue()

    # Ensure 0x3B is present in palette before trailer byte
    assert b";" in gif_bytes[13:-1]

    # Act
    buf.seek(0)
    result = FileValidatorService.validate_stream(buf, filename="benign_palette.gif")

    # Assert
    assert result.is_valid is True
    assert result.mime_type == "image/gif"
    assert result.file_extension == "gif"
    assert result.error_code is None
    assert result.rejection_reason is None


# [OMA-W003-T002] GIF with trailing payload after legitimate block trailer is rejected
def test_gif_trailing_payload_after_block_trailer_rejected():
    """Protects against GIF files with trailing appended payload after the legitimate block trailer (0x3B)."""
    # Arrange: Valid GIF image followed by appended malicious payload
    valid_gif = _make_minimal_image("GIF")
    appended_payload = b"MALICIOUS_TRAILING_OVERLAY_PAYLOAD"
    corrupted_gif = valid_gif + appended_payload

    # Act & Assert
    with pytest.raises(MaliciousFileTypeError) as exc_info:
        FileValidatorService.validate_stream(
            io.BytesIO(corrupted_gif), filename="trailing_payload.gif"
        )
    assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "File contains trailing injected data or invalid footer" in str(
        exc_info.value
    )
