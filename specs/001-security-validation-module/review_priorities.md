# Human Review Priorities Matrix: Security & Validation Module

**Feature**: `001-security-validation-module`  
**Target Branch**: `feat/crawl4ai-adaptive-scraping`  
**Status**: Ready for Implementation Review  

---

## 1. Overview & Architectural Invariants

This document establishes the structured human oversight checklist and risk-weighted review priorities for pull requests implementing `001-security-validation-module`.

### Non-Negotiable Invariants:
1. **Pure Gatekeeper Boundary:** The security module is strictly non-mutating (inspection & rejection only). Any code performing HTML tag stripping, Unicode NFKC normalization, entity decoding, or LLM prompt formatting in `src/modules/security/` **MUST BE REJECTED**.
2. **Directory & File Structure:** Services must reside in `src/modules/security/services/` with the `*_service.py` suffix (`link_validator_service.py`, `file_validator_service.py`, `schema_validator_service.py`).
3. **No Performance Bounds in Tests:** Functional and unit test suites must NEVER assert maximum execution duration or latency SLAs (Constitution v2.4.0 Principle VI).
4. **Zero Live External Network Calls:** Automated tests must use deterministic mocks (`unittest.mock.patch`, `httpx.MockTransport`).

---

## 2. Review Priorities Matrix

| Severity | Risk Area | Key Files | Critical Verification Checkpoints |
| :--- | :--- | :--- | :--- |
| **P0: CRITICAL** | **Anti-SSRF & Cloud IMDS Defense** | `src/modules/security/services/link_validator_service.py` | • Ensure all private, loopback, link-local, multicast, and AWS IMDS (`169.254.169.254`) CIDRs are blocked.<br>• Verify DNS resolution occurs *before* any socket connection.<br>• Ensure Chromium DNS pinning rule (`--host-resolver-rules=MAP <host> <ip>`) uses the verified public IP. |
| **P0: CRITICAL** | **Decompression Bomb Guard (Zip-Bomb)** | `src/modules/security/services/file_validator_service.py` | • Verify zip files are inspected via `ZipFile.infolist()` metadata without extracting file bytes to disk or RAM.<br>• Enforce strict 100:1 compression ratio cap and 50 MB total uncompressed size ceiling. |
| **P0: CRITICAL** | **Binary Executable Rejection** | `src/modules/security/services/file_validator_service.py` | • Ensure magic byte inspection strictly verifies PDF (`%PDF-`), images, and office documents.<br>• Unconditional rejection of Windows PE (`MZ`), Linux ELF (`\x7fELF`), and script headers (`#!`). |
| **P1: HIGH** | **CSS ReDoS Catastrophic Backtracking** | `src/modules/security/services/schema_validator_service.py` | • Verify static linter rejects nested `:has()` depth $>1$ and combinator count $>5$.<br>• Enforce dry-run evaluation timeout guard (200ms) with `asyncio.wait_for`. |
| **P1: HIGH** | **Redirect Loop & Traversal Cap** | `src/modules/security/services/link_validator_service.py` | • Ensure visited URLs set detects circular redirect loops immediately.<br>• Strictly cap redirect chain to 5 hops.<br>• **Mandatory:** Re-validate Anti-SSRF filter on *every single redirect hop*. |
| **P1: HIGH** | **RFC 3986 Canonicalization & Whitelisting** | `src/modules/security/services/link_validator_service.py` | • Only `http` and `https` schemes permitted.<br>• Only ports `80` and `443` permitted.<br>• Unresolvable path traversal tokens (`../`, `..%2f`) rejected. |
| **P2: MEDIUM** | **S3 Key Derivation & Filename Sanitization** | `src/modules/security/services/file_validator_service.py` | • Parse `Content-Disposition` header safely with path traversal removal.<br>• Deterministic fallback to `{sha256[:16]}.{detected_ext}` if filename is missing or dynamic. |
| **P2: MEDIUM** | **IDN Homograph & Cyrillic Spoofing** | `src/modules/security/services/link_validator_service.py` | • Convert domain names to Punycode (`idna.encode`) and detect mixed-script confusable characters. |
| **P2: MEDIUM** | **HTTP 429/503 Rate Limit Backoff** | `src/modules/security/services/link_validator_service.py` | • Parse `Retry-After` header correctly (seconds or HTTP date).<br>• Trigger `RateLimitedCooldownError` when wait time exceeds 300 seconds. |
| **P3: LOW** | **Diagnostic API Routes & Exports** | `src/api/routes/v1/security.py`, `src/modules/security/__init__.py` | • Ensure diagnostic endpoint is thin and delegates purely to `LinkValidatorService`.<br>• Verify clean public exports without leaking private internal helpers. |

---

## 3. Reviewer Checklist

Before approving any PR for this module, the reviewer must check off the following items:

- [ ] **Architecture Check:** Does the code avoid any data transformation (stripping HTML, normalizing Unicode, decoding entities)?
- [ ] **Module Boundaries:** Are `LinkValidatorService`, `FileValidatorService`, and `SchemaValidatorService` in `src/modules/security/services/`?
- [ ] **Test Separation:** Are unit tests in `tests/unit/modules/security/` and integration tests in `tests/integration/modules/security/`?
- [ ] **No Execution Time Assertions:** Are all functional/unit test assertions free of runtime execution duration bounds (e.g. `assert elapsed < 0.2`)?
- [ ] **Pre-commit Quality Gates:** Have SonarQube, ArchUnit, KG-ARCHMAP, Enola, Gitleaks, and Trivy passed with 0 critical findings?
