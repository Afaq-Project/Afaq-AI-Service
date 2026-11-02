# System Architecture Rules, Module Boundaries & Component Catalog

## 1. Document Purpose & Operational Mandate

This document serves as the **official, living, and authoritative specification** of architectural boundaries, component responsibilities, forbidden interactions, and automated enforcement mechanisms for **Afaq-AI-Service**.

### Core Purpose:
1. **Single Source of Truth:** Clearly define what each component is permitted to do, what it is strictly forbidden from doing, and how data moves across system boundaries.
2. **Prevent Functional Conflation:** Maintain strict architectural separation between disparate concerns—specifically isolating pre-scrape security gatekeeping from downstream data cleaning and AI prompt orchestration.
3. **Living Governance:** This document is designed to be continuously updated and expanded as new modules (e.g., adaptive scraping, multi-stage cleaning, opportunity matching) are engineered.
4. **Automated Enforcement:** Every rule in this catalog is backed by static architecture linters and automated tests (**ArchUnit-Python**, **Enola**, **KG-ARCHMAP**, and **SonarQube**) to ensure that architectural integrity is verified on every build.

---

## 2. High-Level System Architecture & Pipeline Stages

Data in `Afaq-AI-Service` flows through three strictly segregated pipeline stages to ensure security, testability, and deterministic failure modes:

