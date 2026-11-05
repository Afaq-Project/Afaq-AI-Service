# [OMA-W001-T004] FileValidatorService with stream size limit, magic bytes, zip bomb check, S3 key derivation

import hashlib
import io
import re
import struct
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from typing import BinaryIO

import pypdf
from PIL import Image, UnidentifiedImageError

from src.modules.security.exceptions import (
    ERR_FILE_SIZE_EXCEEDED,
    ERR_MALICIOUS_FILE_TYPE,
    ERR_ZIP_BOMB_DETECTED,
    FileSizeExceededError,
    MaliciousFileTypeError,
    SecurityValidationError,
    ZipBombDetectedError,
)
from src.modules.security.models import FileValidationResult

# [OMA-W003-T001] File footer and structural integrity verification constants
PNG_IEND_SIGNATURE = b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
JPEG_EOI_MARKER = b"\xff\xd9"
GIF_TRAILER_BYTE = b"\x3b"
PDF_EOF_MARKER = b"%%EOF"
ZIP_EOCD_SIGNATURE = b"PK\x05\x06"

# Stream ceilings and resource thresholds
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
MAX_UNCOMPRESSED_ZIP_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_ZIP_RATIO = 100.0  # 100:1

# [OMA-W001-FIX-CYCLE-1] Extract constant for disguised document descriptions (S1192)
DISGUISED_HTML_DESC: str = "HTML/Script disguised as document"

# Disallowed executable magic byte signatures
DISALLOWED_EXECUTABLE_SIGNATURES = [
    (b"MZ", "Windows PE executable"),
    (b"\x7fELF", "Linux ELF binary"),
    (b"#!", "Shell script"),
    (b"\xca\xfe\xba\xbe", "Java class binary"),
    (b"<!doctype html", DISGUISED_HTML_DESC),
    (b"<html", DISGUISED_HTML_DESC),
    (b"<script", DISGUISED_HTML_DESC),
]


