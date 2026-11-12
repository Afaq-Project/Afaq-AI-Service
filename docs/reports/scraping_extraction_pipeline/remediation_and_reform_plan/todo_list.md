# Feature 2 Remediation & Service Decomposition: Phased To-Do List

This document organizes all tasks into sequential, atomic execution phases. Each phase contains clear acceptance criteria and verification commands.

---

## Phase 1: Production Entrypoint & Routing Alignment
- [ ] **Task 1.1: Mount scrape router in production app**
  - File: [`src/main.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/main.py)
  - Action: Import `scrape` from `src.api.routes.v1` and call `app.include_router(scrape.router)`.
  - Verification: `python -c "from src.main import app; assert any(r.path.startswith('/api/v1/scrape') for r in app.routes)"`
- [ ] **Task 1.2: Delete auxiliary application file**
  - File: `src/api/app.py`
  - Action: Delete `src/api/app.py`.
- [ ] **Task 1.3: Update integration test fixtures**
  - File: [`tests/integration/modules/scraping/conftest.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/conftest.py)
  - Action: Change import to `from src.main import app`.
- [ ] **Task 1.4: Add production entrypoint route assertion test**
  - File: [`tests/integration/modules/scraping/test_batch_scrape_orchestration.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/integration/modules/scraping/test_batch_scrape_orchestration.py)
  - Action: Add test verifying `src.main.app` serves `/api/v1/scrape/operations/log`.

---

## Phase 2: Specification Compliance & Security Encapsulation
- [ ] **Task 2.1: Correct priority scoring weights to match FR-007**
  - File: [`src/modules/scraping/services/prioritization_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/prioritization_service.py)
  - Action: Update `DEFAULT_BASE_PRIORITY_WEIGHT = 100.0`, `DEFAULT_DAYS_SINCE_SCRAPE_WEIGHT = 1.0`, `DEFAULT_CONSECUTIVE_FAILURES_PENALTY = 10.0`.
- [ ] **Task 2.2: Update priority scoring unit tests**
  - File: [`tests/unit/modules/scraping/test_prioritization_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_prioritization_service.py)
  - Action: Update test assertions to match formula $(\text{Admin Tier} \times 100) + \text{Days} - (\text{Failures} \times 10)$.
  - Verification: `uv run pytest tests/unit/modules/scraping/test_prioritization_service.py`
- [ ] **Task 2.3: Expose public IP blocking verification on LinkValidatorService**
  - File: [`src/modules/security/services/link_validator_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/security/services/link_validator_service.py)
  - Action: Add public `@classmethod def is_ip_blocked(cls, ip_str: str) -> bool: return cls._is_blocked_ip(ip_str)`.
