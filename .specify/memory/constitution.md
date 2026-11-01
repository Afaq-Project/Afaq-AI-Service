<!--
Sync Impact Report:
- Version change: Unversioned Template -> v1.0.0
- Bump Rationale: Initial ratification of the project constitution establishing core principles, operational constraints, security boundaries, and engineering standards for Afaq-AI-Service.
- Modified Principles:
  - PRINCIPLE_1: Replaced template with "I. Zero-Trust Security & Ingestion Isolation (NON-NEGOTIABLE)"
  - PRINCIPLE_2: Replaced template with "II. Ultra-Low Memory & Single-Browser Bounded Execution"
  - PRINCIPLE_3: Replaced template with "III. Autonomous Multi-Template Reusability & Zero-Cost Matching"
  - PRINCIPLE_4: Replaced template with "IV. Strict Separation of Raw Extraction and Downstream Cleaning"
  - PRINCIPLE_5: Replaced template with "V. Operational Resilience, Loop Traps & Concurrency Control"
- Added Sections:
  - Technology Stack & Architectural Constraints
  - Testing Philosophy & Quality Standards
- Removed Sections: None
- Follow-up TODOs: None
-->

# Afaq-AI-Service Constitution

## Core Principles

### I. Zero-Trust Security & Ingestion Isolation (NON-NEGOTIABLE)
Every external URL, incoming HTTP response, DOM payload, and binary attachment MUST traverse the mandatory `src/modules/security/` gateway prior to processing or persistence:
* **Network & SSRF Guard:** All URLs MUST pass RFC 3986 syntax validation, private/internal IP filtering (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, link-local, cloud metadata `169.254.169.254`), and 5-hop redirect loop traps. Chromium MUST bind to pre-screened public IPs via `--host-resolver-rules` to prevent DNS rebinding.
* **Content Sanitization:** Plain-text fields MUST be stripped of all HTML/script tags. Rich description fields MUST be sanitized using Rust-backed `nh3`. Untrusted web content passed to LLMs MUST be isolated inside `<untrusted_web_content>` boundaries.
* **Selector ReDoS Protection:** Generated CSS selectors MUST NOT exceed length 300, `:has()` depth 1, or 5 combinators. Candidate selectors MUST pass a 200ms dry-run timeout gate before adoption.
* **Attachment Verification:** Downloads MUST be validated via magic bytes, streamed with a 25MB cutoff, and scanned for Zip-bomb characteristics (max 50MB uncompressed, max 100:1 ratio ceiling).

### II. Ultra-Low Memory & Single-Browser Bounded Execution
The service MUST operate reliably on resource-constrained servers ($\le 1$GB RAM container boundary) running FastAPI alongside headless Chromium:
* **Single-Process Constraint:** Crawling concurrency MUST be bounded to `max_concurrent_crawls = 1`. Concurrent browser instances are strictly forbidden unless horizontal worker scaling is explicitly configured.
* **Chromium Memory Flags:** Chromium MUST launch with `--disable-dev-shm-usage`, `--no-zygote`, `--disable-gpu`, `--disable-extensions`, `--disable-background-networking`, and `--no-first-run`.
* **Resource Reclamation:** Browser contexts and pages MUST be explicitly closed per request with proactive garbage collection (`gc.collect()`). Zombie process reaping MUST be handled via container init (`tini`).
* **Build Isolation:** Running `docker build` locally is strictly forbidden; container packaging is reserved exclusively for CI workflows.

### III. Autonomous Multi-Template Reusability & Zero-Cost Matching
The extraction engine MUST minimize latency and operational AI billing waste by caching and reusing declarative CSS schemas:
* **Deterministic Matching:** Pages MUST be tested against the existing `scraping_templates` pool (3-gate matching: structural anchor, non-empty title, $\ge 1$ action link) before calling any LLM. Successful pool matches MUST execute at zero LLM cost.
* **4-Stage Synthesis Pipeline:** When template synthesis is required, candidate schemas MUST pass Stage A (Syntax/Truncation), Stage B (Pydantic structural shape with `strict=True`, `extra="forbid"`), Stage C (CSS ReDoS complexity linting), and Stage D (200ms dry-run execution gate).
* **Soft-Drift Tracking:** The engine MUST track rolling `field_metrics` fill-rates. If a non-mandatory field drops $> 40\%$ below historical baselines, a targeted micro-repair MUST fix the isolated selector without discarding the template.

