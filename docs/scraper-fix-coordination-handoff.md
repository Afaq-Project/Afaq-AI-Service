# Scraper Fix Coordination Handoff

**Status date:** 2026-11-26  
**Repository:** `/home/abood/Project/Afaq/Afaq-AI-Service`  
**Branch:** `feat/test-coverage-gap-remediation`

## Purpose

This document hands off the approved scraper-fix plan and current execution state to another coordinating agent. It records the intended work, known issues, prior implementation/review activity, test state, and workspace cautions. The approved plan was agreed in the conversation; this is its durable handoff copy.

## Goal and agreed scope

The scraper must process an entry URL, locate and extract scholarship listings, then extract each opportunity's details. The intended flow is:

1. **Level 0 — Discovery:** Analyze the submitted entry page once. Distinguish whether the submitted URL is a homepage, a catalog page, or a detail page. If it is a homepage, record where the catalog is located (URL or tab). If the catalog URL is submitted directly, use that URL as the catalog entry.
2. **Level 1 — Catalog:** Navigate to the catalog, create and validate a catalog template on first use, reuse it for matching catalog layouts, and persist correctly mapped listing metadata and absolute detail URLs.
3. **Level 2 — Details:** Create and validate a detail template on first use, reuse it for matching detail layouts, and map extracted values to the existing `RawOpportunityPayload` contract.

The draft database contract is accepted as-is. Do not redesign it or treat contract standardization as a task. Empty payloads passing the contract were explicitly deferred and should not be added to this scope. Preserve existing crawler protections and the recent fixes to description, application URL candidate, image, and alternate-link handling.

## Confirmed issues and required outcomes

### Level 0

- The old `is_catalog_page` boolean could not distinguish a generic homepage from an opportunity detail page. A `False` value must not be guessed as either role. Discovery needs an explicit page role.
- A generic homepage must not be analyzed as a detail page. Onboarding must not create scraper templates; first-use template synthesis belongs in Levels 1 and 2.
- The robots.txt fetch validated DNS but then used a regular hostname-based HTTP request, leaving a DNS-rebinding gap. The request must go to the validated resolved IP, preserving Host/SNI and revalidating each redirect hop.

### Level 1

- URL catalog navigation is supported; tab navigation is not yet connected to the catalog crawl. Support both safely.
- The template matcher returns card keys such as `card_title_preview`, `card_snippet_preview`, and `card_image_url`, while persistence reads `title`, `snippet`, and `image_url`. Map the actual matcher output so stored listing metadata is not lost.
- Relative card detail links must be resolved against the catalog page URL and validated before being stored or crawled.
- The default production `TemplateEngineService` is created without an LLM client. Ensure the normal API construction path can synthesize a validated template on a cache miss and reuse it thereafter.

### Level 2

- The detail phase matches existing templates but does not call the get-or-synthesize flow on a miss. Wire first-use Level 2 synthesis and subsequent reuse.
- The generated detail selector uses the field name `deadline`; the raw payload contract uses `deadline_raw`. Normalize that and all generated outputs to the existing contract before validation/persistence.
- The default production template engine also needs its LLM client wired for Level 2 synthesis.
- Preserve validation of application URL candidates and canonical final URLs. Add tests for success and rejected URLs.
- Do **not** expand the work into rejecting empty payloads; that issue was explicitly deferred.

## Approved execution order and task acceptance criteria

### T1 — Level 0 role semantics and robots pinning

**Implementation scope:**

- `src/modules/scraping/services/discovery_service/relevance_gate.py`
- `src/modules/scraping/services/discovery_service/prompts.py`
- `src/modules/scraping/services/discovery_service/onboarding.py`
- Minimal security/crawler transport file only if needed for pinned robots requests.

**Acceptance:** A required explicit role distinguishes homepage/catalog/detail; a direct catalog URL remains the catalog entry; homepage navigation is stored separately; onboarding does not analyze a generic homepage as a detail page or persist scraper templates; robots requests use the validated IP and preserve safe redirect handling.

### T2 — Level 1 URL/tab navigation

**Implementation scope:**

- `src/modules/scraping/services/crawler_service.py`
- `src/modules/scraping/services/scraper_service/catalog_phase.py`

**Acceptance:** URL navigation validates before opening; tab navigation activates a validated CSS selector before capture; rejected destinations/selectors and activation failures do not become successful catalog extraction.

### T3 — Level 1 template synthesis and listing persistence

**Implementation scope:**

- `src/api/protocols.py`
- `src/modules/scraping/services/scraper_service/__init__.py`
- `src/modules/scraping/services/scraper_service/coordinator.py`
- `src/modules/scraping/services/template_engine_service/__init__.py`
- `src/modules/scraping/services/scraper_service/catalog_phase.py`
- `src/modules/scraping/services/template_engine_service/matcher.py` only if output normalization belongs there.

**Acceptance:** Normal API wiring supplies the LLM client; the first catalog page generates and validates a Level 1 template; later matching pages reuse it; metadata is persisted under correct fields; relative URLs become absolute and pass validation; synthesis/extraction failure is not reported as successful extraction.

### T4 — Level 2 template synthesis and payload mapping

**Implementation scope:**

- `src/modules/scraping/services/template_engine_service/__init__.py`
- `src/modules/scraping/services/scraper_service/details_phase.py`
- `src/modules/scraping/extraction_contract.py` only if required to reference existing fields; do not redesign the contract.

