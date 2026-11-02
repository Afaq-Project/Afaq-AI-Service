# Test-Driven Development (TDD) Test Plan: Security & Validation Module

**Feature**: `001-security-validation-module`  
**Created**: 2026-11-01  
**Status**: Approved Gate (TDD Red Phase Ready)  

---

## 1. Traceability Matrix: 1-to-1 Use Case to Test Case Mapping

Per Constitution v2.3.0 Principle II & III, every single scenario in [`use_cases.md`](use_cases.md) maps 1-to-1 to a deterministic test case. All tests must be authored **before** implementation code (Red phase):

| Use Case ID | Scenario Name | Test Target File | Test Function Name | Verification Gate |
| :--- | :--- | :--- | :--- | :--- |
| **UC-01** | Standard Public Educational Link Validation | `tests/unit/modules/security/test_link_validator_service.py` | `test_valid_public_https_url_resolves` | Unit |
| **UC-02** | AI Extraction Template Schema Dry-Run Verification | `tests/unit/modules/security/test_schema_validator_service.py`| `test_validate_template_schema_success` | Unit |
| **UC-03** | Official Scholarship PDF Attachment Inspection | `tests/unit/modules/security/test_file_validator_service.py` | `test_valid_pdf_magic_bytes_and_s3_key` | Unit |
| **UC-04** | Relative URL Reference Resolution (`FR-013`) | `tests/unit/modules/security/test_link_validator_service.py` | `test_relative_url_resolves_with_base_url` | Unit |
| **UC-05** | IDN Homograph Cyrillic Domain Spoofing | `tests/unit/modules/security/test_link_validator_service.py` | `test_homograph_cyrillic_spoofing_rejected` | Unit |
| **UC-06** | S3 Naming with Content-Disposition Fallback (`FR-014`)| `tests/unit/modules/security/test_file_validator_service.py` | `test_content_disposition_s3_naming_fallback` | Unit |
| **UC-07** | Multi-Hop Safe Redirect Chain ($\le 5$ Hops) | `tests/integration/modules/security/test_redirect_traversal.py` | `test_safe_redirect_chain_traversal` | Integration |
| **UC-08** | Direct SSRF Against AWS Cloud Metadata & Loopback | `tests/unit/modules/security/test_security_threats.py` | `test_ssrf_blocks_imds_and_loopback` | Security Gate |
| **UC-09** | Circular Redirect Loop Trap | `tests/unit/modules/security/test_link_validator_service.py` | `test_circular_redirect_loop_detected` | Unit |
| **UC-10** | Deep Redirect Chain Exceeding 5 Hops | `tests/unit/modules/security/test_link_validator_service.py` | `test_max_redirects_exceeded_error` | Unit |
| **UC-11** | Redirect-Based SSRF Pivot | `tests/unit/modules/security/test_security_threats.py` | `test_redirect_ssrf_pivot_intercepted` | Security Gate |
| **UC-12** | Disguised Windows Executable Attachment | `tests/unit/modules/security/test_security_threats.py` | `test_disguised_executable_rejected` | Security Gate |
| **UC-13** | High-Ratio Zip Bomb Decompression Attack | `tests/unit/modules/security/test_security_threats.py` | `test_zip_bomb_decompression_guard` | Security Gate |
| **UC-14** | Pathological CSS Selector Exponential Backtracking (ReDoS) | `tests/unit/modules/security/test_security_threats.py` | `test_css_selector_redos_timeout` | Security Gate |
| **UC-15** | Non-Standard Internal Port Querying | `tests/unit/modules/security/test_link_validator_service.py` | `test_non_standard_ports_rejected` | Unit |
| **UC-16** | Disallowed Schemes (`file:`, `gopher:`, `data:`) | `tests/unit/modules/security/test_link_validator_service.py` | `test_disallowed_schemes_rejected` | Unit |
| **UC-17** | HTTP 429 Rate Limiting with High Retry-After | `tests/unit/modules/security/test_link_validator_service.py` | `test_http_429_retry_after_cooldown` | Unit |

