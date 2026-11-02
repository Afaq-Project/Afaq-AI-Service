# Living Architecture Catalog: Module Responsibilities & Boundary Enforcement

This living document defines the core purpose, strict responsibilities, non-negotiable boundaries, and automated tool verification mechanisms for every module in **Afaq-AI-Service**.

---

## 1. Architectural Philosophy: The Three Core Pipeline Stages

To preserve maintainability, security, and testability, our modular monolith separates data lifecycle concerns into three distinct stages:

```
External Web Input (Untrusted)
        │
        ▼
[ Stage 1: Security & Inspection Gatekeeper ] ──▶ Threat? ──▶ Block & Alert (Fail-Closed)
        │ Safe to crawl / stream
        ▼
[ Stage 2: Crawling & Extraction Engine ]     ──▶ Ingests DOM inside XML prompt sandbox
        │ Raw scraped listings
        ▼
[ Stage 3: Cleaning & Normalization Pipeline ]──▶ Decodes entities, normalizes Unicode, parses dates/currency
        │
        ▼
Canonical Clean Data (Postgres Persistence & AI Matching)
```

---

## 2. Living Module Responsibility Directory

### 2.1. Security & Inspection Module (`src/modules/security/`)
* **Identity:** The **Pure, Non-Mutating Gatekeeper**.
* **Core Philosophy:** *Fail-Closed*. The module asks: *"Is this input safe?"* If YES, it lets the exact input pass through without modification. If NO, it rejects, raises a standardized error code, and alerts.
* **Permitted Responsibilities:**
  1. **URL & Network Security (`LinkValidator`):**
     * RFC 3986 syntax normalization, port restrictions (`80`, `443`), scheme restrictions (`http`, `https`).
     * Asynchronous DNS resolution + private/loopback/cloud metadata IP blocking (`169.254.169.254`).
     * Production of Chromium `--host-resolver-rules` for DNS pinning against DNS rebinding (TOCTOU).
     * 5-hop redirect depth enforcement, circular redirect loop detection, and per-hop SSRF re-checks.
     * HTTP 429/503 rate-limit `Retry-After` cool-down evaluation.
     * RFC 3986 relative reference resolution when an optional `base_url` is provided.
  2. **File & Attachment Safety (`FileValidator`):**
     * 25 MB stream ceiling enforcement.
     * Pure-Python binary magic-byte inspection (PDF `%PDF-`, DOCX/XLSX `PK\x03\x04`, JPEG, PNG, WEBP).
     * Discarding disguised executables (`MZ`, `ELF`, shell scripts).
     * Zip-bomb inspection without full decompression ($100:1$ ratio, $50$ MB uncompressed cap).
     * S3 object key derivation with Content-Disposition parsing and hash fallback.
  3. **Template & ReDoS Safety (`SchemaValidator`):**
     * Pydantic structural shape validation (`strict=True`, `extra="forbid"`).
     * CSS selector syntax compilation via `soupsieve`.
     * CSS complexity limits (max length 300, max 1 `:has()` depth, max 5 combinators).
     * 200ms dry-run execution timeout against ReDoS backtracking bombs.
* **Explicitly Prohibited Actions (Forbidden in this Module):**
  * ❌ **NO Data Mutation or Formatting:** Does NOT strip tags from text, decode HTML entities (`&amp;`), or normalize Unicode (NFKC).
  * ❌ **NO Prompt Delimiter Escaping or Text Redaction:** Does NOT escape XML tags or modify prompt content. Delimiter escaping and prompt packaging belong strictly to the scraping module.
  * ❌ **NO Database Access:** Must never import repositories, Prisma, or `asyncpg`.
  * ❌ **NO Crawler / Browser Management:** Must never launch Playwright or manage browser processes.
  * ❌ **NO LLM Prompt Orchestration:** Does not construct system prompts or invoke LLM APIs.
* **Inputs & Outputs:**
  * *Inputs:* Raw URLs, raw file streams, candidate schema dictionaries.
  * *Outputs:* Immutable validation results (`ValidatedUrl`, `FileValidationResult`, `TemplateSchemaValidationResult`), or raises `SecurityValidationError`.

---

### 2.2. Crawling & Extraction Module (`src/modules/scraping/`)
* **Identity:** The **Autonomous Adaptive Web Ingestion Engine**.
* **Permitted Responsibilities:**
  * Single-process Playwright / Crawl4AI browser lifecycle management (concurrency bound = 1, RAM $\le 1$ GB).
  * Consuming Chromium `--host-resolver-rules` from `LinkValidator` to enforce pinned DNS.
  * Orchestrating Stage 0 (Architectural Mapping), Stage 1 (Template Synthesis), and Stage 2 (Batch Crawling).
  * Constructing LLM prompts with explicit system instructions (priming models to treat `<untrusted_web_content>` as passive data) and escaping literal delimiter tags (`</untrusted_web_content>` $\rightarrow$ `&lt;/untrusted_web_content&gt;`).
  * Executing validated CSS/JSON extraction strategies against target DOMs.
