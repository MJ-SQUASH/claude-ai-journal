---
description: Sweep the codebase for the project's top footguns (from dev.md §0) and report ranked findings — propose, don't apply.
argument-hint: "[optional: footgun name]"
---

Run a footgun sweep over this repo. A "footgun" is a mistake that raises **no compiler/type error** yet breaks security, billing, or correctness (e.g. a missing tenant filter, an ungated quota/paywall, a skipped authz check). This command reports and LOGS findings only — it never edits product code and never commits.

## 1. Locate the journal and load the footguns
- Find the single `*_journal/` directory at the repo root. If none exists, tell the user to run `/journal-init` first, then stop.
- Read `{project}_journal/dev.md` and extract the **§0 golden rules** — these are this project's authoritative footguns. Also note the "§14"-style pre-merge checklist for grading context.
- Scope:
  - If `$ARGUMENTS` names a footgun, sweep for that ONE (match it to the closest §0 rule).
  - Otherwise sweep for ALL top footguns listed in dev.md §0.
- If dev.md or its §0 section is missing, say so and stop — do not invent footguns.

## 2. Sweep
Prefer delegating to the **journal-reviewer** subagent for the evidence-gathering pass; otherwise sweep directly. Either way:
- For each footgun, derive concrete search signatures from dev.md's own guidance (the query builders, decorators, guards, middleware, or filters that §0 says must be present) and grep/glob the codebase for both the **safe pattern** and its **absence** at the enforcement points.
- Be a skeptic: "the guard exists somewhere" ≠ "this call site is guarded". Verify each hit at its actual `file:line`.
- Ignore the journal itself and generated artifacts (`journal.html`, `__pycache__/`).

## 3. Report — ranked
Print a single ranked table, worst first, one row per finding:

| Rank | Footgun (§0 rule) | `file:line` | What's wrong | Severity | Confidence |

- Severity by blast radius: cross-tenant/security/billing leaks first, then correctness.
- Confidence = Confirmed (read the code, exploitable) vs Suspected (pattern match, needs a human look). Never inflate.
- End with a one-line summary: N confirmed, M suspected, or "no footgun violations found".

## 4. Log each finding (proposal only)
For every finding, create ONE journal entry under `{project}_journal/` — a record for the user to review, not an action:
- A **confirmed violation in existing behavior** → `issues/{slug}_issue.md` (Status box: `🔴 open`, Severity, Owner, Last reviewed today; "← Back" link to `../README.md`; symptom, affected code paths at `file:line`, fix checklist, verification).
- A **hardening idea / potential-but-unproven risk** → `suggestions/{slug}_suggestion.md` (Status box: `proposed`, rough impact + effort, Owner, Last reviewed today; "← Back" link; the suggestion, why it helps, affected paths).
- Use kebab/snake slugs; don't overwrite an existing entry for the same finding — update its Last reviewed instead.

## 5. Propose fixes — never apply
For each finding, describe the fix inline in the report and in its journal entry (the diff shape, the guard to add, the call sites to touch) — but **do not edit product code, do not run fixes, do not commit.** Applying a fix is a separate, user-approved step.

Close by pointing the user at the new `issues/`/`suggestions/` entries and the refreshed `journal.html` (regenerated on the next Stop hook, or via `journal_sync.py render`).
