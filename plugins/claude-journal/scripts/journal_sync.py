#!/usr/bin/env python3
"""journal_sync.py — deterministic sync tool for the claude-journal plugin.

Python 3 stdlib only. Four subcommands (argv[1]):

  flag           git-diff the working tree, map changed code paths to pending
                 tasks via pending_task/.step_map.json, and insert/update a
                 "**Stale:** ⚠️ code changed <date> — needs reconcile" line right
                 after each affected task's Status line. Idempotent. Never edits code.
  detect         scan pending_task/*.md + issues/*.md for stale markers; if any,
                 print the SessionStart hook JSON envelope to stdout. Silent if none.
  clear <file>   remove the stale marker from a pending_task/issues file. Idempotent.
  render         regenerate {journal}/journal.html — one self-contained dark
                 dashboard with four status-colored boards (target tracker,
                 pending tasks, issues, suggestions).

The journal is auto-discovered by globbing CLAUDE_PROJECT_DIR (fallback cwd) for a
single *_journal/ directory. If zero or ambiguous, the tool exits 0 silently so the
plugin's hooks are harmless in non-journal repos. Any internal error also exits 0
(printing to stderr) so a hook is never crashed.
"""

import glob
import html
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime

# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #

STALE_PREFIX = "**Stale:**"
STATUS_RE = re.compile(r"^\s*\**\s*status\s*\**\s*:", re.IGNORECASE)
STATUS_VAL_RE = re.compile(r"^\s*\**\s*status\s*\**\s*:\s*(.*?)\s*$", re.IGNORECASE)
SEVERITY_VAL_RE = re.compile(r"^\s*\**\s*severity\s*\**\s*:\s*(.*?)\s*$", re.IGNORECASE)
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

EMOJIS = ("🔴", "🟡", "🟢")


def log(msg):
    """Write a line to stderr (never stdout — stdout is reserved for hook JSON)."""
    sys.stderr.write(msg + "\n")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def read_lines(path):
    text = read_text(path)
    if text is None:
        return None
    return text.split("\n")


