# Stage 1 Specification: Content Extraction & Template Creation

## 1. Stage Objective & Operational Boundaries

Stage 1 is the **Data Extraction, Pulling & Template Management** engine of the Afaq scraping pipeline.

### Operational Boundaries:
* **What this stage DOES:**
  * Uses the configuration established in Stage 0 (`source_configs`) to drive `crawl4ai` across the platform's catalog and detail pages.
  * Tests pages against the source's **Template Pool** to achieve zero-LLM execution for recurring and known page layouts.
  * Employs **Sample-Anchored DOM Pruning** to minimize token consumption while preserving the semantic clues required by AI.
  * Synthesizes new declarative extraction templates via Gemini Flash when existing templates fail or soft drift occurs.
  * Enforces an automated **Soft-Drift Micro-Repair** routine (`v1.0` $\rightarrow$ `v1.1`) to fix individual broken selectors without regenerating entire templates.
  * Extracts scholarship featured image URLs (`image_url`) at both listing and detail levels.
  * Handles advanced platform quirks identified in Stage 0 (multi-tab scholarship panels and in-article pagination).
  * Enforces mandatory security gates (`src/modules/security/`): validates URLs via `LinkValidator`, sanitizes plain text and rich descriptions via `ContentSanitizer`, and validates image URLs and attachment streams via `FileValidator`.
  * Persists extracted data into `raw_listings` and `raw_grant_details` with `status = "pending"`.
* **What this stage DOES NOT do:**
  * It does **not** perform canonical taxonomy mapping (e.g. mapping "Postgraduate" to `EducationLevel` UUIDs).
  * It does **not** translate content between Arabic and English.
  * (These responsibilities belong strictly to the downstream Data Cleaning Module).

---

## 2. Complete Stage 1 Extraction Architecture

