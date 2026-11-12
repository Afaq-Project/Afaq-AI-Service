# Use Cases & Behavioral Scenarios: Scraping & Extraction Pipeline

**Feature**: `002-scraping-extraction-pipeline`  
**Created**: 2026-11-05  
**Status**: Ready for Review  

---

## 1. Primary (Happy Path) Scenarios

### UC-01: End-to-End Autonomous Scraping Run (Catalog Discovery to Detail Ingestion)
* **Preconditions**: Target source `https://almin7.com/scholarships/` is registered, active, and unlocked in `source_configs` with a matching Level 1 and Level 2 template in `scraping_templates`.
* **Trigger**: Admin sends `POST /api/v1/scrape/run` with `source_ids: ["<source_id>"]`.
* **Expected System Behavior**:
  1. API returns `202 Accepted` with unique `operation_id`.
  2. Background task acquires atomic lock (`is_locked = true, locked_at = NOW()`).
  3. **Phase 1 (Catalog)**: Crawler navigates through catalog pages, extracts 20 opportunity card records, and upserts them into `raw_listings` with `status = "pending_detail_crawl"`.
  4. **Phase 2 (Details)**: Crawler iterates through all 20 records sequentially. Navigates to each detail page, extracts structured attributes (title, stipend, deadline, country) and rich descriptions, detects languages via n-grams, verifies application URLs, streams attachment PDFs to S3, and writes complete records into `raw_grant_details` with `status = "pending"`.
  5. Updates `raw_listings.status = "details_extracted"`.
  6. Releases source lock (`is_locked = false`), marks `scrape_operations.status = "completed"`, and dispatches completion webhook.
* **Postconditions**: 20 `raw_listings` in `details_extracted` state, 20 `raw_grant_details` in `pending` state ready for downstream cleaning, source lock released.

---

### UC-02: Zero-Configuration Stage 0 Portal Onboarding
* **Preconditions**: A newly discovered educational portal URL (`https://daad.de/scholarships/`) is submitted by an admin.
* **Trigger**: `POST /api/v1/scrape/sources/onboard` with URL payload.
* **Expected System Behavior**:
  1. Pre-flight health check validates RFC 3986 syntax and resolves public IP, confirming `HTTP 200 OK` and valid SSL.
  2. Fetches `robots.txt`, extracting `Crawl-delay` and declared XML sitemaps.
  3. Captures homepage DOM in headless Chromium with DNS pinning, strips noise, and collapses cards down to a 5 KB skeleton.
  4. Feeds skeletonized DOM wrapped in `<untrusted_web_content>` to Gemini Flash with relevance prompt.
  5. AI identifies portal name, languages (`["de", "en"]`), and catalog URL.
  6. Executes a conditional 2nd-hop crawl on the catalog URL to determine pagination mechanics (`pagination_type = "url_param"`).
  7. Inserts technical record into `source_configs` and activates `sources.is_active = true`.
* **Postconditions**: Source is onboarded and fully prepared for subsequent batch extractions.

---

### UC-03: Zero-AI Template Pool Hit (Layout Continuity)
* **Preconditions**: Source has 3 active historical templates in `scraping_templates` with varying `hit_count`.
* **Trigger**: Level 2 detail crawl encounters an incoming opportunity page.
* **Expected System Behavior**:
  1. Engine loads active templates ordered by `hit_count DESC`.
  2. Runs 3-gate deterministic test: Gate 1 verifies base container, Gate 2 asserts non-empty title and application link, Gate 3 confirms clean text bounds.
  3. Template matches successfully on Gate 3.
  4. Extracted data is parsed and stored with **zero LLM invocations**.
  5. Template `hit_count` increments and `last_successful_use_at` updates.
* **Postconditions**: Opportunity extracted rapidly with 0 API cost.

---

### UC-04: Native Bilingual Opportunity Pairing via `opportunity_group_id`
* **Preconditions**: Portal publishes opportunities in Arabic (`/ar/grant-101`) and English (`/en/grant-101`).
* **Trigger**: Pipeline scrapes both URLs during scheduled batch crawl.
* **Expected System Behavior**:
  1. Arabic page is crawled, extracted in native Arabic text, and saved with `title_language = "ar", body_language = "ar"`.
  2. English page is crawled, extracted in native English text, and saved with `title_language = "en", body_language = "en"`.
  3. Pipeline recognizes language switch relationship and assigns the exact same `opportunity_group_id: UUID` to both rows in `raw_grant_details`.
