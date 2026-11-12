# Technical Research & Architecture Decisions: Scraping & Extraction Pipeline

**Feature**: `002-scraping-extraction-pipeline`  
**Created**: 2026-11-05  
**Status**: Completed & Approved  

---

## 1. Single-Browser Sequential Crawling & Chromium Memory Management (≤1 GB RAM Bound)

### Decision
Operate the Crawl4AI / Playwright engine under a strictly bounded **single-process sequential model** (`max_concurrent_crawls = 1`). Launch headless Chromium with aggressive memory-pruning flags:
* `--disable-dev-shm-usage`: Forces Chromium to use `/tmp` rather than exhausting container `/dev/shm` (64MB default in Docker).
* `--no-zygote`: Bypasses spawning the separate zygote process (saving ~80MB–100MB RAM).
* `--disable-gpu`, `--disable-extensions`, `--disable-background-networking`, `--disable-default-apps`, `--disable-sync`, `--no-first-run`: Purges all non-essential browser subsystems.
* **Context Lifecycle**: Create a lightweight browser context per page request, explicitly close it immediately after DOM capture, and trigger Python garbage collection (`gc.collect()`).

### Rationale
* **Server Stability**: The production host and Docker containers operate with a strict **1 GB RAM ceiling**. Spawning multiple concurrent browser tabs rapidly consumes 800MB–1.5GB of RAM, triggering Linux kernel Out-Of-Memory (OOM) killer terminations.
* **Predictable Footprint**: By isolating each page crawl to a short-lived browser context and disposing of memory immediately, Chromium RSS memory remains strictly pegged between **300 MB and 450 MB**, guaranteeing complete system headroom.

### Alternatives Considered
* **Multi-Tab Concurrency (`max_concurrent_crawls = 4`)**: Rejected due to high risk of container OOM evictions on memory-constrained servers.
* **Persistent Browser Contexts**: Rejected because Chromium internal caches and DOM trees accumulate memory across navigations (memory leak vulnerability).

---

## 2. Two-Phase Execution Sequencing (Level 1 Catalog First, Level 2 Details Second)

### Decision
Execute scraping operations in a strict **sequential two-phase order** per source:
1. **Phase 1 (Catalog Traversal)**: Crawl all catalog pages, extract opportunity card previews and detail URLs, and persist them immediately into `raw_listings` with `status = "pending_detail_crawl"`.
2. **Phase 2 (Detail Extraction)**: Fetch `pending_detail_crawl` records sequentially from `raw_listings`, navigate to each scholarship detail page, extract comprehensive fields, and persist them into `raw_grant_details`.

### Rationale
* **Crash Resilience & State Recovery**: If the service process crashes or is restarted during detail extraction, zero discovered opportunities are lost. All URLs discovered during Phase 1 remain preserved in PostgreSQL and can be cleanly resumed without re-crawling catalog pages.
* **Browser Isolation**: Separating catalog navigation from detail navigation eliminates browser context state conflicts, prevents pagination cursor corruption, and enables distinct timeout settings.

### Alternatives Considered
* **Interleaved Page-by-Page Execution**: Crawling page 1 of the catalog, immediately crawling its detail pages, then proceeding to catalog page 2. Rejected because failures midway through detail crawls complicate pagination resumption and lock tracking.
* **Asynchronous Message Queue (Celery/RabbitMQ)**: Rejected as unnecessary infrastructure bloat for our modular monolith. PostgreSQL-backed queue state with atomic status flags provides complete reliability without extra operational dependencies.

---

## 3. Multi-Source Dynamic Prioritization & Atomic Distributed Locking

### Decision
* **Prioritization Formula**:
  $$\text{Score} = (\text{Admin Tier} \times 100) + \text{Days Since Last Scrape} - (\text{Consecutive Failures} \times 10)$$
  * Manual administrative trigger ("Scrape Now") acts as a P0 priority override.
  * Multi-source batches interleave domains to prevent repeated consecutive hits against the same host.
* **Atomic Distributed Locking**:
  Utilize PostgreSQL conditional check-and-set on `source_configs`:
  ```sql
  UPDATE source_configs 
  SET is_locked = true, locked_at = NOW() 
  WHERE source_id = :source_id 
    AND (is_locked = false OR locked_at < NOW() - INTERVAL '30 minutes')
  RETURNING id;
  ```
  If zero rows are returned, the source is skipped safely with a recorded lock notice.

### Rationale
* **Freshness & Yield Optimization**: Balances high-value sources (Tier 1 portals like DAAD, Chevening, Fulbright) with stale sources that haven't been visited in days, while penalizing broken sources that consistently fail.
* **Deadlock Immunity**: Automatic 30-minute lock expiration ensures that even if a worker crashes abruptly, the target source becomes automatically eligible for reclamation on subsequent runs without manual DBA intervention.

