# Crawl4AI Adaptive Multi-Level Scraping & Raw Extraction Pipeline

## 1. Executive Summary & Architectural Decoupling

The Afaq opportunity ingestion architecture strictly decouples **Data Extraction** (Producer) from **Data Cleaning & Normalization** (Consumer).

* **The Extraction Module (Scope of this specification):**
  Responsible for discovering scholarship sources, executing modern browser-driven web crawls via `crawl4ai`, running deterministic multi-level extraction templates, autonomously repairing broken templates via AI, verifying link legitimacy, downloading attached documents (PDFs), and storing structured, uncleaned raw records in the database with `status = "pending"`.
* **The Cleaning & Normalization Module (Downstream Phase):**
  Asynchronously consumes pending raw records, maps synonyms to canonical backend taxonomies (`Countries`, `EducationLevel`, `Majors`, `Institutions`), translates content between Arabic and English, and populates the clean bilingual database tables.

```
[ External Web ]
       │
       ▼ (Crawl4AI: Headless Chromium + Stealth)
[ Level 1: Listing Crawl ] ──▶ Discovers Detail URLs ──▶ Stored in `raw_listings`
       │
       ▼ (Crawl4AI: Multi-page execution)
[ Level 2: Detail Crawl ]  ──▶ Extracts Full Scholarship ──▶ Stored in `raw_grant_details`
       │
       ├─▶ Link Legitimacy & Anti-Fraud Verification
       ├─▶ Document / PDF Stream Downloader
       └─▶ Language Detection (AR vs. EN)
       │
       ▼
[ Storage in Raw Tables with status = "pending" ]
       │
       ▼ (Future Phase)
[ Data Cleaning, Normalization & Translation Pipeline ]
```

---

## 2. Database Schema Design (Extraction Layer)

Four dedicated tables in PostgreSQL support this extraction pipeline without relying on miscellaneous JSON catch-alls for operational state.

### 2.1. `sources` (Scraping Source Catalog)
Reconfigured from legacy REST API assumptions to native web crawling:
* `id: UUID (PK)`
* `name: String (Unique)` — Identifier (e.g., `almin7`, `scholars4dev`).
* `display_name: String` — Human-readable label.
* `base_url: String` — Root domain URL.
* `listing_url: String` — Starting entry-point for the crawler (e.g., `https://almin7.com/scholarships/`).
* `domain: String` — Normalized domain for template indexing (`almin7.com`).
* `crawl_frequency: String` — Schedule (`daily`, `weekly`, `hourly`).
* `wait_for_selector: String?` — Optional CSS selector Crawl4AI waits for before parsing.
* `page_timeout_sec: Int` — Maximum page load timeout (default: 30s).
* `max_pages_per_run: Int` — Maximum listing pages to traverse per batch (default: 10).
* `level_1_template: Json` — Active JSON schema for listing catalog extraction.
* `level_2_template: Json` — Active JSON schema for individual detail extraction.
* `is_active: Boolean` — Admin toggle to enable/disable crawling.
* `drift_detected: Boolean` — Flagged when template failure or yield collapse occurs.
* `consecutive_failures: Int` — Failure counter for health alerts.
* `last_scraped_at: DateTime?`

### 2.2. `scrape_operations` (Batch Telemetry & Reporting)
Records high-level audit and monitoring metrics for every scrape run:
* `id: UUID (PK)` — The `operation_id` generated at job trigger.
* `status: String` — `running`, `completed`, `failed`, `partial`.
* `triggered_by: String` — `cron`, `admin_api`, `manual_retry`.
* `sources_attempted: String[]`
* `sources_succeeded: String[]`
* `sources_failed: String[]`
* `total_listings_found: Int` — Total Level 1 cards discovered.
* `total_details_extracted: Int` — Total Level 2 opportunities scraped.
* `total_files_downloaded: Int` — Total PDF/doc attachments persisted.
* `error_summary: Json` — Detailed breakdown of failure reasons per source.
* `started_at: DateTime`
* `completed_at: DateTime?`

### 2.3. `raw_listings` (Level 1 Catalog Extraction)
Stores discovered items from catalog pages, enabling isolated retries:
* `id: UUID (PK)`
* `operation_id: UUID (FK)` — References `scrape_operations.id`.
* `source_id: UUID (FK)` — References `sources.id`.
* `discovered_url: String` — Direct link to the opportunity detail page.
* `card_title_preview: String?` — Title snippet from the card.
* `card_snippet_preview: String?`
* `listing_page_url: String` — The paginated catalog URL where this card was found.
* `status: String` — `pending_detail_crawl`, `details_extracted`, `failed`.
* `scraped_at: DateTime`
* `created_at: DateTime`
* `CONSTRAINT unique_source_discovered_url UNIQUE (source_id, discovered_url)`

