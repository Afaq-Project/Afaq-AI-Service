# Feature Specification: Autonomous Crawl4AI Multi-Level Scraping & Raw Extraction Pipeline

**Feature Directory**: `specs/002-scraping-extraction-pipeline`  
**Feature Branch**: `feat/crawl4ai-adaptive-scraping`  
**Created**: 2026-11-05  
**Status**: Ready for Review  
**Input**: User description: "Scraping component: Two-level distinct templates (Level 1 catalog discovery & Level 2 scholarship details extraction), task management & concurrency control system with non-blocking 202 Accepted and atomic per-source locking, multi-source dynamic prioritization engine, zero-configuration Stage 0 discovery pass, multi-template pool with self-healing micro-repairs, bilingual dual-crawl pairing, and secure document streaming to AWS S3."

---

## Clarifications

### Session 2026-11-05
- Q: How should the scraping pipeline sequence Level 1 catalog discovery and Level 2 scholarship detail extraction during a scrape operation? → A: Option A: Sequential Two-Phase Execution — All Level 1 catalog pages are crawled first to discover and persist listings into `raw_listings` with status `pending_detail_crawl`, followed by sequential Level 2 detail extraction. This strict phase separation guarantees that no two scraping operations run simultaneously on the browser and that discovered URLs are safely persisted before heavy detail processing begins.
- Q: How should the document ingestion engine handle attachment downloads when an identical attachment link has already been downloaded and stored in S3 from a previous run? → A: Option A: S3 Cache Reuse — If an attachment URL or its derived S3 object key already exists in `raw_grant_details` with valid metadata (SHA256 checksum and S3 key), the system links the existing S3 metadata to the new record and skips downloading the file stream, saving bandwidth and storage costs.
- Q: What maximum sub-page traversal depth cap should the scraper enforce on multi-page scholarship articles to prevent infinite crawler loops? → A: Option A: Maximum 5 Sub-Pages (Tree Depth ≤ 4) — When `has_multi_page_details` is true, the engine traverses a maximum of 5 consecutive article pages, concatenates the body text into a single unified virtual DOM, and logs an audit notice if additional sub-pages exist beyond the cap.
- Q: Should the scraping trigger endpoint (POST /api/v1/scrape/run) support an optional max_pages parameter to override the default crawl depth for a single execution? → A: Option B: Strict Database Configuration — The trigger API payload omits ad-hoc `max_pages` overrides; crawl depth is strictly and consistently governed by `source_configs.max_pages_per_run` in the database to prevent unexpected long-running executions.
- Q: What minimum classification confidence threshold should the system require before assigning an ISO 639-1 language code, below which it tags the language as "und" (undetermined)? → A: Option B: Confidence < 0.50 → "und" — The language classifier uses a permissive 0.50 confidence threshold, tagging text as "und" only when the statistical model is below 50% certain (such as evenly split mixed languages or extreme ambiguity), ensuring most valid single-language content is categorized.

---

## 1. User Scenarios & Testing *(mandatory)*

### User Story 1 - Two-Level Specialized Template Extraction (Priority: P1)

As an autonomous scraping pipeline worker,  
I want to execute distinct Level 1 (catalog) and Level 2 (detail) page extraction workflows using specialized templates tailored to each page type,  
So that catalog listing pages yield opportunity card links and pagination metadata while scholarship detail pages extract rich educational attributes, requirements, and official application channels without structural cross-contamination.

* **Why this priority**: Fundamental core capability. Catalog listing pages and individual scholarship detail pages have fundamentally incompatible DOM layouts and data requirements; attempting a one-size-fits-all template results in extraction failures and lost opportunities.
* **Independent Test**: Can be tested independently by feeding a catalog listing HTML document to the Level 1 extraction engine (verifying extraction of opportunity card links, titles, thumbnail URLs, and next-page controls) and feeding an opportunity detail HTML page to the Level 2 extraction engine (verifying extraction of scholarship title, funding type, university/host, eligibility criteria, deadlines, and official application links).

