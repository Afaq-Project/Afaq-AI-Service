# Code and Test Review: Feature 2 (Autonomous Crawl4AI Multi-Level Scraping & Raw Extraction Pipeline)

## Verdict
**Request changes**

---

## Scope Reviewed
- **Task**: Feature 2 — Autonomous Crawl4AI Multi-Level Scraping & Raw Extraction Pipeline ([`specs/002-scraping-extraction-pipeline/spec.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/specs/002-scraping-extraction-pipeline/spec.md)).
- **Files reviewed**:
  - **API Layer**:
    - [`src/main.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/main.py)
    - [`src/api/app.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/app.py)
    - [`src/api/protocols.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/protocols.py)
    - [`src/api/routes/v1/scrape.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py)
    - [`src/api/routes/v1/__init__.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/__init__.py)
  - **Core & Repository**:
    - [`src/modules/core/config/settings.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/core/config/settings.py)
    - [`src/modules/core/database/repositories/scraping_repository.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/core/database/repositories/scraping_repository.py)
  - **Scraping Domain**:
    - [`src/modules/scraping/__init__.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/__init__.py)
    - [`src/modules/scraping/models.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/models.py)
    - [`src/modules/scraping/exceptions.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/exceptions.py)
    - [`src/modules/scraping/services/scraper_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/scraper_service.py)
    - [`src/modules/scraping/services/crawler_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/crawler_service.py)
    - [`src/modules/scraping/services/discovery_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/discovery_service.py)
    - [`src/modules/scraping/services/template_engine_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/template_engine_service.py)
    - [`src/modules/scraping/services/pagination_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/pagination_service.py)
    - [`src/modules/scraping/services/prioritization_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/prioritization_service.py)
    - [`src/modules/scraping/services/document_ingestion_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/document_ingestion_service.py)
    - [`src/modules/scraping/services/language_classifier_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/language_classifier_service.py)
  - **Tests**:
    - [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py)
    - [`tests/unit/modules/scraping/test_crawler_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_crawler_service.py)
    - [`tests/unit/modules/scraping/test_language_classifier_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_language_classifier_service.py)
    - [`tests/unit/modules/scraping/test_models.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_models.py)
    - [`tests/unit/modules/scraping/test_pagination_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_pagination_service.py)
    - [`tests/unit/modules/scraping/test_prioritization_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_prioritization_service.py)
    - [`tests/unit/modules/scraping/test_template_engine_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_template_engine_service.py)
    - [`tests/integration/modules/scraping/conftest.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/conftest.py)
    - [`tests/integration/modules/scraping/mock_db.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/mock_db.py)
    - [`tests/integration/modules/scraping/test_batch_scrape_orchestration.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/test_batch_scrape_orchestration.py)
    - [`tests/integration/modules/scraping/test_dead_letter_queue.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/test_dead_letter_queue.py)
    - [`tests/integration/modules/scraping/test_stage_0_discovery.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/test_stage_0_discovery.py)
- **Checks run**:
  - `uv run pytest` (207 passed, 10 warnings in 24.48s)
  - `uv run pytest tests/architecture/ -v` (5 passed)
  - `uv run pytest tests/contracts/ -v` (1 passed)
  - `uv run ruff check .` (0 errors)
  - `uv run black --check .` (0 files to reformat)
  - `archmap analyze src --fail-on-cycles --fail-on-layer-violations` (Health: 70/100 Grade C, 0 cycles, 0 layer violations)
  - `enola check . --fail-on=layers,cycles` (Clean pass)
  - `gitleaks detect --source . -v` (0 leaks)
  - `trivy fs . --scanners vuln --pkg-types library --severity HIGH,CRITICAL --skip-db-update` (0 CRITICAL, 1 HIGH in dev nltk)
  - `sonar-scanner` & `sonar list issues` (Multiple CRITICAL and MAJOR issues found in `src/`)
- **Constraints sources**:
  - [`specs/002-scraping-extraction-pipeline/spec.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/specs/002-scraping-extraction-pipeline/spec.md)
  - [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md)
  - [`ARCHITECTURAL_RULES_AND_BOUNDARIES.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/ARCHITECTURAL_RULES_AND_BOUNDARIES.md)
- **Missing information**: None.

---

## Summary

The Feature 2 implementation delivers comprehensive functionality matching the core architectural vision: two-phase sequential crawl execution (Level 1 Catalog discovery persisting to `raw_listings`, followed by Level 2 scholarship details extraction), headless Playwright browser management with strict memory-pruning flags and DNS pinning, zero-configuration Stage 0 onboarding with DOM skeletonization down to 3–8 KB, multi-template matching with soft-drift repair, S3 streaming attachment ingestion with binary verification, and dead-letter queues.

However, **the changes cannot be approved in their current state** due to seven critical and high-priority blocking issues:
1. **Critical Deployment / Routing Defect**: The new scrape router is never mounted in [`src/main.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/main.py) (the production FastAPI entrypoint). An ad-hoc file [`src/api/app.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/app.py) was created and imported solely by scraping integration tests; in production (`uvicorn src.main:app`), all `/api/v1/scrape/*` routes return 404.
2. **Quality Gate Failures**:
   - SonarQube reported 15 CRITICAL cognitive complexity violations (up to 58 vs. allowed 15), 1 CRITICAL bug (unchecked element dereference), 1 MAJOR bug (swallowing `asyncio.CancelledError`), and multiple MAJOR code smells (deprecated BeautifulSoup arguments, method with 19 parameters).
   - KG-ARCHMAP health score fell to **70/100 (Grade C)** (threshold is $\ge 90$ Grade A) due to multiple god classes and dependency explosion.
3. **Unauthorized Modification of Architectural Test Rules**: [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py) was modified without explicit user authorization, directly violating [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md#L25-L34).
4. **Specification Formula Deviation (FR-007)**: Dynamic source priority calculation uses an invented formula (`base*1 + days*2 - failures*5`) instead of the explicit specification: $\text{Score} = (\text{Admin Tier} \times 100) + \text{Days Since Last Scrape} - (\text{Consecutive Failures} \times 10)$.
5. **Architectural Protocol Bypass**: [`src/api/routes/v1/scrape.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py) completely ignores [`src/api/protocols.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/protocols.py), directly depends on concrete classes, duplicates singleton container definitions, and returns untyped `dict[str, Any]` without `response_model` on multiple endpoints.
6. **Error Masking & Null-Pointer Risks**: Catching generic `Exception` in Stage 0 onboarding masks server/database crashes as `HTTP 400 ERR_NOT_OPPORTUNITY_PORTAL`. Accessing `source_token.is_set()` directly without checking `if source_token is not None` risks `AttributeError`.
7. **Test Bloat**: 352 lines in [`tests/unit/modules/scraping/test_models.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_models.py) test trivial Pydantic instantiation and framework features (expressly prohibited by [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md#L165-L168)).

---

## Findings

| Severity | Area | Location | Finding | Evidence | Recommended action |
|---|---|---|---|---|---|
| **Critical** | Architecture / Routing | [`src/main.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/main.py#L38-L41) & [`src/api/app.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/app.py#L4-L7) | `scrape.router` is never mounted on the production `app` in `src/main.py`. In production (`uvicorn src.main:app`), all scraping endpoints return 404. | Dockerfile (`CMD ["uvicorn", "src.main:app", ...]`) and README use `src.main:app`. `scrape.router` is only imported in `src/api/app.py`, which is only used in tests. | Mount `scrape.router` directly in [`src/main.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/main.py) and remove the redundant [`src/api/app.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/app.py). Update [`tests/integration/modules/scraping/conftest.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/conftest.py#L9) to import `app` from `src.main`. |
| **High** | Spec Compliance | [`src/modules/scraping/services/prioritization_service.py#L16-L20`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/prioritization_service.py#L16-L20) & [`tests/unit/modules/scraping/test_prioritization_service.py#L13-L41`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_prioritization_service.py#L13-L41) | Prioritization scoring formula deviates from the mandatory specification (FR-007). | Spec FR-007 requires: `(Admin Tier * 100) + Days - (Failures * 10)`. The code implemented: `base * 1.0 + days * 2.0 - failures * 5.0`. | Correct the formula weights in `PrioritizationService` to match FR-007, and update unit test assertions accordingly. |
| **High** | Project Governance | [`tests/architecture/test_architecture.py#L16`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py#L16) | Architectural test rule file was modified without explicit user authorization. | [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md#L25-L34) strictly forbids modifying architectural rule definitions (`tests/architecture/test_architecture.py`) without direct user command. Diffs show `api*` changed to `src/api*`. | Revert unauthorized changes to [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py) or seek explicit user consent. |
| **High** | Concurrency / Error Handling | [`src/modules/scraping/services/scraper_service.py#L404-L420`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/scraper_service.py#L404-L420) | `asyncio.CancelledError` is caught and swallowed in the source loop without being re-raised when an external cancellation occurs. | SonarQube rule `python:S7497`. Swallowing `CancelledError` prevents proper asyncio task cancellation and termination. | Re-raise `asyncio.CancelledError` after performing cleanup when the cancellation is task-level or operation-level. |
| **High** | Runtime Safety | [`src/modules/scraping/services/scraper_service.py#L524`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/scraper_service.py#L524), [`#L689`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/scraper_service.py#L689), [`#L367`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/scraper_service.py#L367) | Calling `source_token.is_set()` directly without checking `if source_token is not None` risks `AttributeError`. | Parameter type is declared `source_token: asyncio.Event | None`. If `None`, `source_token.is_set()` crashes. | Use `(source_token and source_token.is_set())` consistently. |
| **Medium** | Quality Gate | Multiple files across `src/modules/scraping/` | Quality Gate failure: 15 CRITICAL cognitive complexity violations (up to 58) and KG-ARCHMAP score of 70/100 (Grade C). | [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md#L218) requires 0 CRITICAL/HIGH/MEDIUM issues in SonarQube and $\ge 90$ Grade A in ArchMap. | Refactor giant methods (`discovery_service.py:409`, `crawler_service.py:438`, `scraper_service.py:298`, `template_engine_service.py:136`) into cohesive helper functions. |
| **Medium** | Architecture / Protocols | [`src/api/routes/v1/scrape.py#L42-L80`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py#L42-L80) & [`src/api/protocols.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/protocols.py) | Dependency inversion bypass: `scrape.py` does not use `src/api/protocols.py`, directly imports concrete classes, and duplicates singleton container logic. | [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md#L100-L103) requires routes to depend on abstract Protocols via FastAPI DI. Lines 61-80 in `scrape.py` duplicate `protocols.py:151-198`. | Import and depend on protocols from [`src/api/protocols.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/protocols.py), removing duplicated providers in `scrape.py`. |
| **Medium** | API Standards | [`src/api/routes/v1/scrape.py#L257-L289`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py#L257-L289), [`#L305-L339`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py#L305-L339) | Endpoints return untyped `dict[str, Any]` and lack explicit `response_model=...`. | [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md#L121-L123) mandates explicit Pydantic response models on every endpoint. | Add `response_model=ScrapeOperationEnvelope` (or equivalent) and return typed models instead of calling `.model_dump()`. |
| **Medium** | Error Masking | [`src/api/routes/v1/scrape.py#L479-L484`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py#L479-L484) | Catching generic `Exception` and converting it to `HTTP 400 ERR_NOT_OPPORTUNITY_PORTAL` masks internal runtime bugs and system failures. | If a database, network, or internal error occurs, the API reports the portal was rejected for relevance. | Catch domain-specific exceptions explicitly; let unexpected exceptions propagate to global 500 error handlers. |
| **Medium** | Boundary Encapsulation | [`src/modules/scraping/services/crawler_service.py#L227`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/crawler_service.py#L227) | Direct invocation of private method `_is_blocked_ip` across module boundaries. | `LinkValidatorService._is_blocked_ip(host)` accesses a private internal helper of `security`. | Expose a public classmethod on `LinkValidatorService` (e.g. `is_ip_blocked(ip)`) or validate via `LinkValidatorService.validate_url`. |
| **Medium** | Repository Design | [`src/modules/core/database/repositories/scraping_repository.py#L527-L546`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/core/database/repositories/scraping_repository.py#L527-L546) | `create_grant_detail` takes 19 parameters beyond `self` (20 total), violating Sonar rule S107 (max 13 allowed). | Flagged by SonarQube. Makes caller code brittle and difficult to maintain. | Encapsulate creation arguments into a dataclass or Pydantic DTO (e.g. `GrantDetailCreateInput`). |
| **Low** | Test Quality | [`tests/unit/modules/scraping/test_models.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_models.py) | 352 lines of boilerplate tests asserting Pydantic instantiation and default field values. | Expressly prohibited anti-pattern in [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md#L165-L168) ("Do not test that Pydantic validates fields..."). | Remove trivial model instantiation tests; retain only tests verifying custom validators or non-trivial transformations. |
| **Low** | Deprecation Warnings | [`src/modules/scraping/services/discovery_service.py#L287`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/discovery_service.py#L287), [`#L311`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/discovery_service.py#L311), [`#L328`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/discovery_service.py#L328) | Deprecated `text` keyword argument used in BeautifulSoup `find_all` calls. | Generates 8 pytest warnings and Sonar MAJOR code smells (`python:S8900`). | Replace `text=` with `string=`. |
| **Nit** | Code Hygiene | [`src/modules/scraping/models.py#L82`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/models.py#L82), [`prioritization_service.py#L135`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/prioritization_service.py#L135) | Commented-out code in `models.py` and unused variable assignment in `prioritization_service.py`. | Flagged by SonarQube (`python:S125`, `python:S1854`). | Clean up commented code and unused assignments. |

---

## Complexity and Minimality Review

- **Essential complexity**:
  - Sequential two-phase execution (Phase 1 Catalog $\rightarrow$ Phase 2 Details) with atomic per-source locking and 30-min stale lock reclamation.
  - Chromium lifecycle management with memory-pruning flags (`--single-process`, `--disable-gpu`, `--no-zygote`) and DNS pinning via `--host-resolver-rules`.
  - SHA-256 card title fingerprinting to halt stagnant and circular pagination loops, plus 2-page incremental lookahead.
  - S3 streaming document ingestion with binary magic-byte inspection, archive bomb defense, and checksum cache reuse.
  - Fast offline statistical n-gram language classification using `py3langid` with softmax-normalized confidence scoring.
- **Accidental complexity**:
  - **God Classes**: `scraper_service.py` (1,132 lines), `scraping_repository.py` (1,029 lines), `template_engine_service.py` (805 lines), `discovery_service.py` (705 lines), and `scrape.py` (556 lines). These single-file monoliths combine multiple responsibilities, resulting in cognitive complexity scores up to 58.
  - **Duplication between API Routes and Protocols**: `_singleton_scraper_service`, `get_scraper_service()`, and `get_discovery_service()` are defined independently in both `src/api/protocols.py` and `src/api/routes/v1/scrape.py`.
  - **Side-car Application Wrapper**: Creating `src/api/app.py` instead of adding a single route mount line to `src/main.py`.
  - **Unwieldy Parameter Lists**: `ScrapingRepository.create_grant_detail` accepting 20 arguments rather than a typed input object.
- **Simplification opportunities**:
  - Break `scraper_service.py` into dedicated coordinators (e.g. `CatalogCrawlCoordinator`, `DetailCrawlCoordinator`, and `OperationLockManager`).
  - Eliminate `src/api/app.py` and register `scrape.router` in `src/main.py`.
  - Delete redundant provider functions from `src/api/routes/v1/scrape.py` and import them from `src/api/protocols.py`.
  - Replace 20-parameter repository methods with domain DTOs.
- **Changes that should not be simplified**:
  - The 5 pagination termination conditions in [`pagination_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/pagination_service.py).
  - The S3 streaming validation pipeline and checksum cache checks in [`document_ingestion_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/document_ingestion_service.py).
  - The DOM skeletonization multi-pass compression in [`discovery_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/discovery_service.py).

---

## Test Quality Review

- **Meaningful coverage**:
  - Integration tests in [`test_batch_scrape_orchestration.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/test_batch_scrape_orchestration.py) and [`test_dead_letter_queue.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/test_dead_letter_queue.py) verify observable business outcomes: Phase 1 to Phase 2 sequencing, idempotency deduplication, timeout abortion, DLQ state transitions, S3 cache hits, and bilingual pairing under a shared UUID.
  - [`test_pagination_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_pagination_service.py) accurately verifies circular loop traps, stagnant page detection, and next-button selectors.
- **Missing high-value tests**:
  - **FR-007 Verification**: No test validates the true formula $\text{Score} = (\text{Admin Tier} \times 100) + \text{Days} - (\text{Failures} \times 10)$. The current test only verifies the incorrect weights.
  - **Production Entrypoint Mounting**: No test asserts that `app` imported from `src.main` contains the `/api/v1/scrape` routes.
  - **`source_token=None` Null-Safety**: No test verifies that `_crawl_catalog_phase` and `_crawl_details_phase` handle `source_token=None` without crashing.
- **Redundant or low-value tests**:
  - [`tests/unit/modules/scraping/test_models.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_models.py) (352 lines, 20 tests): Nearly 100% test bloat testing standard Pydantic instantiation and extra field rejection without custom validation logic.
- **Determinism and isolation concerns**:
  - Tests run deterministically without external network calls, using `mock_db.py` and mocks.
  - Execution speed: Local test suite execution currently takes **24.5 seconds** (exceeding the 15-second guideline in `AGENT.md#L172`). Trimming redundant model tests and optimizing setup will bring execution under 15 seconds.

---

## Project Compliance Matrix

| Constraint source | Requirement | Evidence | Status |
|---|---|---|---|
| `AGENT.md` §1 | Never modify architectural rule files without explicit user directive | `tests/architecture/test_architecture.py` was altered | **Non-compliant** |
| `AGENT.md` §2 | Clean Architecture: Routes must delegate to service protocols via DI | `scrape.py` directly imports concrete services, ignores `protocols.py` | **Non-compliant** |
| `AGENT.md` §3 | RESTful API: Explicit `response_model` on every endpoint, no untyped dicts | `scrape.py` lines 257 & 305 return untyped `dict[str, Any]` | **Non-compliant** |
| `AGENT.md` §4 | Testing: Avoid boilerplate testing of Pydantic models; under 15s suite | `test_models.py` has 352 lines testing models; test run = 24.5s | **Non-compliant** |
| `AGENT.md` §5.3 | SonarQube: 0 BLOCKER, 0 HIGH, 0 MEDIUM issues | Multiple CRITICAL and MAJOR issues in `src/` | **Non-compliant** |
| `AGENT.md` §5.8 | KG-ARCHMAP: Health score $\ge 90$ (Grade A) | Health score is **70/100 (Grade C)** | **Non-compliant** |
| `spec.md` FR-007 | Priority formula: $(\text{Tier} \times 100) + \text{Days} - (\text{Failures} \times 10)$ | Implemented `base * 1 + days * 2 - failures * 5` | **Non-compliant** |
| `spec.md` FR-003, FR-004 | Async trigger with `202 Accepted`, `Idempotency-Key` 15-min deduplication | Tested and functional in `scrape.py` | **Compliant** |
| `spec.md` FR-005, FR-006 | Atomic per-source locking with 30-min stale lock reclamation | Implemented in repository and tested | **Compliant** |
| `spec.md` FR-009 | Browser concurrency = 1, memory pruning flags, context disposal | Implemented in `crawler_service.py` | **Compliant** |
| `spec.md` FR-015, FR-016 | Catalog pagination, 5 termination signals, 2-page lookahead cutoff | Implemented in `pagination_service.py` | **Compliant** |
| `spec.md` FR-020 | Statistical language classification with 0.50 confidence threshold | Implemented in `language_classifier_service.py` | **Compliant** |
| `spec.md` FR-021 | Arabic/English pairing linked under shared `opportunity_group_id` | Implemented and verified in integration tests | **Compliant** |
| `spec.md` FR-023 | S3 streaming, 25MB ceiling, magic bytes, zip-bomb checks, cache reuse | Implemented in `document_ingestion_service.py` | **Compliant** |
| `spec.md` FR-024 | Dead letter queue transitioning to `failed_permanently` after 3 retries | Implemented in repository and tested | **Compliant** |
| `spec.md` FR-026 | Decommission legacy scraper adapters (`Almin7`, `Scholars4Dev`, etc.) | Fully purged from codebase | **Compliant** |
| `spec.md` FR-027 | Strict sequential two-phase execution per source (Catalog $\rightarrow$ Details) | Implemented in `scraper_service.py` | **Compliant** |
| `spec.md` FR-028–031 | Endpoints: `/operations`, `/operations/latest`, `/operations/{id}/abort`, `/sources/{id}/abort` | Endpoints defined in `scrape.py` | **Compliant** |

---

## Required Changes

1. **Mount Scrape Router in Production App & Remove `src/api/app.py`**:
   - Register `scrape.router` in [`src/main.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/main.py#L38-L41).
   - Delete [`src/api/app.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/app.py).
   - Update [`tests/integration/modules/scraping/conftest.py#L9`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/conftest.py#L9) to `from src.main import app`.
2. **Correct Priority Scoring Formula to Match FR-007**:
   - In [`src/modules/scraping/services/prioritization_service.py#L16-L20`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/prioritization_service.py#L16-L20), set:
     - `DEFAULT_BASE_PRIORITY_WEIGHT = 100.0`
     - `DEFAULT_DAYS_SINCE_SCRAPE_WEIGHT = 1.0`
     - `DEFAULT_CONSECUTIVE_FAILURES_PENALTY = 10.0`
   - Update tests in [`tests/unit/modules/scraping/test_prioritization_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_prioritization_service.py) to reflect this formula.
3. **Revert Unauthorized Changes to Architectural Tests**:
   - Revert lines 16, 30, and 48 in [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py) back to `"api*"` or seek explicit user consent.
4. **Fix Cancellation and Null-Safety in `scraper_service.py`**:
   - In [`scraper_service.py#L404-L420`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/scraper_service.py#L404-L420), ensure task-level or operation-level `asyncio.CancelledError` is re-raised.
   - In [`scraper_service.py#L367, L524, L689`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/scraper_service.py#L524), replace `or source_token.is_set()` with `or (source_token is not None and source_token.is_set())`.
   - In [`scraper_service.py#L951`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/scraper_service.py#L951), verify `hero_img is not None and hasattr(hero_img, "get")` before accessing attributes.
5. **Enforce DI Protocols and Response Models in API Controller**:
   - Update [`src/api/routes/v1/scrape.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py) to inject `ScraperServiceProtocol` and `DiscoveryServiceProtocol` from [`src/api/protocols.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/protocols.py).
   - Remove duplicated singleton containers from `scrape.py`.
   - Add explicit Pydantic response models (`response_model=...`) to `get_latest_operation` and `get_operation_by_id`.
   - Stop masking generic exceptions as `ERR_NOT_OPPORTUNITY_PORTAL` in [`scrape.py#L483`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py#L483).
6. **Resolve SonarQube Critical/Major Issues & Deprecations**:
   - Replace deprecated `text=` with `string=` in [`discovery_service.py#L287, L311, L328`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/discovery_service.py#L287).
   - Define a constant `HTML_PARSER = "html.parser"` instead of repeating the string literal across modules.
   - Refactor high-complexity methods (`discovery_service.py:409`, `crawler_service.py:438`, `scraper_service.py:298`) into smaller functions to bring cognitive complexity within the allowed limit ($\le 15$) and restore ArchMap health score ($\ge 90$).
7. **Prune Redundant Test Bloat**:
   - Remove boilerplate tests from [`tests/unit/modules/scraping/test_models.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_models.py) to comply with [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md#L165-L168) and reduce test execution time under 15 seconds.

---

## Suggested Improvements

1. **Encapsulate Repository Parameters**:
   Refactor `ScrapingRepository.create_grant_detail` to accept a typed dataclass (e.g. `GrantDetailCreateData`) instead of 20 positional/keyword arguments.
2. **Public Method for IP Blocking Inspection**:
   In `src/modules/security/services/link_validator_service.py`, expose a public classmethod `is_ip_blocked(ip: str) -> bool` so that `crawler_service.py` does not access the private `_is_blocked_ip` method.
3. **Domain Interleaving Robustness**:
   Extract `extract_domain` and domain normalization logic from `PrioritizationService` into a shared core URL utility to avoid coupling routing concerns directly to prioritization.

---

## Residual Risks
- **Playwright Memory Footprint in Production**: While launch flags (`--single-process`, `--disable-gpu`, `--no-zygote`) and context disposal are configured, continuous long-running multi-source scraping under a strict 1 GB RAM container limit requires monitoring via real load/performance tests (`k6`) to guarantee that OS-level memory fragmentation does not trigger container eviction.
- **In-Memory Prisma Mock Fidelity**: Integration tests rely heavily on `tests/integration/modules/scraping/mock_db.py`. If schema or query complexity increases, differences between the in-memory dictionary mock and real PostgreSQL/Prisma behavior may hide database constraint bugs until staging.

---

## Evidence Limitations
- SonarQube, ArchUnit, Enola, ArchMap, Gitleaks, and Trivy were executed successfully against local binaries and repositories.
- Live database queries and external Playwright headless browser runs were executed against mocked network and in-memory DB fixtures in accordance with test determinism rules. Live remote crawling was not tested against production educational portals.