* **Postconditions**: Two raw records exist sharing the identical `opportunity_group_id`, enabling downstream cleaning to merge them into a single canonical opportunity with zero machine translation expense.

---

### UC-05: S3 Attachment Cache Reuse on Recurring Scrape
* **Preconditions**: Scholarship contains an official PDF application guide that was already downloaded and stored in S3 during a previous run.
* **Trigger**: Detail crawler encounters the same attachment URL.
* **Expected System Behavior**:
  1. Before downloading the 15 MB stream, crawler checks `raw_grant_details` for existing attachment metadata with that URL or derived S3 key.
  2. Existing valid S3 key and SHA-256 checksum are found.
  3. Crawler skips downloading the stream over the network.
  4. Sets `has_attachment = true` and copies the cached S3 metadata into the new extraction record.
* **Postconditions**: Record created with full attachment metadata; zero network bandwidth or duplicate S3 storage consumed.

---

## 2. Edge Cases & Boundary Scenarios

### UC-06: Incremental Lookahead Cutoff (Chronological Feed)
* **Preconditions**: Source catalog has 50 historical pages sorted chronologically (`ordering_strategy = "chronological_descending"`). Pages 1 through 10 were scraped previously.
* **Trigger**: Scheduled crawl runs on Page 1 and Page 2.
* **Expected System Behavior**:
  1. Page 1 returns 10 cards that all already exist in `raw_listings` (`consecutive_existing_pages = 1`).
  2. Lookahead advances to Page 2.
  3. Page 2 returns 10 cards that also all already exist in `raw_listings` (`consecutive_existing_pages = 2`).
  4. Lookahead threshold ($\ge 2$) is met: catalog traversal terminates immediately.
* **Postconditions**: Crawl finishes in 2 pages rather than scanning all 50 pages, saving 96% crawl time.

---

### UC-07: Circular and Stagnant Pagination Loop Traps
* **Preconditions**: Faulty portal web server redirects page 5 back to page 1, or continues returning page 4 content for all subsequent page parameters.
* **Trigger**: Catalog crawler navigates to paginated URLs.
* **Expected System Behavior**:
  1. Crawler normalizes card titles per page and computes a SHA-256 card fingerprint (`page_card_fingerprint`).
  2. When page 5 matches the first page's fingerprint (circular trap) or page 5 matches page 4's fingerprint (stagnant trap), the engine halts traversal immediately with an audit log.
* **Postconditions**: Pagination halts safely without exceeding operation timeouts or filling the database with duplicate listings.

---

### UC-08: Multi-Tab Detail Page Unhiding
* **Preconditions**: Portal places requirements under `.tab-pane` elements hidden with `display: none` or `visibility: hidden`.
* **Trigger**: Detail crawler navigates to scholarship URL.
* **Expected System Behavior**:
  1. Reads `source_configs.has_multi_tab_details == true`.
  2. Executes pre-extraction client-side script in Chromium to unhide all `.tab-pane` and `[role="tabpanel"]` elements.
  3. Evaluates Level 2 template against fully revealed DOM.
  4. All tabbed section contents (Eligibility, Benefits, Deadlines) are captured in the extraction payload.
* **Postconditions**: Complete scholarship data captured without missing hidden tab sections.

---

### UC-09: Multi-Page Article Tree Lineage & Depth Cap
* **Preconditions**: A long scholarship article spans 6 sequential sub-pages (`/grant/1`, `/grant/2`, ..., `/grant/6`).
* **Trigger**: Detail crawler navigates to the root article.
* **Expected System Behavior**:
  1. Crawler records Page 1 as the root node (`root_listing_id = id, parent_id = NULL, tree_depth = 0`).
  2. Sequentially crawls sub-pages 2 through 5, linking `parent_id` and recording `tree_depth = 1, 2, 3, 4`.
  3. Upon reaching depth 4 (5th page), the hard cap is reached. The crawler concatenates all 5 pages into a virtual DOM, extracts the complete article, logs an audit warning for sub-page 6, and halts recursion.