**Acceptance Scenarios**:
1. **Given** a paginated educational portal catalog page, **When** processed with a Level 1 catalog template, **Then** the engine extracts an array of opportunity card records (each containing `discovered_url`, `card_title_preview`, optional `card_image_url`, and `listing_page_url`) and identifies the next-page pagination mechanism.
2. **Given** a direct scholarship opportunity detail page, **When** processed with a Level 2 detail template, **Then** the engine extracts structured scalar fields (title, host institution, country, degree level, financial coverage, deadline) and rich text descriptions, saving the unmutated extraction as raw publisher text.
3. **Given** a scholarship detail page featuring tabbed content containers (e.g., separate tabs for "Overview", "Eligibility", and "Benefits"), **When** the page is loaded, **Then** the browser executes client-side unhiding to make all tab panels visible simultaneously before extraction, ensuring all tab contents are captured in the final extraction payload.
4. **Given** a long scholarship announcement spanning multiple sequential sub-pages, **When** extracted, **Then** the system preserves parent-child tree lineage across pages up to a maximum cap of 5 sub-pages (depth $\le 4$) and concatenates article sections into a single complete record before downstream handoff.

---

### User Story 2 - Task Management, Concurrency Control & Dynamic Multi-Source Prioritization (Priority: P2)

As an operations manager or automated scheduler,  
I want to trigger scraping runs asynchronously with immediate non-blocking acknowledgment (`202 Accepted`), manage active runs with atomic per-source distributed locking, and automatically prioritize target sources based on administrative tier, staleness, and health,  
So that concurrent administrative requests never conflict or trigger duplicate browser sessions, crawl jobs execute safely within memory bounds, and high-priority or stale sources are processed first.

* **Why this priority**: Uncontrolled concurrent scraping requests can exhaust server resources, trigger memory crashes (exceeding the strict 1 GB RAM server limit), or spawn duplicate crawler sessions against the same host resulting in IP bans.
* **Independent Test**: Can be tested independently by submitting multiple concurrent scraping trigger requests (some targeting overlapping sources, others with `Idempotency-Key` headers), verifying non-blocking `202 Accepted` responses with unique operation tracking identifiers, verifying that already-locked sources are skipped safely, and asserting that the task dispatcher processes sources in order of their calculated priority score.

**Acceptance Scenarios**:
1. **Given** an administrative or automated trigger request to initiate scraping, **When** received, **Then** the system immediately returns `202 Accepted` with an `operation_id` tracking identifier and runs the scraping orchestrator in the background.
2. **Given** a trigger request bearing an `Idempotency-Key` header matching an operation initiated within the past 15 minutes, **When** received, **Then** the system returns the existing `operation_id` with `200 OK` without spawning duplicate background workflows.
3. **Given** a source currently undergoing an active crawl (`is_locked = true`), **When** another scraping request includes this source, **Then** the engine skips that source with a recorded lock notice, continuing to process other eligible sources without blocking.
4. **Given** an abandoned crawl where a source lock has remained active for more than 30 minutes, **When** a new crawl operation evaluates eligible sources, **Then** the stale lock is automatically broken and reset, allowing the source to be reclaimed.
5. **Given** multiple candidate sources awaiting crawl, **When** the task dispatcher schedules the run, **Then** sources are queued in descending order of dynamic priority score: $\text{Score} = (\text{Admin Tier} \times 100) + \text{Days Since Last Scrape} - (\text{Consecutive Failures} \times 10)$, with manual "Scrape Now" requests treated as highest-priority overrides.
6. **Given** a multi-source queue containing several targets from the same parent domain, **When** jobs are dispatched, **Then** the engine interleaves target domains to avoid hammering any single host consecutively.
7. **Given** an administrator wishing to review historical crawler activity, **When** querying past operations, **Then** the system returns a paginated list of operations with status, counts, and timing details without requiring an ID.
8. **Given** an administrator monitoring active crawler state, **When** requesting the latest operation without an ID, **Then** the system returns the currently running operation if active, or the most recently completed operation if idle.
9. **Given** an ongoing scraping operation that must be terminated, **When** an administrator issues an operation abort request, **Then** the engine gracefully cancels running browser contexts, releases all acquired source locks, and updates the operation status to `aborted`.
10. **Given** a specific target source causing issues in an ongoing batch, **When** an administrator halts that specific source, **Then** the engine terminates crawling for that source and releases its lock while allowing other queued sources in the batch to continue execution.

---

### User Story 3 - Stage 0 Zero-Configuration Source Onboarding & Relevance Verification (Priority: P3)