---

## 2. Test Execution Policy & Performance Independence

* **Strict Prohibition on Execution Time Limits:**
  * In accordance with `AGENT.md` Section 1 and Constitution v2.3.0 Principle VI, functional and unit tests **MUST NOT** assert, expect, or enforce execution duration limits or latency bounds.
  * System operations and network interactions possess inherently unpredictable durations; tests must verify purely logical outcomes, safety verdicts, and error conditions.
  * **Performance Testing Boundary:** Latency and throughput benchmarks are restricted exclusively to **k6 load test suites** configured and driven by the user.
* **Determinism & Mocking:**
  * Network DNS calls must be mockable via `unittest.mock.patch` or injected resolver fakes during unit testing.
  * HTTP client redirect responses must use `httpx.MockTransport`.
  * Zero live external network dependencies during automated unit tests.
* **Coverage Target:** Minimum **95% branch coverage** on `src/modules/security/`.

---

## 3. Mandatory Security, Quality & Architecture Gate Suites

In accordance with [`AGENT.md`](../../AGENT.md) Section 5 and Constitution v2.3.0, the module must pass all quality, security, and architectural verification suites prior to code completion:

### 3.1. Code Quality & Formatting
1. **Ruff Linter:**
   ```bash
   uv run ruff check .
   ```
   *Threshold:* 0 errors.
2. **Code Formatter:**
   ```bash
   uv run ruff format --check .
   ```
   *Threshold:* 0 files to reformat.

### 3.2. Static Security & Quality Analysis (SonarQube)
* **SonarScanner Execution:**
  ```bash
  sonar-scanner \
    -Dsonar.projectKey=afaq-ai-service \
    -Dsonar.sources=src \
    -Dsonar.tests=tests \
    -Dsonar.python.coverage.reportPaths=coverage.xml \
    -Dsonar.host.url=http://localhost:9000 \
    -Dsonar.token=$SONAR_TOKEN
  ```
* **Issue Inspection:**
  ```bash
  sonar-cli list issues --project afaq-ai-service --severities BLOCKER,CRITICAL,MAJOR
  ```
* **Quality Gate Acceptance:** **0 BLOCKER**, **0 CRITICAL**, **0 HIGH** vulnerabilities, bugs, or security hotspots.

### 3.3. Secret & Credential Scanning (Gitleaks)
* **Execution Command:**
  ```bash
  gitleaks detect --source . -v
  ```
* **Acceptance Criteria:** **0 leaks found**.

### 3.4. Dependency Vulnerability Audit (Trivy)
* **Execution Command:**
  ```bash
  trivy fs . --scanners vuln --pkg-types library --severity HIGH,CRITICAL --skip-db-update
  ```
* **Acceptance Criteria:** **0 CRITICAL** vulnerabilities in active runtime dependencies.

### 3.5. Architectural Fitness & Layer Boundaries (ArchUnit-Python)
* **Execution Command:**
  ```bash
  uv run pytest tests/architecture/ -v
  ```
* **Invariants Enforced:**
  * Security module never depends on `repositories` (`no-security-to-repositories`).
  * Security module never depends on `api` transport layer (`no-security-to-api`).
  * Security module never depends on `infrastructure` clients (`no-security-to-infrastructure`).
  * Zero circular dependencies across `src/`.

### 3.6. Architecture Graph & Coupling Budget (KG-ARCHMAP)
* **Execution Command:**
  ```bash
  archmap analyze src --fail-on-cycles --fail-on-layer-violations
  ```
* **Acceptance Criteria:** 0 circular dependencies, 0 layer violations, Health Score $\ge 90$ (Grade A).

### 3.7. Architectural Drift & Intent Gate (Enola)
* **Execution Command:**
  ```bash
  enola check . --fail-on=layers,cycles
  ```
* **Acceptance Criteria:** Exit code `0` (Clean structural delta against baseline).
