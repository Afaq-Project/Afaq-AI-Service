# Security, Link Validation & Content Sanitization Module Specification

## 1. Executive Summary & Architectural Mandate

The **Security, Link Validation & Content Sanitization Module** (`src/modules/security/`) is the central, mandatory security gateway for the entire `Afaq-AI-Service` scraping and ingestion ecosystem. 

### 1.1. Threat Model & Motivations
Operating an autonomous, web-scale scraping engine involves ingesting unvetted, third-party data from dynamic external platforms. This creates substantial attack surfaces:
1. **Server-Side Request Forgery (SSRF):** Malicious inputs or hidden redirects attempting to coerce our crawler, headless browsers, or HTTP clients into querying cloud metadata endpoints (`169.254.169.254`), local loopback (`127.0.0.1`), or private VPC services (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
2. **Infinite & Circular Redirect Traps:** Malicious or misconfigured servers returning looping redirects or chains exceeding limits to exhaust memory, sockets, and worker execution quotas.
3. **Cross-Site Scripting (XSS) & Code Injection:** Malicious HTML, inline JavaScript (`<script>`, `onload=`, `javascript:`), SVG scripts, or embedded objects hidden within scholarship descriptions or titles.
4. **LLM Prompt Hijacking (Addressed in Scraping Pipeline):** Adversarial instructions placed in target DOMs (e.g., `"<!-- Ignore previous instructions... -->"`) addressed via system prompt priming in the scraping module.
5. **Malicious Attachment Payloads:** Disguised executable files (`.exe`, `.sh`, `.php`, `.vbs`) masquerading as scholarship application forms or PDF guidelines.
6. **IDN Homograph & Punycode Attacks:** Visually deceptive internationalized domain names spoofing legitimate universities or government portals.

### 1.2. Architectural Mandate
* **Pure Gatekeeper Principle:** The security module acts strictly as a non-mutating gatekeeper. It evaluates inputs (URLs, files, schemas) against security invariants: if safe, it allows them through unmutated; if dangerous, it rejects immediately with a standardized error code and alert.
* **Zero In-Module Content Mutation:** The security module does **not** alter, format, clean, or normalize data. Content transformation (stripping HTML tags, decoding entities, Unicode NFKC normalization, date/currency parsing) is strictly deferred to the downstream **Data Cleaning & Normalization Pipeline** (`src/modules/cleaning/`).
* **Fail-Secure Principle:** Any validation failure defaults to immediate rejection, source or listing flagging, zero AI cost expenditure, and structured audit telemetry.

---

## 2. Module Architecture & Directory Structure

The security module resides under `src/modules/security/` as a self-contained, high-performance, non-mutating domain:

```
src/modules/security/
├── __init__.py               # Public API exports (validators, models, error codes)
├── link_validator.py         # RFC 3986 syntax, Anti-SSRF, DNS verification & Redirect Inspector
├── file_validator.py         # Magic-byte inspection, streaming limits, zip bomb, S3 key
├── schema_validator.py       # Pydantic schema validation, CSS ReDoS linter & delimiter escaping
├── models.py                 # Pydantic models for validation results & security metrics
└── exceptions.py             # Domain-specific security exception hierarchy
```

---

## 3. Link Verification Subsystem (`LinkValidator`)

The `LinkValidator` is responsible for inspecting, sanitizing, and validating all URLs across every pipeline phase: administrative source entries, discovered catalog URLs, pagination endpoints, detail page links, and external application links.

### 3.1. Verification Lifecycle & Execution Steps

Every URL undergoes a deterministic 5-step inspection:

```
Input URL
   │
   ▼
[ 1. Syntax & Normalization ] ────▶ Invalid? ────▶ Raise SecurityValidationError(ERR_INVALID_URL_SYNTAX)
   │ Valid
   ▼
[ 2. Scheme & Port Check ] ───────▶ Invalid? ────▶ Raise SecurityValidationError(ERR_INVALID_SCHEME / ERR_INVALID_PORT)
   │ http / https / 80 / 443
   ▼
[ 3. Anti-Homograph / IDN ] ──────▶ Spoof? ──────▶ Raise SecurityValidationError(ERR_HOMOGRAPH_ATTACK)
   │ Clean
   ▼
[ 4. Path Traversal & Normal ] ───▶ Suspicious? ─▶ Raise SecurityValidationError(ERR_PATH_TRAVERSAL)
   │ Canonical Path
   ▼
[ 5. DNS Pinning & Anti-SSRF ] ───▶ Private IP? ─▶ Raise SecurityValidationError(ERR_SSRF_ATTEMPT_BLOCKED)
   │ Public IP Verified
   ▼
[ 6. Safe Redirect Traversal ] ───▶ Loop/Depth? ─▶ Raise SecurityValidationError(ERR_CIRCULAR_REDIRECT / ERR_MAX_REDIRECTS_EXCEEDED)
   │ Final Public Destination
   ▼
Validated Safe URL Object
```

### 3.2. Detailed Check Specifications

#### A. RFC 3986 Syntax & Normalization
* Parses input string using strict URL parsing.
* Normalizes scheme to lowercase (`https`), strips trailing whitespace, removes non-standard control characters.
* Rejects empty hostnames, invalid characters, and malformed query strings.

#### B. Scheme & Port Whitelisting
* **Allowed Schemes:** Strictly `http` and `https`. Schemes like `file:`, `gopher:`, `ftp:`, `data:`, `javascript:`, or `blob:` trigger immediate termination (`ERR_INVALID_SCHEME`).
* **Allowed Ports:** Strictly `80` (HTTP default) and `443` (HTTPS default). Non-standard internal ports (`22`, `25`, `3306`, `5432`, `6379`, `8080`, `9200`) are blocked (`ERR_INVALID_PORT`).

#### C. Path Traversal & Dot-Segment Defense
* Rejects raw or URL-encoded path traversal tokens: `../`, `..%2f`, `%252e%252e%252f`.
* Resolves path segments canonically. If traversal attempts escape root hierarchy, rejects with `ERR_PATH_TRAVERSAL`.

#### D. Anti-Homograph & Punycode Sanitization
* Inspects domain for mixed-script spoofing (e.g., Cyrillic 'а' replacing Latin 'a').
* Converts Internationalized Domain Names (IDN) to ASCII Punycode (`xn--...`).
* Validates against blacklisted confusing character pairs and enforces normalized string comparisons.

#### E. Anti-SSRF (Server-Side Request Forgery) Defense & DNS Resolution
* Prior to dispatching network requests, asynchronously resolves the hostname via DNS.
* Inspects all returned IPv4 and IPv6 addresses against reserved, private, and internal CIDR blocks:
  * **Loopback:** `127.0.0.0/8`, `::1`
  * **Private RFC 1918:** `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
  * **Link-Local / Cloud Metadata (IMDS):** `169.254.0.0/16` (specifically blocking AWS IMDS `169.254.169.254`), `fe80::/10`
  * **Unique Local IPv6:** `fc00::/7`
  * **Broadcast / Multicast:** `224.0.0.0/4`, `ff00::/8`
  * **Carrier-Grade NAT:** `100.64.0.0/10`
* Rejection Code: `ERR_SSRF_ATTEMPT_BLOCKED`.
* **DNS Rebinding Protection & Chromium Pinning:**
  * To prevent Time-of-Check to Time-of-Use (TOCTOU) DNS rebinding attacks, the verified IP is passed to Playwright/Crawl4AI via Chromium's native command-line argument:
    ```python
    extra_args = [f'--host-resolver-rules=MAP {validated_url.host} {validated_url.resolved_ip}']
    ```
  * This guarantees that Chromium bypasses its internal DNS resolver entirely and establishes its TCP connection strictly with the pre-screened public IP.

#### F. Circular & Multiple Redirect Detection
* Safe redirect inspector traverses HTTP `HEAD` / `GET` redirects asynchronously up to a strict maximum of **5 hops**.
* Tracks every hop in an ordered `visited_urls` set.
* If a hop encounters a previously visited URL $\rightarrow$ terminates with `ERR_CIRCULAR_REDIRECT`.
* If redirect chain exceeds 5 hops $\rightarrow$ terminates with `ERR_MAX_REDIRECTS_EXCEEDED`.
* **Redirect SSRF Re-Check:** Each hop's target URL is fully re-validated against the Anti-SSRF filter. A public URL redirecting to an internal IP (e.g., `https://evil.com/` $\rightarrow$ `http://169.254.169.254/`) is intercepted and blocked before the hop is performed.

#### G. HTTP 429 & 503 Rate Limiting (`Retry-After` Adherence)
* Intercepts `HTTP 429 Too Many Requests` and `HTTP 503 Service Unavailable` responses.
* **Header Parsing:** Evaluates the `Retry-After` header supporting both delta-seconds (e.g., `Retry-After: 120`) and RFC 7231 dates (e.g., `Retry-After: Fri, 31 Dec 2026 23:59:59 GMT`).
* **Threshold Handling:**
  * If requested wait $> 300$ seconds: sets `source_configs.cool_down_until = NOW() + backoff_seconds`, halts crawling for that source immediately with `ERR_RATE_LIMITED_COOLDOWN`, and releases the distributed lock.
  * If requested wait $\le 300$ seconds: the crawler pauses for the requested duration and retries once.
* **Fallback Jittered Backoff:** If HTTP 429 is received without a `Retry-After` header, applies exponential backoff with full jitter:
  $$\text{delay} = \min(60, 2^{\text{attempt}} + \text{random}(0, 1))$$

---

## 4. Extraction Schema & ReDoS Safety Subsystem (`SchemaValidator`)

The `SchemaValidator` verifies candidate extraction templates, enforces CSS complexity limits, and provides delimiter breakout protection before execution.

> [!NOTE]
> **Separation of Concerns:** 
> 1. **Data Transformations:** Plain-text extraction (`to_clean_text`), HTML entity decoding (`&amp;` $\rightarrow$ `&`), Unicode NFKC normalization, and safe HTML rich-text filtering (`sanitize_html` via `nh3`) are **strictly deferred to the downstream Data Cleaning Pipeline (`src/modules/cleaning/`)**.
> 2. **Prompt Boundary Packaging:** XML delimiter escaping (`</untrusted_web_content>` $\rightarrow$ `&lt;/untrusted_web_content&gt;`) and system prompt engineering belong strictly to the **Scraping / Prompt Builder module (`src/modules/scraping/`)**.
> 3. The security module acts exclusively as a non-mutating gatekeeper.

### 4.1. Template Schema Safety Validator & CSS ReDoS Linter (`validate_template_schema`)
Before any AI-generated `template_schema` is saved into `scraping_templates` or executed via `JsonCssExtractionStrategy`, it must traverse a strict 4-stage validation pipeline:

#### 1. Stage A: JSON Extraction & Syntax Integrity
* Cleans raw text (removes markdown fences ` ```json ... ``` ` and whitespace).
* Executes `json.loads()`.
* On truncation or decode failure, triggers an immediate compact JSON-mode retry (`response_mime_type="application/json"`). If still malformed, aborts with `ERR_LLM_OUTPUT_TRUNCATED`.

#### 2. Stage B: Pydantic Structural Shape Enforcement
* Validates schema against strict Pydantic definitions:
  * `strict=True`: Disallows implicit type coercions (e.g. `123` to `"123"`).
  * `extra="forbid"`: Rejects hallucinated extraneous keys.
  * Ensures `fields` is a list (rejecting dict formats) with minimum field count $\ge 2$.
  * Restricts field names to canonical contracts (`title`, `discovered_url`, `deadline`, `official_apply_url`, `source_url`, etc.).
* On failure, captures exact Pydantic validation errors and triggers a targeted correction prompt (`ERR_SCHEMA_SHAPE_INVALID`).

#### 3. Stage C: CSS Selector Syntax & ReDoS Complexity Linter
* **Pre-Compilation:** Every selector must compile cleanly via `soupsieve.compile(selector)` (`ERR_SELECTOR_SYNTAX_INVALID`).
* **CSS ReDoS Complexity Constraints:**
  * **Length Bound:** `max_selector_length = 300` characters.
  * **Single-Level `:has()` Only:** Nested `:has()` (e.g., `div:has(.a:has(.b))`) is strictly banned (`max_has_depth = 1`).
  * **Combinator Cap:** Count of structural combinators (`>`, `+`, `~`, `:has`, `:not`) must be $\le 5$ per selector.
  * **No Universal Root:** Selectors starting with unanchored `*` or using `*:not(...)` are banned.
  * **Comma Branches:** Maximum 3 comma-separated alternative selector branches.
* On failure of a single selector, triggers an isolated Micro-Repair prompt for that specific field rather than regenerating the entire template.

#### 4. Stage D: Dry-Run Execution Gate with 200ms Timeout
* Evaluates candidate schema against the pruned sample HTML inside a strict execution timer:
  $$\text{execution\_time} \le 200\text{ ms}$$
* If selector evaluation takes $> 200$ms, immediately terminates with `ERR_CSS_SELECTOR_REDOS_TIMEOUT` to prevent worker freezing.
* Verifies yield: non-empty title and $\ge 1$ valid action link. On zero yield, triggers alternative sample card re-synthesis.

---

## 5. File & Attachment Verification Subsystem (`FileValidator`)

Scholarship applications frequently link to downloadable official announcement PDFs, application forms, and guidelines that are downloaded and archived to AWS S3.

### 5.1. Verification Lifecycle

```
Downloadable Document URL
           │
           ▼
[ 1. LinkValidator Check ] ──▶ SSRF / Invalid? ──▶ Abort (ERR_SSRF_ATTEMPT_BLOCKED)
           │ Valid Public URL
           ▼
[ 2. Safe Streaming Download ]
     - Stream chunks up to 25 MB limit
     - Size > 25 MB? ──▶ Abort Connection (ERR_FILE_SIZE_EXCEEDED)
           │ Stream Complete
           ▼
[ 3. Magic-Byte Signature Inspection ]
     - PDF? ──▶ Must start with `%PDF-` (\x25\x50\x44\x46\x2d)
     - DOCX / ZIP? ──▶ Must start with `PK\x03\x04`
     - Disguised EXE / Script / HTML? ──▶ Reject & Delete (ERR_MALICIOUS_FILE_TYPE)
           │ Clean Signature Verified
           ▼
[ 4. Cryptographic Key Derivation ]
     - Compute SHA256 of verified binary stream
     - Build S3 Key: `documents/{source_id}/{sha256[:16]}_{safe_filename}.pdf`
           │
           ▼
[ 5. Upload to AWS S3 ] ──▶ Record S3 Key & Checksum in Database
```

### 5.2. Magic-Byte Verification Rules
Content-Type headers provided by HTTP servers are notoriously unreliable or easily spoofed. The `FileValidator` verifies files by inspecting leading magic bytes:

| Permitted Type | Required Magic Bytes (Hex) | ASCII Representation | Allowed File Extensions |
| :--- | :--- | :--- | :--- |
| **PDF** | `25 50 44 46 2D` | `%PDF-` | `.pdf` |
| **DOCX / XLSX** | `50 4B 03 04` | `PK\x03\x04` | `.docx`, `.xlsx` |
| **JPEG Image** | `FF D8 FF` | `\xFF\xD8\xFF` | `.jpg`, `.jpeg` |
| **PNG Image** | `89 50 4E 47 0D 0A 1A 0A` | `\x89PNG\r\n\x1a\n` | `.png` |
| **WEBP Image** | `52 49 46 46 ... 57 45 42 50` | `RIFF....WEBP` | `.webp` |

**Explicitly Blocked Signatures:**
* Windows Executable / DLL (`4D 5A` / `MZ`) $\rightarrow$ `ERR_MALICIOUS_FILE_TYPE`.
* ELF Executable (`7F 45 4C 46` / `\x7fELF`) $\rightarrow$ `ERR_MALICIOUS_FILE_TYPE`.
* Shell Scripts (`23 21` / `#!`) $\rightarrow$ `ERR_MALICIOUS_FILE_TYPE`.
* HTML / XML disguising as PDF/Image (`3C 21 44 4F 43 54 59 50 45` or `3C 68 74 6D 6C`) $\rightarrow$ `ERR_MALICIOUS_FILE_TYPE`.

### 5.3. Zip-Bomb Decompression Guard (`validate_zip_archive`)
DOCX and XLSX files are zipped packages of XML files. Checking only the initial `PK\x03\x04` magic bytes is insufficient to prevent **Decompression Bomb (Zip Bomb)** attacks that exhaust server memory or disk space during downstream XML extraction:

* **Inspection Without Full Decompression:** The validator inspects member metadata from the central directory table (`zipfile.ZipFile(stream).infolist()`) before accepting or storing the file.
* **Hard Uncompressed Size Cap:** Sums the declared uncompressed size across all members. If $\sum \text{file\_size} > 50\text{ MB}$, the file is rejected with `ERR_ZIP_BOMB_DETECTED`.
* **Compression Ratio Ceiling:** Calculates the compression ratio:
  $$\text{Ratio} = \frac{\sum \text{uncompressed\_file\_size}}{\text{compressed\_stream\_bytes}}$$
  If $\text{Ratio} > 100:1$, the file is classified as a malicious decompression bomb and immediately dropped (`ERR_ZIP_BOMB_DETECTED`).

### 5.4. Image URL Verification (`validate_image_url`)
For scholarship card and hero images (`card_image_url`, `image_url`):
* URL verified via `LinkValidator`.
* Protocol strictly `http` or `https` (rejects base64 data URIs `data:image/...` to prevent database bloat and embedded payloads).
* Validates that extension and response Content-Type match recognized raster/modern formats (`jpg`, `jpeg`, `png`, `webp`, `avif`). SVG is rejected by default to prevent stored SVG-based XSS attacks unless explicitly sanitized.

---

## 6. Standard Security Error Codes

All exceptions raised by the security module inherit from `SecurityValidationError` and carry a machine-readable `error_code` stored in `source_configs.last_error`, `scrape_operations.error_summary`, or `raw_listings.extraction_errors`:

| Error Code | Category | Cause / Description |
| :--- | :--- | :--- |
| `ERR_SSRF_ATTEMPT_BLOCKED` | Network Security | URL resolves to private, loopback, link-local, or cloud metadata IP address. |
| `ERR_INVALID_SCHEME` | Link Structure | URL uses disallowed scheme (e.g. `file:`, `ftp:`, `javascript:`, `data:`). |
| `ERR_INVALID_PORT` | Network Security | URL specifies a non-standard port other than 80 or 443. |
| `ERR_PATH_TRAVERSAL` | Link Structure | URL path contains relative traversal segments (`../`, `..%2f`). |
| `ERR_HOMOGRAPH_ATTACK` | Link Security | Domain contains suspicious mixed-script characters spoofing legitimate targets. |
| `ERR_CIRCULAR_REDIRECT` | Network Traversal | Redirect loop detected during link inspection. |
| `ERR_MAX_REDIRECTS_EXCEEDED`| Network Traversal | Redirect chain exceeded 5 hops without resolving to final destination. |
| `ERR_UNTRUSTED_DOMAIN` | Domain Health | Target domain is an unregistered, dead, or parked domain. |
| `ERR_MALICIOUS_FILE_TYPE` | Attachment Safety | Attachment magic bytes indicate an executable, script, or unauthorized file type. |
| `ERR_FILE_SIZE_EXCEEDED` | Resource Protection| Downloadable attachment exceeded the 25 MB stream limit. |
| `ERR_INVALID_IMAGE_TYPE` | Media Safety | Image URL points to unsupported format, SVG script, or data URI. |
| `ERR_INVALID_TEMPLATE_SCHEMA` | Schema Safety | AI-generated extraction template contains illegal or dangerous selector constructs. |
| `ERR_SOURCE_ALREADY_LOCKED` | Concurrency Control | Source is currently locked and being scraped by another active operation. |
| `ERR_OPERATION_TIMEOUT` | Operational Ceiling | Entire scrape operation exceeded the hard execution ceiling (default: 20 min). |
| `ERR_RATE_LIMITED_COOLDOWN` | Rate Limiting | Host returned HTTP 429 with high Retry-After; source placed into cool-down. |
| `ERR_LLM_OUTPUT_TRUNCATED` | AI Format Safety | LLM response hit token boundary or returned broken JSON syntax. |
| `ERR_SCHEMA_SHAPE_INVALID` | Schema Validation | LLM JSON returned invalid schema structure (Pydantic validation failure). |
| `ERR_SELECTOR_SYNTAX_INVALID` | Selector Safety | Generated CSS selector fails compilation in soupsieve. |
| `ERR_CSS_SELECTOR_REDOS_TIMEOUT`| ReDoS Prevention | CSS selector exceeded 200ms dry-run timeout (combinator backtracking bomb). |
| `ERR_ZIP_BOMB_DETECTED` | Attachment Safety | File exceeded 100:1 compression ratio or 50MB uncompressed limit. |

---

## 7. Python Implementation Contracts & Function Signatures

### 7.1. Module Models (`src/modules/security/models.py`)

```python
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, HttpUrl

class ValidatedUrl(BaseModel):
    """Immutable representation of a thoroughly validated URL."""
    original_url: str
    canonical_url: str
    scheme: str
    host: str
    port: int
    resolved_ip: str
    is_https: bool
    redirect_hops: int = 0
    redirect_chain: List[str] = Field(default_factory=list)
    validated_at: datetime = Field(default_factory=datetime.utcnow)

class ValidatedFile(BaseModel):
    """Metadata for a downloaded and magic-byte verified file."""
    source_url: str
    mime_type: str
    file_extension: str
    file_size_bytes: int
    sha256_checksum: str
    suggested_s3_key: str
```

### 7.2. Module Exceptions (`src/modules/security/exceptions.py`)

```python
class SecurityValidationError(Exception):
    """Base exception for all security, link validation, and content sanitization errors."""
    def __init__(self, message: str, error_code: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

class SSRFAttemptBlockedError(SecurityValidationError):
    def __init__(self, host: str, ip: str):
        super().__init__(
            f"Blocked SSRF attempt to non-public destination: {host} -> {ip}",
            error_code="ERR_SSRF_ATTEMPT_BLOCKED",
            details={"host": host, "ip": ip}
        )

class CircularRedirectError(SecurityValidationError):
    def __init__(self, url: str, chain: List[str]):
        super().__init__(
            f"Circular redirect loop detected for URL: {url}",
            error_code="ERR_CIRCULAR_REDIRECT",
            details={"url": url, "chain": chain}
        )

class MaliciousFileTypeError(SecurityValidationError):
    def __init__(self, detected_magic: str, expected_types: List[str]):
        super().__init__(
            f"Disallowed or malicious file signature detected: {detected_magic}",
            error_code="ERR_MALICIOUS_FILE_TYPE",
            details={"detected_magic": detected_magic, "expected_types": expected_types}
        )
```

### 7.3. Link Validator Interface (`src/modules/security/link_validator.py`)

```python
from typing import Optional, Set
from src.modules.security.models import ValidatedUrl

class LinkValidator:
    """Universal gateway for link verification, Anti-SSRF, and redirect security."""

    MAX_REDIRECT_HOPS: int = 5
    REQUEST_TIMEOUT_SEC: float = 10.0
    ALLOWED_SCHEMES: Set[str] = {"http", "https"}
    ALLOWED_PORTS: Set[int] = {80, 443}

    @classmethod
    async def validate_url(
        cls, 
        raw_url: str, 
        allow_redirects: bool = True,
        pinned_ip: Optional[str] = None
    ) -> ValidatedUrl:
        """
        Executes full 5-step security inspection on a URL:
        1. RFC 3986 syntax and normalization
        2. Scheme and port whitelisting
        3. Anti-homograph / Punycode validation
        4. Path traversal and dot-segment check
        5. Asynchronous DNS resolution & Anti-SSRF private IP check
        6. Safe redirect traversal with loop detection and per-hop SSRF validation
        
        Returns:
            ValidatedUrl: Verified safe destination with resolved public IP.
        Raises:
            SecurityValidationError: If any security gate fails.
        """
        ...

    @classmethod
    def is_private_or_reserved_ip(cls, ip_str: str) -> bool:
        """Returns True if IP address belongs to loopback, private, link-local, or multicast blocks."""
        ...
```

### 7.4. Schema & ReDoS Validator Interface (`src/modules/security/schema_validator.py`)

```python
from typing import Any, Dict, Optional
from src.modules.security.models import TemplateSchemaValidationResult

class SchemaValidator:
    """Non-mutating gatekeeper for AI extraction template schemas and CSS ReDoS safety."""

    MAX_SELECTOR_LENGTH: int = 300
    MAX_HAS_DEPTH: int = 1
    MAX_COMBINATORS: int = 5
    DRY_RUN_TIMEOUT_SEC: float = 0.200  # 200 milliseconds

    @classmethod
    async def validate_template_schema(
        cls,
        schema_dict: Dict[str, Any],
        sample_html: Optional[str] = None
    ) -> TemplateSchemaValidationResult:
        """
        Validates AI-generated template schema:
        - Enforces Pydantic structural shape (strict=True, extra="forbid")
        - Compiles CSS selectors via soupsieve
        - Lints combinator depth and complexity limits
        - Evaluates against sample HTML within 200ms dry-run timeout
        """
        ...
```

### 7.5. File Validator Interface (`src/modules/security/file_validator.py`)

```python
from typing import AsyncIterator, Tuple
from src.modules.security.models import ValidatedFile

class FileValidator:
    """Manages secure document downloads, stream limits, and magic-byte inspection."""

    MAX_FILE_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB

    @classmethod
    async def download_and_validate_stream(
        cls, 
        file_url: str, 
        source_id: str
    ) -> Tuple[ValidatedFile, bytes]:
        """
        Streams downloadable attachment safely:
        1. Validates file URL via LinkValidator (Anti-SSRF)
        2. Streams response chunks with strict 25 MB cap (aborts immediately if exceeded)
        3. Inspects magic-byte signatures (%PDF-, PK\x03\x04, JPEG, PNG, WEBP)
        4. Rejects executables, scripts, or disguised HTML payloads
        5. Computes SHA256 checksum and builds clean suggested S3 key
        
        Returns:
            Tuple[ValidatedFile, bytes]: Verified metadata and raw file payload.
        """
        ...

    @classmethod
    def validate_image_url(cls, image_url: Optional[str]) -> Optional[str]:
        """
        Validates scholarship featured image URLs:
        - Rejects data: URIs and non-HTTP(S) schemes
        - Validates format against allowed raster extensions (jpg, png, webp, avif)
        - Rejects raw SVG to prevent stored XSS
        """
        ...
```

---

## 8. Cross-Pipeline Integration Points

The security module integrates into all existing scraping pipeline stages as an unskippable filter:

```
[ Stage 0: Source Discovery ]
  ├── LinkValidator.validate_url(admin_source_url) ──▶ Pre-flight SSRF & dead link check
  └── ContentSanitizer.wrap_untrusted_prompt(pruned_dom) ──▶ Shield prompt before LLM discovery pass

[ Stage 1: Content Extraction (Level 1 Catalog Crawl) ]
  ├── LinkValidator.validate_url(catalog_url / pagination_url) ──▶ Verify pagination before fetch
  ├── ContentSanitizer.validate_template_schema(ai_generated_schema) ──▶ Validate template before save
  ├── ContentSanitizer.to_clean_text(card_title) ──▶ Plain text in raw_listings
  └── FileValidator.validate_image_url(card_image_url) ──▶ Safe image URL

[ Stage 1: Content Extraction (Level 2 Detail Crawl) ]
  ├── LinkValidator.validate_url(raw_listing.detail_url) ──▶ Check before detail crawl
  ├── ContentSanitizer.to_clean_text(...) ──▶ Plain text for all structured grant fields
  ├── ContentSanitizer.sanitize_html(raw_description) ──▶ nh3 clean HTML in raw_grant_details
  ├── FileValidator.validate_image_url(hero_image_url) ──▶ Safe hero image
  └── FileValidator.download_and_validate_stream(pdf_url) ──▶ Magic-byte check ➔ AWS S3
```

By placing this security layer at the foundational boundary, `Afaq-AI-Service` ensures that no unverified URL is ever requested and no untrusted string or binary payload enters downstream cleaning, database storage, or user-facing interfaces.
