# Interfaces & Endpoint Contracts: Security & Validation Module

**Feature**: `001-security-validation-module`  
**Created**: 2026-11-01  
**Status**: Ready for Implementation  

---

## 1. Internal Module Python Contracts (`src/modules/security/services/`)

The security module serves as the internal universal gateway. All crawling workers, normalizers, and template synthesizers call these service methods from `src/modules/security/services/`:

### 1.1. `LinkValidatorService.validate_url`
* **Signature:**
  ```python
  @classmethod
  async def validate_url(
      cls,
      raw_url: str,
      base_url: Optional[str] = None,
      allow_redirects: bool = True,
      pinned_ip: Optional[str] = None
  ) -> ValidatedUrl:
  ```
* **Inputs:**
  * `raw_url` (`str`): Target URL string (absolute or relative).
  * `base_url` (`Optional[str]`): Optional parent URL for RFC 3986 relative reference resolution.
  * `allow_redirects` (`bool`, default `True`): Whether to follow HTTP redirects up to 5 hops.
  * `pinned_ip` (`Optional[str]`): Pre-verified IP address if bypassing DNS lookup.
* **Outputs:**
  * Returns: `ValidatedUrl` instance.
* **Error Catalog:**
  * `InvalidUrlSyntaxError` (`ERR_INVALID_URL_SYNTAX`) on malformed URL.
  * `InvalidUrlSchemeError` (`ERR_INVALID_SCHEME`) on schemes other than `http`/`https` (or missing scheme when `base_url` is omitted).
  * `InvalidUrlPortError` (`ERR_INVALID_PORT`) on ports other than `80` or `443`.
  * `PathTraversalError` (`ERR_PATH_TRAVERSAL`) on unresolvable `../` traversal attempts.
  * `HomographAttackError` (`ERR_HOMOGRAPH_ATTACK`) on deceptive mixed-script domain names.
  * `SSRFAttemptBlockedError` (`ERR_SSRF_ATTEMPT_BLOCKED`) on private, loopback, or cloud metadata CIDRs.
  * `CircularRedirectError` (`ERR_CIRCULAR_REDIRECT`) on loop detection.
  * `MaxRedirectsExceededError` (`ERR_MAX_REDIRECTS_EXCEEDED`) on chains $>5$ hops.
  * `RateLimitedCooldownError` (`ERR_RATE_LIMITED_COOLDOWN`) on HTTP 429/503 with Retry-After $>300$s.

---

### 1.2. `FileValidatorService.validate_stream`
* **Signature:**
  ```python
  @staticmethod
  def validate_stream(
      stream: BinaryIO,
      filename: Optional[str] = None,
      source_id: str = "default",
      content_disposition: Optional[str] = None
  ) -> FileValidationResult:
  ```
* **Inputs:**
  * `stream` (`BinaryIO`): Downloaded binary byte stream.
  * `filename` (`Optional[str]`): Filename from URL path.
  * `source_id` (`str`): Source identifier for S3 key prefixing.
  * `content_disposition` (`Optional[str]`): HTTP Content-Disposition header.
* **Outputs:**
  * Returns: `FileValidationResult`.
* **Error Catalog:**
  * `MaliciousFileTypeError` (`ERR_MALICIOUS_FILE_TYPE`) on PE, ELF, script signatures.
  * `FileSizeExceededError` (`ERR_FILE_SIZE_EXCEEDED`) on size $> 25$ MB.
  * `ZipBombDetectedError` (`ERR_ZIP_BOMB_DETECTED`) on compression ratio $> 100:1$ or uncompressed size $> 50$ MB.

---

### 1.3. `SchemaValidatorService.validate_template_schema`
* **Signature:**
  ```python
  @classmethod
  async def validate_template_schema(
      cls,
      schema_dict: Dict[str, Any],
      sample_html: Optional[str] = None
  ) -> TemplateSchemaValidationResult:
  ```
* **Inputs:**
  * `schema_dict` (`Dict[str, Any]`): Extraction template schema.
  * `sample_html` (`Optional[str]`): Representative HTML fragment for dry-run timeout evaluation.
* **Outputs:**
  * Returns: `TemplateSchemaValidationResult`.
* **Error Catalog:**
  * `SchemaShapeInvalidError` (`ERR_SCHEMA_SHAPE_INVALID`) on Pydantic shape failure.
  * `SelectorSyntaxInvalidError` (`ERR_SELECTOR_SYNTAX_INVALID`) on soupsieve compilation failure.
  * `CssSelectorReDosTimeoutError` (`ERR_CSS_SELECTOR_REDOS_TIMEOUT`) on evaluation latency $> 200$ms.

---

> [!NOTE]
> **Separation of Concerns:** 
> 1. **Content Transformations:** Functions such as `to_clean_text`, entity decoding, Unicode NFKC normalization, and `sanitize_html` are **strictly deferred to the downstream Data Cleaning Pipeline (`src/modules/cleaning/`)**.
> 2. **Prompt Construction & Delimiter Escaping:** XML boundary wrapping and tag escaping (`</untrusted_web_content>` $\rightarrow$ `&lt;/untrusted_web_content&gt;`) belong strictly to the **Scraping / Prompt Builder module (`src/modules/scraping/`)**.
> 3. The Security Module provides exclusively non-mutating validation and security screening (`LinkValidatorService`, `FileValidatorService`, `SchemaValidatorService`).

---

## 2. Optional Diagnostic API Endpoints (Admin / Integration)

To facilitate integration testing and external verification, the module exposes optional internal API diagnostic endpoints under `/api/v1/security/`:

### 2.1. Inspect URL Endpoint
* **Route:** `POST /api/v1/security/inspect-url`
* **Auth:** API Key Header (`X-API-Key`)
* **Request Body:**
  ```json
  {
    "url": "https://scholarships.example.edu/grant/101",
    "base_url": null,
    "allow_redirects": true
  }
  ```
* **Success Response (`200 OK`):**
  ```json
  {
    "status": "success",
    "data": {
      "original_url": "https://scholarships.example.edu/grant/101",
      "canonical_url": "https://scholarships.example.edu/grant/101",
      "scheme": "https",
      "host": "scholarships.example.edu",
      "port": 443,
      "resolved_ip": "93.184.216.34",
      "is_https": true,
      "redirect_hops": 0,
      "redirect_chain": [],
      "dns_pinned_rule": "--host-resolver-rules=MAP scholarships.example.edu 93.184.216.34"
    },
    "message": "URL verified as safe."
  }
  ```
* **Error Responses:**
  * `422 Unprocessable Entity`: Input schema validation failed.
  * `400 Bad Request`: `{"detail": "Blocked SSRF attempt to non-public destination: 169.254.169.254"}` (`ERR_SSRF_ATTEMPT_BLOCKED`).
