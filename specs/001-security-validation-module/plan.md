# Implementation Plan: Security, Link & Schema Validation Module

**Branch**: `feat/crawl4ai-adaptive-scraping` | **Date**: 2026-11-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-security-validation-module/spec.md` and architectural report `docs/reports/security_and_validation_module/security_and_validation_specification.md`.

---

## 1. Summary

Build the foundational **Security & Validation Gatekeeper Module** (`src/modules/security/`) as the mandatory universal gateway for all scraping, extraction, attachment handling, and schema verification in `Afaq-AI-Service`. The module enforces RFC 3986 syntax normalization, Anti-SSRF private IP blocking, Chromium DNS pinning, safe redirect traversal, binary magic-byte inspection, zip-bomb defense, and CSS ReDoS protection. All content mutation, HTML cleaning, and entity decoding are strictly deferred to the downstream Data Cleaning Pipeline (`src/modules/cleaning/`).

---

## 2. Technical Context

* **Language/Version**: Python 3.12+ (runtime managed with `uv`).
* **Primary Dependencies**:
  * `pydantic` v2 (strict immutable schemas with `frozen=True` and `extra="forbid"`).
  * `soupsieve` (CSS selector parser & compiler).
  * `httpx` (asynchronous HTTP client for redirect inspection).
  * Standard library: `ipaddress`, `urllib.parse`, `zipfile`, `hashlib`, `asyncio`.
* **Storage**: In-memory domain validation. (AWS S3 keys are derived deterministically; database persistence is handled by downstream repositories).
* **Testing**: `pytest`, `pytest-asyncio`, `pytest-cov`, `archunitpython`.
* **Target Platform**: Linux server / Docker container (single-process concurrency, RAM $\le 1$ GB).
* **Performance Goals & Benchmark Boundary**:
  * CSS selector dry-run timeout guard $\le 200$ms (algorithmic timeout enforced in code to prevent ReDoS).
  * System throughput and latency benchmarks (in-memory validation $<5$ms, DNS/redirect probes $<500$ms) are directional targets benchmarked **exclusively via user-configured k6 load test suites**.
  * **Constitution Principle VI & AGENT.md Compliance:** Automated functional, unit, and integration test suites **MUST NEVER** assert, expect, or enforce execution duration limits or latency SLAs.
* **Constraints**:
  * 100% of private/loopback/cloud metadata CIDRs intercepted before socket connection.
  * Zero external network calls during unit testing (deterministic mocked fixtures via `unittest.mock` and `httpx.MockTransport`).

---

## 3. Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

* **Public Data Only & Zero Paywall Bypass:** **PASS** — The security module enforces strict scheme/port boundaries and does not bypass paywalls or CAPTCHAs.
* **Zero-Trust Ingestion Isolation:** **PASS** — The module is the explicit architectural gateway mandated for all URLs, text, and files prior to persistence.
* **Single-Browser Low-Memory Bound:** **PASS** — The module is lightweight, purely functional, and enforces a 25 MB file download ceiling and zip-bomb decompression caps.
* **Raw vs. Cleaning Separation:** **PASS** — The module provides pure transformations without mutating raw database tables.
* **TDD Drift Prevention:** **PASS** — Test plan mandates Red-Green-Refactor with 1-to-1 use-case traceability.

---

## 4. Project Structure

### Documentation & Planning Artifacts
```text
specs/001-security-validation-module/
├── spec.md               # Functional requirements & user stories (completed)
├── checklists/
│   └── requirements.md   # Quality validation checklist (12/12 passed)
├── research.md           # Phase 0 architectural & technical decisions
├── data-model.md         # Phase 1 domain entities & standard error codes
├── endpoints.md          # Internal Python contracts & diagnostic API routes
├── use_cases.md          # 20 primary, edge, and worst-case failure scenarios
├── security.md           # Pre-implementation STRIDE threat model & negative tests
├── quickstart.md         # Fast runnable validation guide
├── plan.md               # This phased implementation blueprint
├── test_plan.md          # TDD test specifications (linked 1-to-1 to use cases)
├── tasks.md              # Consolidated, dependency-ordered task breakdown
└── review_priorities.md  # Human review oversight matrix (Critical to Low)
```

### Source Code Layout
```text
src/
└── modules/
    └── security/
        ├── __init__.py                     # Public exports (services, models, exceptions)
        ├── models.py                       # Pydantic schemas (ValidatedUrl, FileValidationResult, etc.)
        ├── exceptions.py                   # SecurityValidationError exception hierarchy
        └── services/
            ├── __init__.py                 # Services export
            ├── link_validator_service.py   # RFC 3986, Anti-SSRF, DNS Pinning, Safe Redirects
            ├── file_validator_service.py   # Stream limits, magic bytes, zip bomb, S3 key derivation
            └── schema_validator_service.py # AI template schema validation, ReDoS linter

