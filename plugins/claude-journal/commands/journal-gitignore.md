---
description: Toggle whether {project}_journal/ is tracked in git (shared) or ignored (private/local-only). Edits .gitignore only — never commits.
argument-hint: "[private | shared | status]"
---

Choose how this repo's journal is stored in git. This command edits the target repo's **`.gitignore` only** — it never touches product code and never runs `git add` / `commit` / `push`. Two modes:

- **shared** *(the `/journal-init` default)* — the journal is committed and versioned with the repo; only generated artifacts are ignored (`journal.html`, `.investigation.md`, `__pycache__/`). Pick this when the team shares the AI operating system.
- **private** — the entire `{project}_journal/` is gitignored and stays local to your clone. Pick this when the journal is a personal scratch layer you don't want in history.

## 1. Locate the journal
Find the single `*_journal/` directory at the repo root. If none exists, tell the user to run `/journal-init` first, then stop. Derive `{project}` from its name.

## 2. Pick the mode
From `$ARGUMENTS`:
- `private` → ignore the whole journal.
- `shared` (or `tracked`) → track the journal, ignore only the generated artifacts.
- `status` or empty → **change nothing yet**: report the current state (is the private block present in `.gitignore`?), say which mode is active, and ask the user which they want. Only proceed once they choose.

## 3. Edit `.gitignore` — idempotent and reversible
Manage a single fenced block so the toggle is clean and re-runnable. If the block already exists, rewrite it in place — never duplicate lines already present (respect the baseline `/journal-init` wrote).

- **Baseline — always present, both modes.** Ensure these artifact ignores exist:
  ```
  {project}_journal/journal.html
  {project}_journal/.investigation.md
  __pycache__/
  ```
- **private mode — add/keep this block** (in addition to the baseline):
  ```
  # >>> claude-journal: private (journal ignored) >>>
  {project}_journal/
  # <<< claude-journal: private <<<
  ```
- **shared mode — remove the private block** if present; leave the baseline intact.

## 4. Untrack already-committed files (private mode only)
`.gitignore` does **not** remove files already tracked by git. If switching to **private** while the journal is already committed, tell the user to run this themselves:
```
git rm -r --cached {project}_journal/
```
That stops tracking the files while keeping them on disk. This command does **not** run it — no `git` writes here — it's the user's to run, then commit.

## 5. Report
State the new mode, the exact `.gitignore` lines added/removed, and the next step: the user reviews and commits the `.gitignore` change (plus the `git rm --cached` above if going private). Never commit.