As a platform administrator,  
I want to onboard a target scholarship website simply by registering its entry URL,  
So that the system autonomously conducts pre-flight security inspections, analyzes website structure via DOM skeletonization, identifies official portal metadata, discovers catalog pagination mechanics, and verifies opportunity relevance before any extraction templates are generated.

* **Why this priority**: Eliminates manual selector engineering, replaces brittle hardcoded adapters, and acts as an early gatekeeper preventing expensive AI calls on irrelevant commercial blogs, expired domains, or parking pages.
* **Independent Test**: Can be tested independently by supplying entry URLs of valid scholarship portals, commercial e-commerce websites, and unreachable domains to the Stage 0 discovery pipeline, confirming automated population of technical crawler configuration (`source_configs`) for valid portals and immediate rejection with typed error codes for invalid targets.

**Acceptance Scenarios**:
1. **Given** a registered target website entry URL, **When** Stage 0 discovery initiates, **Then** the engine performs a pre-flight network health check (verifying RFC 3986 compliance, blocking private IP ranges, confirming HTTP 200 reachability, and reading `robots.txt` rate-limit delays) prior to launching any browser or AI calls.
2. **Given** a reachable web page, **When** the DOM is captured, **Then** the engine skeletonizes the HTML—stripping scripts, styling, tracking tags, and collapsing repetitive cards—compressing typical 1.5 MB payloads down to 3 KB–8 KB (~800–1,800 tokens) for token-efficient AI analysis.
3. **Given** the skeletonized DOM wrapped in untrusted data boundaries, **When** inspected by the AI platform analyzer, **Then** the analyzer verifies opportunity relevance; if the page is an irrelevant commercial blog or ad-farm, the system halts with `ERR_NOT_OPPORTUNITY_PORTAL` and deactivates the source.
4. **Given** a relevant scholarship portal whose entry URL is a homepage, **When** the analyzer discovers a distinct catalog/listing path, **Then** the engine executes a conditional second-hop crawl to inspect the catalog page and lock in its pagination mechanics (`pagination_type`, `pagination_config`, `wait_for_selector`) into `source_configs`.

---

### User Story 4 - Multi-Template Historical Pool & Self-Healing Micro-Repairs (Priority: P4)

As an adaptive scraping orchestrator,  
I want to match incoming web pages against a historical pool of known layout templates before invoking AI schema synthesis, and automatically repair localized selector drift when field fill-rates degrade,  
So that recurring page layouts are extracted with zero AI cost, and minor markup changes are repaired autonomously without discarding functioning selectors.

* **Why this priority**: Educational portals frequently rotate between 2 to 4 distinct article layouts (e.g., standard vs. sponsored articles, list vs. grid views). Re-synthesizing templates on every layout switch wastes LLM tokens, while throwing away entire templates for one broken selector creates needless fragility.
* **Independent Test**: Can be tested independently by running page extractions against mock DOMs matching historical templates (verifying fast deterministic matching with zero AI invocations), and testing mutated DOMs where a single non-mandatory field has shifted (verifying rolling fill-rate degradation detection and targeted micro-repair execution).

**Acceptance Scenarios**:
1. **Given** an HTML page to extract, **When** evaluated against the source's template pool, **Then** the engine tests candidate templates ordered by historical hit count using a 3-gate deterministic test (container existence, coverage threshold, text quality) without invoking AI.
2. **Given** a successful template match, **When** extraction completes, **Then** the template's `hit_count` is incremented, `last_successful_use_at` is updated, and rolling field fill-rate metrics are recorded in `scraping_templates.field_metrics`.
3. **Given** an active template where a single field's fill-rate drops by more than 40% below its historical baseline across consecutive runs (soft drift), **When** detected, **Then** the system dispatches a targeted micro-repair prompt (~300 tokens) to adjust only that failing selector, saving a new minor version (e.g., `v1.0` $\rightarrow$ `v1.1`) without re-synthesizing the entire schema.
4. **Given** a page layout where no historical template matches and soft drift repair is inapplicable (hard drift), **When** evaluated, **Then** the engine synthesizes a new schema via AI, subjects it to a 4-stage validation pipeline (syntax check, strict structural shape check forbidding unknown fields, CSS complexity/backtracking checks, and a 200 ms dry-run timeout), and adds the validated template to the permanent pool.

