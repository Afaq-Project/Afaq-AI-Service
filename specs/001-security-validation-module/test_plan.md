# Test-Driven Development (TDD) Test Plan: Security & Validation Module

**Feature**: `001-security-validation-module`  
**Created**: 2026-11-01  
**Status**: Approved Gate (TDD Red Phase Ready)  

---

## 1. Traceability Matrix: 1-to-1 Use Case to Test Case Mapping

Per Constitution v2.1.0 Principle II & III, every single scenario in [`use_cases.md`](use_cases.md) maps 1-to-1 to a deterministic test case. All tests must be authored **before** implementation code (Red phase):

| Use Case ID | Scenario Name | Test Target File | Test Function Name | Verification Gate |
| :--- | :--- | :--- | :--- | :--- |
| **UC-01** | Standard Public Educational Link Validation | `tests/modules/security/test_link_validator.py` | `test_valid_public_https_url_resolves` | Unit |
| **UC-02** | AI Extraction Template Schema Dry-Run Verification | `tests/modules/security/test_schema_validator.py`| `test_validate_template_schema_success` | Unit |
| **UC-03** | Official Scholarship PDF Attachment Inspection | `tests/modules/security/test_file_validator.py` | `test_valid_pdf_magic_bytes_and_s3_key` | Unit |
| **UC-04** | Relative URL Reference Resolution (`FR-013`) | `tests/modules/security/test_link_validator.py` | `test_relative_url_resolves_with_base_url` | Unit |
| **UC-05** | IDN Homograph Cyrillic Domain Spoofing | `tests/modules/security/test_link_validator.py` | `test_homograph_cyrillic_spoofing_rejected` | Unit |
| **UC-06** | S3 Naming with Content-Disposition Fallback (`FR-014`)| `tests/modules/security/test_file_validator.py` | `test_content_disposition_s3_naming_fallback` | Unit |
| **UC-07** | Multi-Hop Safe Redirect Chain ($\le 5$ Hops) | `tests/modules/security/test_link_validator.py` | `test_safe_redirect_chain_traversal` | Integration |
| **UC-08** | Direct SSRF Against AWS Cloud Metadata & Loopback | `tests/modules/security/test_security_threats.py` | `test_ssrf_blocks_imds_and_loopback` | Security Gate |
| **UC-09** | Circular Redirect Loop Trap | `tests/modules/security/test_link_validator.py` | `test_circular_redirect_loop_detected` | Unit |
| **UC-10** | Deep Redirect Chain Exceeding 5 Hops | `tests/modules/security/test_link_validator.py` | `test_max_redirects_exceeded_error` | Unit |
| **UC-11** | Redirect-Based SSRF Pivot | `tests/modules/security/test_security_threats.py` | `test_redirect_ssrf_pivot_intercepted` | Security Gate |
| **UC-12** | Disguised Windows Executable Attachment | `tests/modules/security/test_security_threats.py` | `test_disguised_executable_rejected` | Security Gate |
| **UC-13** | High-Ratio Zip Bomb Decompression Attack | `tests/modules/security/test_security_threats.py` | `test_zip_bomb_decompression_guard` | Security Gate |
| **UC-14** | Pathological CSS Selector Exponential Backtracking (ReDoS) | `tests/modules/security/test_security_threats.py` | `test_css_selector_redos_timeout` | Security Gate |
| **UC-15** | Non-Standard Internal Port Querying | `tests/modules/security/test_link_validator.py` | `test_non_standard_ports_rejected` | Unit |
| **UC-16** | Disallowed Schemes (`file:`, `gopher:`, `data:`) | `tests/modules/security/test_link_validator.py` | `test_disallowed_schemes_rejected` | Unit |
| **UC-17** | HTTP 429 Rate Limiting with High Retry-After | `tests/modules/security/test_link_validator.py` | `test_http_429_retry_after_cooldown` | Integration |

---

## 2. Test Execution Tiers & Performance Budgets

* **Execution Speed:** Entire security test suite must execute in under **4 seconds** locally.
* **Determinism:**
  * Network DNS calls must be mockable via `unittest.mock.patch("asyncio.get_event_loop")` or injected resolver fakes.
  * HTTP client redirect responses must use `httpx.MockTransport`.
  * Zero live network calls during automated test runs.
* **Coverage Target:** Minimum **95% branch coverage** on `src/modules/security/`.

---

## 3. Architectural & Contract Verification Gates

In addition to functional unit tests, the security module must pass all global architectural gates before merging:

1. **ArchUnit Layer Separation:**
   * `uv run pytest tests/architecture/ -v`
   * Ensures `src/modules/security/` does not depend on database repositories or presentation controllers.
2. **KG-ARCHMAP Graph Integrity:**
   * `archmap analyze src --fail-on-cycles --fail-on-layer-violations`
   * Verifies 0 cyclic imports and Grade A coupling health.
3. **Enola Drift Check:**
   * `enola check . --fail-on=layers,cycles`
   * Asserts no architectural regressions against baseline.