def write_lines(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def is_stale_line(line):
    return line.lstrip().startswith(STALE_PREFIX)


def find_base_dir():
    base = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.abspath(base)


def discover_journal(base):
    """Return the single *_journal/ dir under base, else None (zero or ambiguous)."""
    matches = [
        d for d in glob.glob(os.path.join(base, "*_journal")) if os.path.isdir(d)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def status_emoji(text):
    for e in EMOJIS:
        if e in text:
            return e
    return ""


# keyword -> chip colour (checked after explicit emoji)
_GREY = ("declined", "wontfix", "wont fix", "rejected", "cancelled", "canceled",
         "deferred", "obsolete")
_GREEN = ("done", "resolved", "complete", "completed", "shipped", "verified",
          "closed", "merged", "fixed", "green")
_AMBER = ("progress", "accepted", "partial", "review", "wip", "amber", "yellow",
          "ongoing")
_RED = ("open", "proposed", "todo", "not started", "blocked", "new", "pending",
        "red", "failing", "backlog")


def chip_class(value):
    v = value.lower()
    if "🟢" in value:
        return "green"
    if "🟡" in value:
        return "amber"
    if "🔴" in value:
        return "red"
    for k in _GREY:
        if k in v:
            return "grey"
    for k in _GREEN:
        if k in v:
            return "green"
    for k in _AMBER:
        if k in v:
            return "amber"
    for k in _RED:
        if k in v:
            return "red"
    return "grey"


def file_title(path, text):
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return os.path.basename(path)


def first_match(text, regex):
    for line in text.split("\n"):
        m = regex.match(line)
        if m:
            return m.group(1).strip().strip("*").strip()
    return ""


# --------------------------------------------------------------------------- #
# flag
# --------------------------------------------------------------------------- #

def git_root(base):
    try:
        out = subprocess.run(
            ["git", "-C", base, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, ValueError):
        pass
    return base


def _unquote(path):
    path = path.strip()
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        path = path[1:-1]
    return path


def changed_paths(repo_root):
    """Return changed tracked + untracked paths (relative to repo_root)."""
    try:
        out = subprocess.run(
            ["git", "-C", repo_root, "status", "--porcelain"],
            capture_output=True, text=True,
        )
    except (OSError, ValueError):
        return []
    if out.returncode != 0:
        return []
    paths = []
    for line in out.stdout.split("\n"):
        if not line.strip():
            continue
        rest = line[3:] if len(line) > 3 else ""
        if not rest:
            continue
        if " -> " in rest:  # rename: "old -> new"
            rest = rest.split(" -> ", 1)[1]
        paths.append(_unquote(rest))
    return paths


def load_step_map(journal_dir):
    path = os.path.join(journal_dir, "pending_task", ".step_map.json")
    text = read_text(path)
    if text is None:
        return {}
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        log("journal_sync: .step_map.json is not valid JSON — skipping flag.")
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def resolve_task_file(journal_dir, value):
    value = str(value).strip()
    cands = [
        os.path.join(journal_dir, "pending_task", value),
        os.path.join(journal_dir, value),
        os.path.join(journal_dir, "pending_task", os.path.basename(value)),
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def insert_stale_marker(task_path, date_str):
    """Insert/refresh a single stale marker right after the task's Status line."""
    lines = read_lines(task_path)
    if lines is None:
        return False
    # Drop any existing stale markers first (makes insert == update, idempotent).
    lines = [l for l in lines if not is_stale_line(l)]
    marker = "%s ⚠️ code changed %s — needs reconcile" % (STALE_PREFIX, date_str)
    status_idx = None
    for i, l in enumerate(lines):
        if STATUS_RE.match(l):
            status_idx = i
            break
    if status_idx is not None:
        lines.insert(status_idx + 1, marker)
    else:
        # No Status line: place after the first heading, else at the very top.
        insert_idx = 0
        for i, l in enumerate(lines):
            if l.lstrip().startswith("#"):
                insert_idx = i + 1
                break
        lines.insert(insert_idx, marker)
    write_lines(task_path, lines)
    return True


def cmd_flag(journal_dir):
    repo_root = git_root(journal_dir)
    journal_rel = os.path.relpath(journal_dir, repo_root).replace(os.sep, "/")
    step_map = load_step_map(journal_dir)
    if not step_map:
        log("journal_sync flag: no .step_map.json entries — nothing to flag.")
        return

    paths = changed_paths(repo_root)
    # Loop guard: never react to journal-only changes.
    code_paths = []
    for p in paths:
        norm = p.replace(os.sep, "/")
        if norm == journal_rel or norm.startswith(journal_rel + "/"):
            continue
        code_paths.append(norm)

    affected = {}  # task_path -> set(matching prefixes)
    for p in code_paths:
        for prefix, task_files in step_map.items():
            if not prefix:
                continue
            if p.startswith(prefix):
                if isinstance(task_files, str):
                    task_files = [task_files]
                for tf in task_files or []:
                    tp = resolve_task_file(journal_dir, tf)
                    if tp:
                        affected.setdefault(tp, set()).add(prefix)

    if not affected:
        log("journal_sync flag: %d changed path(s), none mapped to a task."
            % len(code_paths))
        return

    today = date.today().isoformat()
    flagged = []
    for tp in sorted(affected):
        if insert_stale_marker(tp, today):
            flagged.append(os.path.basename(tp))
    log("journal_sync flag: marked %d task(s) stale: %s"
        % (len(flagged), ", ".join(flagged)))


# --------------------------------------------------------------------------- #
# detect
# --------------------------------------------------------------------------- #

def cmd_detect(journal_dir):
    stale = []
    for sub in ("pending_task", "issues"):
        d = os.path.join(journal_dir, sub)
        if not os.path.isdir(d):
            continue
        for f in sorted(glob.glob(os.path.join(d, "*.md"))):
            text = read_text(f)
            if text and any(is_stale_line(l) for l in text.split("\n")):
                stale.append(os.path.basename(f))
    if not stale:
        return  # print NOTHING
    n = len(stale)
    context = ("%d stale item(s): %s. Use the journal-reviewer subagent to "
               "reconcile them." % (n, ", ".join(stale)))
    envelope = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    sys.stdout.write(json.dumps(envelope, separators=(",", ":")))
    sys.stdout.write("\n")


# --------------------------------------------------------------------------- #
# clear
# --------------------------------------------------------------------------- #

def cmd_clear(journal_dir, name):
    if not name:
        log("journal_sync clear: missing <file> argument.")
        return
    cands = [
        name,
        os.path.join(journal_dir, name),
        os.path.join(journal_dir, "pending_task", name),
        os.path.join(journal_dir, "issues", name),
        os.path.join(journal_dir, "pending_task", os.path.basename(name)),
        os.path.join(journal_dir, "issues", os.path.basename(name)),
    ]
    path = next((c for c in cands if os.path.isfile(c)), None)
    if path is None:
        log("journal_sync clear: file not found: %s" % name)
        return
    lines = read_lines(path)
    if lines is None:
        return
    new_lines = [l for l in lines if not is_stale_line(l)]
    if len(new_lines) != len(lines):
        write_lines(path, new_lines)
        log("journal_sync clear: removed stale marker from %s"
            % os.path.basename(path))
    else:
        log("journal_sync clear: no stale marker in %s (idempotent)"
            % os.path.basename(path))


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #

def parse_target_steps(journal_dir):
    path = os.path.join(journal_dir, "steps_pending_to_target.md")
    text = read_text(path)
    if text is None:
        return []
    steps = []
    for line in text.split("\n"):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        first = cells[0]
        # skip header and separator rows
        if not re.match(r"^\d+$", first):
            continue
        step_cell = cells[1]
        status_cell = cells[2]
        m = LINK_RE.search(step_cell)
        if m:
            title, href = m.group(1).strip(), m.group(2).strip()
        else:
            title, href = re.sub(r"[*`]", "", step_cell).strip(), None
        status = status_cell.strip()
        steps.append({
            "num": first,
            "title": title,
            "href": href,
            "status": status or status_emoji(status_cell),
        })
    return steps


def collect_cards(journal_dir, sub, with_severity=False):
    d = os.path.join(journal_dir, sub)
    cards = []
    if not os.path.isdir(d):
        return cards
    for f in sorted(glob.glob(os.path.join(d, "*.md"))):
        text = read_text(f)
        if text is None:
            continue
        title = file_title(f, text)
        status = first_match(text, STATUS_VAL_RE)
        rel = "%s/%s" % (sub, os.path.basename(f))
        card = {"title": title, "href": rel, "status": status}
        if with_severity:
            card["severity"] = first_match(text, SEVERITY_VAL_RE)
        cards.append(card)
    return cards


def _chip_html(status_text):
    text = status_text.strip() or "—"
    cls = chip_class(status_text)
    return '<span class="chip %s">%s</span>' % (cls, html.escape(text))


def _card_html(title, href, status_text, extra=""):
    inner = (
        '<div class="card-head">'
        '<span class="card-title">%s</span>%s'
        "</div>%s"
    ) % (html.escape(title), _chip_html(status_text), extra)
    if href:
        return '<a class="card" href="%s">%s</a>' % (html.escape(href), inner)
    return '<div class="card">%s</div>' % inner


def _board_html(title, accent, cards_html, count):
    body = cards_html or '<div class="empty">Nothing here yet.</div>'
    return (
        '<section class="board board-%s">'
        '<h2><span class="dot"></span>%s<span class="count">%d</span></h2>'
        '<div class="cards">%s</div>'
        "</section>"
    ) % (accent, html.escape(title), count, body)


def build_html(journal_dir):
    project = os.path.basename(journal_dir.rstrip("/")).replace("_journal", "")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Target tracker
    steps = parse_target_steps(journal_dir)
    target_cards = "".join(
        _card_html("%s. %s" % (s["num"], s["title"]), s["href"], s["status"])
        for s in steps
    )

    # Pending tasks
    tasks = collect_cards(journal_dir, "pending_task")
    task_cards = "".join(
        _card_html(t["title"], t["href"], t["status"]) for t in tasks
    )

    # Issues (status + severity)
    issues = collect_cards(journal_dir, "issues", with_severity=True)
    issue_cards = "".join(
        _card_html(
            i["title"], i["href"], i["status"],
            extra=('<div class="meta">Severity: %s</div>'
                   % html.escape(i["severity"])) if i.get("severity") else "",
        )
        for i in issues
    )

    # Suggestions
    suggestions = collect_cards(journal_dir, "suggestions")
    suggestion_cards = "".join(
        _card_html(s["title"], s["href"], s["status"]) for s in suggestions
    )

    boards = (
        _board_html("Target tracker", "target", target_cards, len(steps))
        + _board_html("Pending tasks", "tasks", task_cards, len(tasks))
        + _board_html("Issues", "issues", issue_cards, len(issues))
        + _board_html("Suggestions", "suggestions", suggestion_cards,
                      len(suggestions))
    )

    return HTML_TEMPLATE % {
        "project": html.escape(project or "project"),
        "stamp": html.escape(stamp),
        "boards": boards,
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(project)s journal</title>
<style>
  :root {
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2230; --border:#2a3038;
    --fg:#e6edf3; --muted:#8b949e;
    --red:#f85149; --amber:#e3b341; --green:#3fb950; --grey:#6e7681;
    --accent:#58a6ff;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:var(--bg); color:var(--fg);
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
    padding:24px;
  }
  header { max-width:1200px; margin:0 auto 20px; }
  header h1 { margin:0 0 4px; font-size:22px; letter-spacing:.2px; }
  header .sub { color:var(--muted); font-size:12.5px; }
  header .sub code { color:var(--accent); }
  .grid {
    max-width:1200px; margin:0 auto;
    display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:16px;
  }
  .board {
    background:var(--panel); border:1px solid var(--border); border-radius:10px;
    padding:14px 14px 16px; display:flex; flex-direction:column;
  }
  .board h2 {
    margin:0 0 12px; font-size:14px; font-weight:600; letter-spacing:.3px;
    display:flex; align-items:center; gap:8px; text-transform:uppercase;
    color:var(--fg);
  }
  .board h2 .dot { width:9px; height:9px; border-radius:50%%; flex:0 0 auto; }
  .board h2 .count {
    margin-left:auto; background:var(--panel2); color:var(--muted);
    border-radius:20px; padding:1px 9px; font-size:12px; font-weight:600;
  }
  .board-target h2 .dot { background:var(--accent); }
  .board-tasks h2 .dot { background:var(--amber); }
  .board-issues h2 .dot { background:var(--red); }
  .board-suggestions h2 .dot { background:var(--green); }
  .cards { display:flex; flex-direction:column; gap:9px; }
  a.card, div.card {
    display:block; text-decoration:none; color:inherit;
    background:var(--panel2); border:1px solid var(--border);
    border-left:3px solid var(--grey);
    border-radius:8px; padding:10px 12px; transition:border-color .12s,background .12s;
  }
  a.card:hover { background:#232c3d; border-color:var(--accent); }
  .card-head { display:flex; align-items:center; gap:10px; }
  .card-title { font-weight:500; flex:1 1 auto; word-break:break-word; }
  .meta { color:var(--muted); font-size:12px; margin-top:5px; }
  .chip {
    flex:0 0 auto; font-size:11.5px; font-weight:600; padding:2px 9px;
    border-radius:20px; white-space:nowrap; border:1px solid transparent;
  }
  .chip.red   { color:var(--red);   background:rgba(248,81,73,.12);  border-color:rgba(248,81,73,.35); }
  .chip.amber { color:var(--amber); background:rgba(227,179,65,.12); border-color:rgba(227,179,65,.35); }
  .chip.green { color:var(--green); background:rgba(63,185,80,.12);  border-color:rgba(63,185,80,.35); }
  .chip.grey  { color:var(--muted); background:rgba(110,118,129,.12);border-color:rgba(110,118,129,.35); }
  .empty { color:var(--muted); font-size:12.5px; font-style:italic; padding:6px 2px; }
  footer { max-width:1200px; margin:22px auto 0; color:var(--muted); font-size:12px; }
</style>
</head>
<body>
  <header>
    <h1>%(project)s &mdash; journal</h1>
    <div class="sub">Review dashboard &middot; generated by
      <code>journal_sync.py render</code> &middot; self-contained, no external requests</div>
  </header>
  <main class="grid">
    %(boards)s
  </main>
  <footer>Last rendered %(stamp)s</footer>
</body>
</html>
"""


def cmd_render(journal_dir):
    out_path = os.path.join(journal_dir, "journal.html")
    doc = build_html(journal_dir)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    log("journal_sync render: wrote %s" % out_path)


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #

def main(argv):
    if len(argv) < 2:
        log("usage: journal_sync.py {flag|detect|clear <file>|render}")
        return 0

    cmd = argv[1]
    base = find_base_dir()
    journal_dir = discover_journal(base)
    if journal_dir is None:
        # zero or ambiguous *_journal/ — no-op silently.
        return 0

    if cmd == "flag":
        cmd_flag(journal_dir)
    elif cmd == "detect":
        cmd_detect(journal_dir)
    elif cmd == "clear":
        cmd_clear(journal_dir, argv[2] if len(argv) > 2 else "")
    elif cmd == "render":
        cmd_render(journal_dir)
    else:
        log("journal_sync: unknown command %r" % cmd)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as exc:  # never crash a hook
        log("journal_sync: internal error: %s" % exc)
        sys.exit(0)
