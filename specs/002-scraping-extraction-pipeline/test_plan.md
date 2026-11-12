# Test Plan: Scraping & Extraction Pipeline

**Feature**: `002-scraping-extraction-pipeline`  
**Created**: 2026-11-05  
**Status**: Ready for Review  

---

## 1. Testing Philosophy & Constitution Compliance

In strict accordance with **Constitution v2.4.0 (Principles II, III, VI & VII)**:
1. **1-to-1 Traceability**: Every single use case defined in [`use_cases.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/specs/002-scraping-extraction-pipeline/use_cases.md) (UC-01 through UC-17) is mapped 1-to-1 to an automated test case in this plan.
2. **Strict Test Separation**:
   * **Unit Tests (`tests/unit/modules/scraping/`)**: Test individual domain services, prioritization scoring, template matching, language detection, and schema validation with in-memory fixtures and mocked clients (zero live network, zero live database).
   * **Integration Tests (`tests/integration/modules/scraping/`)**: Test end-to-end multi-step crawling workflows, database repository transactions, and background task dispatching using `httpx.MockTransport` and local test database fixtures.
3. **Prohibition of Execution Time Assertions (Principle VI)**:
   * **No test case will assert or enforce execution time thresholds, latency SLAs, or duration expectations.**
   * External web interactions and network responses are inherently unpredictable; enforcing latency limits produces brittle tests. Performance evaluation is restricted exclusively to user-configured k6 scripts.

---

## 2. 1-to-1 Use Case Test Traceability Matrix

| Test ID | Target Component | Verifying Use Case | Description & Verification Invariants |
| :--- | :--- | :--- | :--- |
| **TEST-01** | `ScraperService` | **UC-01** (Happy Path Batch) | Verify sequential two-phase batch crawl: Level 1 catalog URLs saved to `raw_listings`, followed by sequential Level 2 extraction into `raw_grant_details`. |
| **TEST-02** | `DiscoveryService` | **UC-02** (Zero-Config Stage 0) | Verify pre-flight check, `robots.txt` parsing, DOM skeletonization, relevance validation, and `source_configs` population. |
| **TEST-03** | `TemplateEngineService` | **UC-03** (Zero-AI Template Hit) | Verify 3-gate deterministic test matches cached template, increments `hit_count`, and extracts fields with zero AI calls. |
| **TEST-04** | `ScraperService` | **UC-04** (Bilingual Pairing) | Verify native Arabic and English detail extractions share the identical `opportunity_group_id: UUID` in `raw_grant_details`. |
| **TEST-05** | `DocumentIngestionService` | **UC-05** (S3 Cache Reuse) | Verify that when an attachment URL already exists in `raw_grant_details`, the download stream is skipped and existing S3 metadata is linked. |
| **TEST-06** | `PaginationService` | **UC-06** (Lookahead Cutoff) | Verify that 2 consecutive pages of 100% existing cards trigger early catalog termination on chronologically ordered feeds. |
| **TEST-07** | `PaginationService` | **UC-07** (Loop & Stagnation) | Verify that identical card title fingerprints (circular loop or stagnant page) halt catalog traversal immediately. |
| **TEST-08** | `CrawlerService` | **UC-08** (Multi-Tab Unhiding) | Verify that when `has_multi_tab_details == true`, client-side script unhides `.tab-pane` and `[role="tabpanel"]` prior to DOM extraction. |
| **TEST-09** | `CrawlerService` | **UC-09** (Multi-Page Tree & Cap) | Verify multi-page article lineage tracking (`parent_id`, `root_listing_id`, `tree_depth`) and enforce 5-page depth cap ($\le 4$). |
| **TEST-10** | `TemplateEngineService` | **UC-10** (Soft-Drift Micro-Repair) | Verify that a $>40\%$ fill-rate drop on a single selector triggers a targeted micro-repair prompt, producing a `v1.1` template schema. |
| **TEST-11** | `ScrapeRouter` | **UC-11** (Idempotency Key) | Verify that retrying `POST /api/v1/scrape/run` with the same `Idempotency-Key` within 15 minutes returns `200 OK` with the existing `operation_id`. |
| **TEST-12** | `CrawlerService` | **UC-12** (Cloudflare Interception) | Verify that DOM bot challenge tokens raise `ERR_ACCESS_CHALLENGE_BLOCKED`, set source cooldown, and halt without AI calls. |
| **TEST-13** | `CrawlerService` | **UC-13** (HTTP 429 Backoff) | Verify that `Retry-After: 600` response sets `cool_down_until = NOW() + 600s`, raises `ERR_RATE_LIMITED_COOLDOWN`, and releases lock. |
| **TEST-14** | `ScraperService` | **UC-14** (20-Min Operation Timeout) | Verify that operation-level hard timeout cleanly aborts active browser context, records `status = "timed_out"`, and clears locks. |
| **TEST-15** | `SourceRepository` | **UC-15** (Lock Auto-Reclamation) | Verify that a source locked for $>30$ minutes is automatically reclaimed by the conditional check-and-set query. |
| **TEST-16** | `DocumentIngestionService` | **UC-16** (File Safety Gates) | Verify that disguised executables (`MZ` header) and zip bombs ($>100:1$ ratio) are rejected before S3 upload. |
| **TEST-17** | `ScraperService` | **UC-17** (DLQ Exhaustion) | Verify that records failing 3 extraction attempts transition to `status = "failed_permanently"` with stack traces in `extraction_errors`. |
| **TEST-18** | `ScraperService` / Route | **UC-18** (Operations Log & Latest) | Verify paginated historical operations query and verify `GET /operations/latest` returns running operation or latest completed run without ID. |
| **TEST-19** | `ScraperService` / Route | **UC-19** (Abort Operation) | Verify `POST /operations/{id}/abort` terminates active browser contexts, releases all source locks, and sets operation status to `aborted`. |
| **TEST-20** | `ScraperService` / Route | **UC-20** (Halt Single Source) | Verify `POST /sources/{id}/abort` halts crawling for specific source, releases its lock, and allows remaining batch sources to continue. |

---

## 3. Dedicated Unit Test Suites (`tests/unit/modules/scraping/`)

### 3.1. `test_prioritization_service.py`
* Tests dynamic scoring formula across multiple sources with varying tiers, days since scrape, and failure counts.
* Tests domain interleaving ensuring no two consecutive jobs target the same remote domain.
* Tests manual P0 override ("Scrape Now") ensuring requested sources jump to the head of the queue.

### 3.2. `test_language_classifier_service.py`
* Tests statistical n-gram classification on Arabic, English, French, and German opportunity texts.
* Tests independent classification of `title_language` and `body_language`.
* Tests confidence threshold ($<0.50 \rightarrow \text{"und"}$).

### 3.3. `test_template_engine_service.py`
* Tests 3-gate deterministic evaluation against sample DOMs.
* Tests rolling fill-rate metric updates in `field_metrics`.
* Tests soft-drift micro-repair prompt generation and minor version incrementing.
* Tests 4-stage validation pipeline for newly synthesized AI schemas (JSON syntax, shape, CSS linter, 200 ms timeout).

### 3.4. `test_pagination_service.py`
* Tests query param (`?page=N`), path param (`/page/N/`), and next-button selector traversal.
* Tests 5 termination signals: disabled button, empty cards, circular loop, stagnant loop, HTTP 404.
* Tests 2-page lookahead window on chronologically sorted catalogs.

---

## 4. Dedicated Integration Test Suites (`tests/integration/modules/scraping/`)

### 4.1. `test_batch_scrape_orchestration.py`
* Uses mocked HTTP transport (`httpx.MockTransport`) and mock browser driver.
* Tests complete lifecycle: `POST /api/v1/scrape/run` $\rightarrow$ atomic source lock $\rightarrow$ Level 1 catalog discovery $\rightarrow$ Level 2 detail crawl $\rightarrow$ S3 streaming $\rightarrow$ lock release $\rightarrow$ webhook notification.

### 4.2. `test_stage_0_discovery.py`
* Tests Stage 0 onboarding flow on valid educational portals, irrelevant commercial blogs (`ERR_NOT_OPPORTUNITY_PORTAL`), and unreachable domains.

### 4.3. `test_dead_letter_queue.py`
* Tests retry increments on transient failures and final dead-letter isolation upon reaching `max_retries = 3`.