### IV. Strict Separation of Raw Extraction and Downstream Cleaning
The scraping engine is purely a high-fidelity producer of unmutated raw content:
* **No Premature Mutation:** Raw extraction tables (`raw_listings`, `raw_grant_details`) MUST store publisher text in its native form. The scraping engine MUST NOT attempt canonical taxonomy mapping, fuzzy heuristics, or premature translation.
* **Multilingual Lineage:** Detail pages published in dual languages (e.g., Arabic and English) MUST be linked via `opportunity_group_id: UUID`. Statistical language classification (`py3langid`) MUST tag native ISO 639-1 codes (`title_language`, `body_language`, `language_confidence`).
* **Downstream Responsibility:** Normalization of fields of study, funding types, study levels, and translation of foreign third-party content are strictly delegated to downstream cleaning pipelines.

### V. Operational Resilience, Loop Traps & Concurrency Control
The scraping lifecycle MUST be self-healing, polite, and resistant to infinite crawl traps:
* **Distributed Locks:** Concurrent crawling of the same source MUST be prevented using atomic check-and-set database locks (`is_locked`, `locked_at` with a 30-minute auto-expiry threshold).
* **Rate Limits & Cool-Down:** Host `Crawl-delay` and HTTP 429 `Retry-After` headers MUST be strictly honored. Delay $> 300$s MUST place the source in `cool_down_until` and release the lock immediately.
* **Lookahead Pagination Cutoff:** Catalog traversal MUST employ a 2-page Lookahead Window (`consecutive_existing_pages >= 2`) to tolerate pinned or sponsored listings. Cutoff MUST automatically disengage if `ordering_strategy != "chronological_descending"`.
* **Content Fingerprint Loop Traps:** Pagination loops MUST be intercepted via SHA256 Content Fingerprints of normalized titles and URLs, comparing Page $N$ to Page $N-1$ (stagnant) and Page 1 (circular).
* **Database Dead-Letter Queue:** Failures MUST be recorded with structured error codes. Records exceeding `max_retries = 3` MUST be flagged as `failed_permanently` for DLQ triage.

## Technology Stack & Architectural Constraints

* **Modular Monolith & Layer Separation:**
  * `src/api/routes/`: Thin controllers handling authentication, status codes, and routing. No direct DB queries.
  * `src/modules/*/services/`: Pure business workflows independent of transport protocols.
  * `src/modules/*/repositories/`: Encapsulated database persistence via Prisma Client Python or `asyncpg`.
  * `src/modules/infrastructure/`: External integrations (HTTP, S3, Webhooks, LLM APIs).
  * `src/modules/security/`: Mandatory zero-trust validation and sanitization gatekeeper.
* **Database & Migration Policy:**
  * Schema managed via `prisma/schema.prisma`.
  * Application queries MUST use `url` (PgBouncer pooled connection).
  * Migrations and schema synchronization MUST use `directUrl` (direct port 5432) to prevent transaction-pooler deadlocks.
* **REST & Webhook Conventions:**
  * All endpoints MUST enforce explicit Pydantic response models.
  * Long-running operations MUST return `202 Accepted` with `operation_id` and execute in background tasks, delivering final telemetry via authenticated webhooks.

## Testing Philosophy & Quality Standards

* **Value-Driven, High-Signal Testing:**
  * Unit tests MUST target core domain algorithms, security gates, edge boundaries, and repository data contracts.
  * Anti-patterns strictly banned: testing framework boilerplate, trivial getters/models, and hollow over-mocking.
* **Deterministic Execution & Performance Ceiling:**
  * The entire unit test suite MUST execute in **under 15 seconds** locally (`uv run pytest tests/`).
  * Unit tests MUST NEVER make live network, external database, or third-party API calls.
* **Static Analysis & Tooling:**
  * Package management strictly managed via `uv`.
  * Code MUST pass `uv run ruff check` and `uv run black --check` prior to commit.
  * Strict type hints required for all public interfaces.
* **Documentation Standards:**
  * All engineering and architectural reports MUST reside in `docs/reports/<purpose>/` accompanied by `metadata.md`.

## Governance

This Constitution acts as the supreme technical and architectural agreement for **Afaq-AI-Service**. All pull requests, code modifications, and automated agent plans MUST verify compliance against these non-negotiable principles.

* **Amendment Procedure:** Amendments require explicit justification, impact assessment, and documentation updates.
* **Versioning Policy:**
  * **MAJOR (X.0.0):** Breaking governance changes, principle removals, or redefinitions.
  * **MINOR (1.X.0):** Addition of new principles, architectural sections, or materially expanded guidelines.
  * **PATCH (1.0.X):** Clarifications, wording refinements, and non-semantic corrections.
* **Compliance Checks:** Any technical deviation or proposed exception MUST be documented with explicit justification and approved before implementation.

**Version**: 1.0.0 | **Ratified**: 2026-11-01 | **Last Amended**: 2026-11-01
