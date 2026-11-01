# Stage 0 Specification: Source Discovery & Architectural Mapping

## 1. Stage Objective & Operational Boundaries

Stage 0 is the **Zero-Configuration Onboarding & Architectural Mapping** phase of the Afaq scraping pipeline.

### Operational Boundaries:
* **What this stage DOES:**
  * Validates network reachability and SSL security of the administrator-provided URL.
  * Crawls the platform entry-point using `crawl4ai` in stealth headless mode.
  * Strips away page noise, text bodies, and redundant elements to create a lean structural DOM skeleton.
  * Uses AI with a strict content-relevance gate to map the platform’s navigation hierarchy, determine supported languages, pinpoint where the opportunity catalog resides (`catalog_url`), deduce pagination mechanics, and detect advanced layout patterns (multi-tab articles and multi-page single scholarship layouts).
  * Executes a conditional 2nd-hop crawl if the entry URL was a portal homepage to lock in pagination rules and inspect detail page rendering patterns.
  * Populates the decoupled `source_configs` table.
* **What this stage DOES NOT do:**
  * It does **not** extract individual scholarship cards or listings.
  * It does **not** scrape opportunity detail pages.
  * It does **not** generate Level 1 or Level 2 extraction templates (which belongs exclusively to the subsequent extraction phase).

---

## 2. Complete Stage 0 Pipeline Workflow

```
[ Admin inputs Target URL into `sources` ]
                     │
                     ▼
[ Step 1: Pre-flight URL & Network Health Gate ] ──▶ Fail? ──▶ [ Abort: Mark Source Inactive + Error ] (0 AI Cost)
                     │ Passed
                     ▼
[ Step 2: Crawl4AI Initial Entry Fetch ] ────────▶ Blocked? ──▶ [ Abort: ERR_ACCESS_CHALLENGE_BLOCKED ]
                     │ Clean DOM
                     ▼
[ Step 3: DOM Skeletonization & Pruning ] ───────▶ (Compresses 1.5MB HTML to 4KB-8KB structural skeleton)
                     │
                     ▼
[ Step 4: AI Architectural Analysis & Relevance Gate ]
                     │
         Is it an opportunity portal?
         ├── NO  ──▶ [ Abort: ERR_NOT_OPPORTUNITY_PORTAL ] (Source deactivated, alert logged)
         └── YES ──▶ Deduces: Site Name, Languages, Catalog Path
                     │
[ Step 5: Conditional 2nd-Hop Crawl ]
  - Entry URL already has Catalog + Pagination? ──▶ [ Skip 2nd Hop ]
  - Entry URL is Root Homepage? ─────────────────▶ [ Crawl Discovered catalog_url to Lock Pagination ]
                     │
                     ▼
[ Step 6: Database Persistence ]
  (Insert/Update `source_configs` with discovered metadata + set `sources.is_active = true`)
```

---

## 3. Step-by-Step Technical Breakdown

### Step 1: Pre-flight URL & Network Health Gate (Zero AI Cost)
Before initializing browser drivers or passing content to LLMs, the system passes the admin-provided URL through the mandatory security gateway (`LinkValidator.validate_url` from `src/modules/security/`):
1. **URL Sanitization & Syntax:** Validates RFC 3986 format, normalizes hostnames, and enforces allowed schemes (`http`, `https`) and ports (`80`, `443`). Rejects non-standard protocols (`file:`, `data:`, `gopher:`) and port tampering (`ERR_INVALID_SCHEME`, `ERR_INVALID_PORT`).
2. **Anti-Homograph & Path Traversal Verification:** Detects mixed-script IDN homograph spoofing (`ERR_HOMOGRAPH_ATTACK`) and rejects path traversal sequences like `../` or `..%2f` (`ERR_PATH_TRAVERSAL`).
3. **Anti-SSRF & DNS Pinning:** Resolves target domain to its underlying IP addresses before dispatching requests. Blocks private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), local loopback (`127.0.0.1`), and AWS metadata (`169.254.169.254`). Rejects with `ERR_SSRF_ATTEMPT_BLOCKED`.
4. **Connectivity, SSL & Circular Redirect Traversal:** Sends an asynchronous `HEAD` (or lightweight `GET` fallback) request following HTTP redirects up to a maximum of 5 hops:
   * Traps circular/infinite redirect loops (`ERR_CIRCULAR_REDIRECT`).
   * Ensures no intermediate redirect points to private/internal IPs.
   * Destination must return `HTTP 200 OK` with a valid, unexpired SSL certificate.
   * Total network timeout is capped at 10 seconds.
5. **Dead Domain & Parking Page Traps:**
   * Identifies DNS resolution failures (`NXDOMAIN`).
   * Intercepts parked domain signatures, domain-for-sale splash screens, or default web server screens (e.g. "Apache2 Default Page", "cPanel Default Page").
