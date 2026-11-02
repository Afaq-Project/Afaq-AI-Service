# Feature Specification: Security, Link Validation & Content Sanitization Module

**Feature Directory**: `specs/001-security-validation-module`  
**Feature Branch**: `feat/crawl4ai-adaptive-scraping`  
**Created**: 2026-11-01  
**Status**: Ready for Review  
**Input**: User description: "docs/reports/security_and_validation_module Alright, let’s move on to building the modules. We will start with the inspection and security module, as it will be used extensively later on in the pipeline; therefore, it must be built first. Now, create the module specifications and read through its documentation files."

---

## Clarifications

### Session 2026-11-01
- Q: Should the LinkValidator accept an optional base URL to automatically resolve relative paths into canonical absolute URLs, or should it require callers to provide pre-resolved absolute URLs? → A: Option A: Accept an optional `base_url` parameter; if provided and `raw_url` is relative, resolve it canonically via RFC 3986 relative reference resolution before validating; if omitted and `raw_url` is relative, reject with `ERR_INVALID_SCHEME`.
- Q: When the content sanitizer detects high-confidence prompt injection trigger phrases in scraped web content, should the pipeline immediately abort the listing extraction with an error, or should it neutralize the phrases and continue extraction with an audit flag? → A: Option A: Neutralize & Flag (Resilient Extraction): Redact or defang high-confidence trigger patterns (replacing with `[REDACTED_SUSPICIOUS_PROMPT]`), escape closing delimiter tags (`&lt;/untrusted_web_content&gt;`), set `is_suspicious_prompt=True` in validation metadata, and encapsulate within `<untrusted_web_content>` XML boundaries without aborting extraction. (Note: LLM system prompt formulation and priming belong strictly to the downstream scraping module, not the security module).
- Q: How should the FileValidator generate the S3 object key when a downloadable document's URL path lacks a recognizable filename or uses dynamic query parameters (e.g., `/download.php?id=9481`)? → A: Option A: Content-Disposition with Hash Fallback: Sanitize filename from `Content-Disposition` header; if missing, fall back to `{sha256[:16]}.{detected_ext}` based on verified magic bytes.

---

## 1. User Scenarios & Testing *(mandatory)*

### User Story 1 - Safe External URL Inspection & Anti-SSRF Defense (Priority: P1)

As an autonomous scraping pipeline worker,  
I want to rigorously inspect, normalize, and verify every external URL before initiating any HTTP or headless browser request,  
So that our infrastructure is completely protected against Server-Side Request Forgery (SSRF), internal network scanning, cloud metadata theft, redirect loops, and malicious port querying.

* **Why this priority**: Crawling arbitrary external web pages presents an immediate existential risk of leaking AWS IMDS credentials (`169.254.169.254`) or scanning private VPC services. This gate must exist before any crawling occurs.
* **Independent Test**: Can be independently tested by passing internal IPs (`127.0.0.1`, `10.0.0.1`, `169.254.169.254`), non-standard ports (`22`, `6379`), and circular redirect URLs to `LinkValidator`, asserting immediate rejection with standardized error codes without dispatching unsafe requests.

**Acceptance Scenarios**:
1. **Given** a URL pointing to AWS metadata (`http://169.254.169.254/latest/meta-data/`) or a loopback address (`http://127.0.0.1:8000`), **When** the URL is processed by the validator, **Then** it is rejected immediately with `ERR_SSRF_ATTEMPT_BLOCKED` and no network request is initiated.
2. **Given** a publicly resolvable domain that attempts a DNS rebinding attack, **When** DNS resolution occurs, **Then** the resolved IP is captured for Chromium DNS pinning (`--host-resolver-rules`), ensuring the browser connects exclusively to the verified public IP.
3. **Given** an external URL that redirects through a loop or exceeds 5 hops, **When** the redirect chain is traversed, **Then** the operation aborts with `ERR_CIRCULAR_REDIRECT` or `ERR_MAX_REDIRECTS_EXCEEDED`.
4. **Given** a legitimate public educational scholarship portal URL (`https://scholarships.example.edu/apply`), **When** validated, **Then** it returns an immutable `ValidatedUrl` object containing the canonicalized URL, scheme, host, port, and resolved IP.

---

### User Story 2 - AI Template Schema & CSS ReDoS Shielding (Priority: P1)

As an adaptive scraping orchestrator,  
I want to validate AI-generated extraction schemas and verify CSS selectors against catastrophic backtracking (ReDoS),  
So that corrupt schemas or complex nested selectors cannot stall or freeze crawler worker threads.

* **Why this priority**: AI models occasionally generate overly complex or recursive CSS selectors (e.g. deeply nested `:has()` combinators) that trigger exponential backtracking in CSS engines, freezing worker threads.
* **Independent Test**: Can be tested independently by feeding valid schemas, malformed JSON, and pathological backtracking selectors into `SchemaValidator`, ensuring schemas pass shape checks and pathological selectors fail the 200ms timeout or complexity rules.