### 2.4. `raw_grant_details` (Level 2 Comprehensive Extraction)
Stores rich, uncleaned scholarship data and verification results:
* `id: UUID (PK)`
* `listing_id: UUID? (FK)` — References parent `raw_listings.id`.
* `operation_id: UUID (FK)` — References `scrape_operations.id`.
* `source_id: UUID (FK)` — References `sources.id`.
* `source_url: String` — Exact URL of the scraped scholarship page.
* `template_version: Int` — Version number of the template used for extraction.
* `raw_payload: Json` — Full structured extraction payload (title, university, funding, eligibility, deadline, etc.).
* `detected_language: String` — `ar` or `en`.
* `link_verification_status: String` — `verified`, `suspicious`, `unreachable`, `file_download`.
* `final_application_url: String?` — Resolved destination URL after redirects.
* `is_legitimate_domain: Boolean?`
* `has_attachment: Boolean` — Default `false`.
* `attachment_metadata: Json?` — File path, type, size, SHA256 hash.
* `status: String` — `pending` (awaiting cleaning), `processing`, `cleaned`, `failed`.
* `error_message: String?`
* `scraped_at: DateTime`
* `created_at: DateTime`

---

## 3. End-to-End Pipeline Stage Breakdown

### Stage 1: Triggering & Operation Tracking
* **Entry Point:** `POST /api/v1/scrape/run` (optionally accepts `source_ids: list[str]`).
* **Execution Flow:**
  1. Generates a new `operation_id = uuid4()`.
  2. Queries active sources from database (`is_active == true`).
  3. Inserts a new record into `scrape_operations` with `status = "running"`.
  4. Returns `HTTP 202 Accepted` immediately with `{"status": "accepted", "operation_id": "...", "message": "..."}`.
  5. Launches the asynchronous background scraping worker (`BackgroundTasks`).

### Stage 2: Crawl4AI Core Engine Configuration
* **Crawler Implementation:** Uses `crawl4ai.AsyncWebCrawler` inside an async context manager.
* **Resilience & Politeness Defaults:**
  * **Headless Browser:** Modern Chromium instance managed by Crawl4AI.
  * **User-Agent Rotation:** Standard modern desktop browser profiles.
  * **Rate Limiting:** Random jitter delay (2.0 to 4.5 seconds) between page fetches to protect source servers and prevent Cloudflare/IP rate-limiting.
  * **Timeouts:** 30-second navigation timeout per page; 60-second circuit-breaker per source.

### Stage 3: Multi-Level Template Extraction

#### Level 1: Catalog Crawl & Discovery
1. The crawler visits the `Source.listing_url`.
2. Loads `Source.level_1_template` (`JsonCssExtractionStrategy`).
3. Executes extraction on the page DOM:
   * Extracts container cards: `base_selector`.
   * Extracts item fields: `title`, `discovered_url`, `date_preview`.
   * Extracts pagination link: `next_page_selector`.
4. Saves all newly discovered URLs into `raw_listings`. If a URL already exists, it is deduplicated via `ON CONFLICT DO NOTHING`.

#### Level 2: Comprehensive Detail Extraction
1. For every pending listing discovered, the crawler navigates to `discovered_url`.
2. Loads `Source.level_2_template` (`JsonCssExtractionStrategy`).
3. Extracts full scholarship fields:
   * `title`, `university_name`, `university_url`, `official_apply_url`
   * `description`, `funding_type_raw`, `stipend_raw`, `accommodation_raw`
   * `eligibility_criteria_raw`, `gpa_raw`, `study_levels_raw`, `fields_of_study_raw`
   * `deadline_raw`, `country_raw`
4. Assembles the structured JSON object and passes it to verification and storage.

### Stage 4: Autonomous Schema Generation & Self-Healing Loop
When a template does not exist (cold start) or structural drift is detected:

```
[ Extraction Yield = 0 OR Mandatory Fields Missing ]
                     │
                     ▼
        [ Trigger Self-Healing Loop ]
                     │
                     ▼
      [ Crawl4AI: Fetch Cleaned HTML Sample ]
                     │
                     ▼
[ JsonCssExtractionStrategy.agenerate_schema() via Gemini LLM ]
                     │
                     ▼
            [ Validation Gate ]
     - Container matched >= 1 element?
     - Title is non-empty string?
     - Apply URL or Source URL present?
          │                     │
        Passed                Failed
          │                     │
          ▼                     ▼
[ Update Source Template ]   [ Fallback to LLMExtractionStrategy & Alert ]
[ Reset drift_detected ]
```