- [ ] **Task 2.4: Update CrawlerService to use public security helper**
  - File: [`src/modules/scraping/services/crawler_service.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/modules/scraping/services/crawler_service.py)
  - Action: Replace `LinkValidatorService._is_blocked_ip(host)` with `LinkValidatorService.is_ip_blocked(host)`.
  - Verification: `uv run pytest tests/unit/modules/scraping/test_crawler_service.py`

---

## Phase 3: God Service Decomposition into Packages

### 3A. ScrapingRepository Decomposition
- [ ] **Task 3A.1: Create DTO module and `GrantDetailCreateInput`**
  - Target: `src/modules/core/database/repositories/scraping_repository/dto.py`
  - Action: Define `GrantDetailCreateInput` Pydantic model to eliminate the 19-parameter method signature.
- [ ] **Task 3A.2: Split repository methods into modular query components**
  - Target: `src/modules/core/database/repositories/scraping_repository/`
    - `operations.py` (run lifecycle, progress counters, error summary)
    - `sources.py` (source retrieval, configs, priority updates, distributed lock management)
    - `grants.py` (raw listings, grant details persistence using DTO)
    - `dead_letter.py` (DLQ records, retry transitions)
- [ ] **Task 3A.3: Expose ScrapingRepository public facade**
  - Target: `src/modules/core/database/repositories/scraping_repository/__init__.py`
  - Action: Assemble sub-components into `ScrapingRepository` class and export `GrantDetailCreateInput`.
  - Action: Delete old `src/modules/core/database/repositories/scraping_repository.py`.
  - Verification: `uv run pytest tests/integration/modules/scraping/`

### 3B. DiscoveryService Decomposition
- [ ] **Task 3B.1: Split discovery logic into sub-modules**
  - Target: `src/modules/scraping/services/discovery_service/`
    - `prompts.py` (XML prompt formatting and delimiter escaping)
    - `skeletonizer.py` (DOM noise pruning, comment stripping; replace `text=` with `string=`)
    - `relevance_gate.py` (Gemini Flash portal verification, classification)
    - `onboarding.py` (Stage 0 flow coordinator, robots.txt check, 2nd-hop crawl)
- [ ] **Task 3B.2: Expose DiscoveryService public facade**
  - Target: `src/modules/scraping/services/discovery_service/__init__.py`
  - Action: Assemble and export `DiscoveryService`.
  - Action: Delete old `src/modules/scraping/services/discovery_service.py`.
  - Verification: `uv run pytest tests/integration/modules/scraping/test_stage_0_discovery.py`

### 3C. TemplateEngineService Decomposition
- [ ] **Task 3C.1: Split template engine into sub-modules**
  - Target: `src/modules/scraping/services/template_engine_service/`
    - `matcher.py` (3-gate deterministic matching)
    - `micro_repair.py` (soft-drift detection, minimal DOM snippet, 4-stage validation)
    - `metrics.py` (rolling fill-rate calculations)
- [ ] **Task 3C.2: Expose TemplateEngineService public facade**
  - Target: `src/modules/scraping/services/template_engine_service/__init__.py`
  - Action: Assemble and export `TemplateEngineService`.
  - Action: Delete old `src/modules/scraping/services/template_engine_service.py`.
  - Verification: `uv run pytest tests/unit/modules/scraping/test_template_engine_service.py`

### 3D. ScraperService Decomposition
- [ ] **Task 3D.1: Split scraper coordinator into sub-modules**
  - Target: `src/modules/scraping/services/scraper_service/`
    - `lock_manager.py` (atomic locking, 30-min auto-reclamation)
    - `token_manager.py` (cancellation token registry, selective source abortion)
    - `catalog_phase.py` (Phase 1 Level 1 catalog crawl, lookahead progression)
    - `details_phase.py` (Phase 2 Level 2 details extraction, worker tasks, bilingual pairing, S3 ingestion)
    - `coordinator.py` (master batch orchestration, operation lifecycle, query facades)
- [ ] **Task 3D.2: Apply runtime safety and cancellation fixes**
  - Action: Enforce `(source_token is not None and source_token.is_set())` guards.
  - Action: Safe dereference on `hero_img` in `details_phase.py`.
  - Action: Re-raise task-level `asyncio.CancelledError` in `coordinator.py`.
- [ ] **Task 3D.3: Expose ScraperService public facade**
  - Target: `src/modules/scraping/services/scraper_service/__init__.py`
  - Action: Assemble and export `ScraperService`.
  - Action: Delete old `src/modules/scraping/services/scraper_service.py`.
  - Verification: `uv run pytest tests/integration/modules/scraping/test_batch_scrape_orchestration.py`

---

## Phase 4: API Protocols & Strict Typed Contracts
- [ ] **Task 4.1: Clean up redundant container definitions in route module**
  - File: [`src/api/routes/v1/scrape.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py)
  - Action: Delete duplicated `_singleton_scraper_service`, `get_scraper_service`, `get_discovery_service`.
  - Action: Import providers directly from [`src/api/protocols.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/protocols.py).
- [ ] **Task 4.2: Enforce typed response models on operation endpoints**
  - File: [`src/api/routes/v1/scrape.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py)
  - Action: Add `response_model=...` to `get_latest_operation` and `get_operation_by_id`.
  - Action: Return typed Pydantic models instead of untyped `dict[str, Any]`.
- [ ] **Task 4.3: Discontinue generic exception masking in Stage 0 onboarding**
  - File: [`src/api/routes/v1/scrape.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/src/api/routes/v1/scrape.py)
  - Action: Catch only expected domain exceptions; allow unexpected exceptions to trigger global 500 error handlers.

---

## Phase 5: Test Suite Optimization & Diagnostic Gate Verification
- [ ] **Task 5.1: Prune boilerplate Pydantic tests**
  - File: [`tests/unit/modules/scraping/test_models.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/unit/modules/scraping/test_models.py)
  - Action: Remove tests asserting standard field defaults and extra-field handling.
  - Action: Retain custom validator and edge-case tests.
- [ ] **Task 5.2: Verify test suite execution time**
  - Command: `uv run pytest tests/unit/modules/scraping/ tests/integration/modules/scraping/`
  - Criteria: Runtime must be $\le 15$ seconds.
- [ ] **Task 5.3: Run full diagnostic verification suite**
  - [ ] Ruff: `uv run ruff check src/ tests/` (0 errors)
  - [ ] Black: `uv run black --check src/ tests/` (0 files to reformat)
  - [ ] ArchUnit: `uv run pytest tests/architecture/ -v` (5/5 passing)
  - [ ] KG-ARCHMAP: `archmap analyze src --fail-on-cycles --fail-on-layer-violations` (Score $\ge 90$, Grade A)
  - [ ] Enola: `enola check . --fail-on=layers,cycles` (Clean pass)
  - [ ] Gitleaks: `gitleaks detect --source . -v` (0 leaks)
  - [ ] Trivy: `trivy fs . --scanners vuln --pkg-types library --severity HIGH,CRITICAL --skip-db-update`
  - [ ] Strict Ledger: `node /home/abood/.gemini/config/plugins/oh-my-antigravity/scripts/verify-ledger.js --mode strict` (0 issues)