**Acceptance Scenarios**:
1. **Given** an AI-generated template schema, **When** evaluated, **Then** it validates JSON syntax, verifies Pydantic structural requirements (`strict=True`, `extra="forbid"`, minimum 2 fields), and compiles all CSS selectors.
2. **Given** a CSS selector with nested `:has()` structures, $>5$ structural combinators, or execution exceeding 200 milliseconds against sample DOMs, **When** analyzed, **Then** the validator rejects it with `ERR_SELECTOR_SYNTAX_INVALID` or `ERR_CSS_SELECTOR_REDOS_TIMEOUT`.

---

### User Story 3 - Downloadable Document & Attachment Verification (Priority: P2)

As a document ingestion pipeline handler,  
I want to verify file size limits, inspect true binary magic bytes, and guard against zip bombs before uploading attachments to AWS S3,  
So that disguised malware, executable scripts, and resource-exhaustion archives are rejected before persistence.

* **Why this priority**: Official grant guidelines frequently link to downloadable PDFs and forms. Attackers can upload disguised executables or decompression bombs that crash workers.
* **Independent Test**: Can be tested independently by providing mock file streams containing PDF signatures, disguised PE/ELF headers, and high-ratio zip archives to `FileValidator`, asserting acceptance or rejection based strictly on byte inspections.

**Acceptance Scenarios**:
1. **Given** a downloadable document stream claiming to be a PDF, **When** inspected by `validate_file_stream`, **Then** the validator verifies the leading magic bytes (`%PDF-`), rejecting files with mismatched or executable headers (`4D 5A`, `7F 45 4C 46`) with `ERR_MALICIOUS_FILE_TYPE`.
2. **Given** a file stream exceeding the maximum allowed size (25 MB), **When** downloaded, **Then** the stream terminates immediately with `ERR_FILE_SIZE_EXCEEDED` to prevent memory and bandwidth exhaustion.
3. **Given** a zipped archive (DOCX/XLSX) with a compression ratio exceeding 100:1 or an uncompressed footprint exceeding 50 MB, **When** checked, **Then** it is rejected as a decompression bomb with `ERR_ZIP_BOMB_DETECTED`.

---

### User Story 4 - Prompt Sandbox Delimiter Breakout Protection (Priority: P2)

As an adaptive scraping pipeline coordinator,  
I want to escape XML delimiter closing tags from untrusted scraped content,  
So that raw text cannot prematurely close `<untrusted_web_content>` sandbox boundaries when packaged for downstream LLM prompt synthesis.

* **Why this priority**: Attackers can embed literal `</untrusted_web_content>` tags into target DOMs to break out of data enclosures during AI extraction.
* **Independent Test**: Can be tested independently by passing strings containing `</untrusted_web_content>` into `escape_prompt_delimiters`, asserting conversion to `&lt;/untrusted_web_content&gt;`.

**Acceptance Scenarios**:
1. **Given** raw external HTML submitted for LLM prompt synthesis containing `</untrusted_web_content>`, **When** passed through `escape_prompt_delimiters`, **Then** the closing tag is escaped to `&lt;/untrusted_web_content&gt;` without altering other content.

---

### Edge Cases

* **DNS Rebinding Attacks (TOCTOU):** An attacker configures a domain that resolves to a public IP on initial DNS lookup, but instantly resolves to `127.0.0.1` or `169.254.169.254` during the HTTP request. Handled by Chromium DNS pinning (`--host-resolver-rules=MAP <host> <verified-ip>`).
* **IDN Homograph Spoofing:** Domains using mixed Cyrillic/Latin scripts (e.g., `oxfоrd.edu` where 'о' is Cyrillic) are converted to ASCII Punycode (`xn--...`) and validated against confusables.
* **HTTP 429 / 503 Rate Limiting:** When remote servers respond with 429/503 and a `Retry-After` header $>300$ seconds, the validator flags the source for cool-down (`ERR_RATE_LIMITED_COOLDOWN`) and releases the distributed lock.
* **Disguised Script Extensions:** Files named `form.pdf` containing HTML/JavaScript or executable headers are rejected via magic-byte inspection.
* **Delimiter Breakout Injection:** Raw content containing literal `</untrusted_web_content>` closing tags is escaped to prevent sandbox breakouts.

---

