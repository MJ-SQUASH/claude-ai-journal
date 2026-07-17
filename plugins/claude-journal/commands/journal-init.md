---
description: Set up (or refresh) this repo's AI operating system: journal docs + automation, via factorized subagents.
argument-hint: "[optional: target milestone]"
---

You are the orchestrator for this repo's AI operating system. Run the five phases
below **in order**, delegating each to its subagent. This command is the
installed-agent equivalent of running `PROMPT.md` by hand — the two MUST stay
consistent; if you find yourself diverging from it, stop and reconcile.

Derive `{project}` from the target repo's name (kebab/snake as fits). The journal
lives at `{project}_journal/` in the repo root.

## Ground rules (apply through every phase)
- **Never commit.** No `git add` / `commit` / `push`. This is setup only.
- **Don't duplicate the plugin.** The claude-journal plugin already ships the
  Stop/SessionStart hooks, `journal_sync.py` (referenced via
  `${CLAUDE_PLUGIN_ROOT}`), and the `journal-reviewer` subagent. If those are
  already active in this repo, do NOT re-create the script, the hooks, or a
  `{project}-journal-reviewer.md` — wire the repo to the plugin's copies instead.
- **Keep every doc lean:** one owner per fact, link instead of duplicating.
- Run phases strictly in sequence — each subagent's output feeds the next. Carry
  the Phase 0 findings brief forward to every later phase.

## Phase 0 — Investigate (read-only)
Delegate to **journal-investigator**. It explores the stack, run/test/lint
tooling, CI, existing docs, design tokens, auth/tenancy model, integration SDKs,
and deploy story, then identifies this project's 2–4 footguns. Hold onto the
findings brief it returns — everything written later is grounded in it. Write
nothing in this phase.

## Phase 1 — Write the journal
**First, establish the TARGET milestone** (go-live / MVP / a specific release):
- If `$ARGUMENTS` is given, use it as the target.
- Otherwise ask the user, or identify a candidate from the repo state and confirm
  it. Do not proceed on an unconfirmed target.

**Then derive the step list** from the actual repo state and **ask the user to
confirm it** before any tracker is written.

Delegate to **journal-scribe** (hand it the findings brief + confirmed target +
confirmed step list). It creates the 15 lean, cross-linked, "Last reviewed"–dated
journal files: README index, `{project}_architecture.md`, `{project}_services.md`,
`design.md` (only if there's UI), `dev.md`, `setup.md`, `runbook.md`,
`steps_pending_to_target.md` + `pending_task/` files + `pending_task/.step_map.json`,
`issues/`, `suggestions/`, `journal.html`, `claude_info.md`, and
`scripts/journal_sync.py`.
- **Plugin-aware:** if the plugin already provides `journal_sync.py`, the scribe
  does NOT re-create it under `{project}_journal/scripts/`; the repo relies on the
  plugin's copy (the automator confirms wiring in Phase 3).

## Phases 2–4 — Automate
Delegate to **journal-automator** (with the findings brief). It handles:
- **Phase 2 — CLAUDE.md router:** create or **merge** (never clobber) a lean root
  router — 3-line what-it-is, run/test commands, one-line footgun golden rules, and
  a "Working docs" section linking every journal file with a one-line "read when".
- **Phase 3 — `.claude/` automation:** `permissions.allow` for safe read-only
  commands on this stack, plus the sync hooks and slash commands. **Plugin-aware:**
  if the plugin's hooks + `journal_sync.py` are already active, do NOT add
  duplicate hooks or script and do NOT re-create `journal-reviewer` — only add the
  project-specific `new-<unit>` command (note that `/journal-ship` and
  `/journal-audit` already ship with the plugin). Only when the plugin is absent
  does it wire `.claude/settings.json` hooks to
  `{project}_journal/scripts/journal_sync.py` and create the reviewer subagent.
- **Phase 4 — git hooks + PR template + hygiene:** `.githooks/post-commit` (runs
  `flag`), `.githooks/pre-commit` (format/lint STAGED files, gracefully skipping
  missing tools, block merge-conflict markers), `chmod +x` both,
  `git config core.hooksPath .githooks`; `.github/PULL_REQUEST_TEMPLATE.md` (the
  `dev.md` pre-merge checklist as checkboxes); a `.gitkeep` in `issues/`,
  `suggestions/`, and `pending_task/`; and append to the target repo `.gitignore`:
  `{project}_journal/journal.html`, `__pycache__/`, and
  `{project}_journal/.investigation.md`.
- **Surface any blocker, never force.** If `core.hooksPath` is already set,
  existing hooks / PR template would be overwritten, a format/lint tool is missing,
  or a CI gate fails on the current code — STOP, tell the user exactly what's
  blocked and why, and wait for their call. Never silently skip, overwrite, or
  work around it.

## Phase 5 — Verify (do not skip)
Delegate to **journal-verifier**. It link-checks every journal markdown link,
pipe-tests both hook commands, jq-validates `settings.json`, probe-tests the sync
loop (touch a mapped file → `flag` → stale marker appears → `detect` emits the
envelope → `clear` → restore, leaving zero markers behind), runs `render` and
confirms `journal.html`'s four boards (target, tasks, issues, suggestions)
populate and link to real files, and runs the test suite if cheaply runnable. It
returns a summary table of everything created plus the two manual steps for the
user: `git config core.hooksPath .githooks` on other clones, and opening `/hooks`
once (or restarting) so the new `settings.json` is picked up.

Relay the verifier's summary to the user, and note any blockers the automator
surfaced. Remember: nothing was committed — the user reviews and commits.
