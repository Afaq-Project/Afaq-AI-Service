# Agent Engineering Guidelines & Standards

This document establishes the architectural principles, coding conventions, testing guidelines, security gates, and operational standards for engineers and AI agents working on **Afaq-AI-Service**.

---

## 1. Operating Rules & Core Constraints

* **Strict Communication & Code Language:**
  * All communications, reasoning summaries, commit messages, PR descriptions, documentation, and code comments must be conducted **exclusively in English**.

* **Branching & Pull Request Policy:**
  * **NEVER push or merge directly into the `main` branch.**
  * All proposed changes, features, refactors, and bug fixes must be developed on a dedicated branch (e.g., `feat/<feature-name>`, `fix/<bug-name>`).
  * Changes must be submitted via a Pull Request (PR) for review and approval.

* **Commit Cadence for Functional Units:**
  * A commit must be made **immediately upon the completion of every distinct, cohesive functional unit**.
  * Commits must be atomic, well-described, and follow Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`).

* **Pre-Installed Tools & Zero Re-Download Rule:**
  * All quality, security, contract, architectural, and performance tools (**SonarScanner**, **Sonar CLI**, **Trivy**, **Gitleaks**, **Pact Broker CLI**, **k6**, **KG-ARCHMAP**, **Enola**, and **ArchUnitPython**) are **already installed** on the system or environment.
  * **DO NOT** attempt to re-install, re-download, or run package managers to fetch these tools. Use the existing binaries and environment dependencies as documented in Section 5.

* **Strict Architectural Rules Protection (User-Only Modification Gate):**
  * The agent is **strictly prohibited from modifying, loosening, deleting, or bypassing architectural rule files and quality gate configurations on its own**.
  * This restriction applies to:
    - Architecture test definitions (e.g., [`tests/architecture/test_architecture.py`](file:///home/abood/Project/Afaq/Afaq-AI-Service/tests/architecture/test_architecture.py))
    - Enola architectural specifications and constraints ([`mcp-arch.yaml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/mcp-arch.yaml), `enola-intent.yaml`)
    - KG-ARCHMAP configuration and budget files ([`.archmap.toml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/.archmap.toml))
    - SonarQube properties and gate definitions ([`sonar-project.properties`](file:///home/abood/Project/Afaq/Afaq-AI-Service/sonar-project.properties))
    - Security scanning policies ([`.gitleaks.toml`](file:///home/abood/Project/Afaq/Afaq-AI-Service/.gitleaks.toml), Trivy arguments)
  * Any update, adjustment of thresholds, or alteration of architectural rules may **ONLY be executed upon an explicit, direct command from the user**. If a code change triggers an architectural violation or quality gate failure, the agent must fix the application code to comply—never tamper with the rules to force a pass.

* **Zero Local Container Builds:**
  * **Never run `docker build` locally.** Container builds are handled exclusively by CI/CD pipelines.

---

## 2. Architectural Boundaries (Modular Monolith)

The codebase follows Clean Architecture and Modular Monolith principles. Maintain strict layer separation at all times:

* **API Layer (`src/api/routes/`):**
  * Controllers must remain thin. They handle authentication, request validation, HTTP status codes, and route dispatching.
  * No direct database queries or heavy business logic inside route functions.
  * Route functions must delegate to service protocols via FastAPI dependency injection.

* **Service Layer (`src/modules/*/services/`):**
  * Houses all core domain logic, calculation rules, workflows, and orchestration.
  * Services should remain independent of transport protocols (HTTP, CLI, WebSockets).

* **Data Access Layer (`src/modules/*/repositories/`):**
  * All database persistence, queries, updates, and transactions must be encapsulated within repository classes.
  * Direct ORM calls (Prisma / `asyncpg`) belong exclusively in this layer.

* **Infrastructure Layer (`src/modules/infrastructure/`):**
  * Manages communication with external systems (HTTP clients, webhooks, LLM APIs).
  * Exposes clean abstractions and handles retries, rate limits, and network errors.

* **Dependency Inversion & Protocols (`src/api/protocols.py`):**
  * High-level modules and route handlers must depend on abstract Protocols, never directly on concrete implementations.
  * Ensure services can be swapped, decorated, or mocked without altering consumer code.

---

## 3. RESTful API Standards & Response Conventions

All HTTP endpoints must follow strict RESTful conventions and predictable payload formats:

* **HTTP Status Codes:**
  * `200 OK`: Successful synchronous retrieval or state update.
  * `201 Created`: Successful synchronous resource creation.
  * `202 Accepted`: Asynchronous long-running jobs (batch operations, heavy syncs).
  * `400 Bad Request`: Client input errors not caught by schema validation.
  * `401 Unauthorized`: Missing or invalid API key / authentication token.
  * `403 Forbidden`: Authenticated user/client lacks required permissions.
  * `404 Not Found`: Target resource does not exist.
  * `422 Unprocessable Entity`: Request body failed Pydantic schema validation.
  * `500 Internal Server Error`: Unexpected server-side failure.

* **Standard Response Envelopes:**
  * Every endpoint must define explicit Pydantic response models (`response_model=...`). No untyped dictionaries.
  * **Synchronous Success:**
    ```json
    {
      "status": "success",
      "data": { ... },
      "message": "Operation completed successfully."
    }
    ```
  * **Asynchronous Jobs (`202 Accepted`):**
    Long-running background tasks must return immediately with tracking metadata, execute using FastAPI `BackgroundTasks`, and emit a webhook notification upon completion:
    ```json
    {
      "status": "accepted",
      "operation_id": "uuid-here",
      "message": "Operation started in background; a webhook will be sent on completion."
    }
    ```

* **Error Responses:**
  * Use FastAPI `HTTPException` with clear, structured error details:
    ```json
    {
      "detail": "Description of the error condition"
    }
    ```

---

## 4. Testing Philosophy & Boundaries

Tests exist to prevent regressions and verify real business behaviors. Avoid test bloat and redundant coverage metrics.

### What MUST Be Tested (High-Value Areas)
* **Core Business Logic:** Scoring algorithms, eligibility evaluation, normalization rules, state transitions, and deduplication logic.
* **Edge Cases & Boundaries:**
  * Empty inputs, null/missing optional fields, unicode/special characters.
  * Extreme values, boundary limits, and malformed dates.
  * Timeouts, upstream service failures, and non-200 HTTP responses.
* **Repository Contracts:** Ensuring database queries return expected shapes and handle missing records cleanly.
* **Security & Auth Gates:** Enforcing API key presence, validity, and scope checks.
* **Contract Integrity:** Pact contract interactions ensuring breaking payload or status changes are caught.

### What MUST NOT Be Tested (Anti-Patterns to Avoid)
* **Boilerplate & Framework Guarantees:** Do not test that Pydantic validates fields, that FastAPI routes traffic, or that Python's built-in functions work.
* **Trivial Getters / Setters / Models:** Do not write unit tests simply to instantiate a class or assert default model field values unless custom validation logic is present.
* **Hollow / Over-Mocked Tests:** Avoid tests where 90% of the code is configuring mocks that do not reflect realistic execution paths.
* **Duplicate Coverage:** If a behavior is thoroughly tested in a service unit test, do not write identical duplicate tests in route tests just to increase lines covered.

### Test Hygiene & Speed
* **Execution Constraint:** The entire test suite must run in **under 15 seconds** locally (`uv run pytest`).
* **Determinism:** Tests must be completely deterministic. Never make real network, database, or LLM calls during standard unit testing—use fakes, in-memory fixtures, or mocked clients.

---

## 5. Mandatory Pre-Commit Verification Pipeline

Before committing ANY code, the agent MUST run the full verification pipeline and ensure all checks pass with zero violations.

### 5.1 Code Formatting & Linting (Ruff & Black)
* **Ruff (Linter & Import Organizer):**
  ```bash
  uv run ruff check .
  ```
* **Black (Code Formatter):**
  ```bash
  uv run black --check .
  # To automatically format:
  uv run black .
  ```

### 5.2 Test Suite & Coverage Report Generation
Generate the `coverage.xml` report required by SonarQube:
```bash
uv run pytest --cov=src --cov-report=xml
```

### 5.3 Static Code Analysis & Quality Gates (SonarQube)
SonarQube runs locally inside a Docker container. All binaries and environment variables are pre-configured:
* **Host URL:** `http://localhost:9000`
* **SonarScanner:** Installed at `/opt/sonarscanner/` and symlinked at `/usr/local/bin/sonar-scanner` (in `PATH`).
* **Sonar CLI:** Installed at `~/.local/share/sonarqube-cli/bin/sonar`, available via `~/.local/bin/sonar` (in `PATH`).
* **Authentication:** `$SONARQUBE_CLI_TOKEN` is exported in the user's environment (`~/.bashrc`).

**Execution Steps:**
1. Run the scanner:
   ```bash
   sonar-scanner -Dsonar.host.url=http://localhost:9000 -Dsonar.token=$SONARQUBE_CLI_TOKEN
   ```
2. Inspect issues table:
   ```bash
   sonar list issues --project afaq-ai-service --severities BLOCKER,HIGH,MEDIUM --format table
   ```
3. **Acceptance Criteria:** **0 BLOCKER, 0 HIGH, 0 MEDIUM** issues permitted.

### 5.4 Secret Scanning (Gitleaks)
* **Binary Location:** `/usr/bin/gitleaks` (installed via `apt`, in `PATH`).
* **Execution Command:**
  ```bash
  gitleaks detect --source . -v
  ```
* **Acceptance Criteria:** **0 leaks found**.

### 5.5 Dependency Vulnerability Scanning (Trivy)
* **Binary Location:** `/usr/bin/trivy` (v0.71.2, installed via `apt`, in `PATH`).
* **Important Guidelines:**
  * Use `--pkg-types library` instead of the deprecated `--vuln-type`.
  * **Always include `--skip-db-update`** to utilize the cached local database and prevent downloading multi-hundred-megabyte databases during routine checks.
* **Execution Command:**
  ```bash
  trivy fs . --scanners vuln --pkg-types library --severity HIGH,CRITICAL --skip-db-update
  ```
* **Acceptance Criteria:** **0 CRITICAL** vulnerabilities in active runtime dependencies.

### 5.6 Contract Verification & Deployment Gate (Pact)
Pact is used to prevent breaking contract changes between `afaq-ai-service` and consumer services (e.g., `afaq-main-service`).
* **Pact Broker URL:** `http://localhost:9292` (Docker container, no auth required).
* **CLI Tool:** `pact-broker-cli` v0.9.0 (installed at `/home/abood/.pact/bin/pact-broker-cli`, in `PATH`).
* **Mandatory Flag:** Always specify `--broker-base-url http://localhost:9292`.

**Core Commands:**
* **List Registered Pacticipants:**
  ```bash
  pact-broker-cli list-pacticipants --broker-base-url http://localhost:9292
  ```
* **Fetch Provider Contracts:**
  ```bash
  pact-broker-cli get-pacts --broker-base-url http://localhost:9292 --provider afaq-ai-service
  ```
* **Publish Contract (when updating contracts):**
  ```bash
  pact-broker-cli publish --broker-base-url http://localhost:9292 --consumer-app-version "<version>" --branch "main" pacts/afaq-main-service-afaq-ai-service.json
  ```
* **Check Deployment Safety:**
  ```bash
  pact-broker-cli can-i-deploy --pacticipant afaq-ai-service --version "<version>" --to-environment test --broker-base-url http://localhost:9292 --dry-run
  ```
* **Automated All-in-One Pact Verification Script:**
  ```bash
  ./scripts/pact_check.sh
  ```
  This script executes `pytest tests/contracts/`, publishes verification results to the local broker, and runs `can-i-merge` and `can-i-deploy` validation checks.

### 5.7 Architectural Fitness Testing (ArchUnitPython)
* **Package & Installation:** `archunitpython` v1.8.1 installed as a development dependency via `uv` in `pyproject.toml`.
* **Test Suite Location:** `tests/architecture/`
* **Execution Command:**
  ```bash
  uv run pytest tests/architecture/ -v
  ```
* **Architectural Invariants Enforced:**
  * **Zero Circular Dependencies:** `files("src").should().have_no_cycles()`
  * **Strict Layer Separation:** The `api` layer must never directly depend on `repositories` (`where_layer("api").may_not_depend_on_layers("repositories")`).
  * Domain services and protocols remain decoupled from external infrastructure implementations.
* **Acceptance Criteria:** 100% of architectural unit tests must pass.

### 5.8 Architectural Graph & Dependency Health (KG-ARCHMAP)
* **Binary Location:** Installed globally via `uv` tool at `/home/abood/.local/bin/archmap` and `/home/abood/.local/bin/archmap-check` (in `PATH`).
* **Execution Command:**
  ```bash
  archmap analyze src --fail-on-cycles --fail-on-layer-violations
  ```
* **Acceptance Criteria:**
  * **0 circular dependencies**.
  * **0 layer violations**.
  * **Health score $\ge 90/100$ (Grade A)** and 100% import resolution rate.

### 5.9 Architectural Baseline & Drift Prevention (Enola)
* **Binary Location:** Installed globally via official installer at `/home/abood/.local/bin/enola` (version `0.4.38`, in `PATH`).
* **Workflow:**
  1. **Before starting modifications**, pin the architectural baseline if needed:
     ```bash
     enola baseline pin .
     ```
  2. **Before committing**, grade architectural changes against the baseline:
     ```bash
     enola check . --fail-on=layers,cycles
     ```
* **Acceptance Criteria:** Exit code `0` (`PASS — no architectural change` or non-regressive structural delta).

### 5.10 Performance & Load Testing (k6)
* **Binary Location:** Installed globally via `snap` at `/snap/bin/k6` (in `PATH`).
* **Configuration & Workflow:**
  * Expected performance metrics (RPS, latency p95/p99, error rate thresholds) and concurrent virtual user (VU) load profiles will be provided in a designated **Markdown specification file**.
  * The agent **must read that Markdown file** before authoring or modifying any k6 test scripts to ensure load stages, thresholds, and scenarios match the stated requirements.
  * Run k6 scripts with:
    ```bash
    k6 run <path-to-script>.js
    ```

---

## 6. Pre-Commit Checklist Summary

Every functional commit must satisfy the following checklist:

| Verification Gate | Command | Passing Threshold |
| :--- | :--- | :--- |
| **Linting** | `uv run ruff check .` | 0 errors |
| **Formatting** | `uv run black --check .` | 0 files to reformat |
| **Unit & Contract Tests** | `uv run pytest --cov=src --cov-report=xml` | All tests pass, coverage XML generated |
| **Architectural Rules (ArchUnit)** | `uv run pytest tests/architecture/ -v` | All architectural invariant rules pass |
| **Architectural Health (KG-ARCHMAP)** | `archmap analyze src --fail-on-cycles --fail-on-layer-violations` | 0 cycles, 0 layer violations, Score $\ge 90$ |
| **Architecture Drift Gate (Enola)** | `enola check . --fail-on=layers,cycles` | Exit code 0 (Clean / No regression) |
| **Contract Gates (Pact)** | `./scripts/pact_check.sh` | Contracts verified, `can-i-deploy` ok |
| **Secrets Audit** | `gitleaks detect --source . -v` | 0 leaks found |
| **Dependency Security** | `trivy fs . --scanners vuln --pkg-types library --severity HIGH,CRITICAL --skip-db-update` | 0 CRITICAL vulnerabilities |
| **Quality & Vulnerabilities** | `sonar-scanner ...` & `sonar list issues ...` | 0 BLOCKER, 0 HIGH, 0 MEDIUM |

---

## 7. Documentation & Reporting Standards

* **Report Storage Location:**
  * All technical, audit, architecture, and engineering reports must be stored within the `docs/reports/` directory of the project.
  * Never place ad-hoc report markdown files loosely in the project root or top-level `docs/`.

* **Folder Organization:**
  * Each report or set of related reports must be placed in a dedicated subfolder that clearly identifies its purpose (e.g., `docs/reports/scraping_extraction_pipeline/`).
  * The subfolder must contain:
    1. The report document(s) themselves.
    2. A metadata file (`metadata.md`) documenting essential tracking details:
       - **Date:** (YYYY-MM-DD)
       - **Branch:** The active git branch
       - **Feature / Scope:** Associated feature name or ticket
       - **Author / Context:** Brief context or author reference

* **Exclusions:**
  * `speckit` files and reports are strictly excluded from this requirement, as they are treated as separate, specialized specification and tracking artifacts.
