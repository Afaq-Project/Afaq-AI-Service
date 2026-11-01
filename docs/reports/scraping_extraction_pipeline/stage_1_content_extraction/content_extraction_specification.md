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

## 3. The 3-Gate Deterministic Template-Matching Engine (Zero LLM Cost)

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

## 4. Sample-Anchored DOM Pruning (Token Minimization)

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

---

## 5. Soft-Drift Micro-Repair (`v1.0` $\rightarrow$ `v1.1`) vs. Hard Drift (`v2.0`)

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

## 6. Scholarship Image Extraction (`image_url`)

Images are required for displaying opportunity cards and detail banners on the Afaq portal:

* **Level 1 (Card Thumbnail):**
  * Extracted from the catalog card: `img.wp-post-image[src]`, `img.thumbnail[src]`, or background-image CSS style.
  * Stored in `raw_listings.card_image_url`.
* **Level 2 (Detail Hero Image):**
  * Extracted from the main article banner: `article img.featured[src]`, `div.post-thumbnail img[src]`, or OpenGraph meta tags:
    `<meta property="og:image" content="...">`.
  * Stored in `raw_grant_details.image_url`.
* **Sanitization & URL Resolution:**
  * Relative image paths (`/uploads/2026/05/scholarship.jpg`) are automatically resolved to absolute URLs via `urljoin(base_url, img_src)`.
  * Strips data-URIs, base64 blobs, 1x1 tracking pixels, gravatars, and SVG icons.

---

## 7. Handling Advanced Platform Rendering Quirks

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

### 2. Multi-Page In-Article Pagination (`has_multi_page_details == true`)
* **The Challenge:** WordPress `<!--nextpage-->` divides long articles into `/page/2/`, `/page/3/`.
* **The Solution:** The engine inspects `subpage_pagination_selector`, crawls each sub-page URL sequentially, concatenates the article body containers into a single virtual DOM, and executes the Level 2 extraction on the unified document.

### 3. Alternative Application Channels (Mailto / Phone)
* If no web application portal exists, the extractor captures `mailto:admissions@univ.edu` or `tel:+123456789` links, labeling the contact method appropriately in `raw_payload`.

### 4. Unstructured / Rolling Deadlines
* If a deadline reads "Rolling basis", "Open until filled", or "متاح حتى اكتمال المقاعد", the raw text is preserved in `deadline_raw` without triggering date-parsing exceptions.

### 5. Obfuscated / Hashed CSS Classes
* Prompt instructions strictly guide the LLM to generate resilient selectors using semantic tag hierarchy, attribute containment (`[class*="deadline"]`), and adjacent sibling selectors (`h3:contains("Deadline") + p`) rather than fragile randomized hashes.

---

## 8. Database Persistence & Telemetry

### Level 1 Insertion (`raw_listings`):
```sql
INSERT INTO raw_listings (
    operation_id,
    source_id,
    discovered_url,
    card_title_preview,
    card_snippet_preview,
    card_image_url,
    listing_page_url,
    status,
    scraped_at,
    created_at
) VALUES (
    :operation_id, :source_id, :discovered_url, :card_title_preview,
    :card_snippet_preview, :card_image_url, :listing_page_url,
    'pending_detail_crawl', NOW(), NOW()
) ON CONFLICT (source_id, discovered_url) DO NOTHING;
```

### Level 2 Insertion (`raw_grant_details`):
```sql
INSERT INTO raw_grant_details (
    listing_id,
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
    scraped_at,
    created_at
) VALUES (
    :listing_id, :operation_id, :source_id, :template_id, :source_url,
    :template_version, :raw_payload, :image_url, :detected_language,
    'pending_verification', 'pending', NOW(), NOW()
);

UPDATE raw_listings 
SET status = 'details_extracted' 
WHERE id = :listing_id;
```

---

## 9. Module Structure in the Codebase

This stage is isolated in `src/modules/scraping/extraction/`:

```
src/modules/scraping/extraction/
├── __init__.py
├── template_matcher.py        # 3-Gate Deterministic Matching Engine
├── dom_pruner.py              # Sample-Anchored Pruning & Truncation
├── schema_generator.py        # Crawl4AI + Gemini agenerate_schema wrapper
├── micro_repair_service.py    # Soft-Drift Selector Repair (v1.0 -> v1.1)
├── multi_tab_handler.py       # JS Tab unhiding and multi-page concatenation
├── extraction_pipeline.py     # Orchestrator: Level 1 -> Level 2 extraction
└── models.py                  # Pydantic schemas for templates, extraction payloads & drift
```