## 2. Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: System MUST parse all URLs strictly according to RFC 3986, normalizing schemes to lowercase, stripping trailing whitespace, and rejecting syntactically malformed URLs with `ERR_INVALID_URL_SYNTAX`.
* **FR-002**: System MUST permit only `http` and `https` schemes, and strictly ports `80` and `443`. All other schemes and ports MUST be rejected with `ERR_INVALID_SCHEME` or `ERR_INVALID_PORT`.
* **FR-003**: System MUST reject raw and URL-encoded path traversal tokens (`../`, `..%2f`) with `ERR_PATH_TRAVERSAL`.
* **FR-004**: System MUST asynchronously resolve hostnames to IP addresses prior to connection and block all private, loopback, link-local, multicast, and cloud metadata CIDR ranges with `ERR_SSRF_ATTEMPT_BLOCKED`.
* **FR-005**: System MUST produce Chromium-compatible host resolver mapping strings (`--host-resolver-rules`) for verified public IPs to prevent DNS rebinding.
* **FR-006**: System MUST traverse HTTP redirects safely up to a maximum of 5 hops, detecting circular references (`ERR_CIRCULAR_REDIRECT`) and re-validating each hop against the Anti-SSRF filter.
* **FR-007**: System MUST parse `Retry-After` headers on HTTP 429/503 responses, enforcing cool-down periods when wait times exceed 300 seconds.
* **FR-008**: System MUST escape any literal `</untrusted_web_content>` tags found within untrusted content (`&lt;/untrusted_web_content&gt;`) to prevent delimiter breakout attacks.
* **FR-009**: System MUST validate AI-generated extraction schemas against Pydantic models with `strict=True` and `extra="forbid"`.
* **FR-010**: System MUST lint CSS selectors against ReDoS complexity limits (max length 300 chars, max 1 `:has()` depth, max 5 combinators) and enforce a strict 200ms dry-run execution timeout.
* **FR-011**: System MUST stream-download attachments with a strict 25 MB ceiling, aborting downloads exceeding this limit with `ERR_FILE_SIZE_EXCEEDED`.
* **FR-012**: System MUST verify true binary magic bytes for allowed attachment types (PDF `%PDF-`, DOCX/XLSX `PK\x03\x04`, JPEG, PNG, WEBP) and unconditionally reject executable signatures (PE `MZ`, ELF, shell scripts).
* **FR-013**: System MUST inspect zip-based archives without full decompression, enforcing a 100:1 compression ratio cap and a 50 MB total uncompressed size limit (`ERR_ZIP_BOMB_DETECTED`).
* **FR-014**: System MUST accept an optional `base_url` parameter in URL validation; if provided and the target URL is a relative reference, resolve it canonically using RFC 3986 reference resolution before security inspection. If omitted and the target URL is relative, reject immediately with `ERR_INVALID_SCHEME`.
* **FR-015**: System MUST derive the suggested S3 object key by sanitizing the filename extracted from the URL path or HTTP `Content-Disposition` header; if neither is present or valid, fall back deterministically to `{sha256[:16]}.{detected_ext}` based on verified magic bytes.

### Key Entities

* **ValidatedUrl**: Represents an immutable, thoroughly verified URL containing `original_url`, `canonical_url`, `scheme`, `host`, `port`, `resolved_ip`, `dns_pinned_rule`, and `redirect_history`.
* **FileValidationResult**: Result of attachment inspection containing `is_valid`, `mime_type`, `magic_bytes_detected`, `file_size_bytes`, `sha256_checksum`, `safe_s3_key`, and optional `rejection_reason`.
* **TemplateSchemaValidationResult**: Outcome of extraction schema validation containing `is_valid`, `validated_schema`, `selector_count`, `dry_run_latency_ms`, and `rejection_reason`.

### Non-Goals & Out-of-Scope Boundaries

* **No Content Mutation or Data Cleaning:** The security module is strictly a non-mutating gatekeeper. It does not strip tags, decode entities, normalize Unicode, or parse values; these transformations are deferred to the downstream Data Cleaning Pipeline (`src/modules/cleaning/`).
* **No Direct Database Persistence:** The security module does not read or write directly to Postgres or Prisma tables. It returns pure domain models and validation results to calling services.
* **No Browser Engine Lifecycle Management:** The module does not manage Playwright browser pools or launch processes; it provides safe arguments and validation guarantees to the crawling engine.
* **No Paywall / CAPTCHA Bypassing:** The module operates strictly within public domain data bounds, adhering to legal and architectural non-bypass principles.
* **No LLM System Prompting / Prompt Engineering:** The security module does not author or execute LLM system prompts. System instruction priming belongs strictly to the downstream scraping / synthesis module (`src/modules/scraping/`).

---

## 3. Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: 100% of tested URLs resolving to private, loopback, or cloud metadata CIDRs (including AWS IMDS `169.254.169.254`) are intercepted and blocked before any network connection is initiated.
* **SC-002**: 100% of disguised executables, ELF binaries, and scripts are rejected based on magic-byte inspection regardless of spoofed file extensions.
* **SC-003**: 100% of path traversal tokens and non-whitelisted ports are rejected immediately with standard error codes.
* **SC-004**: Zero CSS selectors exceeding 200ms execution latency or exceeding ReDoS complexity budgets are accepted into active scraping templates.
* **SC-005**: Synchronous in-memory validation latency is under 5ms, and DNS/redirect probes complete under 500ms.
* **SC-006**: Complete test coverage of all defined security error codes across unit and integration suites.

---

## 4. Assumptions

* **DNS Environment:** The execution environment has access to DNS resolvers capable of resolving standard public hostnames and returning A/AAAA records.
* **Parsing Dependencies:** High-performance libraries (`nh3`, `soupsieve`, `pydantic`) are installed and functional in the Python runtime.
* **Network Isolation:** Crawling workers will receive Chromium CLI arguments (`--host-resolver-rules`) generated by this module to enforce DNS pinning.