### Alternatives Considered
* **Redis Distributed Locking (Redlock)**: Rejected to keep the architecture streamlined and avoid introducing Redis as a mandatory single point of failure for state management.
* **FIFO Simple Queue**: Rejected because high-value and stale sources would be starved behind slow or broken sources.

---

## 4. Multi-Template Historical Pool & Soft-Drift Micro-Repairs

### Decision
Maintain a historical library of extraction schemas in `scraping_templates` per source.
* **Evaluation Pipeline (Fast 3-Gate Deterministic Test)**:
  * Gate 1: Base container exists in DOM.
  * Gate 2: Yield meets coverage threshold ($\ge 1$ card with title/URL for Level 1; title + application URL for Level 2).
  * Gate 3: Text length valid (5–250 chars) with zero script/raw HTML residue.
* **Soft-Drift Micro-Repair**:
  * Track rolling field fill-rate metrics in `scraping_templates.field_metrics`.
  * If a single selector's fill-rate drops by $>40\%$ below its historical baseline while overall template match is $\ge 85\%$, dispatch a targeted ~300-token Micro-Repair prompt to patch only the broken selector, saving a new minor version (e.g. `v1.0` $\rightarrow$ `v1.1`).
* **Hard Drift Fallback**:
  * If all pool templates fail, invoke AI schema synthesis with a strict 4-stage validation pipeline (JSON syntax, strict schema shape, CSS backtracking checks, 200ms dry-run timeout).

### Rationale
* **Token Cost Reduction**: Over 85% of recurring runs match known layouts, eliminating LLM API spending completely for established portals.
* **Resilience to Layout Tweaks**: Portals frequently tweak minor CSS classes (e.g., changing `.stipend-badge` to `.grant-amount`). Micro-repairs patch the broken field without risking regression on functioning selectors.

### Alternatives Considered
* **Single Active Template per Source**: Rejected because websites frequently rotate between multiple distinct layouts (e.g., standard articles vs. sponsored posts, list vs. grid views), causing thrashing and continuous template regeneration.
* **Always-on AI Extraction**: Rejected due to prohibitive latency and ongoing LLM billing costs.

---

## 5. Bilingual Dual-Crawl Pairing & S3 Attachment Cache Reuse

### Decision
* **Native Bilingual Linking**:
  When a portal publishes opportunities in both Arabic and English (e.g., `/ar/grant-1` and `/en/grant-1`), both versions are crawled natively and stored in `raw_grant_details` sharing the exact same `opportunity_group_id` UUID.
* **S3 Attachment Deduplication**:
  Prior to downloading downloadable application forms (PDF/DOCX), check if the attachment URL or derived S3 key already exists in `raw_grant_details` with verified checksum metadata. If present, reuse the existing S3 metadata and skip downloading the file stream.

### Rationale
* **Zero Translation Cost**: Linking native Arabic and English versions allows the downstream cleaning engine to merge them into a single canonical record with 100% human-level accuracy and zero machine translation API costs.
* **Bandwidth & Storage Conservation**: Educational PDF application forms typically range from 5 MB to 20 MB. Skipping redundant downloads on recurring crawls saves server bandwidth and S3 storage costs while accelerating crawl completions.

### Alternatives Considered
* **Translating all content via LLM**: Rejected due to token cost and potential hallucination of critical eligibility criteria.
* **Unconditional File Re-downloading**: Rejected because it consumes significant network I/O and S3 bandwidth on every recurring crawl.

---

## 6. Statistical Language Classification via N-Gram Analysis

### Decision
Integrate lightweight, offline statistical language classification (`py3langid`) using n-gram frequency models. Evaluate `title_language` and `body_language` independently. Tag language as `'und'` (undetermined) only when the model confidence score drops below `0.50`.

### Rationale
* **Sub-Millisecond Execution**: Offline n-gram analysis executes in $<1$ ms per text snippet with zero network calls and zero API fees.
* **Independent Title/Body Handling**: Many international portals feature an English title (preserving the official program name) paired with an Arabic explanatory description. Classifying both independently enables targeted indexing and downstream processing.
* **Permissive Threshold (0.50)**: Ensures legitimate single-language content is correctly assigned an ISO 639-1 code while safely tagging severely ambiguous or mixed snippets as undetermined.

### Alternatives Considered
* **LLM Language Detection**: Rejected because spending LLM tokens solely to detect language is wasteful and adds hundreds of milliseconds of latency.
* **HTML `lang` Attribute Inspection**: Rejected because real-world portals frequently omit the `lang` attribute or set it incorrectly to `en` even on purely Arabic pages.