---

### User Story 5 - Bilingual Dual-Crawl Pairing & Secure Document Ingestion (Priority: P5)

As an educational data consumer and downstream cleaning pipeline,  
I want scholarships published in both Arabic and English to be captured natively and linked under a unified opportunity group identifier, while downloadable application forms are verified and streamed to secure cloud storage,  
So that international opportunities are available in their original publisher languages at zero translation cost, and official application guides (PDF/DOCX) are preserved permanently against link rot.

* **Why this priority**: Dual-language portals provide authoritative native text in both languages. Capturing both natively and pairing them eliminates expensive downstream machine translation. Furthermore, third-party download links frequently break; streaming documents to secure S3 storage guarantees long-term availability.
* **Independent Test**: Can be tested independently by scraping paired Arabic and English URLs for the same opportunity, asserting shared `opportunity_group_id` linking in raw storage, and supplying downloadable file links (PDFs, DOCX, and simulated zip bombs), confirming binary magic-byte verification, decompression safety checks, and S3 upload streaming.

**Acceptance Scenarios**:
1. **Given** an educational portal that publishes opportunities natively in Arabic and English, **When** both language versions are scraped, **Then** both raw records are persisted in `raw_grant_details` in their original languages, sharing the exact same `opportunity_group_id` UUID to allow zero-cost downstream deduplication.
2. **Given** an extracted opportunity containing an official application link pointing to a downloadable file (PDF/DOCX), **When** processed by the ingestion engine, **Then** the file stream is inspected for true binary magic bytes (`%PDF-`, `PK\x03\x04`), rejecting disguised executables or scripts with `ERR_MALICIOUS_FILE_TYPE`.
3. **Given** a downloadable archive document, **When** evaluated for decompression safety, **Then** the system inspects directory member metadata without full extraction, rejecting archives exceeding a 100:1 compression ratio or 50 MB uncompressed footprint with `ERR_ZIP_BOMB_DETECTED`.
4. **Given** a verified application document within the 25 MB stream limit, **When** validated, **Then** it is streamed directly to AWS S3 (`s3://{BUCKET}/attachments/{source_id}/{sha256}.ext`) with its S3 key, file size, mime-type, and SHA256 checksum recorded in raw extraction metadata. If the attachment link or S3 key is already recorded in the database, the system links the existing metadata and skips re-downloading.

---

### Edge Cases

* **Cloudflare Turnstile, CAPTCHA, or Bot Challenges:** When the browser encounters an access challenge page, the engine intercepts the challenge indicators in the DOM, classifies the event as `ERR_ACCESS_CHALLENGE_BLOCKED`, increments consecutive failure counters, triggers a source cool-down period, and aborts before dispatching any AI prompts.
* **HTTP 429 Rate Limiting with `Retry-After`:** When a remote server returns HTTP 429 or 503 with a `Retry-After` header: if the specified delay is $\le 300$ seconds, the worker pauses and retries; if the delay exceeds 300 seconds, the engine sets `cool_down_until = NOW() + delay`, aborts the current run cleanly (`ERR_RATE_LIMITED_COOLDOWN`), and immediately releases the source lock.
* **Circular and Stagnant Pagination Loops:** If a website repeatedly serves the same cards across pagination parameters or loops back to page 1, the engine computes a SHA256 fingerprint of normalized card titles per page. If the current fingerprint matches the previous page (stagnant) or the initial page (circular), pagination halts immediately.
* **Incremental Lookahead Cutoff:** On chronologically sorted catalogs, if two consecutive pages yield 100% already-known opportunity cards (`consecutive_existing_pages >= 2`), the catalog traversal terminates early, avoiding redundant crawling while tolerating sticky/pinned announcements on page 1.
* **Single-Browser Sequential Memory Cap ($\le 1$ GB Server Limit):** To prevent Linux Out-Of-Memory (OOM) kills on memory-constrained servers, the browser automation engine enforces `max_concurrent_crawls = 1`, launches Chromium with aggressive memory-pruning flags (`--disable-dev-shm-usage`, `--no-zygote`, `--disable-gpu`), explicitly disposes of browser contexts per page, and runs garbage collection to keep browser RAM strictly under 300 MB–450 MB.
* **Operation-Level Hard Timeout Ceiling:** Each source scrape operation is bound to a hard timeout ceiling (default 20 minutes / 1200 seconds). If breached, the operation aborts cleanly, records `status = "timed_out"` with `ERR_OPERATION_TIMEOUT`, and resets `is_locked = false`.
* **Database-Backed Dead Letter Queue (DLQ):** When individual listing or detail extractions fail, the system increments their `retry_count`. Once the count reaches `max_retries` (default 3), the record transitions to `failed_permanently`, preserving the full error history for administrative auditing without stalling the pipeline.

