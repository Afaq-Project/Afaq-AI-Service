# Agent Engineering Guidelines & Standards

This document establishes the architectural principles, coding conventions, testing guidelines, and operational standards for engineers and AI agents working on **Afaq-AI-Service**.

---

## 1. Architectural Boundaries (Modular Monolith)

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

## 2. RESTful API Standards & Response Conventions

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

## 3. Testing Philosophy (Value-Driven, High Signal)

Tests exist to prevent regressions and verify real business behaviors. Avoid test bloat and redundant coverage metrics.

### What MUST Be Tested (High-Value Areas)
* **Core Business Logic:** Scoring algorithms, eligibility evaluation, normalization rules, state transitions, and deduplication logic.
* **Edge Cases & Boundaries:**
  * Empty inputs, null/missing optional fields, unicode/special characters.
  * Extreme values, boundary limits, and malformed dates.
  * Timeouts, upstream service failures, and non-200 HTTP responses.
* **Repository Contracts:** Ensuring database queries return expected shapes and handle missing records cleanly.
* **Security & Auth Gates:** Enforcing API key presence, validity, and scope checks.

### What MUST NOT Be Tested (Anti-Patterns to Avoid)
* **Boilerplate & Framework Guarantees:** Do not test that Pydantic validates fields, that FastAPI routes traffic, or that Python's built-in functions work.
* **Trivial Getters / Setters / Models:** Do not write unit tests simply to instantiate a class or assert default model field values unless custom validation logic is present.
* **Hollow / Over-Mocked Tests:** Avoid tests where 90% of the code is configuring mocks that do not reflect realistic execution paths.
* **Duplicate Coverage:** If a behavior is thoroughly tested in a service unit test, do not write identical duplicate tests in route tests just to increase lines covered.

### Test Hygiene & Speed
* **Execution Constraint:** The entire test suite must run in **under 15 seconds** locally (`uv run pytest`).
* **Determinism:** Tests must be completely deterministic. Never make real network, database, or LLM calls during standard unit testing—use fakes, in-memory fixtures, or mocked clients.

---

## 4. Code Quality & Tooling Standards

* **Package Management:**
  * Strictly use `uv` for all dependency management (`uv add`, `uv sync`, `uv run`).
  * Never use or commit `poetry`, `pip`, or alternative package managers.

* **Code Formatting & Linting:**
  * Code must strictly comply with **Ruff** and **Black**.
  * Run static checks before committing:
    ```bash
    uv run ruff check src tests
    uv run black --check src tests
    uv run mypy src
    ```

* **Type Safety:**
  * Strict type annotations are mandatory for all public functions, methods, and class attributes.
  * Avoid `Any` wherever possible. Use `typing.Protocol`, generics, or Pydantic models.

* **Git Conventions:**
  * Follow Conventional Commits: `feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`.
  * Work on dedicated feature branches (e.g. `feat/feature-name`).
  * Keep commits atomic and logically separated.

* **Environment Safety:**
  * **Never run `docker build` locally.** Container builds are handled exclusively by GitHub Actions CI.

---

## 5. Documentation & Reporting Standards

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