* **Explicitly Prohibited Actions:**
  * ❌ Must never dispatch HTTP/browser requests to an unverified URL (must call `LinkValidator` first).
  * ❌ Must never bypass authentication paywalls or CAPTCHAs.
* **Inputs & Outputs:**
  * *Inputs:* Verified source configurations, validated target URLs.
  * *Outputs:* `RawListing` dictionaries and unmutated scraped HTML/text stored in raw extraction tables.

---

### 2.3. Cleaning & Normalization Module (`src/modules/cleaning/` - Future Track)
* **Identity:** The **Data Sanitization, Transformation & Canonicalization Pipeline**.
* **Permitted Responsibilities:**
  * Plain-text extraction from layout tags for structured fields.
  * HTML entity decoding (`&amp;` $\rightarrow$ `&`, `&quot;` $\rightarrow$ `"`).
  * Unicode NFKC normalization (`ＵＣＬＡ` $\rightarrow$ `UCLA`, `ﬁ` $\rightarrow$ `fi`).
  * Non-printable control character removal (`\x00` - `\x1f`).
  * Safe rich-text HTML sanitization using `nh3` (Mozilla ammonia Rust engine).
  * Domain-specific value parsing: Date normalization (ISO 8601), currency and funding extraction, academic degree classification.
* **Explicitly Prohibited Actions:**
  * ❌ Does not make external network requests or perform DNS resolution.
  * ❌ Does not launch browser processes.
* **Inputs & Outputs:**
  * *Inputs:* Raw listing records from the database.
  * *Outputs:* Clean, canonical, structured scholarship entities ready for vector embedding and AI matching.

---

## 3. How Our Installed Tools Enforce Module Integrity

We enforce these boundaries automatically using our pre-installed static analysis, contract, and architectural toolchain:

### 3.1. Enola Architectural Intent Engine (`enola-intent.yaml` & `mcp-arch.yaml`)
* **How It Works:** Enola builds an architectural dependency graph from abstract syntax trees. We define component boundaries and explicit import laws.
* **Enforced Rules:**
  * `no-modules-to-api`: Ensures modules never import from API route layers.
  * `security-isolation`: Can enforce that `src/modules/security/` has 0 imports from `src/modules/core/database/` and 0 imports from `src/modules/scraping/`.
* **Execution Gate:** `enola check . --fail-on=layers,cycles` runs in the pre-commit pipeline and fails the build with exit code 1 if a forbidden boundary is crossed.

### 3.2. ArchUnitPython (`tests/architecture/test_architecture.py`)
* **How It Works:** Allows writing programmatic architectural unit tests in Python using a fluent API.
* **Automated Rule Examples:**
  ```python
  def test_security_module_isolation():
      # Security module must never depend on database repositories or ORMs
      files("src.modules.security").should().not_import("src.modules.core.database")
      files("src.modules.security").should().not_import("prisma")
      files("src.modules.security").should().not_import("asyncpg")
  ```
* **Execution Gate:** `uv run pytest tests/architecture/ -v` fails immediately if an unauthorized dependency is introduced.

### 3.3. KG-ARCHMAP Dependency & Coupling Health (`.archmap.toml`)
* **How It Works:** Analyzes coupling metrics, instability, abstractness, and circular dependencies.
* **Enforced Rules:**
  * Coupling budget enforcement: flags whenever a module's afferent/efferent coupling exceeds its budget.
  * Cycle detection: `archmap analyze src --fail-on-cycles --fail-on-layer-violations`.
* **Execution Gate:** Rejects any commit dropping the architecture score below 90/100 (Grade A).

### 3.4. SonarQube Code Quality & Complexity Gates
* **How It Works:** Analyzes code smells, maintainability ratings, and cognitive complexity per package.
* **Enforced Rules:**
  * Ensures modules remain focused and lean (0 Blocker, 0 High, 0 Medium issues).
  * Prevents bloated god-classes or intertwined logic.

---

## 4. Maintenance & Expansion Protocol

* **Living Evolution:** As new pipeline modules are designed (e.g. `src/modules/matching/`, `src/modules/notifications/`), their responsibilities, forbidden actions, and input/output contracts must be added to this catalog.
* **Rule Invariant:** Whenever a new module is added to this catalog, matching architectural tests must be added to `tests/architecture/test_architecture.py` and `enola-intent.yaml` to ensure automated enforcement by our verification tools.