---

## 2. Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: System MUST perform autonomous Stage 0 discovery for newly registered sources, validating pre-flight network reachability, reading `robots.txt` rate-limit delays and sitemaps, skeletonizing the entry DOM, and persisting discovered technical settings into `source_configs`.
* **FR-002**: System MUST verify opportunity domain relevance during Stage 0 and Stage 4; if a website is an irrelevant commercial blog, ad-farm, or parking domain, the system MUST halt with `ERR_NOT_OPPORTUNITY_PORTAL` or `ERR_IRRELEVANT_CONTENT_REJECTED` and deactivate the source.
* **FR-003**: System MUST provide an asynchronous trigger endpoint (`POST /api/v1/scrape/run`) accepting optional `source_ids: list[str]`, returning an immediate `202 Accepted` response envelope with a unique `operation_id` tracking identifier, executing crawl orchestration via background tasks where catalog pagination depth is strictly governed by `source_configs.max_pages_per_run`.
* **FR-004**: System MUST support the `Idempotency-Key` HTTP header on trigger requests; if a key matches an operation started within the previous 15 minutes, the system MUST return the existing `operation_id` with `200 OK` without creating duplicate jobs.
* **FR-005**: System MUST enforce atomic per-source distributed locking (`is_locked: Boolean`, `locked_at: DateTime`) in `source_configs` to prevent concurrent crawl jobs on the same target website.
* **FR-006**: System MUST automatically release and reclaim any source lock whose `locked_at` timestamp exceeds 30 minutes to prevent deadlocks from crashed worker processes.
* **FR-007**: System MUST calculate dynamic multi-source priority scores using: $\text{Score} = (\text{Admin Tier} \times 100) + \text{Days Since Last Scrape} - (\text{Consecutive Failures} \times 10)$, processing the highest-scoring sources first while honoring manual administrative P0 overrides ("Scrape Now").
* **FR-008**: System MUST interleave domains when processing multi-source batches to prevent consecutive requests against the same remote host.
* **FR-009**: System MUST operate browser crawling sequentially (`max_concurrent_crawls = 1`) per server instance, launching headless Chromium with memory-conserving flags (`--disable-dev-shm-usage`, `--no-zygote`, `--disable-gpu`) and disposing of browser contexts per page to maintain total memory usage strictly within the 1 GB server threshold.
* **FR-010**: System MUST enforce an operation-level hard timeout ceiling (default 20 minutes) per source, terminating the job cleanly with `ERR_OPERATION_TIMEOUT` and releasing the source lock upon breach.
* **FR-011**: System MUST maintain distinct extraction templates categorized by hierarchy: Level 1 for catalog listing pages (extracting card arrays and pagination links) and Level 2 for opportunity detail pages (extracting full educational attributes, funding details, and application channels).
* **FR-012**: System MUST evaluate incoming pages against a source's historical template pool using a 3-gate deterministic test (container existence, coverage threshold, text quality) before triggering AI schema generation.
* **FR-013**: System MUST track rolling field fill-rate metrics in `scraping_templates.field_metrics`; when a non-mandatory field's fill-rate drops by $>40\%$ below baseline across runs (soft drift), the system MUST trigger a targeted micro-repair (~300 tokens) to update only the affected selector, saving a new minor version (e.g., `v1.0` $\rightarrow$ `v1.1`).
* **FR-014**: System MUST validate newly synthesized AI schemas through a 4-stage validation pipeline: JSON syntax check, strict structural schema validation (enforcing exact field shape and forbidding unexpected fields), CSS selector compilation and backtracking complexity linting, and a 200 ms dry-run timeout on sample DOM.
* **FR-015**: System MUST support dynamic catalog pagination via query parameters, URL path formatting, and next-button DOM selectors, stopping when encountering any of the 5 termination signals: absent/disabled next button, zero-card yield, circular card title fingerprint, stagnant card title fingerprint, or HTTP 404/410.
* **FR-016**: System MUST apply an incremental lookahead cutoff on chronologically ordered catalogs, halting traversal early when 2 consecutive pages contain 100% already-known opportunity cards.
* **FR-017**: System MUST execute client-side JavaScript to unhide all tabbed containers (`.tab-pane`, `[role="tabpanel"]`) on multi-tab detail pages before extraction.
* **FR-018**: System MUST support multi-page article tree hierarchies, recording child page records with `parent_id`, `root_listing_id`, and `tree_depth` up to a maximum cap of 5 sub-pages (tree depth $\le 4$), logging an audit notice if further pages exist, and concatenating all sub-page article sections into a single complete record.
* **FR-019**: System MUST record unmutated publisher text in raw storage tables, performing pure plain-text extraction for structured fields and safe HTML sanitization (purging executable scripts, inline handlers, and styling while preserving semantic readability) for rich descriptions.
* **FR-020**: System MUST perform statistical language classification using n-gram models on extracted text, recording ISO 639-1 language codes and classification confidence scores (tagging as `'und'` if confidence is below 0.50).
* **FR-021**: System MUST link natively published Arabic and English versions of the same opportunity under the exact same `opportunity_group_id` UUID in `raw_grant_details` to enable zero-cost downstream deduplication.
* **FR-022**: System MUST inspect external application links via the security gateway, enforcing Anti-SSRF private IP blocking, safe redirect traversal (max 5 hops), and circular redirect trapping.
* **FR-023**: System MUST stream-download downloadable application documents (PDF/DOCX) with a strict 25 MB limit, verify binary magic bytes (`%PDF-`, `PK\x03\x04`), reject decompression archive bombs (ratio $>100:1$ or uncompressed size $>50$ MB), and upload verified files to AWS S3. If an attachment URL or its derived S3 object key already exists in `raw_grant_details` with verified checksum metadata, the system MUST link the existing S3 metadata to the current record and skip downloading the stream.
* **FR-024**: System MUST maintain a database-backed dead letter queue (DLQ) in `raw_listings` and `raw_grant_details`, transitioning items exceeding `max_retries` (default 3) to `failed_permanently` with complete error logs.
* **FR-025**: System MUST compile execution summary telemetry in `scrape_operations` upon batch completion and dispatch a status webhook notification to the primary application service.
* **FR-026**: System MUST completely decommission and remove all legacy hardcoded scraper adapters (`Almin7Adapter`, `GrabScholarshipAdapter`, `Scholars4DevAdapter`, `WordPressApiAdapter`, `AdapterFactory`, `BaseAdapter`), replacing them with the autonomous multi-template pipeline.
* **FR-027**: System MUST execute scrape operations in strict sequential two-phase order per source: completing Phase 1 (Level 1 catalog traversal and persisting all discovered opportunity card links into `raw_listings` with `status = 'pending_detail_crawl'`) before initiating Phase 2 (sequential Level 2 detail extraction), ensuring zero simultaneous browser crawls and guaranteed persistence of discovered records.
* **FR-028**: System MUST provide an endpoint (`GET /api/v1/scrape/operations`) to list historical scraping operations with pagination (`limit`, `offset`), status filtering, and reverse-chronological ordering.
* **FR-029**: System MUST provide an endpoint (`GET /api/v1/scrape/operations/latest`) to retrieve the currently active operation or the most recent historical operation without requiring an `operation_id`.
* **FR-030**: System MUST provide an endpoint (`POST /api/v1/scrape/operations/{operation_id}/abort`) to gracefully terminate an ongoing operation, canceling browser contexts, releasing all acquired source locks, and setting the operation status to `aborted`.
* **FR-031**: System MUST provide an endpoint (`POST /api/v1/scrape/sources/{source_id}/abort`) to selectively halt scraping for a specific source, releasing its lock and marking its source-level status as aborted without interrupting the remaining sources in the active batch.