src/api/routes/v1/
└── security.py                             # Optional diagnostic inspect-url route (thin controller)

tests/unit/modules/security/
├── __init__.py
├── test_models.py                          # Schema validation & immutability tests
├── test_link_validator_service.py          # RFC 3986, Anti-SSRF, DNS rebinding, homograph
├── test_file_validator_service.py          # Magic bytes, PE/ELF drop, zip-bomb ratio checks
├── test_schema_validator_service.py        # Pydantic shape, soupsieve ReDoS timeout checks
└── test_security_threats.py                # STRIDE negative test cases & failure injection

tests/integration/modules/security/
├── __init__.py
└── test_redirect_traversal.py              # Multi-hop redirect traversal with MockTransport
```

---

## 5. Phased Implementation Roadmap

### Phase 1: Domain Models & Exception Hierarchy
1. Author `tests/unit/modules/security/test_models.py`.
2. Implement `src/modules/security/exceptions.py` with `SecurityValidationError` hierarchy and standardized error codes.
3. Implement `src/modules/security/models.py` (`ValidatedUrl`, `FileValidationResult`, `TemplateSchemaValidationResult`).
4. Validate tests pass.

### Phase 2: Link Verification & Anti-SSRF Service Subsystem
1. Author `tests/unit/modules/security/test_link_validator_service.py` and `tests/integration/modules/security/test_redirect_traversal.py`.
2. Implement `src/modules/security/services/link_validator_service.py`:
   * RFC 3986 parsing, port/scheme whitelist, path traversal rejection.
   * `base_url` relative reference resolution (`FR-013`).
   * Asynchronous DNS resolution + private CIDR matching (`is_private_or_reserved_ip`).
   * Chromium `--host-resolver-rules` DNS pinning rule production.
   * Safe 5-hop redirect traversal with circular loop detection and per-hop SSRF re-checks.
   * HTTP 429/503 `Retry-After` evaluation.
3. Validate tests pass.

### Phase 3: Schema & ReDoS Safety Service Subsystem
1. Author `tests/unit/modules/security/test_schema_validator_service.py`.
2. Implement `src/modules/security/services/schema_validator_service.py`:
   * `validate_template_schema`: Pydantic shape validation (`strict=True`, `extra="forbid"`), `soupsieve` compilation, complexity linter, and 200ms dry-run timeout.
3. Validate tests pass.

### Phase 4: File & Attachment Inspection Service Subsystem
1. Author `tests/unit/modules/security/test_file_validator_service.py`.
2. Implement `src/modules/security/services/file_validator_service.py`:
   * 25 MB stream limit enforcement.
   * Pure-Python magic-byte slicing (`%PDF-`, `PK\x03\x04`, JPEG, PNG, WEBP).
   * Unconditional rejection of executable headers (`MZ`, `\x7fELF`, `#!`).
   * Zip-bomb inspection without full decompression (100:1 ratio, 50 MB cap).
   * S3 key derivation with Content-Disposition parsing and hash fallback (`FR-014`).
3. Validate tests pass.

### Phase 5: Module Public API & Diagnostic Route
1. Implement `src/modules/security/services/__init__.py` and `src/modules/security/__init__.py` exporting public service classes, models, and exceptions.
2. Implement thin diagnostic route `src/api/routes/v1/security.py` and register in FastAPI router.
3. Author route tests in `tests/api/routes/v1/test_security_routes.py`.

### Phase 6: Full Verification Pipeline Execution
1. Run linting and formatting: `ruff check .` & `black --check .`.
2. Run full test suite with coverage: `pytest --cov=src --cov-report=xml`.
3. Run ArchUnit architectural tests: `pytest tests/architecture/ -v`.
4. Run KG-ARCHMAP analysis: `archmap analyze src --fail-on-cycles --fail-on-layer-violations`.
5. Run Enola baseline check: `enola check . --fail-on=layers,cycles`.
6. Run Pact contract checks: `./scripts/pact_check.sh`.
7. Run security scans: `gitleaks detect` & `trivy fs`.
8. Run SonarQube quality gate analysis: `sonar-scanner`.

---

## 6. Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
| :--- | :--- | :--- |
| *None* | Architecture strictly complies with Modular Monolith and Clean Architecture boundaries. | N/A |