* **Postconditions**: Complete 5-page article parsed and linked hierarchically in `raw_listings`; runaway crawl loops eliminated.

---

### UC-10: Soft-Drift Detection & Micro-Repair Prompting
* **Preconditions**: Target portal renames its deadline container from `.deadline-date` to `.application-cutoff`. All other fields match existing template.
* **Trigger**: Crawler extracts scholarship detail page.
* **Expected System Behavior**:
  1. Template matches on 85% of fields (title, university, funding match), but deadline extraction yield drops.
  2. Rolling field metrics record fill-rate drop $>40\%$ for `deadline`.
  3. Engine sets `source_configs.drift_detected = true`.
  4. Dispatches targeted Micro-Repair prompt (~300 tokens) providing only the deadline snippet.
  5. AI generates updated CSS selector `.application-cutoff`.
  6. Updated schema saved as `v1.1` in `scraping_templates`. `drift_detected` reset to `false`.
* **Postconditions**: Selector healed autonomously with minimal token usage; template pool updated.

---

### UC-11: Idempotent Scrape Triggering
* **Preconditions**: Admin or automated cron script triggers `POST /api/v1/scrape/run` with `Idempotency-Key: "a1b2c3d4-..."`.
* **Trigger**: Network glitch causes client to retry the identical request 10 seconds later with the same key.
* **Expected System Behavior**:
  1. API checks `scrape_operations` for `idempotency_key = "a1b2c3d4-..."` started within 15 minutes.
  2. Finds active operation `7c9e6679-...`.
  3. Immediately returns `HTTP 200 OK` with the existing `operation_id` without spawning a second background task.
* **Postconditions**: Zero duplicate operations or conflicting crawler runs spawned.

---

## 3. Worst-Case & Failure Scenarios

### UC-12: Cloudflare Turnstile / CAPTCHA Challenge Interception
* **Preconditions**: Remote portal activates Cloudflare anti-bot challenge on crawler requests.
* **Trigger**: Crawler navigates to catalog entry URL.
* **Expected System Behavior**:
  1. DOM inspection detects challenge tokens (`cf-turnstile`, `challenges.cloudflare.com`).
  2. Intercepts event as `ERR_ACCESS_CHALLENGE_BLOCKED`.
  3. Increments `consecutive_failures` on `source_configs`.
  4. Sets `cool_down_until = NOW() + 1 hour` and releases source lock immediately.
  5. Halts operation without dispatching any AI prompts.
* **Postconditions**: Crawler exits cleanly without wasting LLM tokens or entering retry loops.

---

### UC-13: HTTP 429 Rate Limiting with `Retry-After` Header
* **Preconditions**: Target portal returns `HTTP 429 Too Many Requests` with `Retry-After: 600` (10 minutes).
* **Trigger**: Crawler requests detail page.
* **Expected System Behavior**:
  1. Response parser inspects `Retry-After` delay (600s $> 300$s threshold).
  2. Sets `source_configs.cool_down_until = NOW() + 600 seconds`.
  3. Aborts current source run cleanly with `ERR_RATE_LIMITED_COOLDOWN`.
  4. Releases source lock (`is_locked = false`).
* **Postconditions**: Source put in cooldown; crawler respects remote host politeness and moves to next source.

---

### UC-14: Hard Operation Timeout Breach (20-Minute Ceiling)
* **Preconditions**: Extremely slow remote server delays each HTTP response by 25 seconds, causing operation to exceed 1200 seconds.
* **Trigger**: `asyncio.wait_for` timeout triggers at the 20-minute mark.
* **Expected System Behavior**:
  1. Operation manager intercepts `TimeoutError`.
  2. Cancels active browser context cleanly and triggers `gc.collect()`.
  3. Updates `scrape_operations.status = "timed_out"` with error code `ERR_OPERATION_TIMEOUT`.
  4. Resets `source_configs.is_locked = false`.
* **Postconditions**: Process memory reclaimed, locks cleared, system remains fully operational for subsequent runs.

---

### UC-15: Abandoned Worker Lock Auto-Reclamation
* **Preconditions**: A previous worker process crashed violently (e.g. host power cut), leaving `is_locked = true` and `locked_at = NOW() - 45 minutes`.
* **Trigger**: New scrape operation runs.
* **Expected System Behavior**:
  1. Conditional lock query checks `locked_at < NOW() - INTERVAL '30 minutes'`.
  2. Identifies stale lock, breaks it, and acquires new lock: `is_locked = true, locked_at = NOW()`.
  3. Source executes normally.