---

### Key Entities

* **Source**: The administrative registry of target websites, capturing entry URL, optional human label, and active status switch.
* **SourceConfig**: The autonomous technical crawling configuration per source, capturing discovered domain, official name, supported languages, pagination mechanics, rate limits, lock states (`is_locked`, `locked_at`), timeout ceilings, and health telemetry.
* **ScrapingTemplate**: The multi-template pool entity storing Level 1 (catalog) and Level 2 (detail) declarative schemas, layout signatures, version numbers, hit counts, and rolling field fill-rate metrics.
* **ScrapeOperation**: The batch audit and telemetry record capturing `operation_id`, idempotency key, run status (`running`, `completed`, `failed`, `partial`, `timed_out`, `aborted`), attempted/succeeded/failed source lists, counts of discovered listings, extracted details, downloaded files, and completion timestamps.
* **RawListing**: The Level 1 discovered opportunity card record, storing card preview snippets, thumbnail URLs, direct detail URLs (`discovered_url`), pagination origin, multi-page tree hierarchy (`parent_id`, `root_listing_id`, `tree_depth`), extraction retry counts, and dead-letter status.
* **RawGrantDetail**: The Level 2 comprehensive scholarship record, storing complete uncleaned publisher payloads, hero image URLs, detected title/body languages, shared `opportunity_group_id` bilingual pairing links, link verification statuses, and S3 attachment metadata.

