<!--
Sync Impact Report:
- Version change: v2.2.0 -> v2.3.0
- Bump Rationale: Establish explicit prohibition on performance/execution time assertions in functional/unit/integration test suites and mandate that performance testing is restricted exclusively to user-configured k6 suites.
- Modified Principles: Added Principle VI and added domain invariant.
- Added Sections:
  - Principle VI: Prohibition of Performance & Execution Time Assertions in Functional Tests (Section 3).
- Removed Sections: None
- Follow-up TODOs: None
-->

# Afaq-AI-Service Constitution

## 1. Governance Purpose & Scope Guard

This Constitution serves as the authoritative governance document for **requirements engineering, architectural planning, task decomposition, and feature delivery** handled by SpecKit and AI agents on **Afaq-AI-Service**.

* **Separation of Concerns:**
  * General development workflows, static analysis tooling commands, binary locations, and pre-commit security pipelines are governed exclusively by [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md).
  * System architectural rules, component definitions, module boundaries, and automated tool enforcement mechanisms are governed exclusively by the living catalog [`ARCHITECTURAL_RULES_AND_BOUNDARIES.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/ARCHITECTURAL_RULES_AND_BOUNDARIES.md).
  * Feature planning, requirement specifications, test-driven designs, task structures, and human review governance are governed exclusively by this **Constitution**.

* **Mandatory Precautionary Reading of AGENT.md & Architecture Rules:**
  * Whenever the AI agent initiates or executes any SpecKit command or feature planning workflow (including `/speckit-specify`, `/speckit-plan`, `/speckit-tasks`, `/speckit-implement`, etc.), the agent **MUST** actively read [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md) and verify compliance with [`ARCHITECTURAL_RULES_AND_BOUNDARIES.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/ARCHITECTURAL_RULES_AND_BOUNDARIES.md).
  * Although the environment or prompt may automatically load `AGENT.md`, this explicit reading rule serves as a mandatory precautionary guardrail.
  * **Rationale:** Actively ingesting these documents ensures that the agent remains continuously aligned with current architectural rules, boundary definitions, pre-commit quality gates, and git branching policies across all stages of feature specification and task execution.

---

## 2. Mandatory 8-Artifact Feature Lifecycle

Before writing any application or service code for any feature or major enhancement, the AI agent and SpecKit **MUST** generate a dedicated feature directory containing exactly eight structured governance artifacts:

```
specs/<feature-name>/
├── 1. spec.md               # Functional requirements & user stories
├── 2. endpoints.md          # Complete API and webhook contracts
├── 3. use_cases.md          # Primary, edge, and worst-case failure scenarios
├── 4. plan.md               # Phased technical implementation blueprint
├── 5. test_plan.md          # TDD test specifications linked 1-to-1 to use cases
├── 6. security.md           # Pre-code threat modeling & sanitization strategy
├── 7. tasks.md              # Consolidated, dependency-ordered task breakdown
└── 8. review_priorities.md  # Human oversight priority matrix (Critical to Low)
```

### Artifact Specifications & Standards:

#### 1. Specification File (`spec.md`)
* **Purpose:** Defines the complete functional scope, user stories, and acceptance criteria.
* **Requirements:**
  * Must follow industry best practices for requirements engineering.
  * Every requirement must include: User Persona, User Story (`As a... I want to... So that...`), Technical Rationale, and Measurable Acceptance Criteria formatted in unambiguous `Given-When-Then` notation.
  * Must explicitly declare **Non-Goals & Out-of-Scope Boundaries** to prevent scope creep.

#### 2. Endpoints Contract File (`endpoints.md`)
* **Purpose:** Concrete, unambiguous specification of every new or modified API route and webhook.
* **Requirements:**
  * HTTP Method, full route path, and route description.
  * Authentication and authorization requirements (API key header, roles).
  * Detailed Request Specification: Query parameters, path parameters, and full Pydantic request models with types and field validations.
  * Detailed Response Specification: Standard response envelopes (`status`, `data`, `message`), HTTP status codes (`200`, `201`, `202`, etc.).
  * Error Catalog: Complete table of expected error status codes (`400`, `401`, `403`, `404`, `422`, `500`), error conditions, and exact error detail payloads.