1. **Detection:** A source is flagged as `drift_detected = true` if:
   * Level 1 yields 0 items where items were previously expected.
   * Level 2 returns null for mandatory fields (`title` or `official_apply_url` / `source_url`).
2. **Autonomous Generation:** Invokes `JsonCssExtractionStrategy.agenerate_schema` passing the cleaned HTML DOM, canonical target JSON schema, and Gemini configuration.
3. **Dry-Run Validation Gate:** Runs the candidate schema against the fetched sample. If it extracts the mandatory fields, it is automatically written to `Source.level_1_template` or `level_2_template`.
4. **Resumption:** Scraping immediately resumes using the newly persisted template without human intervention or application redeployment.

### Stage 5: Link Legitimacy, Anti-Fraud & Document Download Handling
Before saving the extracted Level 2 record:

#### 1. Link Verification & Anti-Fraud
* Executes an asynchronous `HEAD` or lightweight `GET` request following HTTP redirects.
* Discovers the `final_application_url`.
* **Checks:**
  * Valid SSL certificate.
  * HTTP status returns `200 OK`.
  * Detects and flags suspicious ad-redirects, known scam referral domains, or landing pages asking for unauthorized payment.
* Stores verification status: `verified`, `suspicious`, or `unreachable`.

#### 2. File / PDF Attachment Handling
* If the destination URL or `Content-Type` header indicates a downloadable file (`application/pdf`, `.docx`):
  1. Streams and downloads the document to persistent local storage (`storage/attachments/{source_id}/{file_hash}.pdf`).
  2. Computes the SHA256 checksum to prevent duplicate storage.
  3. Records `has_attachment = true` with full path, size, and mime-type in `raw_grant_details.attachment_metadata`.

### Stage 6: Language Determination & Bilingual Routing
* **Script Frequency Analysis:** Evaluates the extracted text using Unicode range checks:
  * Arabic block: `[\u0600-\u06FF]`.
  * If Arabic character count exceeds 30% of total letters, `detected_language = "ar"`.
  * Otherwise, `detected_language = "en"`.
* Recorded on `raw_grant_details` so the downstream cleaning module knows whether to translate from AR $\rightarrow$ EN or EN $\rightarrow$ AR.

### Stage 7: Downstream Handoff (The Producer-Consumer Contract)
* Once Level 2 extraction, link verification, and language detection are complete:
  * A record is inserted into `raw_grant_details` with `status = "pending"`.
  * The parent `raw_listings` record is updated to `status = "details_extracted"`.
* **Operation Finalization:**
  * When all sources in the batch finish, `scrape_operations` is marked `status = "completed"`.
  * The webhook client sends a structured `ScrapeCompletePayload` containing the `operation_id`, total counts, and succeeded/failed source lists to the primary backend.

---

## 4. Dependencies & Technical Requirements

| Component | Library / Tool | Purpose |
| :--- | :--- | :--- |
| **Web Crawler** | `crawl4ai>=0.9.4` | Modern async browser automation, anti-bot handling, and cleaned DOM retrieval |
| **Browser Engine** | Playwright / Chromium | Headless browser execution environment |
| **LLM Provider** | Google Gemini (`google-generativeai`) | Schema synthesis via `agenerate_schema` |
| **Database ORM** | Prisma Client Python (`prisma`) | Schema migrations, type-safe queries, connection pooling |
| **Direct DB Reads** | `asyncpg` | High-speed concurrent reads and bulk operations |
| **File Storage** | Local volume / S3 compatible | Persistent document/PDF attachments storage |

---

## 5. Phased Implementation Roadmap

* **Phase 1: Schema Updates & Database Migration:**
  Create tables `scrape_operations`, `raw_listings`, `raw_grant_details`, and update `sources` in `prisma/schema.prisma`.
* **Phase 2: Crawl4AI Crawler Wrapper:**
  Implement `Crawl4AiCrawler` with browser initialization, proxy/user-agent settings, and rate-limiting delays.
* **Phase 3: Multi-Level Template Engine & Generator:**
  Implement `TemplateEngine` supporting Level 1 & Level 2 `JsonCssExtractionStrategy`, template validation gates, and Gemini-backed `agenerate_schema`.
* **Phase 4: Link Verifier & File Downloader:**
  Implement `LinkVerificationService` (redirect follower, fraud detection) and `DocumentStorageService` (stream downloading, SHA256 deduplication).
* **Phase 5: Orchestrator Integration & Unit Testing:**
  Update `ScraperService` to run the end-to-end pipeline, record metrics in `scrape_operations`, and cover edge cases with unit tests following `AGENT.md`.