```
[ Trigger Scrape Job: Source ID ]
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ LEVEL 1: LISTING CATALOG CRAWL & PULLING                    │
│ 1. Crawl source_configs.catalog_url via Crawl4AI            │
│ 2. Check Level 1 Template Pool (hit_count DESC)             │
│    ├── Match Found? ──▶ Execute JsonCssExtractionStrategy   │
│    └── Match Failed? ─▶ Prune DOM ➔ Generate L1 Schema      │
│ 3. Follow Dynamic Pagination (URL params / Next button)     │
│ 4. Insert discovered items into `raw_listings`              │
└─────────────────────────────────────────────────────────────┘
               │
               ▼ (Pending listings discovered)
┌─────────────────────────────────────────────────────────────┐
│ LEVEL 2: COMPREHENSIVE DETAIL CRAWL                         │
│ For each raw_listing where status = 'pending_detail_crawl': │
│ 1. Check Stage 0 Flags (Multi-Tab / Multi-Page)             │
│    ├── has_multi_tab_details: Run JS Tab Activation         │
│    └── has_multi_page_details: Concatenate Sub-pages        │
│ 2. Check Level 2 Template Pool                              │
│    ├── Match Found? ──▶ Extract Full Opportunity Payload    │
│    └── Match Failed? ─▶ Analyze Drift Type                  │
│         ├── Soft Drift (>=85% valid): Micro-Repair v1.1     │
│         └── Hard Drift (<85% valid): Synthesize L2 v2.0     │
│ 3. Extract Image URL (Hero image or og:image)               │
│ 4. Save to `raw_grant_details` with status = 'pending'      │
│ 5. Update `raw_listings.status = 'details_extracted'`       │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Bilingual Platform Extraction Strategy (Native Dual-Crawl)

When Stage 0 discovers that a platform natively supports both Arabic and English (`source_configs.supported_languages = ["ar", "en"]`), the extraction pipeline executes a **Native Dual-Crawl** rather than relying on artificial translation:

### A. The Alternate Language Resolver
When crawling a detail page (e.g. Arabic):
1. **Priority 1 (`hreflang` Tag):** Reads `<link rel="alternate" hreflang="en" href="...">` from the `<head>` of the page.
2. **Priority 2 (Language Toggle in DOM):** Extracts link from the header/footer toggle button (e.g., `a.lang-en[href]`).
3. **Priority 3 (URL Rewrite Rule):** Applies the rule discovered in Stage 0 (e.g., swapping `/ar/` for `/en/` or appending `?lang=en`).

### B. Template Reusability Across Languages
* **Universal Structure:** Modern CMS engines (WordPress WPML/Polylang, Drupal, Next.js) share identical HTML/CSS selectors across language versions—only text content and text direction (`dir="rtl"` vs `dir="ltr"`) change. Selectors (`h1.entry-title`, `div.deadline`, `a.apply-button`) remain identical.
* **Validation:** The engine tests the active template against the alternate language DOM. If it passes the 3-Gate Test, it extracts immediately. If the alternate language uses a distinct layout, a language-specific template (`language = "en"`) is pulled from `scraping_templates`.

### C. Shared `opportunity_group_id` Linking
* The crawler fetches and extracts the Arabic page $\rightarrow$ saves with `detected_language = "ar"`.
* The crawler fetches and extracts the English page $\rightarrow$ saves with `detected_language = "en"`.
* **Both raw records are linked with the exact same `opportunity_group_id: UUID`**.
* **Zero Translation Cost Benefit:** When native Arabic and English versions are scraped directly from the publisher, the downstream Cleaning Module skips calling the Translation API entirely, achieving 100% native translation quality at zero extra cost.

---

## 4. Dynamic Pagination Engine (`page`, `limit`, `offset` & Stop Conditions)

Level 1 catalog crawling traverses all available opportunity cards using the pagination rules in `source_configs.pagination_config`:

### A. Supported Pagination Models:
1. **Query Parameter Pagination (`page` & `limit`):**
   * Pattern: `?page=N&limit=50` or `?paged=N`.
   * **Page Size Expansion (`limit`):** If Stage 0 verified that the portal accepts `limit=50` or `per_page=50`, the crawler passes this parameter. This pulls 50 items per HTTP request instead of 10, reducing total network calls by **5x–10x**.
2. **Path Parameter Pagination:**
   * Pattern: `/scholarships/page/{page}/` (e.g., `/page/1/`, `/page/2/`).
3. **Offset & Count Pagination:**
   * Pattern: `?offset=N&count=50` (increments `offset += limit`).
4. **Next-Button DOM Link:**
   * Crawl4AI extracts the `href` attribute from `.pagination a.next, a[rel="next"]`.

### B. The 5 Deterministic Catalog Termination & Cutoff Signals:
The engine identifies that it has reached the end of the catalog and that no further new content exists through five automated signals:

1. **DOM Next-Button Absence / Disabled State:**
   * For platforms using next-button traversal, Crawl4AI checks the selector configured in `pagination_config.selector` (e.g., `.pagination a.next`).
   * On the final page, this element either completely disappears from the DOM (`0` elements found) or bears disabled attributes/classes (`disabled`, `aria-disabled="true"`, `.disabled`, `.page-nav-end`). Traversal stops immediately.
2. **Zero-Yield State (Empty Catalog Container):**
   * For URL parameter pagination (`?page=15` when only 14 pages exist), the server returns HTTP 200, but the list container yields zero opportunity cards (`len(soup.select(base_selector)) == 0`).
   * The DOM often displays empty-state markers (e.g., *"No opportunities found"*, *"لا توجد نتائج"*). Traversal halts after this confirmation.
3. **Circular Redirect & Duplicate Page Fingerprinting (The CMS Loop Trap):**
   * Many platforms (particularly WordPress) do not return an error when you exceed the last page; instead, they silently redirect back to **Page 1** or repeat the contents of the last valid page.
   * **Detection:** The engine tracks an in-memory set of the URLs extracted on Page 1 (`first_page_card_urls`).
   * If Page $N$ returns cards whose URLs are **100% identical** to Page 1 or identical to Page $N-1$, the engine flags a circular loop trap and terminates catalog crawling.
4. **HTTP 404 / 410 Response Codes:**
   * Platforms using path pagination (`/scholarships/page/15/`) often return `HTTP 404 Not Found` or `410 Gone` when the page index is exceeded.
   * The crawler treats 404 on page $N > 1$ as a normal catalog termination signal, closing the loop cleanly.
5. **Incremental Database Cutoff (Detecting No "NEW" Content):**
   * Scholarship listings are almost universally ordered chronologically (`newest first`).
   * During recurring scheduled runs, the engine checks whether all opportunity links discovered on Page $N$ already exist in `raw_listings`.
   * If **100% of the cards on Page $N$ are already in the database**, all subsequent pages ($N+1$, $N+2$) contain even older historical records that were already ingested in past runs.
   * Traversal halts early, typically completing a recurring crawl in under 15 seconds.

### C. Execution Loop Code Implementation:
```python
current_page = pagination_config.get("start_page", 1)
max_pages = source_configs.max_pages_per_run or 10
consecutive_empty_pages = 0
first_page_card_urls = set()