#### 3. Use Cases & Scenarios File (`use_cases.md`)
* **Purpose:** Maps out the behavioral spectrum of the feature before implementation.
* **Requirements:**
  * **Primary (Happy Path) Scenarios:** Standard end-to-end execution flow.
  * **Edge Cases:** Null/omitted optional values, boundary numerical limits, unexpected unicode/multilingual characters, empty arrays, duplicate entries.
  * **Worst-Case & Failure Scenarios:** Network timeouts, upstream third-party service failures, invalid schemas, database locks, and malformed HTML payloads.
  * Each scenario must document: Preconditions, Trigger, Expected System Behavior, and Postconditions.

#### 4. Execution Plan File (`plan.md`)
* **Purpose:** Phased technical implementation plan generated by SpecKit.
* **Requirements:**
  * Architectural breakdown into logical phases (Data Models, Repositories, Core Domain Services, Security Gates, API Controllers).
  * Explicit dependency graph showing which components must be built first.
  * Rollback and contingency strategies for complex schema or contract changes.

#### 5. Test Plan File (`test_plan.md`)
* **Purpose:** Drives Test-Driven Development (TDD) to prevent architectural drift.
* **Requirements:**
  * **1-to-1 Mapping:** Every single use case and scenario from `use_cases.md` MUST have an associated test case explicitly specified in this plan.
  * **Test Categorization:** Unit tests, integration tests, contract tests (Pact), and architectural fitness tests (ArchUnit).
  * **TDD Enforcement:** Tests must be authored *before* feature code (Red-Green-Refactor). Tests act as guardrails that prevent deviations from the specification before code is created.

#### 6. Security Analysis & Strategy File (`security.md`)
* **Purpose:** Proactive, pre-implementation threat modeling and mitigation design.
* **Requirements:**
  * Identifies potential security vectors during the design stage (SSRF, Injection, ReDoS, XSS in scraped content, unauthorized data access).
  * Explicit Defense & Boundary Strategy: Specifies exact pre-scrape security verification rules, delimiter escaping, and strict boundary separation between non-mutating gatekeepers and downstream data cleaning pipelines.
  * Authentication & Permission Gates: Documents required API keys, headers, and access restrictions.
  * Automated Security Test Cases: Defines the negative tests and fuzz cases that must be executed to verify the security mitigations.

#### 7. Task List File (`tasks.md`)
* **Purpose:** The structured execution roadmap consolidating all prior artifacts into atomic tasks.
* **Requirements:**
  * Must consolidate inputs from `spec.md`, `endpoints.md`, `use_cases.md`, `plan.md`, `test_plan.md`, and `security.md`.
  * Tasks must be atomic, dependency-ordered, and sequenced sequentially.
  * Each task must declare: Task ID, Description, Target Files, Prerequisite Tasks, and Verification Command.

#### 8. Human Review Priority File (`review_priorities.md`)
* **Purpose:** Explicit ranking of tasks to guide human oversight and review efficiency.
* **Requirements:**
  * Categorizes every task from `tasks.md` into one of four review tiers:
    * **Tier 1 (Critical Review):** Security sanitization gates, authentication boundaries, raw database schema migrations, and external ingestion points. Must receive rigorous human review before merging.
    * **Tier 2 (High Review):** Core business logic, extraction algorithms, contract changes (Pact), and new API route handlers.
    * **Tier 3 (Medium Review):** Internal service refactoring, repository queries, error handling, and performance tuning.
    * **Tier 4 (Low Review):** Boilerplate code, unit test fixtures, documentation, type annotations, and lint formatting.
  * Lists tasks in descending order of oversight necessity so the human reviewer knows exactly which outputs to inspect first.

---

## 3. Spec-Driven Quality & Execution Principles

### Principle I: Zero Premature Implementation (Specification Gate)
* **Rule:** The AI agent and developers are **strictly prohibited** from writing application source code, feature routes, database queries, or domain logic until all eight mandatory planning artifacts are generated, cross-referenced, and **explicitly approved by the user**.
* **Rationale:** Writing code prior to detailed specification leads to architectural drift, rework, wasted context, and unreviewed assumptions.

### Principle II: Strict Bi-Directional Traceability
* **Rule:** Every functional task in `tasks.md` MUST cite its origin requirement in `spec.md`, its target use case in `use_cases.md`, and its verifying test in `test_plan.md`.
* **Zero Orphan Tasks:** Tasks that do not tie directly back to an approved requirement or test case are strictly forbidden.

