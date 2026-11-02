# Pre-Implementation Threat Model & Security Strategy: Security & Validation Module

**Feature**: `001-security-validation-module`  
**Created**: 2026-11-01  
**Status**: Approved Gate  

---

## 1. Threat Modeling (STRIDE Matrix)

| Threat Category | Attack Vector | Target Component | Mitigating Control | Test Verification |
| :--- | :--- | :--- | :--- | :--- |
| **Spoofing** | IDN Homograph Cyrillic spoofing (e.g. `oxfоrd.edu`) | `LinkValidator` | Unicode NFKC normalization + ASCII Punycode conversion (`xn--...`) | `test_homograph_attack_rejected` |
| **Tampering** | Malformed / ReDoS CSS selectors injected into extraction templates | `SchemaValidator` | Selector length $\le 300$, `:has()` depth $\le 1$, combinators $\le 5$, 200ms execution timeout | `test_redos_selector_rejected` |
| **Repudiation** | Unaudited SSRF or attachment security incidents | Security Gateway | Structured security error codes & audit logging in `ValidatedUrl` / `FileValidationResult` | `test_security_audit_metadata` |
| **Information Disclosure** | SSRF targeting AWS IMDS (`169.254.169.254`) or VPC internal endpoints | `LinkValidator` | Pre-request DNS resolution + Reserved CIDR block inspection + Chromium DNS pinning | `test_ssrf_cloud_metadata_blocked` |
| **Denial of Service** | Infinite redirects / ReDoS CSS selectors / Zip Bomb attachments | `LinkValidator`, `SchemaValidator`, `FileValidator` | 5-hop redirect cap; 200ms selector dry-run timeout; 100:1 ratio cap / 50MB zip cap | `test_circular_redirects_halted`, `test_zip_bomb_dropped`, `test_redos_timeout` |
| **Elevation of Privilege** | Malicious executable (`.exe`, `.sh`) masquerading as application form | `FileValidator` | Pure-python binary magic-byte inspection (`%PDF-`, `PK\x03\x04`); drop PE/ELF | `test_disguised_executable_rejected` |

---

## 2. Gatekeeper Defense & Isolation Architecture

### 2.1. Pure Gatekeeper Invariant
The security module acts strictly as a non-mutating gatekeeper. It evaluates inputs (URLs, streams, schemas) against security invariants: if safe, it allows them through unmutated; if dangerous, it rejects immediately with a standardized error code.

> [!NOTE]
> **Data Cleaning Separation:** Content transformations (plain-text stripping, HTML entity decoding, Unicode NFKC normalization, and rich-text HTML sanitization via `nh3`) are **strictly deferred to the downstream Data Cleaning Pipeline (`src/modules/cleaning/`)**.

### 2.2. Prompt Sandbox Delimiter Breakout Protection
* **Delimiter Breakout Escaping:** Literal `</untrusted_web_content>` tags found within untrusted content are escaped to `&lt;/untrusted_web_content&gt;` so untrusted text cannot prematurely terminate data sandbox enclosures during downstream LLM prompt synthesis.
* **Architectural Boundary:** The security module does **not** formulate system prompts or invoke LLMs. Prompt orchestration and system instructions (priming the model to treat `<untrusted_web_content>` as passive text) belong strictly to the **scraping / LLM synthesis module** (`src/modules/scraping/`).

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
10. `test_delimiter_escaping_breakout_prevention`: Replaces `</untrusted_web_content>` with `&lt;/untrusted_web_content&gt;`.
11. `test_file_magic_bytes_pdf`: Valid `%PDF-` passes; disguised PE (`MZ`) fails with `ERR_MALICIOUS_FILE_TYPE`.
12. `test_zip_bomb_rejection`: Uncompressed $>50$ MB or ratio $>100:1$ $\rightarrow$ `ERR_ZIP_BOMB_DETECTED`.
13. `test_css_selector_redos_timeout`: Combinator backtracking selector exceeds 200ms $\rightarrow$ `ERR_CSS_SELECTOR_REDOS_TIMEOUT`.