---

## 3. Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: 100% of newly registered public scholarship portals complete autonomous Stage 0 technical mapping and catalog discovery without requiring manual selector engineering or code modification.
* **SC-002**: At least 85% of recurring crawl runs against active portals are successfully extracted using cached templates from the historical pool, incurring zero AI synthesis requests.
* **SC-003**: Memory consumption of the browser automation subsystem remains strictly below 500 MB RAM at all times during operation, preventing container eviction on memory-constrained servers ($\le 1$ GB total server RAM).
* **SC-004**: 100% of concurrent scraping trigger requests receive an immediate acknowledgment with a tracking identifier within 2 seconds, with zero duplicate executions occurring on currently active sources.
* **SC-005**: Dual-language scholarship listings published in both Arabic and English are successfully paired under a single shared group identifier in 100% of eligible extractions, requiring zero downstream translation overhead.
* **SC-006**: 100% of downloadable application documents and attachments undergo stream validation, successfully rejecting files that violate size limits (25 MB), mismatch their declared format, or exhibit archive bomb characteristics prior to persistent storage.
* **SC-007**: Routine incremental scraping operations against chronologically ordered catalogs terminate within 2 pages of already-known records, reducing redundant page traversals by at least 80% compared to full-catalog scans.
* **SC-008**: 100% of legacy hardcoded scraping adapters are safely decommissioned and replaced by the autonomous multi-template pipeline with zero regression in extraction coverage.

---

## 4. Assumptions & Scope Boundaries

### Assumptions
* **Public Educational Data Only**: Target scholarship portals provide publicly accessible listings and do not require authenticated user login sessions or commercial paywalls.
* **Upstream Infrastructure Availability**: Database persistence, AWS S3 bucket storage, and Gemini API services are provisioned and accessible with valid environment credentials.
* **Separation of Raw Extraction and Data Cleaning**: The scraping extraction pipeline is strictly responsible for capturing unmutated publisher content, establishing source provenance, and securing attachments; canonical data normalization, taxonomy mapping, and currency conversion are exclusively handled by downstream pipeline modules.
* **Network Politeness Over Completion Speed**: Remote web servers may apply rate limits; the pipeline prioritizes adherence to `Crawl-delay` and `Retry-After` backoff over execution speed.
* **Sequential Single-Process Concurrency**: Browser crawling operates on a sequential single-browser model per container instance; horizontal scaling across multiple instances is managed externally.

### Non-Goals & Out-of-Scope Boundaries
* **Paywall / Login Bypassing**: Automated bypassing of authentication gates, CAPTCHA solvers, or paywalls is strictly prohibited and out of scope.
* **Taxonomy Normalization & Data Cleaning**: Standardizing degree names, field-of-study categorizations, or normalizing funding amounts into base currencies is deferred to the downstream cleaning service.
* **Machine Translation of Non-Bilingual Portals**: Portals published exclusively in French, German, or single languages are stored in their native text without translation; machine translation is handled downstream.
* **Execution Time Assertions in Functional Tests**: In strict accordance with the Constitution, automated test suites will never assert execution time limits or latency SLAs; performance evaluation is restricted exclusively to user-configured k6 scripts.