**Acceptance:** First detail page generates and validates a Level 2 template; later pages reuse it; generated fields (including `deadline`) normalize to the existing payload names (including `deadline_raw`); application URLs are validated and canonical final URLs are stored; existing description/image/alternate-link processing remains intact.

### T5 — Integration and completion review

**Relevant tests:**

- `tests/integration/modules/scraping/test_stage_0_discovery.py`
- `tests/integration/modules/scraping/test_batch_scrape_orchestration.py`
- `tests/unit/modules/scraping/test_template_engine_service.py`
- `tests/unit/modules/scraping/test_crawler_service.py`
- Add focused Level 1/Level 2 phase tests under `tests/unit/modules/scraping/` as needed.

**Acceptance:** Cover homepage-to-catalog URL, homepage-to-tab, direct catalog input, first-use template creation and reuse for Levels 1 and 2, metadata mapping, URL normalization/validation, and key failure paths. Run targeted suites and report exact commands/results. Do not mark a task complete based solely on an implementer report.

**Order:** `T1 → T2 → T3 → T4 → T5`.

## Current execution state

### T1 production work

An OpenCode `implementer` completed an initial implementation and a review-correction pass in the same session. Session/job ID: `ses_de8c37f38ffeolJYRZ5DBcubTn`.

The current T1 diff touches:

- `src/modules/scraping/services/discovery_service/relevance_gate.py`: adds required `page_role` values and normalization; only legacy `is_catalog_page=True` may infer `catalog`; false/absent must not be guessed.
- `src/modules/scraping/services/discovery_service/prompts.py`: asks for explicit page role and catalog navigation.
- `src/modules/scraping/services/discovery_service/onboarding.py`: stops invoking onboarding-time template persistence/synthesis; uses page role for any remaining role decisions; pins robots requests to resolved IP, sends Host/SNI, revalidates redirects, and brackets IPv6 literals.

My review found and returned one logic issue: mapping legacy `is_catalog_page=False` to `detail`. The implementer corrected it. The current diff appears to meet the T1 production acceptance criteria, but it has **not passed the independent test gate**. The implementer reported `18 passing, 4 stale existing tests failing` after the correction; treat this as an unverified agent claim until the tests and output are inspected.

### Tester/MCP state

The tester was dispatched in a separate OpenCode session/job: `ses_de8ab9167ffePcVO6LwJysFiAX`. The MCP status was inconsistent: a direct status request said “job not found or already completed,” while the job list showed `submitted_waiting_for_messages`, zero messages/tools, and stale. After that observation, `tests/unit/modules/scraping/test_relevance_gate.py` appeared as a new untracked file with focused role-validation tests. No reliable final tester report or exact test output has been received. The next coordinator should inspect this file/diff and check the current OpenCode job/session state before dispatching duplicate work.

### Prior test results (not validation of current T1)

Before T1 changes, the focused scraping suites passed: 67 scraping unit tests and 21 scraping integration tests. These results predate the Level 0 changes and do not verify the current tree.

## Workspace precautions

The branch is `feat/test-coverage-gap-remediation`. The working tree was already dirty before this coordination task. Do not reset, clean, or revert files wholesale. Preserve the existing work and review diffs carefully before editing.

At the latest recorded `git status`, modified tracked files included:

- `src/modules/scraping/services/crawler_service.py`
- `src/modules/scraping/services/discovery_service/onboarding.py`
- `src/modules/scraping/services/discovery_service/prompts.py`
- `src/modules/scraping/services/discovery_service/relevance_gate.py`
- `src/modules/scraping/services/scraper_service/__init__.py`
- `src/modules/scraping/services/scraper_service/catalog_phase.py`
- `src/modules/scraping/services/scraper_service/coordinator.py`
- `src/modules/scraping/services/scraper_service/details_phase.py`
- `src/modules/scraping/services/template_engine_service/__init__.py`
- `tests/integration/modules/scraping/test_batch_scrape_orchestration.py`
- `tests/integration/modules/scraping/test_stage_0_discovery.py`

Untracked files included `scripts/deploy_on_Codespaces/`, `src/modules/scraping/extraction_contract.py`, `tests/unit/modules/scraping/test_extraction_contract.py`, and the newly appearing `tests/unit/modules/scraping/test_relevance_gate.py`. Some of these predate T1; inspect before attributing or modifying them. No commits were made during the orchestration work.

The local Nimbalyst checklist at `nimbalyst-local/wiki/قائمة مهام إصلاحات الكشط.md` has checkboxes that were previously marked complete ahead of implementation. Do not trust those statuses without checking acceptance criteria; update them only after each task passes review and tests.

## Coordination instructions for the next agent

1. Start with `git status --short` and inspect the current Level 0 diff, preserving all existing changes.
2. Resolve the tester job/report ambiguity without submitting duplicate tests blindly. Review `test_relevance_gate.py`, obtain exact test output, and add/update focused tests for onboarding and robots pinning if absent.
3. Complete and mark T1 only after the independent review and test gate passes.
4. Continue T2, T3, T4, then T5 in order. Keep implementer and tester responsibilities separate, review each diff before testing, and use a fresh OpenCode session for each unrelated task.
5. Keep prompts and file reads scoped to the current task to control MCP/model usage. Stop after three fix cycles per task and escalate any unresolved ambiguity.

No LLM API keys, tokens, or other credentials are included in this handoff. Do not copy secrets from conversation history into project files or agent prompts.