6. **Immediate Exit:** If unreachable, invalid, or flagged as dead/dangerous, sets `sources.is_active = false`, logs `last_error = error_code` (e.g., `"ERR_SSRF_ATTEMPT_BLOCKED"`, `"ERR_URL_UNREACHABLE"`), and stops immediately without consuming browser or AI compute.

### Step 2: Crawl4AI Entry Crawl & Anti-Bot Defense
The verified URL is fetched using `crawl4ai.AsyncWebCrawler`:
* **Browser Runtime:** Headless Chromium with modern desktop viewport (1920x1080).
* **Stealth Configuration:** Standard desktop User-Agent rotation, navigator override, and automated Cloudflare challenge detection.
* **Wait Strategy:** Configured to wait for DOM completion (`networkidle` or 3-second settled state).
* **Bot Challenge Check:** Inspects the returned page title and DOM for challenge indicators (e.g., "Just a moment...", "Cloudflare Turnstile", "ddos protection"). If blocked, flags `ERR_ACCESS_CHALLENGE_BLOCKED`.

### Step 3: DOM Skeletonization & Pruning Algorithm
To minimize LLM token consumption while preserving the architecture, the raw HTML is transformed into an **Architectural Skeleton**:

#### A. Elements Aggressively Stripped (Blacklist):
* All `<script>`, `<style>`, `<noscript>`, `<iframe>`, `<svg>`, `<canvas>`, `<video>`, `<audio>`, `<link rel="stylesheet">`.
* All inline styling (`style="..."`), event listeners (`onclick`, `onload`), tracking data (`data-gtm`, `data-analytics`).
* Elements with `display: none`, `visibility: hidden`, or `aria-hidden="true"`.
* Base64 image data and tracking pixels.
* All deep article paragraphs, blog commentary, author bios, and advertisement sidebars.

#### B. Elements Strictly Retained (Whitelist):
* **Semantic Layout Architecture:** `<header>`, `<nav>`, `role="navigation"`, `.navbar`, `<main>`, `<section>`, `<article>`, `<footer>`.
* **Navigation Menus & Tabs:** All top-level and dropdown menu structures, tab wrappers (`[role="tab"]`, `.nav-tabs`, `.sub-menu`).
* **Anchor Links (`<a>`):** Preserves `href`, `class`, `title`, `aria-label`, and short anchor text (e.g., *"Scholarships"*, *"منح دراسية"*, *"Undergraduate"*, *"International Students"*, *"Apply"*).
* **Language Switchers & Locale Indicators:** `html[lang]`, `<link rel="alternate" hreflang="...">`, language toggles (e.g., links containing `/ar/`, `/en/`, `?lang=`, or button text like *"English"*, *"العربية"*).
* **Headings:** `<h1>`, `<h2>`, `<h3>` tags indicating section topics (e.g., *"Latest Grants"*, *"Categories"*, *"Academic Programs"*).
* **Pagination Controls:** `.pagination`, `a.next`, page query parameters (`?page=`), and load-more buttons.

#### C. Sibling Card Collapse Rule:
* If a container (`<ul>`, `<div>`, `<section>`) holds multiple repeating card children with identical classes:
  * Retains the first **2 children** (as architectural samples).
  * Discards all remaining siblings, inserting a comment: `<!-- N similar card siblings collapsed -->`.

*Metric:* A typical 1.5MB portal page compresses down to **3KB–8KB** (~800 to 1,800 tokens), yielding over a 95% token savings.

### Step 4: AI Platform Analysis, Prompt Shielding & Relevance Gate
Before transmitting the pruned structural skeleton to Gemini Flash, it is processed through the security module's prompt isolation boundary:
1. **Prompt Injection Shielding:** The pruned HTML is wrapped in `<untrusted_web_content origin_domain="..." hash="...">` tags via `ContentSanitizer.wrap_untrusted_prompt()`. The system prompt instructs Gemini Flash to evaluate this block strictly as raw passive data, actively neutralizing embedded adversarial prompts or instruction-hijacking attempts.
2. **Relevance Gate First:** The AI must first verify whether the site is an educational, grant, scholarship, or fellowship platform. If it is an e-commerce shop, general news site, or personal blog, it must return:
   ```json
   {
     "is_opportunity_portal": false,
     "error_code": "ERR_NOT_OPPORTUNITY_PORTAL",
     "rejection_reason": "Site does not provide educational scholarships or academic grants."
   }
   ```
2. **Site Identity Extraction:** Identifies the official `site_name` and a concise `site_description`.
3. **Locating the Grants Catalog (`catalog_url`):**
   * Inspects navigation links and section headers.
   * Identifies whether the current page is already the main catalog, or if grants reside under a sub-path (e.g., `/scholarships/`, `/category/opportunities/`).
