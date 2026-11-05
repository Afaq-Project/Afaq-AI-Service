<!-- [OMA-W002-T001] -->
# Security Vulnerability Assessment & Remediation Report

## 1. Executive Summary

This document details the security vulnerability identified in stream handling within `FileValidatorService` (`src/modules/security/services/file_validator_service.py`), specifically regarding unseekable and partially consumed input streams in `_rewind_stream`. It describes the attack and failure vectors enabled by stream offset desynchronization and outlines the strict pointer integrity remediation implemented under task `OMA-W002-T001`.

---

## 2. Vulnerability Description

### Unseekable Stream Offset Desynchronization in `_rewind_stream`

**Affected Component**: `FileValidatorService._rewind_stream(stream: BinaryIO)`  
**Vulnerability Type**: CWE-390 (Detection of Error Condition Without Action) / CWE-441 (Unintended Proxy or Intermediary) / Stream Pointer Desynchronization  
**Severity**: High  

Prior to remediation, `_rewind_stream` contained a permissive exception handler that swallowed `OSError` without inspecting the stream pointer's state:

```python
# Vulnerable Implementation
@staticmethod
def _rewind_stream(stream: BinaryIO) -> None:
    if hasattr(stream, "seek"):
        try:
            stream.seek(0)
        except OSError:
            pass
```

When a stream is non-seekable (such as a network pipe, unbuffered socket, or streaming generator) and has already been partially read (pointer offset `tell() > 0`), the `seek(0)` call fails with `OSError` (or `io.UnsupportedOperation`). Swallowing this error allowed execution to proceed from the arbitrary stream offset rather than from byte 0.

---

## 3. Attack and Failure Vectors

Stream offset desynchronization introduces three primary vulnerability vectors:

### 3.1. False-Positive Denial of Service (DoS)

* **Mechanism**: If upstream middleware, an ingress proxy, or a preliminary inspection routine partially reads data from an unseekable stream before delegating to `FileValidatorService`, the stream arrives at `validate_stream` with an offset greater than zero (`stream.tell() > 0`).
* **Impact**: Because the stream cannot be rewound to the beginning, reading begins past the file header. The magic bytes inspection (`_detect_allowed_type`) fails to match permitted signatures (`%PDF-`, `\xff\xd8\xff`, `\x89PNG`, `PK\x03\x04`), causing legitimate, benign documents to be rejected with `MaliciousFileTypeError` (`ERR_MALICIOUS_FILE_TYPE`).
* **Consequence**: Legitimate client uploads fail systematically whenever an upstream proxy or inspection middleware does not rewind incoming streams, resulting in service denial.

### 3.2. Size Limit Bypass (Resource Exhaustion / S3 Flooding)

* **Mechanism**: `FileValidatorService` enforces a strict 25 MB stream ceiling (`MAX_FILE_SIZE = 25 * 1024 * 1024`) during `_inspect_stream_size` by counting bytes read in chunks from the current stream position:
  ```python
  while chunk := stream.read(chunk_size):
      total_bytes += len(chunk)
      if total_bytes > MAX_FILE_SIZE:
          raise FileSizeExceededError(...)
  ```
* **Attack Vector**: If an attacker crafts an input where an upstream proxy or custom parser reads the initial $N$ megabytes (e.g., 20 MB of padding or executable code) before streaming the remainder into `FileValidatorService`, `_inspect_stream_size` only calculates the remaining bytes ($25\text{ MB} - \epsilon$).
* **Impact**: A total payload of up to $20\text{ MB} + 25\text{ MB} = 45\text{ MB}$ traverses the pipeline, effectively bypassing the 25 MB hard ceiling. The system computes a partial checksum and derived S3 key that does not reflect the complete file, leading to integrity degradation and storage bloat.

### 3.3. Targeted Magic Byte Bypass (Masquerading & Execution Hazards)

* **Mechanism**: Security defenses rely on examining the leading 1024 bytes of the file for disallowed executable signatures (Windows PE `MZ`, Linux ELF `\x7fELF`, shell scripts `#!`, HTML/JavaScript) and verifying valid magic bytes (e.g., `%PDF-1.4`).
* **Attack Vector**: An attacker crafts an executable file (such as a Windows `.exe` or Linux ELF binary) containing an embedded PDF or JPEG header positioned at a known offset $K$. If the stream pointer is advanced by $K$ bytes prior to validation:
  1. The executable header located at offset `0` to `K-1` is skipped entirely.
  2. `_detect_file_signature` never inspects the real executable header.
  3. `_detect_allowed_type` observes the attacker's embedded magic bytes at offset $K$ and classifies the payload as a legitimate PDF or image.