while current_page <= max_pages:
    # 1. Construct & Security-Validate paginated URL
    url = build_paginated_url(catalog_url, current_page, pagination_config)
    validated_url = await LinkValidator.validate_url(url)
    
    # 2. Crawl & Extract Level 1 Cards via active template
    cards = extract_level_1_listings(validated_url.canonical_url, level_1_template)
    card_urls = {c["discovered_url"] for c in cards}
    
    # 3. Stop Signal: Zero-Yield (Empty Catalog)
    if len(cards) == 0:
        consecutive_empty_pages += 1
        if consecutive_empty_pages >= 2:
            logger.info("Catalog container empty on page %d; reached catalog end.", current_page)
            break
            
    # 4. Stop Signal: Circular Redirect / Duplicate Fingerprint
    if current_page == 1:
        first_page_card_urls = card_urls
    elif card_urls == first_page_card_urls:
        logger.info("Page %d redirected to page 1; terminating catalog crawl.", current_page)
        break
        
    # 5. Stop Signal: Incremental Crawl Cutoff (No NEW Content)
    if all_cards_already_in_db(card_urls, source_id):
        logger.info("All cards on page %d are already in DB; stopping incremental crawl.", current_page)
        break
        
    # 6. Save newly discovered cards and advance
    save_raw_listings(cards)
    current_page += pagination_config.get("step", 1)
