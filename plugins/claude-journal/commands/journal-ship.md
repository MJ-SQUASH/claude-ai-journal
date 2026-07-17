---
description: "Pre-merge gate: review the diff against dev.md's checklist, run checks, reconcile the journal, report pass/fail with evidence — never auto-commit."
disable-model-invocation: true
---

You are the pre-merge gate. Judge the working changes against this repo's own
rules, prove the verdict with evidence, and leave committing to the human. Do NOT
`git add`, `git commit`, `git push`, or amend anything — ever.

Work in `{project}_journal/` at the repo root (`{project}` = this repo's name).
If no `*_journal/` exists, tell the user to run `/journal-init` first and stop.

## 1. Scope the diff
Capture exactly what would merge:
- `git status --short` and `git diff` (unstaged + staged, e.g. `git diff HEAD`),
  plus untracked files not covered by `.gitignore`.
Summarize the changed code paths — this scope drives every step below. Ignore
changes confined to `{project}_journal/` for the code review, but keep them for
the reconcile in step 4.

## 2. Diff-review vs dev.md
Open `{project}_journal/dev.md`. Walk the diff against:
- **§0 golden rules** — the project's footguns (missing tenant filter, missing
  quota/authz gate, etc.). Each footgun the diff touches is a mandatory line item.
- the **pre-merge checklist** (the §14-style list at the end of dev.md).
For every item: state PASS or FAIL and cite the concrete `file:line` in the diff
that satisfies or violates it. No hand-waving — a claim without a `file:line` is
not evidence. Cross-check `design.md` too if the diff touches UI.

## 3. Run the project's checks
Run the exact lint / typecheck / test commands recorded in `dev.md`, `runbook.md`,
or `setup.md` — do not invent commands or assume a stack. Capture each command's
real exit status and the relevant output. If a check can't run (missing tool,
needs services), report it as BLOCKED with the reason, not as PASS.

## 4. Reconcile the journal (scoped to the diff)
Invoke the **journal-reviewer** subagent in its reconcile mode, scoped to this
diff only: map the changed code paths to tasks via `pending_task/.step_map.json`,
re-verify only those tasks against the real code, update their
checkboxes/status/dates, and clear resolved stale markers. It must respect human
hand-edits (flag contradictions, never clobber), log any new bugs it finds as
`issues/` entries and improvement ideas as `suggestions/` entries, and it never
creates/renames/deletes steps without explicit approval. It touches only files
under `{project}_journal/`.

## 5. Report PASS / FAIL
Emit one table, most-critical first:

| Check | Result | Evidence (file:line) |
|-------|--------|----------------------|
| §0 footgun: <name> | PASS/FAIL | path:line |
| Checklist: <item> | PASS/FAIL | path:line |
| lint / typecheck / tests | PASS/FAIL/BLOCKED | command + exit status |
| Journal reconcile | PASS/FAIL | tasks/issues/suggestions touched |

Then a one-line **overall verdict**: SHIP only if every row is PASS; otherwise
NO-SHIP with the blocking rows named. Never soften a FAIL and never auto-commit —
report and hand back to the user for their call.

## Note
After the reconcile, `journal_sync.py render` regenerates `journal.html` from the
updated docs. The Stop hook runs `render` automatically; if you want the dashboard
refreshed immediately, run the `render` mode of the journal's `journal_sync.py`
(provided by the claude-journal plugin, or at `{project}_journal/scripts/journal_sync.py`
in a manual setup). `journal.html` is a generated, gitignored artifact — do not commit it.