```
External Untrusted Web / API
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 1: Security & Inspection Gatekeeper                   │
│ Directory: src/modules/security/                            │
│ Philosophy: Pure Gatekeeper, Zero Mutation, Fail-Closed     │
└──────────────────────────────┬──────────────────────────────┘
                               │ Safe to crawl / fetch
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 2: Crawling & Extraction Engine                       │
│ Directory: src/modules/scraping/                            │
│ Philosophy: Autonomous Adaptive Extraction, Prompt Sandbox  │
└──────────────────────────────┬──────────────────────────────┘
                               │ Raw scraped content
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 3: Cleaning & Normalization Pipeline                  │
│ Directory: src/modules/cleaning/                            │
│ Philosophy: Transformation, Sanitization, Entity Decoding   │
└──────────────────────────────┬──────────────────────────────┘
                               │ Canonical Clean Data
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Persistence & Downstream Consumers (Postgres, Matching, API)│
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Module Boundary Catalog & Functional Definitions

### 3.1. Security & Inspection Module (`src/modules/security/`)
* **Role / Identity:** **Pure, Non-Mutating Gatekeeper & Auditor**.
* **Internal Layout:** All business logic resides in `services/*_service.py`:
  - `src/modules/security/services/link_validator_service.py`
  - `src/modules/security/services/file_validator_service.py`
  - `src/modules/security/services/schema_validator_service.py`
  - `src/modules/security/models.py`
  - `src/modules/security/exceptions.py`
* **Core Philosophy:** *Fail-Closed*. The module asks: *"Does this target or artifact violate security invariants?"* If safe, it allows the exact input through unaltered. If unsafe, it rejects immediately with a standardized, typed security error code.
* **Permitted Responsibilities:**
  1. **URL & Network Security (`LinkValidatorService`):**
     * RFC 3986 syntax normalization, port restrictions (`80`, `443`), scheme restrictions (`http`, `https`).
     * Asynchronous pre-request DNS resolution + private, loopback, link-local, and cloud metadata IP blocking (e.g., AWS IMDS `169.254.169.254`).
     * Generation of Chromium `--host-resolver-rules` for deterministic DNS pinning against DNS rebinding (TOCTOU attacks).
     * 5-hop redirect depth limits, circular redirect cycle detection, and per-hop SSRF re-evaluation.
     * RFC 3986 relative reference resolution when an optional `base_url` is provided.
     * HTTP 429/503 rate-limit `Retry-After` cool-down evaluation.
  2. **File & Attachment Safety (`FileValidatorService`):**
     * Strict 25 MB stream ceiling enforcement (`ERR_FILE_SIZE_EXCEEDED`).
     * Pure-Python binary magic-byte inspection (PDF `%PDF-`, DOCX/XLSX `PK\x03\x04`, JPEG, PNG, WEBP).
     * Rejection of executable signatures (PE `MZ`, ELF, shell scripts).
     * Zip-bomb inspection without decompression (100:1 compression ratio cap, 50 MB uncompressed cap).
     * S3 object key derivation from sanitized filenames or `{sha256[:16]}.{ext}` hash fallback.
  3. **Schema & Selector Safety (`SchemaValidatorService`):**
     * Pydantic structural validation (`strict=True`, `extra="forbid"`).
     * CSS selector syntax compilation and ReDoS complexity limiting (max length 300, max 1 `:has()` depth, max 5 combinators).
     * 200ms dry-run execution timeout against ReDoS backtracking bombs.
* **Strictly Prohibited Actions (Forbidden in this Module):**
  * ❌ **NO Content Mutation or Data Cleaning:** Must NEVER strip HTML tags, decode entities (`&amp;`), or perform Unicode normalization (NFKC) on content.
  * ❌ **NO Prompt Delimiter Escaping or Text Redaction:** Must NEVER modify content for prompt preparation (e.g., replacing `</untrusted_web_content>` tags or redacting phrases). All prompt formatting and boundary escaping belong strictly to the scraping/prompt builder pipeline.
  * ❌ **NO Database Access:** Must NEVER import repositories, Prisma, or `asyncpg`.
  * ❌ **NO Browser Process Management:** Must NEVER launch Playwright or manage browser processes.
  * ❌ **NO LLM Prompt Orchestration:** Must NEVER compose system prompts or call LLM APIs.
* **Allowed Dependencies:** `src.modules.core.config`, `src.modules.core.exceptions`, standard library (`ipaddress`, `urllib.parse`, `zipfile`, `hashlib`), `soupsieve`, `pydantic`.
* **Outputs:** Immutable validation result value objects (`ValidatedUrl`, `FileValidationResult`, `TemplateSchemaValidationResult`), or raises `SecurityValidationError`.

---

### 3.2. Crawling & Extraction Engine (`src/modules/scraping/`)
* **Role / Identity:** **Autonomous Adaptive Web Ingestion Engine**.
* **Permitted Responsibilities:**
  * Single-process Playwright / Crawl4AI browser lifecycle management (concurrency bound = 1, RAM $\le 1$ GB).
  * Consuming Chromium `--host-resolver-rules` from `LinkValidator` to enforce pinned DNS.
  * Multi-stage crawling execution: Stage 0 (Architectural Mapping), Stage 1 (Template Synthesis), Stage 2 (Batch Crawling).
  * **LLM Prompt Formatting & Sandbox Packaging:** Constructing LLM prompts, safely escaping literal delimiter tags (e.g. `</untrusted_web_content>` $\rightarrow$ `&lt;/untrusted_web_content&gt;` during prompt serialization), and priming system instructions (directing models to treat `<untrusted_web_content>` strictly as passive data).
  * Executing validated CSS/JSON extraction strategies against target DOMs.
* **Strictly Prohibited Actions:**
  * ❌ Must NEVER initiate network connections or browser requests to an unverified URL without calling `LinkValidator` first.
  * ❌ Must NEVER perform canonical data transformation or database writes directly.

---

### 3.3. Cleaning & Normalization Pipeline (`src/modules/cleaning/`)
* **Role / Identity:** **Data Transformation, Normalization & Sanitization Engine**.
* **Permitted Responsibilities:**
  * Plain-text extraction via `to_clean_text` (stripping HTML/XML tags, decoding entities like `&amp;` $\rightarrow$ `&`).
  * Unicode normalization (NFKC) to eliminate confusables and irregular encodings.
  * Safe rich-text HTML sanitization via Rust-backed `nh3` (enforcing an explicit whitelist of safe formatting tags).
  * Canonical parsing and type casting: dates (ISO 8601), currency amounts (ISO 4217), country codes (ISO 3166-1 alpha-2).
* **Strictly Prohibited Actions:**
  * ❌ Must NEVER initiate network connections or download external files.
  * ❌ Must NEVER perform link security validation or network routing decisions.

---

### 3.4. Core Layer (`src/modules/core/`)
* **Role / Identity:** **Foundational Infrastructure & Common Domain Utilities**.
* **Components:**
  * `core/config`: Application settings and environment configurations.
  * `core/exceptions`: System-wide typed exception hierarchy.
  * `core/database`: Database connection management, Prisma client, and repository implementations.
  * `core/auth`: API authentication and token verification.
* **Rules:**
  * `core/database/repositories` may only be accessed by application service layers, never directly by `api` routes or the `security` module.

---

### 3.5. API Transport Layer (`src/api/`)
* **Role / Identity:** **HTTP Ingress, Transport & Protocol Serialization**.
* **Rules:**
  * Route handlers must remain thin; no business logic or direct database queries.
  * May import application services and protocols, but domain modules (`src/modules/**`) may NEVER import `src/api/**`.

---

## 4. Architectural Rules & Automated Tool Enforcement

| Rule ID | Constraint Statement | Enforcing Tool | Configuration / Test Reference |
| :--- | :--- | :--- | :--- |
| **ARCH-001** | `security` module must NEVER depend on `repositories` (No Database Access) | **ArchUnit-Python** & **Enola** & **KG-ARCHMAP** | [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py#L38-L51), [`enola-intent.yaml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/enola-intent.yaml#L23-L28), [`.archmap.toml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/.archmap.toml#L24) |
| **ARCH-002** | `security` module must NEVER depend on `api` (Transport Agnostic) | **ArchUnit-Python** & **Enola** & **KG-ARCHMAP** | [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py#L38-L51), [`enola-intent.yaml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/enola-intent.yaml#L29-L34), [`.archmap.toml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/.archmap.toml#L25) |
| **ARCH-003** | `security` module must NEVER depend on `infrastructure` clients (HTTP/LLM/Webhooks) | **ArchUnit-Python** | [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py#L54-L65) |
| **ARCH-004** | `modules` must NEVER depend on `api` transport layer | **ArchUnit-Python** & **Enola** | [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py#L26-L35), [`enola-intent.yaml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/enola-intent.yaml#L17-L22) |
| **ARCH-005** | `api` routes must NEVER depend directly on database `repositories` | **ArchUnit-Python** & **KG-ARCHMAP** | [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py#L12-L23), [`.archmap.toml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/.archmap.toml#L22) |
| **ARCH-006** | The entire `src/` codebase must be free of circular dependencies | **ArchUnit-Python** | [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py#L4-L7) |
| **ARCH-007** | Security validators must return immutable inspection results and NEVER mutate content | **Pytest Contract Suites** | `tests/unit/security/test_immutability.py` |
| **ARCH-008** | Functional/unit tests must NEVER assert execution time limits or latency SLAs | **Test Governance & AGENT.md** | Constitution v2.4.0 Principle VI; performance measured exclusively via user-configured `k6` suites |
| **ARCH-009** | All domain services must reside in `services/` and be named `*_service.py` | **Clean Architecture & AGENT.md** | NestJS-style service layer convention; module roots hold only `__init__.py`, `models.py`, `exceptions.py` |

---

## 5. Change Management & Governance Protocol

* **Living Catalog Updates:** Whenever a new domain module is planned or an existing module's responsibilities expand, this document must be updated to reflect the new boundaries, inputs, and outputs.
* **Strict Protection Gate:** In accordance with [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md), AI agents are strictly prohibited from modifying automated rule files ([`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py), [`enola-intent.yaml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/enola-intent.yaml), [`.archmap.toml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/.archmap.toml)) without explicit user instruction.
* **Verification Cadence:** Architectural boundary verification runs automatically before any commit touching source code via:
  ```bash
  uv run pytest tests/architecture/
  uv run enola check .
  uv run archmap analyze src
  ```