```

---

## 5. The 3-Gate Deterministic Template-Matching Engine (Zero LLM Cost)

Before invoking the AI, the engine tests the fetched page against the source's stored template pool in `scraping_templates` ordered by `hit_count DESC`:

### Gate 1: Container Existence
* Checks whether the template's root container selector (e.g., `article.post`, `.scholarship-card`) exists in the page DOM.
* If `soup.select(base_selector)` returns `0` elements $\rightarrow$ **FAIL**.

### Gate 2: Mandatory Fields Coverage
* **Level 1 (Listing):** The schema must extract $\ge 1$ item, and every item must contain a non-empty `title` and a valid `discovered_url`.
* **Level 2 (Detail):** The schema must extract a non-empty `title` AND at least one valid action link (`official_apply_url` or `source_url`).
* If mandatory fields return `None` or empty strings $\rightarrow$ **FAIL**.

### Gate 3: Data Quality Check
* Verifies extracted values are not corrupted:
  * Title length between 5 and 250 characters.
  * Extracted text does not contain raw HTML tags (`<div...>`, `<script...>`).
* **Outcome:** If all 3 gates pass, the template is confirmed. It extracts the structured JSON immediately with **0 tokens consumed**, increments `hit_count`, and updates `last_successful_use_at`. If any gate fails, the engine tests the next template in the pool.

---

## 6. Sample-Anchored DOM Pruning (Token Minimization)

When template synthesis or repair is required, raw HTML (1MB–3MB) is pruned before being passed to the LLM.

### The Sample-Anchoring Rule:
* **Why complete text stripping fails:** Modern web frameworks render generic tags (e.g., `<div class="elementor-widget-container"></div>`). If text is removed, the deadline, university name, and funding amount look identical.
* **The Solution:**
  1. **Short Leaf Text Preserved:** Leaf nodes under 100 characters (titles, dates, numbers, university names, field labels) are **retained as semantic anchors**.
  2. **Prose Truncated:** Body descriptions longer than 60 characters are truncated:
     `<p class="desc">The Clarendon Fund offers full scholarships to academically outstanding...</p>`
     becomes:
     `<p class="desc">The Clarendon Fund offers full scholarships to...</p>`.
  3. **Aggressive Blacklist:** Completely strips `<script>`, `<style>`, `<svg>`, `<canvas>`, `<iframe>`, social sharing bars, comment sections, related post widgets, ad units, and top-level headers/footers.

*Token Reduction:* Compresses 1.5MB pages down to **8KB–18KB (~2,000–3,500 tokens)**, retaining 100% of the semantic anchors the LLM needs to deduce exact selectors.

### Security Wrapping & Template Validation:
* **Prompt Shielding:** All pruned DOM payloads sent to Gemini Flash are wrapped inside `<untrusted_web_content>` isolation boundaries via `ContentSanitizer.wrap_untrusted_prompt()`, preventing prompt injection from third-party HTML.
* **Schema Verification:** Any newly synthesized or repaired template schema must pass `ContentSanitizer.validate_template_schema()` before persisting into `scraping_templates`, verifying CSS selectors and disallowing malicious XPath constructs (`ERR_INVALID_TEMPLATE_SCHEMA`).

---

## 7. Soft-Drift Micro-Repair (`v1.0` $\rightarrow$ `v1.1`) vs. Hard Drift (`v2.0`)

When a template fails on a detail page, the engine evaluates the degree of failure to prevent unnecessary template bloat and excessive token expenditure:

### Evaluation Criteria:
$$\text{Field Success Rate} = \frac{\text{Successfully Extracted Fields}}{\text{Total Fields in Schema}}$$

### Case A: Soft Drift (Field Success Rate $\ge 85\%$)
* **Condition:** Mandatory fields (`title`, `application_url`) succeeded, but 1 or 2 secondary fields failed (e.g. `stipend` changed class from `div.stipend-amount` to `div.allowance-box`).
* **Micro-Repair Protocol:**
  1. The system does **not** regenerate the full template.
  2. It constructs a targeted **Micro-Repair Prompt** containing only:
     * The missing field name (`stipend`).
     * The broken selector (`div.stipend-amount`).
     * A narrow 500-token HTML slice surrounding the content.
  3. The LLM returns **only** the single corrected selector string (`div.allowance-box`).
  4. The engine runs a dry-run test on the sample page.
  5. Upon success, performs an **in-place patch**:
     `template_schema["fields"]["stipend"] = "div.allowance-box"`
     Increments version from `v1.0` $\rightarrow$ `v1.1` and updates `scraping_templates`.
* **Token Cost:** ~300 tokens (vs. ~3,500 tokens for full synthesis).

### Case B: Hard Drift (Field Success Rate $< 85\%$ or Container Missing)
* **Condition:** The page layout changed fundamentally (e.g. site switched from blog article layout to interactive web application layout).
* **Protocol:** Triggers full schema synthesis via `crawl4ai.JsonCssExtractionStrategy.agenerate_schema`, runs the dry-run validation gate, and stores a new template in the pool as `v2.0`.
* **Pool Management:** Each source retains a maximum of **4 to 6 active templates**. If a new template is added, the template with the lowest `hit_count` that has been inactive for >30 days is deprecated.

---

## 8. Scholarship Image Extraction (`image_url`)

Images are required for displaying opportunity cards and detail banners on the Afaq portal:

* **Level 1 (Card Thumbnail):**
  * Extracted from the catalog card: `img.wp-post-image[src]`, `img.thumbnail[src]`, or background-image CSS style.
  * Stored in `raw_listings.card_image_url`.
* **Level 2 (Detail Hero Image):**
  * Extracted from the main article banner: `article img.featured[src]`, `div.post-thumbnail img[src]`, or OpenGraph meta tags:
    `<meta property="og:image" content="...">`.
  * Stored in `raw_grant_details.image_url`.
* **Sanitization, Anti-SSRF & URL Resolution:**
  * Relative image paths (`/uploads/2026/05/scholarship.jpg`) are automatically resolved to absolute URLs via `urljoin(base_url, img_src)`.
  * Verified through `FileValidator.validate_image_url()`: strictly enforces allowed raster/modern image types (`jpg`, `jpeg`, `png`, `webp`, `avif`).
  * Rejects data-URIs, base64 blobs, 1x1 tracking pixels, gravatars, and un-sanitized SVG vectors (`ERR_INVALID_IMAGE_TYPE`).
  * Verified against Anti-SSRF rules to ensure image hosting does not target private or cloud metadata IPs.

---

## 9. Handling Advanced Platform Rendering Quirks

Stage 1 leverages the structural flags discovered during Stage 0 (`source_configs`):

### 1. Multi-Tab Scholarship Panels (`has_multi_tab_details == true`)
* **The Challenge:** Platforms often place Overview in Tab 1, Eligibility in Tab 2, and the Application Link in Tab 3. Inactive tabs are hidden (`display: none`).
* **The Solution:** Crawl4AI executes a pre-extraction JavaScript snippet:
  ```javascript
  // Unhide all tab panels and activate all tab contents
  document.querySelectorAll('.tab-pane, [role="tabpanel"], .elementor-tab-content').forEach(el => {
    el.style.display = 'block';
    el.classList.add('active', 'show');
  });
  ```
  If panels require DOM hydration via click events, Crawl4AI executes sequential clicks across `source_configs.tab_container_selector` prior to extracting the DOM snapshot.

### 2. Multi-Page In-Article Pagination & Tree-Based Lineage (`has_multi_page_details == true`)
* **The Challenge:** WordPress `<!--nextpage-->` and similar CMS plugins divide long articles into sub-pages: `/scholarship/`, `/scholarship/2/`, `/scholarship/3/`. Without structured lineage, extracted sections become fragmented and disconnected from their source.
* **The Tree-Based Lineage Solution:**
  1. **Root Page Registration:** The initial article entry page is inserted into `raw_listings` as the root node of the tree:
     * `parent_id = NULL`
     * `root_listing_id = id`
     * `page_number = 1`
     * `tree_depth = 0`
  2. **Sequential Child Crawl (Single-Browser Context):**
     * The crawler parses `source_configs.subpage_pagination_selector` to discover ordered sub-page links.
     * Pages are fetched sequentially (enforcing the single-browser constraint to protect memory).
     * Each discovered sub-page is inserted into `raw_listings` as a child node referencing its immediate parent and root:
       * `parent_id = previous_subpage_id`
       * `root_listing_id = root_id`
       * `page_number = N`
       * `tree_depth = N - 1`
  3. **Virtual DOM Concatenation:**
     * The main article body containers from all child sub-pages are stitched together into a single, unified virtual DOM.
     * Level 2 extraction executes on the concatenated DOM, ensuring all requirements, guidelines, and application links are captured without loss.
  4. **Data Origin Transparency:**
     * Downstream cleaning and admin verification can trace any extracted paragraph back to the exact sub-page URL where it originated via the tree hierarchy in `raw_listings`.

### 3. Alternative Application Channels (Mailto / Phone)
* If no web application portal exists, the extractor captures `mailto:admissions@univ.edu` or `tel:+123456789` links, labeling the contact method appropriately in `raw_payload`.

### 4. Unstructured / Rolling Deadlines
* If a deadline reads "Rolling basis", "Open until filled", or "متاح حتى اكتمال المقاعد", the raw text is preserved in `deadline_raw` without triggering date-parsing exceptions.

### 5. Obfuscated / Hashed CSS Classes
* Prompt instructions strictly guide the LLM to generate resilient selectors using semantic tag hierarchy, attribute containment (`[class*="deadline"]`), and adjacent sibling selectors (`h3:contains("Deadline") + p`) rather than fragile randomized hashes.

---

## 10. Database Persistence & Sanitization Gateway

Before inserting any data into the database, all extracted payloads pass through the **Security & Validation Gateway** (`src/modules/security/`):
* **Plain Text Purity:** Every structured string field (`title`, `organization`, `stipend`, `deadline_raw`, `country`, `degree_levels`) is sanitized via `ContentSanitizer.to_clean_text()`, stripping tags and normalizing Unicode.
* **Safe Descriptions:** Multi-paragraph description fields inside `raw_payload` are parsed with Rust `nh3` via `ContentSanitizer.sanitize_html()`, removing scripts, inline styles, and unapproved HTML attributes.
* **Image URL Inspection:** Verified with `FileValidator.validate_image_url()`.

### Level 1 Insertion (`raw_listings` with Tree Lineage):
```sql
INSERT INTO raw_listings (
    operation_id,
    source_id,
    parent_id,
    root_listing_id,
    page_number,
    tree_depth,
    discovered_url,
    card_title_preview,
    card_snippet_preview,
    card_image_url,
    listing_page_url,
    status,
    retry_count,
    max_retries,
    scraped_at,
    created_at
) VALUES (
    :operation_id, :source_id, :parent_id, :root_listing_id,
    :page_number, :tree_depth, :discovered_url, :card_title_preview,
    :card_snippet_preview, :card_image_url, :listing_page_url,
    'pending_detail_crawl', 0, 3, NOW(), NOW()
) ON CONFLICT (source_id, discovered_url) DO NOTHING;
```

### Level 2 Insertion (`raw_grant_details` & Database DLQ):
```sql
INSERT INTO raw_grant_details (
    listing_id,
    opportunity_group_id,
    operation_id,
    source_id,
    template_id,
    source_url,
    template_version,
    raw_payload,
    image_url,
    detected_language,
    link_verification_status,
    status,
    retry_count,
    max_retries,
    scraped_at,
    created_at
) VALUES (
    :listing_id, :opportunity_group_id, :operation_id, :source_id,
    :template_id, :source_url, :template_version, :raw_payload,
    :image_url, :detected_language, 'pending_verification',
    'pending', 0, 3, NOW(), NOW()
);