4. **Language Capabilities:**
   * Deduces `supported_languages`: e.g. `["ar"]`, `["ar", "en"]`.
   * Identifies `language_switch_type`: `url_prefix` (e.g. `/ar/`), `query_param` (`?lang=ar`), `hreflang`, or `none`.
5. **Pagination & Mechanics:**
   * Deduces `pagination_type`: `url_param` (`?page=`), `path_param` (`/page/2/`), `next_button`, `infinite_scroll`, or `none`.
   * Recommends a `wait_for_selector` (e.g., `main.content` or `.post-listing`).
6. **Multi-Tab Single-Scholarship Detection:**
   * Inspects whether the CMS organizes opportunity details across client-side tabs (e.g., Bootstrap `.nav-tabs`, Elementor `.elementor-tabs`, or `[role="tab"]`).
   * If detected, flags `has_multi_tab_details: true` and identifies `tab_container_selector: String?` (e.g., `.elementor-tab-title, .nav-tabs a`).
7. **Multi-Page Detail Article Detection:**
   * Checks if single scholarship articles are paginated across sub-pages (e.g., WordPress `<!--nextpage-->`, `.page-links a`, or `.post-pagination`).
   * If detected, flags `has_multi_page_details: true` and identifies `subpage_pagination_selector: String?`.

### Step 5: Conditional 2nd-Hop Crawl (Catalog Verification)
* **Condition Check:**
  * If the entry URL already contained the active catalog and pagination controls: **Skip Step 5 (1 crawl total).**
  * If the entry URL was a portal root homepage (e.g., `https://almin7.com`) and the AI discovered a dedicated `catalog_url` (e.g., `https://almin7.com/scholarship/`):
    1. Validates the discovered `catalog_url` through `LinkValidator.validate_url()`.
    2. Crawl4AI performs **one additional crawl** on `catalog_url`.
    3. The DOM is skeletonized to verify pagination controls (`?page=`, `.pagination a.next`) and inspect sample cards.
    4. Locks in the final `pagination_type`, `pagination_config`, and verifies if tabbed/multi-page structures are present.
* **Cap:** Maximum 2 crawls total for the entire discovery stage. Never crawls detail articles or auxiliary pages.

### Step 6: Database Persistence (`source_configs`)
The discovered parameters are written into the PostgreSQL database:

```sql
INSERT INTO source_configs (
    source_id,
    domain,
    site_name,
    site_description,
    supported_languages,
    language_switch_type,
    pagination_type,
    pagination_config,
    wait_for_selector,
    page_timeout_sec,
    max_pages_per_run,
    has_multi_tab_details,
    tab_container_selector,
    has_multi_page_details,
    subpage_pagination_selector,
    drift_detected,
    consecutive_failures,
    created_at,
    updated_at
) VALUES (
    :source_id,
    :domain,
    :site_name,
    :site_description,
    :supported_languages,
    :language_switch_type,
    :pagination_type,
    :pagination_config,
    :wait_for_selector,
    30,
    10,
    :has_multi_tab_details,
    :tab_container_selector,
    :has_multi_page_details,
    :subpage_pagination_selector,
    false,
    0,
    NOW(),
    NOW()
);

UPDATE sources 
SET name = COALESCE(name, :site_name), 
    is_active = true, 
    updated_at = NOW() 
WHERE id = :source_id;
```

---

## 4. Pre-defined Error Codes for Stage 0

| Error Code | Trigger Condition | System Action |
| :--- | :--- | :--- |
| `ERR_URL_SYNTAX_INVALID` | Malformed URL string provided by admin | Reject immediately at API layer (HTTP 422) |
| `ERR_URL_UNREACHABLE` | DNS failure, connection timeout, non-200 HTTP code | Set `is_active = false`; record error message |
| `ERR_SSL_CERTIFICATE_INVALID` | Expired or untrusted SSL certificate | Set `is_active = false`; log security alert |
| `ERR_ACCESS_CHALLENGE_BLOCKED` | Cloudflare Turnstile / Captcha detected in DOM | Flag stealth failure; alert administrator |
| `ERR_PARKING_DOMAIN` | Domain-for-sale or registrar parking screen detected | Deactivate source permanently |
| `ERR_NOT_OPPORTUNITY_PORTAL` | AI relevance gate determined site is not an opportunity portal | Set `is_active = false`; store AI rejection reason |

---

## 5. Module Structure in the Codebase

This stage is isolated in `src/modules/scraping/discovery/`:

```
src/modules/scraping/discovery/
├── __init__.py
├── preflight_checker.py       # Step 1: Network, DNS, SSL, and parking checks
├── dom_skeletonizer.py        # Step 3: High-speed HTML pruning & sibling collapsing
├── platform_analyzer.py       # Step 4: AI prompt, relevance gate & JSON parsing
├── discovery_service.py       # Orchestrator: Combines Steps 1-6 into a single workflow
└── models.py                  # Pydantic schemas for discovery inputs, outputs & error models
```