* **Postconditions**: Abandoned lock reclaimed automatically with zero deadlocks.

---

### UC-16: Malicious File Type & Decompression Bomb Interception
* **Preconditions**: Scholarship application link points to an executable disguised as `application.pdf` or a 1000:1 zip bomb.
* **Trigger**: Attachment stream downloader inspects file stream.
* **Expected System Behavior**:
  1. Magic-byte inspector reads header: detects Windows executable signature `4D 5A` (`MZ`). Rejects immediately with `ERR_MALICIOUS_FILE_TYPE`.
  2. For zip archives: reads central directory metadata without decompressing; detects uncompressed footprint of 250 MB (exceeds 50 MB limit). Rejects with `ERR_ZIP_BOMB_DETECTED`.
  3. Terminates stream and discards file; does not upload to S3.
* **Postconditions**: System protected against malware persistence and resource exhaustion.

---

### UC-17: Dead Letter Queue (DLQ) Threshold Exhaustion
* **Preconditions**: A broken scholarship listing has failed extraction 2 times previously (`retry_count = 2`).
* **Trigger**: Third extraction attempt fails due to HTTP 404 Not Found.
* **Expected System Behavior**:
  1. Increments `retry_count` to 3.
  2. Evaluates `retry_count >= max_retries (3)`.
  3. Transitions record to `status = "failed_permanently"`.
  4. Records full stack trace and error timeline in `extraction_errors`.
* **Postconditions**: Record moved to DLQ; excluded from future automated runs while available for administrative review.

---

### UC-18: Querying Historical Operations Log & Polling Latest Operation
* **Preconditions**: Several scraping operations have been executed over time; one operation is currently running.
* **Trigger**: 
  1. Admin requests `GET /api/v1/scrape/operations?limit=10&status=completed`.
  2. Admin requests `GET /api/v1/scrape/operations/latest`.
* **Expected System Behavior**:
  1. For `GET /operations`: Queries `scrape_operations` table with pagination and status filters, returning total counts and summary metrics ordered by `started_at DESC`.
  2. For `GET /operations/latest`: Queries the database for any operation with `status = "running"`; if found, returns it with `is_currently_active = true`. If none is running, retrieves the most recent operation record ordered by `started_at DESC` with `is_currently_active = false`.
* **Postconditions**: Administrator obtains full operational visibility and identifies operation IDs without direct database access.

---

### UC-19: Gracefully Aborting an In-Progress Batch Operation
* **Preconditions**: A batch operation `op_123` is currently executing across 3 sources (`is_locked = true`).
* **Trigger**: Admin sends `POST /api/v1/scrape/operations/op_123/abort`.
* **Expected System Behavior**:
  1. Master orchestrator flags the cancellation token for operation `op_123`.
  2. The active crawler terminates ongoing Chromium page evaluations cleanly and triggers `gc.collect()`.
  3. Orchestrator executes lock release across all candidate sources: `UPDATE source_configs SET is_locked = false WHERE source_id IN (...)`.
  4. Updates operation record: `status = "aborted", completed_at = NOW()`.
  5. Returns `200 OK` confirming the abortion and count of released locks.
* **Postconditions**: Operation marked `aborted`, all browser processes terminated, all source locks released for future runs.

---

### UC-20: Selectively Halting an Individual Target Source
* **Preconditions**: A batch operation is actively scraping 4 sources. Source A (`src_001`) encounters an issue or the admin decides to stop it immediately, while Sources B, C, and D must continue.
* **Trigger**: Admin sends `POST /api/v1/scrape/sources/src_001/abort`.
* **Expected System Behavior**:
  1. Orchestrator signals the worker thread/task currently handling `src_001`.
  2. Crawler cancels browser evaluation for `src_001`, releases its lock (`is_locked = false`), and logs the aborted status in `scrape_operations.error_summary`.
  3. The batch orchestrator advances immediately to the next queued source (`src_002`) without terminating the overall operation.
* **Postconditions**: Source `src_001` is stopped and unlocked; batch operation continues executing remaining sources.