UPDATE raw_listings 
SET status = 'details_extracted' 
WHERE id = :listing_id;
```

### Database-Backed Dead Letter Queue (DLQ) Lifecycle:
* When an extraction fails:
  * The worker increments `retry_count = retry_count + 1`.
  * If `retry_count < max_retries`: sets `status = 'failed'` and logs the error in `extraction_errors`.
  * If `retry_count >= max_retries`: permanently dead-letters the record by setting `status = 'failed_permanently'`.
  * Isolates unrecoverable failures without blocking the pipeline or crashing worker memory.

---

## 11. Module Structure in the Codebase

This stage is isolated in `src/modules/scraping/extraction/` and coordinates with the mandatory security module:

```
src/modules/
├── security/                  # Mandatory System-Wide Security Gateway
│   ├── link_validator.py      # Anti-SSRF, DNS Pinning & Circular Redirect Trap
│   ├── content_sanitizer.py   # Plain-Text Stripper, Safe HTML (nh3) & Prompt Shielding
│   ├── file_validator.py      # Pre-S3 Magic Byte Inspection & Stream Download Limits
│   ├── models.py              # ValidatedUrl & ValidatedFile Pydantic contracts
│   └── exceptions.py          # SecurityValidationError & machine error codes
│
└── scraping/extraction/       # Data Extraction & Template Subsystem
    ├── __init__.py
    ├── template_matcher.py    # 3-Gate Deterministic Matching Engine
    ├── dom_pruner.py          # Sample-Anchored Pruning & Truncation
    ├── schema_generator.py    # Crawl4AI + Gemini agenerate_schema wrapper
    ├── micro_repair_service.py# Soft-Drift Selector Repair (v1.0 -> v1.1)
    ├── multi_tab_handler.py   # JS Tab unhiding and multi-page concatenation
    ├── extraction_pipeline.py # Orchestrator: Level 1 -> Level 2 extraction
    └── models.py              # Pydantic schemas for templates, extraction payloads & drift
```