# [OMA-W001-T004] FileValidatorService implementation
class FileValidatorService:
    """Pure-Python file and attachment security validator.

    Enforces 25 MB stream ceiling, binary magic-byte inspection, zip-bomb
    decompression defenses, and deterministic S3 object key derivation.
    """

    @staticmethod
    def validate_stream(
        stream: BinaryIO,
        filename: str | None = None,
        source_id: str = "default",
        content_disposition: str | None = None,
        source_url: str = "",
        raise_on_error: bool = True,
    ) -> FileValidationResult:
        """Inspects downloaded file stream for binary type safety, size bounds, and zip bomb hazards."""
        try:
            return FileValidatorService._execute_validation(
                stream=stream,
                filename=filename,
                source_id=source_id,
                content_disposition=content_disposition,
                source_url=source_url,
            )
        except SecurityValidationError as err:
            if raise_on_error:
                raise
            return FileValidationResult(
                is_valid=False,
                source_url=source_url,
                mime_type="",
                file_extension="",
                file_size_bytes=0,
                sha256_checksum="",
                suggested_s3_key="",
                magic_bytes_hex="",
                error_code=err.error_code,
                rejection_reason=str(err),
            )

    # [OMA-W002-T001] Strict stream pointer position integrity check
    @staticmethod
    def _rewind_stream(stream: BinaryIO) -> None:
        """Rewinds a seekable stream to beginning, strictly enforcing pointer integrity."""
        current_pos: int | None = None
        if hasattr(stream, "tell"):
            try:
                current_pos = stream.tell()
            except (AttributeError, OSError):
                current_pos = None

        if current_pos is not None and current_pos > 0:
            if not hasattr(stream, "seek"):
                raise MaliciousFileTypeError(
                    "Non-seekable stream is partially consumed (offset > 0) and cannot be rewound to beginning",
                    error_code=ERR_MALICIOUS_FILE_TYPE,
                )
            try:
                stream.seek(0)
            except (OSError, io.UnsupportedOperation) as err:
                raise MaliciousFileTypeError(
                    "Non-seekable stream is partially consumed (offset > 0) and cannot be rewound to beginning",
                    error_code=ERR_MALICIOUS_FILE_TYPE,
                ) from err

            if hasattr(stream, "tell"):
                try:
                    if stream.tell() != 0:
                        raise MaliciousFileTypeError(
                            "Non-seekable stream is partially consumed (offset > 0) and cannot be rewound to beginning",
                            error_code=ERR_MALICIOUS_FILE_TYPE,
                        )
                except (AttributeError, OSError):
                    pass
        else:
            if hasattr(stream, "seek"):
                try:
                    stream.seek(0)
                except (OSError, io.UnsupportedOperation):
                    pass

            if hasattr(stream, "tell"):
                try:
                    if stream.tell() != 0:
                        raise MaliciousFileTypeError(
                            "Non-seekable stream is partially consumed (offset > 0) and cannot be rewound to beginning",
                            error_code=ERR_MALICIOUS_FILE_TYPE,
                        )
                except (AttributeError, OSError):
                    pass

    # [OMA-W001-FIX-CYCLE-1] Stream reader and size ceiling enforcer
    @staticmethod
    def _inspect_stream_size(stream: BinaryIO) -> tuple[bytearray, int, str]:
        """Reads stream in chunks, checks max size, and computes sha256 checksum."""
        total_bytes = 0
        sha256 = hashlib.sha256()
        buffer = bytearray()
        chunk_size = 64 * 1024

        while chunk := stream.read(chunk_size):
            total_bytes += len(chunk)
            if total_bytes > MAX_FILE_SIZE:
                raise FileSizeExceededError(
                    f"File size exceeds 25 MB stream ceiling: {total_bytes} bytes",
                    error_code=ERR_FILE_SIZE_EXCEEDED,
                )
            sha256.update(chunk)
            buffer.extend(chunk)

        if total_bytes == 0:
            raise MaliciousFileTypeError(
                "File stream is empty", error_code=ERR_MALICIOUS_FILE_TYPE
            )

        return buffer, total_bytes, sha256.hexdigest()

    # [OMA-W001-FIX-CYCLE-1] Signature verification helper
    @staticmethod
    def _detect_file_signature(header: bytes) -> None:
        """Checks for disallowed executable signatures."""
        lower_header = header.lower()
        for sig, desc in DISALLOWED_EXECUTABLE_SIGNATURES:
            if header.startswith(sig) or lower_header.startswith(sig.lower()):
                raise MaliciousFileTypeError(
                    f"Disallowed executable signature detected ({desc})",
                    error_code=ERR_MALICIOUS_FILE_TYPE,
                )

    # [OMA-W001-FIX-CYCLE-1] ZIP archive safety inspector
    @staticmethod
    def _inspect_zip_archive_safety(
        file_ext: str, header: bytes, buffer: bytearray
    ) -> None:
        """Checks for zip bomb decompression hazards when archive format detected."""
        if file_ext in ("zip", "docx", "xlsx", "pptx") or header.startswith(
            b"PK\x03\x04"
        ):
            FileValidatorService._check_zip_bomb(bytes(buffer))

    # [OMA-W001-FIX-CYCLE-1] Refactored validation orchestrator (Cognitive Complexity <= 15)
    @staticmethod
    def _execute_validation(
        stream: BinaryIO,
        filename: str | None = None,
        source_id: str = "default",
        content_disposition: str | None = None,
        source_url: str = "",
    ) -> FileValidationResult:
        """Reads stream, enforces size bounds, checks magic bytes, and derives S3 key."""
        FileValidatorService._rewind_stream(stream)
        buffer, total_bytes, checksum_hex = FileValidatorService._inspect_stream_size(
            stream
        )
        # [OMA-W002-T001] Attempt rewind for seekable streams; unseekable streams are already fully consumed
        try:
            FileValidatorService._rewind_stream(stream)
        except MaliciousFileTypeError:
            pass

        header = bytes(buffer[:1024])
        magic_hex = header[:16].hex().upper()

        FileValidatorService._detect_file_signature(header)
        mime_type, file_ext = FileValidatorService._detect_allowed_type(header, buffer)
        FileValidatorService._inspect_zip_archive_safety(file_ext, header, buffer)

        # [OMA-W003-T001] File footer and structural integrity verification
        FileValidatorService._verify_file_footer(file_ext, buffer)
        FileValidatorService._verify_structural_integrity(file_ext, buffer)

        suggested_key = FileValidatorService._derive_s3_key(
            checksum_hex=checksum_hex,
            detected_ext=file_ext,
            filename=filename,
            content_disposition=content_disposition,
            source_id=source_id,
        )

        try:
            FileValidatorService._rewind_stream(stream)
        except MaliciousFileTypeError:
            pass

        return FileValidationResult(
            is_valid=True,
            source_url=source_url,
            mime_type=mime_type,
            file_extension=file_ext,
            file_size_bytes=total_bytes,
            sha256_checksum=checksum_hex,
            suggested_s3_key=suggested_key,
            magic_bytes_hex=magic_hex,
        )

    # [OMA-W003-T001] File footer and structural integrity verification
    @staticmethod
    def _verify_jpeg_footer(buffer: bytearray) -> None:
        """Verifies JPEG concludes with EOI marker and contains no trailing overlay payload."""
        first_eoi = buffer.find(JPEG_EOI_MARKER)
        if (
            first_eoi == -1
            or buffer.count(JPEG_EOI_MARKER) > 1
            or buffer[first_eoi + 2 :].strip(b"\x00\r\n\t ") != b""
        ):
            raise MaliciousFileTypeError(
                "File contains trailing injected data or invalid footer",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )

    # [OMA-W003-T001] File footer and structural integrity verification
    @staticmethod
    def _verify_png_footer(buffer: bytearray) -> None:
        """Verifies PNG concludes with the IEND chunk without trailing overlay injection."""
        if buffer.count(PNG_IEND_SIGNATURE) != 1:
            raise MaliciousFileTypeError(
                "File contains trailing injected data or invalid footer",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )
        first_iend = buffer.find(PNG_IEND_SIGNATURE)
        if buffer[first_iend + 12 :].strip(b"\x00\r\n\t ") != b"":
            raise MaliciousFileTypeError(
                "File contains trailing injected data or invalid footer",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )

    # [OMA-W003-T001] Structural GIF block parser and footer integrity verification
    @staticmethod
    def _verify_gif_footer(buffer: bytearray) -> None:
        """Verifies GIF block structure and trailer byte b';' without trailing overlay injection."""
        if not buffer.rstrip(b"\x00\r\n\t ").endswith(b";"):
            raise MaliciousFileTypeError(
                "File contains trailing injected data or invalid footer",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )

        try:
            if len(buffer) < 13 or bytes(buffer[:6]) not in (b"GIF87a", b"GIF89a"):
                raise MaliciousFileTypeError(
                    "Corrupt or malformed image structure",
                    error_code=ERR_MALICIOUS_FILE_TYPE,
                )

            # Logical Screen Descriptor packed field at offset 10
            has_gct = bool(buffer[10] & 0x80)
            gct_size = 3 * (1 << ((buffer[10] & 0x07) + 1)) if has_gct else 0
            offset = 13 + gct_size

            found_trailer = False
            while offset < len(buffer):
                block_type = buffer[offset]
                if block_type == 0x21:
                    # Extension block: intro + label (2 bytes)
                    offset += 2
                    while buffer[offset] > 0:
                        offset += 1 + buffer[offset]
                    offset += 1  # terminating 0x00 byte
                elif block_type == 0x2C:
                    # Image Descriptor: intro (1 byte) + fields (9 bytes) = 10 bytes
                    packed = buffer[offset + 9]
                    has_lct = bool(packed & 0x80)
                    lct_size = 3 * (1 << ((packed & 0x07) + 1)) if has_lct else 0
                    # Advance header (10 bytes), optional LCT, and LZW min code size (1 byte)
                    offset += 10 + lct_size + 1
                    while buffer[offset] > 0:
                        offset += 1 + buffer[offset]
                    offset += 1  # terminating 0x00 byte
                elif block_type == 0x3B:
                    # Legitimate trailer reached
                    found_trailer = True
                    break
                else:
                    raise MaliciousFileTypeError(
                        "Corrupt or malformed image structure",
                        error_code=ERR_MALICIOUS_FILE_TYPE,
                    )

            if not found_trailer:
                raise MaliciousFileTypeError(
                    "Corrupt or malformed image structure",
                    error_code=ERR_MALICIOUS_FILE_TYPE,
                )

            # The byte after trailer offset + 1 is the true end of the GIF data
            if buffer[offset + 1 :].strip(b"\x00\r\n\t ") != b"":
                raise MaliciousFileTypeError(
                    "File contains trailing injected data or invalid footer",
                    error_code=ERR_MALICIOUS_FILE_TYPE,
                )
        except (IndexError, ValueError) as err:
            raise MaliciousFileTypeError(
                "Corrupt or malformed image structure",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            ) from err

    # [OMA-W003-T001] File footer and structural integrity verification
    @staticmethod
    def _verify_pdf_footer(buffer: bytearray) -> None:
        """Verifies PDF concludes with %%EOF marker and trailing bytes contain only standard whitespace."""
        first_eof = buffer.find(PDF_EOF_MARKER)
        if (
            first_eof == -1
            or buffer.count(PDF_EOF_MARKER) != 1
            or buffer[buffer.rfind(PDF_EOF_MARKER) + 5 :].strip(b"\r\n\t \x00") != b""
        ):
            raise MaliciousFileTypeError(
                "File contains trailing injected data or invalid footer",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )

    # [OMA-W003-T001] File footer boundary singularity verification for ZIP archives
    @staticmethod
    def _verify_zip_footer(buffer: bytearray) -> None:
        """Verifies ZIP concludes with unique EOCD record and total size matches eocd_offset + 22 + comment_length."""
        if buffer.count(ZIP_EOCD_SIGNATURE) != 1:
            raise MaliciousFileTypeError(
                "File contains trailing injected data or invalid footer",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )
        eocd_pos = buffer.find(ZIP_EOCD_SIGNATURE)
        if len(buffer) < eocd_pos + 22:
            raise MaliciousFileTypeError(
                "File contains trailing injected data or invalid footer",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )
        comment_len = struct.unpack("<H", buffer[eocd_pos + 20 : eocd_pos + 22])[0]
        expected_size = eocd_pos + 22 + comment_len
        if (
            len(buffer) < expected_size
            or buffer[expected_size:].strip(b"\x00\r\n\t ") != b""
        ):
            raise MaliciousFileTypeError(
                "File contains trailing injected data or invalid footer",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )

    # [OMA-W003-T001] File footer and structural integrity verification
    @staticmethod
    def _verify_webp_footer(buffer: bytearray) -> None:
        """Verifies WebP RIFF container bounds and rejects trailing overlay injection."""
        if len(buffer) < 8:
            raise MaliciousFileTypeError(
                "File contains invalid footer or unauthorized trailing injected data",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )
        riff_size = struct.unpack("<I", buffer[4:8])[0] + 8
        expected_size = riff_size + (riff_size % 2)
        if len(buffer) > expected_size:
            raise MaliciousFileTypeError(
                "File contains invalid footer or unauthorized trailing injected data",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )

    # [OMA-W003-T001] File footer and structural integrity verification
    @staticmethod
    def _verify_file_footer(file_ext: str, buffer: bytearray) -> None:
        """Inspects footers and trailing bytes to prevent overlay injection and polyglot attacks."""
        if file_ext in ("jpg", "jpeg"):
            FileValidatorService._verify_jpeg_footer(buffer)
        elif file_ext == "png":
            FileValidatorService._verify_png_footer(buffer)
        elif file_ext == "gif":
            FileValidatorService._verify_gif_footer(buffer)
        elif file_ext == "pdf":
            FileValidatorService._verify_pdf_footer(buffer)
        elif file_ext in ("zip", "docx", "xlsx", "pptx"):
            FileValidatorService._verify_zip_footer(buffer)
        elif file_ext == "webp":
            FileValidatorService._verify_webp_footer(buffer)

    # [OMA-W003-T001] File footer and structural integrity verification
    @staticmethod
    def _verify_image_structure(file_ext: str, buffer: bytearray) -> None:
        """Verifies image structural integrity using PIL.Image."""
        try:
            stream = io.BytesIO(buffer)
            with Image.open(stream) as img:
                img.verify()
                expected_formats = {
                    "jpg": ("JPEG", "MPO"),
                    "jpeg": ("JPEG", "MPO"),
                    "png": ("PNG",),
                    "gif": ("GIF",),
                    "webp": ("WEBP",),
                }
                valid_formats = expected_formats.get(file_ext)
                if valid_formats and img.format not in valid_formats:
                    raise MaliciousFileTypeError(
                        "Corrupt or malformed image structure",
                        error_code=ERR_MALICIOUS_FILE_TYPE,
                    )
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as err:
            raise MaliciousFileTypeError(
                "Corrupt or malformed image structure",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            ) from err

    # [OMA-W003-T001] File footer and structural integrity verification
    @staticmethod
    def _verify_zip_structure(file_ext: str, buffer: bytearray) -> None:
        """Verifies ZIP archive and Office OpenXML document structural integrity."""
        try:
            stream = io.BytesIO(buffer)
            with zipfile.ZipFile(stream) as zf:
                bad_member = zf.testzip()
                if bad_member is not None:
                    raise MaliciousFileTypeError(
                        "Corrupt or malformed archive/office document structure",
                        error_code=ERR_MALICIOUS_FILE_TYPE,
                    )
                if file_ext in ("docx", "xlsx", "pptx"):
                    content_types_bytes = zf.read("[Content_Types].xml")
                    ET.fromstring(content_types_bytes)
        except (
            zipfile.BadZipFile,
            zipfile.LargeZipFile,
            ET.ParseError,
            KeyError,
        ) as err:
            raise MaliciousFileTypeError(
                "Corrupt or malformed archive/office document structure",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            ) from err

    # [OMA-W004-T001] Streamlined FileValidatorService: PDF structural verification using pypdf
    @staticmethod
    def _verify_pdf_structure(buffer: bytearray) -> None:
        """Verifies PDF structural integrity using pypdf."""
        if buffer.count(PDF_EOF_MARKER) != 1:
            raise MaliciousFileTypeError(
                "File contains trailing injected data or invalid footer",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )
        first_eof = buffer.find(PDF_EOF_MARKER)
        if first_eof == -1 or buffer[first_eof + 5 :].strip(b"\r\n\t \x00") != b"":
            raise MaliciousFileTypeError(
                "File contains trailing injected data or invalid footer",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )

        if not buffer.startswith(b"%PDF-"):
            raise MaliciousFileTypeError(
                "Corrupt or malformed PDF structure",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            )

        try:
            reader = pypdf.PdfReader(io.BytesIO(buffer))
            _ = reader.trailer
            if len(reader.pages) < 0:
                raise ValueError("Invalid pages tree")
        except Exception as err:
            raise MaliciousFileTypeError(
                "Corrupt or malformed PDF structure",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            ) from err

    # [OMA-W003-T001] File footer and structural integrity verification
    @staticmethod
    def _verify_structural_integrity(file_ext: str, buffer: bytearray) -> None:
        """Dispatches deep structural verification based on file extension."""
        if file_ext in ("jpg", "jpeg", "png", "gif", "webp"):
            FileValidatorService._verify_image_structure(file_ext, buffer)
        elif file_ext == "pdf":
            FileValidatorService._verify_pdf_structure(buffer)
        elif file_ext in ("zip", "docx", "xlsx", "pptx"):
            FileValidatorService._verify_zip_structure(file_ext, buffer)

    @staticmethod
    def _detect_allowed_type(header: bytes, buffer: bytearray) -> tuple[str, str]:
        """Detects allowed attachment MIME type and extension from leading magic bytes."""
        # PDF (%PDF-)
        if header.startswith(b"%PDF-"):
            return "application/pdf", "pdf"

        # JPEG (\xFF\xD8\xFF)
        if header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpg"

        # PNG (\x89PNG\r\n\x1a\n)
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"

        # GIF (GIF87a / GIF89a)
        if header.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif", "gif"

        # WEBP (RIFF....WEBP)
        if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP":
            return "image/webp", "webp"

        # ZIP-based container (DOCX / XLSX / PPTX / ZIP)
        if header.startswith(b"PK\x03\x04"):
            try:
                with zipfile.ZipFile(io.BytesIO(buffer)) as zf:
                    namelist = zf.namelist()
                    if any(name.startswith("word/") for name in namelist):
                        return (
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            "docx",
                        )
                    if any(name.startswith("xl/") for name in namelist):
                        return (
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            "xlsx",
                        )
                    if any(name.startswith("ppt/") for name in namelist):
                        return (
                            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            "pptx",
                        )
                    return "application/zip", "zip"
            except zipfile.BadZipFile as e:
                raise MaliciousFileTypeError(
                    f"Corrupted or invalid ZIP archive: {e}",
                    error_code=ERR_MALICIOUS_FILE_TYPE,
                ) from e

        raise MaliciousFileTypeError(
            "File magic bytes do not match any permitted attachment type (PDF, DOCX, XLSX, PPTX, JPEG, PNG, GIF, WEBP)",
            error_code=ERR_MALICIOUS_FILE_TYPE,
        )

    @staticmethod
    def _check_zip_bomb(zip_bytes: bytes) -> None:
        """Inspects ZIP directory table without decompression to detect zip bombs."""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                infolist = zf.infolist()
                total_uncompressed = sum(info.file_size for info in infolist)
                total_compressed = sum(info.compress_size for info in infolist)

                # Total uncompressed size limit (50 MB)
                if total_uncompressed > MAX_UNCOMPRESSED_ZIP_SIZE:
                    raise ZipBombDetectedError(
                        f"Zip bomb detected: uncompressed size ({total_uncompressed} bytes) exceeds 50 MB limit",
                        error_code=ERR_ZIP_BOMB_DETECTED,
                    )

                # Compression ratio cap (100:1)
                if total_compressed > 0:
                    ratio = total_uncompressed / total_compressed
                    if ratio > MAX_ZIP_RATIO:
                        raise ZipBombDetectedError(
                            f"Zip bomb detected: compression ratio ({ratio:.1f}:1) exceeds 100:1 cap",
                            error_code=ERR_ZIP_BOMB_DETECTED,
                        )
                elif total_uncompressed > 0:
                    raise ZipBombDetectedError(
                        "Zip bomb detected: non-zero uncompressed size with zero compressed size",
                        error_code=ERR_ZIP_BOMB_DETECTED,
                    )
        except zipfile.BadZipFile as e:
            raise MaliciousFileTypeError(
                f"Invalid ZIP container: {e}",
                error_code=ERR_MALICIOUS_FILE_TYPE,
            ) from e

    @staticmethod
    def _derive_s3_key(
        checksum_hex: str,
        detected_ext: str,
        filename: str | None = None,
        content_disposition: str | None = None,
        source_id: str = "default",
    ) -> str:
        """Derives clean S3 key: documents/{source_id}/{sha256[:16]}_{safe_filename}.{ext} or hash fallback."""
        raw_name: str | None = None

        # 1. Try extracting from Content-Disposition header (UC-06)
        if content_disposition:
            # Check filename*=UTF-8''encoded_name
            match_star = re.search(
                r"filename\*\s*=\s*UTF-8''([^;\s]+)", content_disposition, re.IGNORECASE
            )
            if match_star:
                raw_name = urllib.parse.unquote(match_star.group(1))
            else:
                # Check filename="name.pdf" or filename=name.pdf
                match_plain = re.search(
                    r'filename\s*=\s*(?:"([^"]+)"|([^;\s]+))',
                    content_disposition,
                    re.IGNORECASE,
                )
                if match_plain:
                    raw_name = match_plain.group(1) or match_plain.group(2)

        # 2. Fall back to filename argument (URL path)
        if not raw_name and filename:
            raw_name = filename

        # 3. Sanitize filename candidate
        safe_name = ""
        if raw_name:
            # Remove path separators and traversal tokens
            base = raw_name.replace("\\", "/").split("/")[-1].strip()
            # Strip extension if it matches detected extension or other extension
            ext_suffix = f".{detected_ext}"
            if base.lower().endswith(ext_suffix):
                base = base[: -len(ext_suffix)]
            elif "." in base:
                base = base.rsplit(".", 1)[0]

            # Keep only alphanumeric, underscores, hyphens
            safe_name = re.sub(r"[^\w\s-]", "", base).strip().replace(" ", "_")

        # 4. Construct S3 key
        prefix = f"documents/{source_id}/{checksum_hex[:16]}"
        if safe_name:
            return f"{prefix}_{safe_name}.{detected_ext}"

        return f"{prefix}.{detected_ext}"


# [OMA-W001-T004] Backward-compatible alias
FileValidator = FileValidatorService