* **Impact**: The malicious executable bypasses type inspection, is uploaded to object storage with a misleading MIME type, and may be served to downstream clients or workers expecting safe document types.

---

## 4. Implemented Remediation

Under task `[OMA-W002-T001]`, `FileValidatorService._rewind_stream` has been refactored to enforce strict pointer integrity:

```python
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
```

### Key Remediation Guarantees:

1. **Strict Offset Verification**: If `stream.tell() > 0`, the stream is recognized as partially consumed. If `stream.seek(0)` is absent, raises `OSError` / `io.UnsupportedOperation`, or fails to reset `tell()` to `0`, `MaliciousFileTypeError` is raised immediately with `error_code=ERR_MALICIOUS_FILE_TYPE`.
2. **Safe Origin Zero Allowance**: Streams with `tell() == 0` or uninspectable positions (e.g. raw pipes/sockets where `tell()` raises `OSError` or is absent) attempt `seek(0)` safely without raising false-positive errors, allowing clean streaming ingest from position 0.
3. **Verification of Rewind**: After `seek(0)`, if `tell()` is supported, it is verified to equal 0.
4. **Post-Inspection Safety**: In `_execute_validation`, post-inspection rewind is wrapped so that fully consumed unseekable streams that originated at offset 0 complete validation cleanly.

---

## 5. Verification Matrix

| Test Scenario | Stream State | Expected Outcome | Status |
|---|---|---|---|
| Unseekable stream, offset > 0, no `seek` | `tell() == 10`, no `seek` | Raises `MaliciousFileTypeError` (`ERR_MALICIOUS_FILE_TYPE`) | Verified |
| Unseekable stream, offset > 0, `seek` raises `OSError` | `tell() == 5`, `seek` raises `OSError` | Raises `MaliciousFileTypeError` (`ERR_MALICIOUS_FILE_TYPE`) | Verified |
| Unseekable stream, offset > 0, `seek` raises `UnsupportedOperation` | `tell() == 5`, `seek` raises `UnsupportedOperation` | Raises `MaliciousFileTypeError` (`ERR_MALICIOUS_FILE_TYPE`) | Verified |
| Unseekable stream, offset 0, `seek` raises `OSError` | `tell() == 0`, `seek` raises `OSError` | Allowed to proceed without error | Verified |
| Raw unseekable stream (pipe mock), `tell` and `seek` raise `OSError` | `tell()` raises `OSError`, `seek` raises `OSError` | Allowed to proceed without error | Verified |
| Seekable stream, offset > 0, seek succeeds | `tell() == 5`, `seek(0)` succeeds | Rewound cleanly to offset 0 | Verified |
| Silent broken seek, offset > 0, `seek` no-op | `tell() == 5`, `seek` does nothing | Raises `MaliciousFileTypeError` (`ERR_MALICIOUS_FILE_TYPE`) | Verified |
| Validation pipeline with consumed unseekable stream | Origin offset > 0 | Rejection via `MaliciousFileTypeError` | Verified |
| Validation pipeline with clean unseekable stream | Origin offset 0 | Validated successfully | Verified |

---

<!-- [OMA-W003-T001] -->
## 6. SEC-002: File Footer Bypass, Boundary Singularity & Fake Terminator Marker Injection Attacks

### 6.1. Threat Model & Vulnerability Description

**Affected Component**: `FileValidatorService` (`src/modules/security/services/file_validator_service.py`)  
**Vulnerability Type**: CWE-434 (Unrestricted Upload of File with Dangerous Type) / CWE-115 (Misinterpretation of Input) / Polyglot & Trailing Overlay Data Injection / Terminator Marker Desynchronization / File Parser Mismatch  
**Severity**: Critical  

