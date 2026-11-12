---
name: code-and-test-review
description: Review code and tests produced by an AI agent. Verify that the code avoids unnecessary complexity, uses the minimal sufficient implementation, contains meaningful tests rather than test-count padding, and complies with the project's explicit constraints and conventions.
---

# Code and Test Review

## Purpose

Review code and tests authored by an AI agent against four questions:

1. Is the code unnecessarily complex?
2. Is it the minimal sufficient code for the task?
3. Are the tests meaningful and behavior-focused rather than merely numerous?
4. Does the implementation comply with the project's explicit constraints and conventions?

Do not trust the AI agent's self-report. Inspect the actual diff, files, tests, and project instructions.

## Inputs

Use all available sources:

- The task specification or issue.
- The code diff and changed files.
- The test diff and changed tests.
- Project instructions such as `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md`, architecture docs, style guides, and CI configuration.
- Existing nearby code and tests for conventions.
- Test results, lint results, type-check results, and build results if available.

If project constraints are missing or ambiguous, state that explicitly and review against observable conventions. Do not invent requirements.

## Review Principles

### 1. Complexity Review

Check for:

- Unnecessary abstractions, layers, factories, wrappers, or indirection.
- Premature generalization for hypothetical future needs.
- Duplicated logic that should be simplified or consolidated.
- Overly clever code, unnecessary metaprogramming, or hidden control flow.
- Excess configuration where a constant or direct implementation is enough.
- Dead code, unused parameters, unused dependencies, or speculative extension points.
- Functions or modules that do more than their name and responsibility imply.
- Error handling that is excessive, inconsistent, or masks failures.

Distinguish between:

- **Essential complexity**: required by the problem.
- **Accidental complexity**: introduced by the implementation.

Flag accidental complexity only when it has a concrete cost: harder review, harder testing, more failure modes, or more maintenance.

### 2. Minimal Sufficiency Review

Check whether the implementation is the smallest reasonable change that fully solves the task.

Ask:

- Does every changed line serve the stated task?
- Could the same behavior be achieved with fewer concepts, files, dependencies, or abstractions?
- Are new dependencies justified?
- Is there duplicated or redundant code that can be removed without harming clarity?
- Is the solution simple without being fragile or cryptic?
- Does it preserve required readability, safety, and maintainability?

Important: "minimal" does not mean code golf. Prefer clear, idiomatic, maintainable code over the shortest possible code. Do not recommend removing necessary validation, error handling, accessibility, security checks, or tests.

### 3. Test Quality Review

Evaluate whether tests are meaningful, not whether there are many.

Check for:

- Tests that assert observable behavior and outcomes, not implementation details.
- Coverage of the main success path.
- Coverage of important edge cases and failure modes.
- Regression tests for the specific bug or requirement.
- Tests that would fail if the implementation were wrong.
- Clear arrange/act/assert structure where appropriate.
- Deterministic tests with no unnecessary sleeps, network calls, or flakiness.
- Appropriate use of mocks: no over-mocking that makes tests tautological.
- No redundant tests that repeat the same assertion with trivial variations.
- No tests that only assert that code runs, snapshots everything without purpose, or test framework behavior.
- Test names that describe behavior and expected outcome.

Flag:

- Test-count padding.
- Tests coupled to private implementation details.
- Missing negative or boundary tests where risk is real.
- Overly broad integration tests where focused tests would be clearer, or vice versa.
- Tests that cannot fail for the relevant defect.

### 4. Project Compliance Review

Verify compliance with explicit project constraints, including:

- Architecture and module boundaries.
- Public API contracts.
- Error-handling and logging conventions.
- Security and privacy requirements.
- Performance constraints.
- Style, lint, formatting, and typing rules.
- Dependency policies.
- Backward compatibility requirements.
- CI, build, and test commands.
- Documentation or changelog requirements.
- Naming and file-placement conventions.

Create a compliance matrix with:

- Constraint source.
- Requirement.
- Evidence.
- Status: compliant, non-compliant, unclear, or not applicable.

## Process

1. **Establish scope**
   - Identify the task, changed files, and relevant project constraints.
   - Note any missing information.

2. **Read before judging**
   - Read the full diff and enough surrounding code to understand context.
   - Read existing tests and conventions.
   - Run available checks if permitted: tests, lint, type-check, build.

3. **Map requirements to changes**
   - List the task requirements.
   - Map each requirement to implementation and test evidence.
   - Identify unrequested changes.

4. **Review complexity and minimality**
   - Identify concrete instances of unnecessary complexity.
   - Identify opportunities to reduce code, concepts, dependencies, or files.
   - Do not recommend simplification that reduces correctness, clarity, safety, or testability.

5. **Review tests**
   - Evaluate whether tests prove the required behavior.
   - Identify missing high-value tests.
   - Identify low-value or redundant tests.
   - Check determinism and isolation.

6. **Review compliance**
   - Build the compliance matrix.
   - Cite the source of each constraint.
   - Mark unclear items instead of guessing.

7. **Produce findings**
   - Rank by severity.
   - Include file and line references when possible.
   - Explain impact and recommend a concrete action.
   - Separate blocking issues from suggestions.

## Severity Levels

- **Critical**: correctness, security, data loss, or project-breaking violation.
- **High**: likely bug, missing essential test, or clear violation of a hard project constraint.
- **Medium**: unnecessary complexity, maintainability risk, weak test coverage, or convention violation with moderate impact.
- **Low**: minor simplification, naming, or style suggestion.
- **Nit**: optional polish; do not over-report.

## Output Format

Return the review in this structure:

```markdown
# Code and Test Review

## Verdict
One of: Approve, Approve with suggestions, Request changes, Block.

## Scope Reviewed
- Task:
- Files reviewed:
- Checks run:
- Constraints sources:
- Missing information:

## Summary
Short assessment of complexity, minimality, test quality, and compliance.

## Findings

| Severity | Area | Location | Finding | Evidence | Recommended action |
|---|---|---|---|---|---|
| High | Tests | ... | ... | ... | ... |

## Complexity and Minimality Review
- Essential complexity:
- Accidental complexity:
- Simplification opportunities:
- Changes that should not be simplified:

## Test Quality Review
- Meaningful coverage:
- Missing high-value tests:
- Redundant or low-value tests:
- Determinism and isolation concerns:

## Project Compliance Matrix

| Constraint source | Requirement | Evidence | Status |
|---|---|---|---|
| ... | ... | ... | Compliant / Non-compliant / Unclear / N/A |

## Required Changes
1. ...

## Suggested Improvements
1. ...

## Residual Risks
- ...

## Evidence Limitations
- ...
```

## Rules

- Review the actual code and tests; do not rely on summaries.
- Cite concrete evidence for every non-trivial finding.
- Prefer specific, actionable recommendations over general advice.
- Do not request rewrites unless the current approach is unjustifiably complex or non-compliant.
- Do not equate fewer lines with better code.
- Do not equate more tests with better tests.
- Do not invent project constraints.
- Do not report style nits as blocking unless the project treats them as blocking.
- If checks could not be run, say so and lower confidence accordingly.
- Keep the review proportional to the change size and risk.
