# Pre-Implementation Threat Model & Security Strategy: Security & Validation Module

**Feature**: `001-security-validation-module`  
**Created**: 2026-11-01  
**Status**: Approved Gate  

---

## 1. Threat Modeling (STRIDE Matrix)

| Threat Category | Attack Vector | Target Component | Mitigating Control | Test Verification |
| :--- | :--- | :--- | :--- | :--- |
| **Spoofing** | IDN Homograph Cyrillic spoofing (e.g. `oxfоrd.edu`) | `LinkValidator` | Unicode NFKC normalization + ASCII Punycode conversion (`xn--...`) | `test_homograph_attack_rejected` |
| **Tampering** | Stored XSS via scraped grant description | `ContentSanitizer` | Rust-backed `nh3` AST parser; strict tag/attr whitelist; strip scripts/styles | `test_xss_payloads_stripped` |
| **Repudiation** | Unaudited SSRF or prompt injection incidents | Security Gateway | Structured security error codes & audit logging in `SanitizedContent` / `ValidatedUrl` | `test_security_audit_metadata` |
| **Information Disclosure** | SSRF targeting AWS IMDS (`169.254.169.254`) or VPC internal endpoints | `LinkValidator` | Pre-request DNS resolution + Reserved CIDR block inspection + Chromium DNS pinning | `test_ssrf_cloud_metadata_blocked` |
| **Denial of Service** | Infinite redirects / ReDoS CSS selectors / Zip Bomb attachments | `LinkValidator`, `ContentSanitizer`, `FileValidator` | 5-hop redirect cap; 200ms selector dry-run timeout; 100:1 ratio cap / 50MB zip cap | `test_circular_redirects_halted`, `test_zip_bomb_dropped`, `test_redos_timeout` |
| **Elevation of Privilege** | Malicious executable (`.exe`, `.sh`) masquerading as application form | `FileValidator` | Pure-python binary magic-byte inspection (`%PDF-`, `PK\x03\x04`); drop PE/ELF | `test_disguised_executable_rejected` |

---

## 2. Sanitization & Defanging Architecture

### 2.1. Ingestion Isolation Rule
No string, URL, or byte stream from an external website may be persisted into Postgres or dispatched to an LLM prompt without traversing this module.

### 2.2. Dual Sanitization Pipeline
1. **Structured Metadata (Plain-Text Only):**
   * Fields: `title`, `provider`, `host_country`, `amount`, `deadline`, `degree`, `field_of_study`.
   * Engine: `ContentSanitizer.to_clean_text()`.
   * Transformation: Strip tags $\rightarrow$ decode entities $\rightarrow$ delete control characters (`\x00` - `\x1f`) $\rightarrow$ Unicode NFKC normalization $\rightarrow$ whitespace collapse.
2. **Formatted Descriptions (Rich-Text Safe HTML):**
   * Fields: `description_html`, `eligibility_html`, `benefits_html`, `application_process_html`.
   * Engine: `ContentSanitizer.sanitize_html()` using `nh3`.
   * Permitted Tags: `p`, `br`, `b`, `strong`, `i`, `em`, `u`, `ul`, `ol`, `li`, `h3`, `h4`, `h5`, `blockquote`, `table`, `thead`, `tbody`, `tr`, `th`, `td`.
   * Strictly Prohibited & Stripped: `script`, `style`, `iframe`, `frame`, `object`, `embed`, `applet`, `svg`, `math`, `form`, `input`, `button`, `meta`, `link`.
   * Link Hardening: Links receive `rel="noopener noreferrer nofollow"` and `target="_blank"`.

### 2.3. Prompt Shielding & Adversarial Instruction Defanging
* Boundary Tags: Raw DOMs submitted to LLMs are wrapped inside `<untrusted_web_content origin_domain="{domain}" hash="{sha256}">...</untrusted_web_content>`.
* Trigger Defanging: High-confidence prompt injection phrases (e.g. `"ignore previous instructions"`, `"system override"`) are defanged to `[REDACTED_SUSPICIOUS_PROMPT]` and flagged via `is_suspicious_prompt=True` to preserve valid educational data while eliminating execution risk.

---

## 3. Negative Security Test Suite (Pre-Code Definition)

The following automated negative test cases must be authored and passing before feature code is accepted:

1. `test_ssrf_blocks_imds_ipv4`: `http://169.254.169.254/latest/meta-data/` $\rightarrow$ `ERR_SSRF_ATTEMPT_BLOCKED`.
2. `test_ssrf_blocks_imds_ipv6`: `http://[fd00:ec2::254]/` $\rightarrow$ `ERR_SSRF_ATTEMPT_BLOCKED`.
3. `test_ssrf_blocks_loopback`: `http://127.0.0.1:8000/` and `http://localhost/` $\rightarrow$ `ERR_SSRF_ATTEMPT_BLOCKED`.
4. `test_ssrf_blocks_private_rfc1918`: `10.0.0.1`, `172.16.0.1`, `192.168.1.1` $\rightarrow$ `ERR_SSRF_ATTEMPT_BLOCKED`.
5. `test_dns_rebinding_pinning_rule`: Verifies `--host-resolver-rules` contains pre-screened public IP.
6. `test_path_traversal_detection`: `https://example.com/../../etc/passwd` $\rightarrow$ `ERR_PATH_TRAVERSAL`.
7. `test_port_whitelist`: Ports `22`, `25`, `6379`, `8080`, `9200` $\rightarrow$ `ERR_INVALID_PORT`.
8. `test_circular_redirect`: Redirect loop `A -> B -> A` $\rightarrow$ `ERR_CIRCULAR_REDIRECT`.
9. `test_redirect_ssrf_pivot`: `https://public.com/redir` redirecting to `169.254.169.254` $\rightarrow$ `ERR_SSRF_ATTEMPT_BLOCKED`.
10. `test_html_stripping_xss`: `<script>alert(1)</script><img src=x onerror=alert(1)>` $\rightarrow$ clean text.
11. `test_nh3_html_sanitization`: Preserves safe tags, strips event handlers and `javascript:` URIs.
12. `test_prompt_injection_redaction`: Replaces trigger phrases and sets `is_suspicious_prompt=True`.
13. `test_file_magic_bytes_pdf`: Valid `%PDF-` passes; disguised PE (`MZ`) fails with `ERR_MALICIOUS_FILE_TYPE`.
14. `test_zip_bomb_rejection`: Uncompressed $>50$ MB or ratio $>100:1$ $\rightarrow$ `ERR_ZIP_BOMB_DETECTED`.
15. `test_css_selector_redos_timeout`: Combinator backtracking selector exceeds 200ms $\rightarrow$ `ERR_CSS_SELECTOR_REDOS_TIMEOUT`.