### Principle III: Test-Driven Drift Prevention
* **Rule:** Implementation of every distinct functional unit MUST follow the Red-Green-Refactor cycle. Test cases defined in `test_plan.md` must be instantiated first, run to verify expected failure (Red), satisfied with minimal clean code (Green), and verified across static analysis and security tools.
* **Rationale:** Tests are not mere audit checks after the fact; they actively steer implementation code and prevent unauthorized behavioral drift.

### Principle IV: Specification Immutability During Execution
* **Rule:** Once the 8 planning artifacts are approved, the agent cannot alter feature scope or silently rewrite specifications during execution.
* **Amendment Protocol:** If technical blockers or edge cases discovered during implementation require altering the specification, the agent must pause, document the required amendment, and obtain explicit user consent before proceeding.

### Principle V: Precautionary Operational Context Ingestion (AGENT.md Mandate)
* **Rule:** Before authoring, modifying, or decomposing any feature artifacts through SpecKit, the agent **MUST** actively read [`AGENT.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/AGENT.md) to cross-reference technical constraints, verification commands, and operational boundaries.
* **Precautionary Rationale:** While tooling or environment configurations may inject `AGENT.md` into context automatically, this active read requirement prevents subtle context gaps, stale assumptions, and misalignment with current pre-commit verification pipelines or architectural constraints.

### Principle VI: Prohibition of Performance & Execution Time Assertions in Functional Tests
* **Rule:** Specifications, test plans, and automated unit/integration test suites must **NEVER** assert or enforce maximum execution time thresholds, latency SLAs, or duration expectations.
* **Technical Rationale:** The system depends on third-party networks, DNS providers, and external web hosts whose latencies and response speeds are inherently unpredictable. Imposing duration bounds produces flaky test suites.
* **Exclusive Performance Tooling:** The **ONLY** tests authorized to measure performance or latency are **k6 load/performance tests**, which operate strictly based on configuration scripts provided, managed, and executed by the user.

---

## 4. Non-Negotiable Core Domain Invariants

Regardless of feature scope, all feature specifications and plans MUST uphold the service's foundational operational constraints:

* **Public Data Only & Zero Paywall Bypass:** Afaq-AI-Service collects exclusively publicly accessible educational grant and scholarship listings. Automated bypassing of authentication paywalls, CAPTCHAs, or access controls is strictly prohibited.
* **Zero-Trust Gatekeeper Inspection:** Every scraped string, URL, and attachment MUST traverse the `src/modules/security/` gateway (RFC 3986 URL parsing, SSRF private IP blocking, ReDoS selector checks, and binary magic-byte inspection) before network processing. In accordance with [`ARCHITECTURAL_RULES_AND_BOUNDARIES.md`](file:///home/abood/Project/Afaq/Afaq-AI-Service/ARCHITECTURAL_RULES_AND_BOUNDARIES.md), the security module operates strictly as a pure, non-mutating gatekeeper, while rich HTML sanitization (`nh3`), entity decoding, and Unicode NFKC normalization are strictly deferred to downstream cleaning pipelines.
* **Single-Browser Low-Memory Bound:** Crawling operations MUST operate within a single-process concurrency ceiling (`max_concurrent_crawls = 1`) and adhere to the $\le 1$GB container RAM limit.
* **Raw vs. Cleaning Separation:** Raw extraction tables store unmutated publisher text. Canonical taxonomy normalization and translation are strictly reserved for downstream pipeline modules.
* **Zero Test Execution Time Assertions:** Functional, unit, and security test plans must not assert test completion time limits. Performance evaluations are restricted exclusively to user-configured k6 suites.

---

## 5. Governance & Versioning

* **Authority:** This Constitution is the binding governance agreement for all SpecKit workflows and agent planning activities on **Afaq-AI-Service**.
* **Versioning Policy:**
  * **MAJOR (X.0.0):** Governance restructuring, changes to the mandatory artifact set, or principle removals.
  * **MINOR (1.X.0):** Addition of new governance guidelines, review tiers, or expanded artifact standards.
  * **PATCH (1.0.X):** Wording clarifications, template formatting, and non-semantic corrections.
* **Review Cycle:** The constitution must be verified against delivered features at the completion of each major track.

**Version**: 2.3.0 | **Ratified**: 2026-11-01 | **Last Amended**: 2026-11-02
