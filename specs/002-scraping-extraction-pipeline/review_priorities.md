# Human Review Priorities: Scraping & Extraction Pipeline

**Feature**: `002-scraping-extraction-pipeline`  
**Created**: 2026-11-05  
**Status**: Ready for Review  

This document establishes the human oversight review matrix for all 45 tasks defined in [`tasks.md`](tasks.md). Tasks are partitioned into four priority tiers to guide reviewer focus and ensure high-risk security gates, browser lifecycles, and concurrency locks receive thorough human inspection before merging.

---

## Tier 1: Critical Review (High-Risk Boundaries & Security Gates)

*Tasks involving external network ingestion, Chromium process management, security gateway traversal, and atomic database locks. Must receive rigorous human review.*

| Task ID | Component & File Path | Risk Factor & Review Focus |
| :--- | :--- | :--- |
| **T012** | `src/modules/scraping/services/crawler_service.py` | **Chromium Memory & Anti-SSRF DNS Pinning**: Verify `--disable-dev-shm-usage`, `--no-zygote`, `--disable-gpu` flags, per-page browser context lifecycle disposal, and strict Chromium `--host-resolver-rules` pinning via `LinkValidatorService`. |
| **T019** | `src/modules/scraping/services/scraper_service.py` | **Atomic Concurrency & Cancellation Tokens**: Verify atomic per-source lock queries (`UPDATE source_configs SET is_locked = true`), 30-min auto-expiration, 20-min hard timeouts, and graceful abort lock releases. |
| **T024** | `src/modules/scraping/services/discovery_service.py` | **DOM Skeletonization & Prompt Injection Sandbox**: Verify noisy tags are aggressively stripped and candidate HTML is strictly wrapped in `<untrusted_web_content>` with passive priming instructions. |
| **T037** | `src/modules/scraping/services/document_ingestion_service.py` | **S3 Attachment Streaming & File Safety**: Verify 25 MB stream ceiling, binary magic-byte inspection (`%PDF-`, `PK\x03\x04`), and zip-bomb decompression protection via `FileValidatorService`. |
| **T045** | Pre-commit security verification | **Secrets, Vulnerabilities & SonarQube**: Verify 0 Gitleaks secrets, 0 Trivy critical vulnerabilities, and 0 SonarQube BLOCKER/HIGH/MEDIUM issues. |

---

## Tier 2: High Review (Core Domain Logic & Extraction Engines)

*Tasks implementing core extraction algorithms, multi-template pool matching, pagination cutoff heuristics, and API route controllers.*

| Task ID | Component & File Path | Review Focus |
| :--- | :--- | :--- |
| **T011** | `src/modules/scraping/services/pagination_service.py` | **5 Termination Signals & Lookahead**: Verify SHA256 card fingerprinting for circular/stagnant loop traps and the 2-page lookahead cutoff on chronologically sorted catalogs. |
| **T013** | `src/modules/scraping/services/crawler_service.py` | **Multi-Tab & Multi-Page Tree Recursion**: Verify client-side tab unhiding script and 5-page depth cap ($\le 4$) preventing runaway recursion in multi-page articles. |
| **T018** | `src/modules/scraping/services/prioritization_service.py` | **Priority Scoring & Domain Interleaving**: Verify dynamic priority score calculations and ensure no two consecutive crawls target the same remote host. |
| **T020** | `src/api/routes/v1/scrape.py` | **FastAPI Route Handlers**: Verify `202 Accepted` non-blocking response on `POST /run`, 15-minute `Idempotency-Key` deduplication, `GET /operations/latest`, and `/abort` endpoints. |
| **T025** | `src/modules/scraping/services/discovery_service.py` | **Stage 0 Discovery & Relevance Gate**: Verify AI portal mapping, `ERR_NOT_OPPORTUNITY_PORTAL` early halt, and conditional 2nd-hop crawl. |
| **T030** | `src/modules/scraping/services/template_engine_service.py` | **3-Gate Deterministic Matching**: Verify fast evaluation against template pool with zero AI invocations. |
| **T031** | `src/modules/scraping/services/template_engine_service.py` | **Soft-Drift Micro-Repair**: Verify $>40\%$ fill-rate drop triggers targeted ~300-token micro-repairs (`v1.0` $\rightarrow$ `v1.1`) and 4-stage validation pipeline via `SchemaValidatorService`. |
| **T038** | `src/modules/scraping/services/scraper_service.py` | **Bilingual Pairing & DLQ**: Verify native Arabic and English pairs share `opportunity_group_id: UUID` and failed extractions transition to `failed_permanently` after 3 retries. |

---

## Tier 3: Medium Review (Data Access, Language Detection & Tests)

*Tasks implementing database repository queries, offline language classification, and test fixtures.*

| Task ID | Component & File Path | Review Focus |
| :--- | :--- | :--- |
| **T005** | `src/modules/core/database/repositories/scraping_repository.py` | **Prisma Queries**: Verify atomic update queries, unique constraint handling, and transactional consistency. |
| **T036** | `src/modules/scraping/services/language_classifier_service.py` | **N-Gram Language Detection**: Verify sub-millisecond execution, independent title/body language detection, and `<0.50` threshold for `'und'`. |
| **T008, T009** | `tests/unit/modules/scraping/` | **US1 Test Coverage**: Verify tests for pagination, termination signals, multi-tab, and multi-page recursion. |
| **T015, T016** | `tests/unit/` & `tests/integration/` | **US2 Test Coverage**: Verify tests for priority scoring, idempotency, hard timeout, and abort endpoints. |
| **T022** | `tests/integration/modules/scraping/` | **US3 Test Coverage**: Verify Stage 0 discovery integration tests on valid portals and commercial blogs. |
| **T028** | `tests/unit/modules/scraping/` | **US4 Test Coverage**: Verify 3-gate matching, fill-rate metric updates, and micro-repair tests. |
| **T033, T034** | `tests/unit/` & `tests/integration/` | **US5 Test Coverage**: Verify language classifier unit tests and S3 stream / DLQ integration tests. |
| **T043** | Architectural tests | **Fitness Gates**: Verify 0 circular dependencies and strict layer boundaries via ArchUnit, KG-ARCHMAP, and Enola. |

---

## Tier 4: Low Review (Boilerplate, Public Facades & Scaffolding)

*Standard structural initialization, models, linting, and legacy cleanup.*

| Task ID | Component & File Path | Review Focus |
| :--- | :--- | :--- |
| **T001, T002** | Scaffolding | Package structure initialization and `__init__.py` markers. |
| **T003** | `src/modules/scraping/exceptions.py` | Domain exception class hierarchy definitions. |
| **T004** | `src/modules/scraping/models.py` | Pydantic domain models with typed `error_summary: dict[str, Any]` dictionary. |
| **T006, T007** | `tests/unit/modules/scraping/test_models.py` | Foundational model validation tests. |
| **T026** | `src/api/routes/v1/scrape.py` | Route wiring for `POST /sources/onboard`. |
| **T040** | Legacy adapters | Clean deletion of deprecated adapter files (`Almin7Adapter`, `GrabScholarshipAdapter`, etc.). |
| **T041** | `src/modules/scraping/__init__.py` | Public facade exports and FastAPI protocol registration. |
| **T042** | Formatting & Linting | Ruff and Black compliance (0 errors). |
| **T044** | Coverage report | Pytest execution and XML coverage report generation. |
