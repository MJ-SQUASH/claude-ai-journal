# claude-journal (plugin)

The installable half of **claude-journal** — five factorized subagents, four slash
commands, two hooks, and one deterministic sync script that build and maintain a repo's
`{project}_journal/` *AI operating system*. For the full story, the manual `PROMPT.md`
path, and the journal file list, see the [repo README](https://github.com/junaiddop/claude-ai-journal).

## Install

```
/plugin marketplace add junaiddop/claude-ai-journal
/plugin install claude-ai-journal@claude-ai-journal
```

Or just tell Claude Code: `add agent https://github.com/junaiddop/claude-ai-journal`.

## Contents

```
plugins/claude-journal/
├── agents/
│   ├── journal-investigator.md   # stack recon + footguns  (Phase 0)
│   ├── journal-scribe.md         # writes the journal docs  (Phase 1)
│   ├── journal-automator.md      # CLAUDE.md router + .claude/ + git/CI  (Phases 2–4)
│   ├── journal-verifier.md       # link-check, hook + sync-loop tests  (Phase 5)
│   └── journal-reviewer.md       # ongoing audit / reconcile / issues + suggestions
├── commands/
│   ├── journal-init.md           # orchestrator — runs all five phases
│   ├── journal-ship.md           # pre-merge gate
│   ├── journal-audit.md          # footgun sweep
│   └── journal-gitignore.md      # toggle journal tracked (shared) vs ignored (private)
├── hooks/
│   └── hooks.json                # Stop → flag + render, SessionStart → detect
└── scripts/
    └── journal_sync.py           # flag | detect | clear <file> | render
```

## How it maps to the 5 phases

`/journal-init` is the orchestrator: it establishes your **TARGET** first, then drives the
phases through the subagents.

| Phase | Subagent | Does |
|-------|----------|------|
| 0 · Investigate | **journal-investigator** | Read-only recon: languages, run/test/CI, auth + data model, design tokens; pins the 2–4 footguns |
| 1 · Journal | **journal-scribe** | Writes the 15 `{project}_journal/` files (architecture, services, `dev.md`, target tracker, tasks/issues/suggestions, `claude_info.md`) |
| 2 · Router | **journal-automator** | Writes/merges the lean `CLAUDE.md` router linking every journal file |
| 3 · Automation | **journal-automator** | `.claude/settings.json` permissions + hooks; subagent + command scaffolds |
| 4 · Git/CI | **journal-automator** | `.githooks/` (post-commit/pre-commit), PR template, cheap CI gates |
| 5 · Verify | **journal-verifier** | Link-check, pipe-test hooks, probe the flag→detect→clear loop, `render`, run tests, report honestly |

**journal-reviewer** is the day-to-day maintainer, invoked by the two other commands and by
reconcile flows: it audits pending tasks against the real code (evidence, `file:line`;
`code exists ≠ works`, so 🟡 not 🟢 for the unverified), runs a scoped reconcile mode when
a hook flags stale tasks, grades diffs against `dev.md`'s checklist + the §0 footguns, and
logs bugs to `issues/` and ideas to `suggestions/` as **proposals** — it never creates,
deletes, or renames steps without your approval, and only touches files under the journal.

- **`/journal-ship`** → pre-merge gate: diff vs `dev.md` checklist, run checks, reconcile the
  journal, report pass/fail with evidence. Never auto-commits.
- **`/journal-audit`** → footgun sweep: rank findings with `file:line`, propose (not apply)
  fixes.
- **`/journal-gitignore`** → optional toggle: journal **shared** (tracked) vs **private**
  (whole `{project}_journal/` gitignored, local-only). Edits `.gitignore`, never commits.

## Hooks + sync script

`hooks/hooks.json` wires two events to `scripts/journal_sync.py` (resolved via
`${CLAUDE_PLUGIN_ROOT}`):

- **Stop** → `flag` (mark tasks whose mapped code changed) then `render` (rebuild
  `journal.html`).
- **SessionStart** → `detect` (surface any stale tasks as context for reconcile).

The script auto-detects the journal by globbing for a single `*_journal/` directory and
exits `0` **silently** when a repo has none — so this plugin is inert in non-journal repos.

Because the plugin already ships the script and hooks, **journal-automator installs neither**
when the plugin is present — it wires nothing that would duplicate them. (The manual
`PROMPT.md` path is the one that writes `journal_sync.py` into `{project}_journal/scripts/`
and hooks into `.claude/settings.json` instead.)

## Keep in sync

The plugin subagents and the repo's `PROMPT.md` are two front-ends to one system — change
one, update the other. See the
[repo README](https://github.com/junaiddop/claude-ai-journal) for the full file list and rules.
