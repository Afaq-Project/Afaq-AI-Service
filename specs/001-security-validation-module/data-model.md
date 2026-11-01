# Data Model Specification: Security & Validation Module

**Feature**: `001-security-validation-module`  
**Created**: 2026-11-01  
**Status**: Ready for Implementation  

---

## 1. Domain Entities & Schemas (`src/modules/security/models.py`)

### 1.1. `ValidatedUrl`
Represents an immutable, verified destination URL that has passed RFC 3986 syntax validation, port/scheme filtering, Anti-SSRF inspection, and safe redirect resolution.

```python
class ValidatedUrl(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    original_url: str
    canonical_url: str
    scheme: Literal["http", "https"]
    host: str
    port: int
    resolved_ip: str
    is_https: bool
    redirect_hops: int = 0
    redirect_chain: List[str] = Field(default_factory=list)
    dns_pinned_rule: str
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

* **Validation Rules:**
  * `canonical_url` must be a valid RFC 3986 URL with lowercase scheme and trimmed whitespace.
  * `port` must be strictly `80` or `443`.
  * `resolved_ip` must not belong to private, loopback, link-local, multicast, or cloud metadata CIDRs.
  * `dns_pinned_rule` formatted as `--host-resolver-rules=MAP {host} {resolved_ip}`.

---

### 1.2. `SanitizedContent`
Result of text cleaning, HTML sanitization, or LLM prompt shielding.

```python
class SanitizedContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    original_text: str
    cleaned_text: str
    original_char_count: int
    cleaned_char_count: int
    is_modified: bool
    stripped_tags: List[str] = Field(default_factory=list)
    is_suspicious_prompt: bool = False
    detected_injection_patterns: List[str] = Field(default_factory=list)
    sanitized_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

* **Validation Rules:**
  * For structured plain text (`to_clean_text`): `cleaned_text` contains 0 markup tags and 0 control characters (`\x00` - `\x1f`), normalized via Unicode NFKC.
  * For rich HTML (`sanitize_html`): `cleaned_text` contains only whitelisted tags and safe attributes; all links enforce `rel="noopener noreferrer nofollow"`.
  * When `is_suspicious_prompt=True`, `detected_injection_patterns` documents matched trigger phrases that were defanged to `[REDACTED_SUSPICIOUS_PROMPT]`.

---

### 1.3. `FileValidationResult`
Outcome of attachment downloading and binary magic-byte inspection.

```python
class FileValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    is_valid: bool
    source_url: str
    mime_type: str
    file_extension: str
    file_size_bytes: int
    sha256_checksum: str
    suggested_s3_key: str
    magic_bytes_hex: str
    error_code: Optional[str] = None
    rejection_reason: Optional[str] = None
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

* **Validation Rules:**
  * `file_size_bytes` $\le 26,214,400$ (25 MB max stream limit).
  * `sha256_checksum` is 64 hex characters.
  * `suggested_s3_key` formatted as `documents/{source_id}/{sha256[:16]}_{safe_filename}.{ext}`.
  * If `is_valid=False`, `error_code` must match a standardized security error code (e.g. `ERR_MALICIOUS_FILE_TYPE`, `ERR_FILE_SIZE_EXCEEDED`, `ERR_ZIP_BOMB_DETECTED`).

---

### 1.4. `TemplateSchemaValidationResult`
Outcome of extraction template schema and CSS selector safety inspection.

```python
class TemplateSchemaValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    is_valid: bool
    schema_name: str
    selector_count: int
    selectors_validated: List[str]
    dry_run_latency_ms: float
    error_code: Optional[str] = None
    rejection_reason: Optional[str] = None
    failing_selector: Optional[str] = None
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

* **Validation Rules:**
  * `dry_run_latency_ms` $\le 200.0$ milliseconds.
  * Every selector in `selectors_validated` must have length $\le 300$, `:has()` nesting depth $\le 1$, and combinators $\le 5$.

---

## 2. Standard Error Code Registry

| Error Code | Category | Domain Exception |
| :--- | :--- | :--- |
| `ERR_INVALID_URL_SYNTAX` | Link Validation | `InvalidUrlSyntaxError` |
| `ERR_INVALID_SCHEME` | Link Validation | `InvalidUrlSchemeError` |
| `ERR_INVALID_PORT` | Network Security | `InvalidUrlPortError` |
| `ERR_PATH_TRAVERSAL` | Link Validation | `PathTraversalError` |
| `ERR_HOMOGRAPH_ATTACK` | Link Security | `HomographAttackError` |
| `ERR_SSRF_ATTEMPT_BLOCKED` | Network Security | `SSRFAttemptBlockedError` |
| `ERR_CIRCULAR_REDIRECT` | Network Traversal | `CircularRedirectError` |
| `ERR_MAX_REDIRECTS_EXCEEDED`| Network Traversal | `MaxRedirectsExceededError` |
| `ERR_RATE_LIMITED_COOLDOWN` | Rate Limiting | `RateLimitedCooldownError` |
| `ERR_MALICIOUS_FILE_TYPE` | Attachment Safety | `MaliciousFileTypeError` |
| `ERR_FILE_SIZE_EXCEEDED` | Resource Safety | `FileSizeExceededError` |
| `ERR_ZIP_BOMB_DETECTED` | Attachment Safety | `ZipBombDetectedError` |
| `ERR_PROMPT_INJECTION_DETECTED`| AI Safety | `PromptInjectionDetectedError` |
| `ERR_SCHEMA_SHAPE_INVALID` | Schema Safety | `SchemaShapeInvalidError` |
| `ERR_SELECTOR_SYNTAX_INVALID` | Selector Safety | `SelectorSyntaxInvalidError` |
| `ERR_CSS_SELECTOR_REDOS_TIMEOUT`| ReDoS Defense | `CssSelectorReDosTimeoutError` |