Prior to remediation, `FileValidatorService` verified leading magic bytes (e.g. `%PDF-`, `\xff\xd8\xff`, `\x89PNG`, `PK\x03\x04`) within the first 1024 bytes of the file stream, but lacked footer boundary enforcement, trailing payload detection, and deep internal structural validation. Furthermore, initial footer checks relied on backward-searching methods (such as `buffer.rfind()` or `buffer.endswith()`), which introduced critical secondary vulnerabilities: **Fake Terminator Marker Injection & Boundary Singularity Bypasses**, as well as **False-Positive Rejections on Benign Files**.

#### Threat Vectors:
1. **Trailing Overlay Payloads & Appended Web Shells**:
   Attackers craft files with valid leading magic bytes (e.g. valid JPEG or PNG headers) followed by malicious executable scripts (e.g., PHP web shells, Python scripts, HTML/JavaScript, or Windows PE binaries) appended at the end of the file. If served directly by static file servers or processed by permissive interpreters, the appended payload executes while evading magic-byte validation.
2. **Boundary Singularity & Fake Terminator Marker Injection (Phase 3 Bypass Discovery SEC-FINDING-01)**:
   When footer inspection relies on backward search (`rfind()`), an attacker can craft a trailing payload sandwich:
   - **ZIP & Office Documents**: When `_verify_zip_footer` used `buffer.rfind(ZIP_EOCD_SIGNATURE)`, an attacker could inject an appended payload after the legitimate ZIP structure and tack a fake 22-byte EOCD marker (`PK\x05\x06\x00...`) at the very end. `rfind()` bound to the fake trailing EOCD, and with a comment length of 0, the computed expected size matched the file length, allowing arbitrary injected overlays to evade validation. Enforcing boundary singularity (`buffer.count(ZIP_EOCD_SIGNATURE) == 1`) and verifying the primary EOCD boundary eliminates this attack.
   - **JPEG**: Attacker appends a PHP webshell and tacks a fake `\xff\xd9` (EOI) marker at the end of the file. Single-marker singularity enforcement (`count == 1`) blocks this.
   - **PNG**: Attacker appends a PHP webshell and appends a duplicate fake `IEND` chunk (`\x00\x00\x00\x00IEND\xaeB`\x82`). Single-chunk singularity enforcement (`count == 1`) blocks this.
   - **PDF**: Attacker appends a PHP webshell followed by a fake `startxref\n{offset}\n%%EOF` block pointing back to the original xref table. Single-EOF singularity enforcement (`count == 1`) blocks this.
3. **GIF False-Positive Rejections & Fake Terminator Bypasses (Phase 3 Discovery SEC-FINDING-02)**:
   In GIF images, the format trailer is a single byte `0x3B` (`b";"`). Naively searching for the first occurrence via `buffer.find(b";")` causes severe false positives because byte `0x3B` (ASCII 59) frequently occurs naturally inside Global/Local Color Table palette RGB definitions (e.g., color `(59, y, z)`) and LZW compressed raster blocks. Conversely, suffix matching (`buffer.endswith(b";")`) allows attackers to append arbitrary payloads and terminate with a fake `;`. Implementing a structural block-walking parser that parses the Logical Screen Descriptor, color tables, and data blocks from byte 0 to locate the legitimate terminal trailer byte resolves both vulnerabilities completely.
4. **Polyglot Files**:
   Files crafted to be valid under two different formats simultaneously (such as a valid GIF/JPEG and a valid ZIP or JAR file, or a PDF with executable overlays). Without strict end-of-file boundary verification and internal structure parsing, hybrid payloads pass header checks.
5. **File Structure Corruption & Parser Mismatch**:
   Truncated, corrupt, or malformed image, PDF, and archive files can cause downstream services (e.g., PDF renderers, OCR pipelines, image resizing workers, or document indexers) to crash, hang (Denial of Service), or trigger memory corruption vulnerabilities in lower-level C/C++ parsers.
6. **Renamed Zip Exploitation in Office OpenXML Formats**:
   Renaming an arbitrary zip file to `.docx`, `.xlsx`, or `.pptx` could bypass format classification unless Open Packaging Conventions (OPC) structure (specifically `[Content_Types].xml`) and member CRC-32 integrity are strictly verified.

---

### 6.2. Implemented Remediation

Under task `[OMA-W003-T001]`, `FileValidatorService` has been hardened with boundary singularity enforcement and deep structural validation:

#### 1. Boundary Singularity Enforcement & Structural Footer Verification (`_verify_file_footer`)
To eliminate fake terminator injection bypasses and avoid false-positive rejections, footer checks enforce **boundary singularity** and structural block traversal:
- **JPEG (`_verify_jpeg_footer`)**: Locates the first EOI marker via `first_eoi = buffer.find(JPEG_EOI_MARKER)`. Strictly enforces `buffer.count(JPEG_EOI_MARKER) == 1` and verifies that any bytes after `first_eoi + 2` are exclusively benign whitespace or null padding (`buffer[first_eoi + 2:].strip(b"\x00\r\n\t ") == b""`). If `first_eoi == -1`, multiple EOI markers exist, or trailing data is present, raises `MaliciousFileTypeError("File contains trailing injected data or invalid footer", error_code=ERR_MALICIOUS_FILE_TYPE)`.
- **PNG (`_verify_png_footer`)**: Enforces that a legitimate PNG possesses exactly one `IEND` chunk: `buffer.count(PNG_IEND_SIGNATURE) == 1`. Locates `first_iend = buffer.find(PNG_IEND_SIGNATURE)` and ensures `buffer[first_iend + 12:].strip(b"\x00\r\n\t ") == b""`. Rejects files with missing, multiple, or trailing non-padding data.
- **GIF (`_verify_gif_footer`)**: Implements structural GIF block parsing to determine the true terminal offset of the image:
  1. Verifies basic trailer presence: `buffer.rstrip(b"\x00\r\n\t ").endswith(b";")`.
  2. Validates GIF header signature (`GIF87a` or `GIF89a`).
  3. Parses the Logical Screen Descriptor (bytes 6-12), extracts the packed field at offset 10 to check for a Global Color Table (`bool(buffer[10] & 0x80)`), calculates GCT size (`3 * (1 << ((buffer[10] & 0x07) + 1))`), and advances past the header and GCT.
  4. Sequentially parses GIF blocks:
     - Extension Blocks (`0x21`): advances intro and label bytes, walks sub-blocks by reading size bytes until terminating `0x00`.
     - Image Descriptors (`0x2C`): advances descriptor header (10 bytes), checks Local Color Table flag in packed byte (`buffer[offset + 9] & 0x80`) and size (`3 * (1 << ((buffer[offset + 9] & 0x07) + 1))`), skips LZW minimum code size (1 byte), and walks raster data sub-blocks until terminating `0x00`.
     - Trailer Byte (`0x3B`): records legitimate terminal trailer offset.
  5. Verifies that all bytes after the true parsed trailer are strictly benign padding: `buffer[offset + 1:].strip(b"\x00\r\n\t ") == b""`.
  6. Any trailing non-padding data raises `MaliciousFileTypeError("File contains trailing injected data or invalid footer", error_code=ERR_MALICIOUS_FILE_TYPE)`. Any malformed block sequences, truncated streams, or indexing errors raise `MaliciousFileTypeError("Corrupt or malformed image structure", error_code=ERR_MALICIOUS_FILE_TYPE)`.
- **PDF (`_verify_pdf_footer` & `_verify_pdf_structure`)**: Enforces boundary singularity by checking `buffer.count(PDF_EOF_MARKER) == 1`. Locates `first_eof = buffer.find(PDF_EOF_MARKER)` and verifies that `buffer[first_eof + 5:].strip(b"\r\n\t \x00") == b""`. Any file with duplicate `%%EOF` markers or non-whitespace characters after the marker is immediately rejected with `MaliciousFileTypeError("File contains trailing injected data or invalid footer", error_code=ERR_MALICIOUS_FILE_TYPE)`.
- **ZIP & Office Documents (`.docx`, `.xlsx`, `.pptx`) (`_verify_zip_footer`)**: Enforces boundary singularity by verifying `buffer.count(ZIP_EOCD_SIGNATURE) == 1`. Locates `eocd_pos = buffer.find(ZIP_EOCD_SIGNATURE)`, checks `len(buffer) >= eocd_pos + 22`, extracts `comment_len`, and calculates `expected_size = eocd_pos + 22 + comment_len`. Verifies that `len(buffer) >= expected_size` and `buffer[expected_size:].strip(b"\x00\r\n\t ") == b""`. Rejects files with duplicate EOCD markers (fake EOCD sandwich attacks), truncated footers, or trailing injected payloads with `MaliciousFileTypeError("File contains trailing injected data or invalid footer", error_code=ERR_MALICIOUS_FILE_TYPE)`.
- **WebP (`_verify_webp_footer`)**: Verifies RIFF container header length bounds (`riff_size + 8`) and rejects any unauthorized trailing overlay data.

#### 2. Deep File Structural Verification (`_verify_structural_integrity`)
- **Images (JPEG, PNG, GIF, WebP)**: Utilizes Pillow (`PIL.Image`) to open streams and invoke `image.verify()`. Checks internal block structure and format validity without executing untrusted code. Traps `(UnidentifiedImageError, OSError, SyntaxError, ValueError)` and raises `MaliciousFileTypeError("Corrupt or malformed image structure", error_code=ERR_MALICIOUS_FILE_TYPE)`.
- **PDF**: Employs an internal robust structural parser (and integrates `pypdf` if present) to verify header version format, boundary singularity, `startxref` offset validity, xref table / xref stream parsing, trailer dictionary integrity (`/Root` catalog reference), and Document Catalog dictionary validation. Traps parsing errors and raises `MaliciousFileTypeError`.
- **ZIP & Office Documents (`.docx`, `.xlsx`, `.pptx`)**: Uses Python's standard `zipfile.ZipFile` to execute `testzip()` verifying CRC-32 checksums of all compressed archive members. For Office OpenXML formats, verifies that `[Content_Types].xml` is present and well-formed XML using `xml.etree.ElementTree`. Traps `(zipfile.BadZipFile, zipfile.LargeZipFile, ET.ParseError, KeyError)` and raises `MaliciousFileTypeError("Corrupt or malformed archive/office document structure", error_code=ERR_MALICIOUS_FILE_TYPE)`.
- **Stream Rewind & Pointer Integrity**: Ensures all seekable streams are cleanly rewound to offset 0 before returning or passing to subsequent operations, maintaining strict compatibility with `_rewind_stream`.

---

### 6.3. Verification Matrix

| Target Format | Threat / Injection Vector | Expected Defense Outcome | Status |
|---|---|---|---|
| JPEG | Appended web shell with fake trailing `\xff\xd9` | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains trailing injected data or invalid footer") | Verified |
| PNG | Appended web shell with duplicate fake `IEND` chunk | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains trailing injected data or invalid footer") | Verified |
| GIF | Appended web shell with fake `;` trailer | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains trailing injected data or invalid footer") | Verified |
| GIF | Benign GIF with byte `0x3B` in palette RGB or LZW raster data | Successfully validated with `image/gif`, correct extension, and S3 key | Verified |
| PDF | Appended web shell with fake `startxref...%%EOF` | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains trailing injected data or invalid footer") | Verified |
| PNG | Appended script/binary overlay after `IEND` | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains trailing injected data or invalid footer") | Verified |
| JPEG | Appended web shell overlay after `\xff\xd9` | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains trailing injected data or invalid footer") | Verified |
| GIF | Appended overlay after trailer `;` | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains trailing injected data or invalid footer") | Verified |
| PDF | Appended script/binary overlay after `%%EOF` | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains trailing injected data or invalid footer") | Verified |
| ZIP / DOCX | Appended overlay past `PK\x05\x06` EOCD | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains trailing injected data or invalid footer") | Verified |
| ZIP / DOCX | Fake EOCD sandwich attack (injected payload + fake trailing EOCD marker) | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains trailing injected data or invalid footer") | Verified |
| WebP | Appended overlay exceeding RIFF size bounds | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("File contains invalid footer or unauthorized trailing injected data") | Verified |
| PNG / JPEG / GIF / WebP | Corrupt or truncated image stream | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("Corrupt or malformed image structure") | Verified |
| PDF | Missing/corrupt xref, trailer, or catalog | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("Corrupt or malformed PDF structure") | Verified |
| DOCX / XLSX / PPTX | Missing or malformed `[Content_Types].xml` | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("Corrupt or malformed archive/office document structure") | Verified |
| ZIP / Office | Broken CRC-32 member compression | Rejected with `ERR_MALICIOUS_FILE_TYPE` ("Corrupt or malformed archive/office document structure") | Verified |
| All Formats | Valid, uncorrupted files | Successfully validated with correct MIME type, extension, and S3 key | Verified |

