# Journal Service — Technical Specification (MERN)

Last reviewed: 2026-09-08 · Status: proposal (v0.1) · Companion: [ARCHITECTURE.md](./ARCHITECTURE.md)

This document is the build contract. Section numbers are referenced from the roadmap in §12.

## 1. Stack

| Layer | Choice | Version (pin at scaffold) | Notes |
|-------|--------|---------------------------|-------|
| Runtime | Node.js | 22 LTS | `engines.node >= 22` |
| Language | TypeScript | 5.x, `strict: true` | Everywhere, including the web app |
| Database | MongoDB | 7.x | Atlas in prod, `mongo:7` container in dev |
| ODM | Mongoose | 8.x | Schemas below; `strictQuery: true` |
| API | Express | 5.x | Async handlers natively; `zod` for validation |
| Realtime | Socket.IO | 4.x | Same process as Express |
| Jobs | Agenda | 5.x | Queue lives in MongoDB (`jobs` collection) |
| Auth | Passport (`passport-github2`) + `jsonwebtoken` | — | Session = signed JWT in httpOnly cookie |
| Web | React | 19 | Vite 6, React Router 7, TanStack Query 5 |
| Styling | Tailwind CSS | 4 | Dark theme first, matches `journal.html` palette |
| Markdown | `react-markdown` + `remark-gfm` + `rehype-sanitize` + `mermaid` | — | Sanitised; no raw HTML |
| Editor | CodeMirror 6 (`@codemirror/lang-markdown`) | — | Raw editor behind a toggle |
| Board | `@dnd-kit/core` + `@dnd-kit/sortable` | — | Kanban drag-and-drop, keyboard accessible |
| Billing | Stripe (`stripe` SDK) | — | Checkout, Customer Portal, webhooks; no card data in the app |
| Email | Resend (`resend` SDK) | — | Invites, magic links, receipts; adapter interface so Postmark/SES can swap in |
| File storage | MongoDB GridFS (v1) behind a `Storage` adapter | — | Snapshot exports; S3 adapter later |
| Logging | pino + pino-http | — | JSON logs, request ids |
| Testing | Vitest, Supertest, `mongodb-memory-server`, Playwright | — | See §10 |
| Tooling | pnpm workspaces, Turborepo, ESLint (flat), Prettier | — | One lint/format config for all packages |
| Packaging | Docker (multi-stage) + Docker Compose v2, **shipped in the plugin** | — | See §11a; Docker Desktop / Engine 24+ is the only host prerequisite |

## 2. Repository layout

The service lives in this repo beside the plugin so the parser and plugin stay in lockstep.

```
claude-ai-journal/
├── plugins/claude-journal/            # existing plugin
│   ├── commands/journal-serve.md      # NEW: up | down | status | logs | upgrade | reset (§11a)
│   ├── docker/                        # NEW: shipped with the plugin
│   │   ├── docker-compose.yml         # journal-api + journal-mongo, pinned image tag
│   │   └── env.example                # template for ~/.claude-journal/.env
│   └── scripts/journal_sync.py        # gains remote mode (§8)
├── docs/service/                      # this spec + architecture
├── apps/
│   ├── api/                           # Express + Socket.IO + Agenda
│   │   ├── src/
│   │   │   ├── index.ts               # boot: env → mongo → bootstrap(local mode) → express → static web → socket → agenda
│   │   │   ├── config/env.ts          # zod-validated env (§9)
│   │   │   ├── db/                    # mongoose connect, scopedModel helper
│   │   │   ├── models/                # User, Workspace, Membership, Project, Document, Revision, StepMap, ApiKey, SyncEvent
│   │   │   ├── middleware/            # auth (cookie | api-key), ctx, error, rateLimit
│   │   │   ├── routes/                # auth, workspaces, invitations, billing, projects, documents, sync, dashboard, board, assets, share (public), badge (public), webhooks
│   │   │   ├── plans.ts               # plan catalogue + quotas (§9a); enforceQuota()
│   │   │   ├── services/              # documents.service, sync.service, dashboard.service, github.service
│   │   │   ├── realtime/              # socket namespaces + auth
│   │   │   ├── jobs/                  # reparse, linkcheck, githubPull, nightlySnapshot, pruneRevisions, hardDeleteTenants
│   │   │   └── openapi.ts             # generated from zod schemas
│   │   └── test/
│   └── web/                           # React SPA
│       ├── src/
│       │   ├── main.tsx, router.tsx
│       │   ├── api/                   # typed client (generated from OpenAPI)
│       │   ├── features/              # auth, onboarding, workspaces, members, billing, projects, docs, dashboard, board, tasks, issues, suggestions, assets, share (public), settings, activity
│       │   ├── components/            # MarkdownView, StatusChip, Board, Card, DocTree, StaleBanner, RevisionDiff
│       │   └── lib/                   # linkRewrite, socket, theme
│       └── e2e/
├── packages/
│   ├── journal-core/                  # pure TS parser (§4)
│   │   ├── src/{parse,stepMap,stale,tracker,kinds}.ts
│   │   └── test/golden/               # fixtures + expected JSON produced by journal_sync.py
│   └── shared/                        # zod schemas + TS types shared by api, web, core
├── docker-compose.dev.yml             # dev only: mongo + hot-reload api/web
├── Dockerfile                         # the single published image (api + built web)
├── turbo.json, pnpm-workspace.yaml, package.json
└── .github/workflows/ci.yml
```

## 3. Data model (Mongoose)

All project-scoped collections have `projectId` indexed and are only accessed through
`scopedModel(Model, projectId)` (§7). Timestamps (`createdAt`, `updatedAt`) on every schema.

```ts
// users
{ _id, githubId: string (unique), login: string, name?: string, email?: string, avatarUrl?: string }

// workspaces  (= tenant = billing account)
{ _id, slug: string (unique), name: string, ownerId: ObjectId,
  plan: 'free'|'team'|'business'|'self_hosted',
  stripeCustomerId?: string,
  usage: { projects: number, members: number, snapshots: number, shareLinks: number, storageBytes: number },
  deletedAt?: Date | null, hardDeleteAt?: Date | null }

// subscriptions  (mirror of Stripe; written only by webhooks)
{ _id, workspaceId (unique), stripeSubscriptionId: string, plan, status: 'trialing'|'active'|'past_due'|'canceled',
  seats: number, currentPeriodEnd: Date }

// billing_events  (webhook idempotency)
{ _id, stripeEventId: string (unique), type: string, receivedAt: Date }

// invitations
{ _id, workspaceId, email: string, role, tokenHash: string, invitedBy, expiresAt: Date, acceptedAt?: Date }

// auditlogs (append-only)
{ _id, workspaceId, actorId?, action: string, target: { type, id }, ip?: string, meta?: object }

// snapshots  (an asset version)
{ _id, workspaceId, projectId, name: string, createdBy?: ObjectId, trigger: 'manual'|'nightly'|'milestone',
  documentCount: number, exportFileId?: ObjectId (GridFS zip), htmlFileId?: ObjectId }
// snapshot_documents: { snapshotId, path, kind, title, markdown, meta }  — frozen copies

// sharelinks
{ _id, workspaceId, projectId, snapshotId?: ObjectId, tokenHash: string, label?: string,
  expiresAt?: Date, revokedAt?: Date, views: number }

// memberships
{ _id, workspaceId, userId, role: 'owner'|'admin'|'member'|'viewer' }   // unique (workspaceId, userId)

// projects  (= one Repository Asset)
{ _id, workspaceId, slug: string,            // = {project}; unique (workspaceId, slug)
  name: string, repoUrl?: string, defaultBranch?: string,
  journalRoot: string,                       // e.g. "myapp_journal"
  target?: { title: string, confirmedAt: Date },
  syncMode: 'push'|'github'|'both',
  github?: { installationId: number, repoFullName: string },
  lastSyncAt?: Date }

// documents
{ _id, projectId, path: string,              // unique (projectId, path); relative to journalRoot
  kind: 'readme'|'architecture'|'services'|'design'|'dev'|'setup'|'runbook'|'tracker'|'task'|'issue'|'suggestion'|'claude_info'|'step_map'|'other',
  title: string, markdown: string,           // exact text, max 1 MB
  contentHash: string,                       // sha256(markdown)
  version: number,                           // optimistic concurrency
  meta: { status?: string, statusColor?: 'red'|'amber'|'green'|'grey',
          owner?: string, severity?: string, impact?: string, effort?: string,
          lastReviewed?: string, backLink?: string,
          checklist?: { total: number, done: number },
          contradiction?: boolean, parseError?: string },
  stale?: { flaggedAt: Date, changedPaths: string[] } | null,
  board?: { order: number },                 // kanban position inside its column; UI state only, never written to markdown
  deletedAt?: Date | null }                  // soft delete when a file disappears from a push

// revisions (append-only)
{ _id, projectId, documentId, version: number, markdown: string, contentHash: string,
  source: 'hook'|'web'|'api'|'github', actor: { userId? , apiKeyId? }, conflict: boolean }
// index (documentId, version desc); TTL/pruning policy: keep all for v1

// stepmaps
{ _id, projectId (unique), entries: [{ prefix: string, taskPaths: string[] }], raw: object }

// apikeys
{ _id, projectId, label: string, prefix: string,       // first 8 chars, for display
  hash: string (sha256), scopes: ['sync'], lastUsedAt?: Date, revokedAt?: Date }

// syncevents
{ _id, projectId, type: 'push'|'flag'|'detect'|'clear'|'pull'|'github_pull',
  actor: { userId?, apiKeyId? }, summary: { files: number, stale: number, conflicts: number },
  changedPaths: string[], durationMs: number }
```

**Board derivation** (no extra collection):
- *Target tracker* = parse the `tracker` document's table (`|#|Step|Status|`) → rows with `num`,
  `title`, `href`, `status`; `href` resolves to the `task` document with that path.
- *Pending tasks* = `documents` where `kind: 'task'`.
- *Issues* = `kind: 'issue'` (chip + severity). *Suggestions* = `kind: 'suggestion'`.

## 4. `packages/journal-core` — the deterministic parser

A pure, side-effect-free port of the read-only parts of `journal_sync.py`. Must produce identical
results; golden tests enforce it.

| Function | Port of | Contract |
|----------|---------|----------|
| `classifyKind(path)` | file list in README | `steps_pending_to_target.md → tracker`, `pending_task/*.md → task`, `issues/*.md → issue`, `suggestions/*.md → suggestion`, `*_architecture.md → architecture`, `*_services.md → services`, fixed names → their kind, else `other` |
| `parseTitle(md)` | `file_title` | First `# ` heading, else basename |
| `parseStatusMeta(md)` | `first_match(STATUS_VAL_RE / SEVERITY_VAL_RE)` + table form | Handles both the `**Status:** x` line and the `\| Status \| Owner \| Last reviewed \|` table used by the reviewer templates |
| `chipClass(status)` | `chip_class` | Same emoji-first, then keyword lists (`_GREY`, `_GREEN`, `_AMBER`, `_RED`) |
| `parseTracker(md)` | `parse_target_steps` | Numeric first cell, link in step cell, status cell |
| `parseStepMap(json)` | `load_step_map` | Prefix → string \| string[] normalised to string[] |
| `mapChangedPaths(paths, stepMap, journalRel)` | `cmd_flag` core | Drops journal-relative paths (loop guard), prefix match, returns affected task paths |
| `hasStaleMarker(md)` / `insertStaleMarker(md, date)` / `clearStaleMarker(md)` | `is_stale_line`, `insert_stale_marker`, `cmd_clear` | Idempotent; marker after the Status line, else after first heading |
| `parseChecklist(md)` | new | Counts `- [ ]` / `- [x]` |
| `columnFor(kind, status)` | new, built on `chipClass` | Maps a status to a board column id: tasks `todo\|in_progress\|verified`, issues `open\|in_progress\|resolved`, suggestions `proposed\|accepted\|done\|declined` |
| `setStatus(md, status)` / `setOwner`, `setLastReviewed` | new | Rewrites one cell of the `\| Status \| Owner \| Last reviewed \|` table (or the `**Status:**` line); returns new markdown; no-op if unchanged |
| `syncTrackerRow(trackerMd, taskPath, status)` | new | Updates the `Status` cell of the tracker row whose link resolves to `taskPath`; returns unchanged text if no row matches |
| `appendNote(md, line)` | new | Appends a line under `## Notes` (creates the section if missing); used for verification notes and `⚠️ contradiction:` lines |
| `extractLinks(md)` | `LINK_RE` | For link-check job and link rewriting |

**Golden tests:** `test/golden/<case>/journal/**` fixtures plus `expected.json` generated by
running the Python script (`render` output parsed, `flag`/`detect` results) on the same fixture.
A CI step regenerates expected output with Python and diffs against the TS parser.

## 5. API contract (`/api/v1`)

Auth modes: **cookie** (web user) or **`X-Api-Key`** (sync client, project-scoped). Every route
declares which it accepts. Behaviour depends on `AUTH_MODE` (§9):

| `AUTH_MODE` | Web login | Sync key | Project creation |
|-------------|-----------|----------|------------------|
| `local` (plugin default) | None. Requests from the browser are treated as the bootstrap user `local`, owner of workspace `local`. The API binds to `127.0.0.1` only. | The single `LOCAL_API_KEY` from `~/.claude-journal/.env` (hash stored at bootstrap) | `POST /sync/push` with an unknown `projectSlug` auto-creates the project in workspace `local` |
| `github` | GitHub OAuth | Per-project keys created in Settings | Explicit, by a workspace admin | All bodies validated with zod; errors are `{ error: { code, message,
details? } }`. Pagination: `?limit=50&cursor=`.

### Auth
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/auth/github` | — | Start OAuth |
| GET | `/auth/github/callback` | — | Finish OAuth, set cookie, redirect to web |
| POST | `/auth/logout` | cookie | Clear cookie |
| POST | `/auth/email` | — | Send magic link (SaaS mode) |
| GET | `/auth/email/callback` | — | Consume magic link, set cookie |
| GET | `/me` | cookie | Current user + memberships + onboarding state |
| DELETE | `/me` | cookie | Delete account (blocked while sole owner of a workspace) |

### Workspaces & projects
| Method | Path | Auth / role | Purpose |
|--------|------|-------------|---------|
| GET/POST | `/workspaces` | cookie | List / create |
| GET/PATCH | `/workspaces/:ws` | member / admin | Read / rename |
| GET/PATCH/DELETE | `/workspaces/:ws/members/:u` | admin | Change role / remove (quota-checked on invite, audited) |
| GET/POST/DELETE | `/workspaces/:ws/invitations` | admin | List / send / revoke invites (email) |
| POST | `/invitations/:token/accept` | cookie | Join the workspace |
| GET | `/workspaces/:ws/usage` | member | Usage counters vs plan limits |
| GET | `/workspaces/:ws/audit` | admin | Audit log, paginated |
| POST | `/workspaces/:ws/export` | owner | Async job → ZIP of every project; email + download link |
| DELETE | `/workspaces/:ws` | owner | Soft delete now, hard delete in 14 days; revokes keys and share links |
| GET/POST | `/workspaces/:ws/projects` | member / admin | List / create (`slug`, `journalRoot`, `repoUrl`) |
| GET/PATCH/DELETE | `/projects/:p` | member / admin / owner | Read / update target, syncMode / soft delete |
| GET/POST | `/projects/:p/api-keys` | admin | List / create (returns full key once) |
| DELETE | `/projects/:p/api-keys/:k` | admin | Revoke |

### Billing (SaaS mode only; 404 in self-host)
| Method | Path | Auth / role | Purpose |
|--------|------|-------------|---------|
| GET | `/plans` | — | Plan catalogue with quotas and prices |
| POST | `/workspaces/:ws/billing/checkout` | owner | `{ plan }` → Stripe Checkout session URL |
| POST | `/workspaces/:ws/billing/portal` | owner | Stripe Customer Portal URL |
| GET | `/workspaces/:ws/billing` | admin | Subscription mirror + next invoice date |
| POST | `/webhooks/stripe` | Stripe signature | Idempotent by `event.id`; updates `subscriptions` + `workspaces.plan` |

### Repository assets (snapshots, exports, share links, badge)
| Method | Path | Auth / role | Purpose |
|--------|------|-------------|---------|
| GET/POST | `/projects/:p/snapshots` | member | List / create (`{ name }`), quota-checked |
| GET | `/projects/:p/snapshots/:id` | member | Snapshot metadata + document list |
| GET | `/projects/:p/snapshots/:id/docs/*path` | member | Frozen document |
| GET | `/projects/:p/export?format=zip\|html&snapshot=:id?` | member | ZIP of the Markdown tree, or the single-file HTML dashboard (same renderer output as `journal_sync.py render`) |
| GET/POST | `/projects/:p/share-links` | admin | List / create (`{ label, snapshotId?, expiresAt? }`), quota-checked; returns the URL once |
| DELETE | `/projects/:p/share-links/:id` | admin | Revoke |
| GET | `/s/:token` (+ `/s/:token/docs/*path`, `/s/:token/dashboard`) | public | Read-only JSON for the share view; rate-limited; increments `views` |
| GET | `/badge/:token.svg` | public | SVG badge with target progress; cached 5 min |

### Documents (viewer + editor)
| Method | Path | Auth / role | Purpose |
|--------|------|-------------|---------|
| GET | `/projects/:p/docs` | member | Tree: `[{ path, kind, title, meta, stale, version }]` (no markdown) |
| GET | `/projects/:p/docs/*path` | member | Full document incl. `markdown` and parsed `meta` |
| PUT | `/projects/:p/docs/*path` | member | Body `{ markdown, baseVersion }` → new version or `409 CONFLICT` with both texts |
| PATCH | `/projects/:p/docs/*path/meta` | member | Form and board edits: `{ status?, owner?, lastReviewed?, note?, boardOrder?, baseVersion }` → journal-core rewrites the status table (and appends `note` under Notes), then behaves like PUT; for `kind: task` it also updates the tracker row in `steps_pending_to_target.md` in the same MongoDB transaction and returns both new versions |
| GET | `/projects/:p/docs/*path/revisions` | member | List revisions |
| GET | `/projects/:p/docs/*path/revisions/:v` | member | One revision's markdown |
| POST | `/projects/:p/docs/*path/revisions/:v/restore` | member | Restore as new version |
| GET | `/projects/:p/search?q=` | member | Text search over `title` + `markdown` (Mongo text index) |

### Dashboard and kanban board
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/projects/:p/dashboard` | member | `{ target: { title, steps[] }, tasks[], issues[], suggestions[], counts, staleCount, lastSyncAt }` — the four boards |
| GET | `/projects/:p/board?kind=task\|issue\|suggestion` | member | `{ columns: [{ id, label, cards: [{ path, title, num?, owner, status, checklist, lastReviewed, stale, contradiction, order }] }] }` — cards grouped by `columnFor`, sorted by `board.order` then step number |
| POST | `/projects/:p/board/move` | member | `{ path, toColumn, order, baseVersion, note? }` → resolves `toColumn` to the canonical status for that kind (`todo → 🔴`, `in_progress → 🟡`, `verified → 🟢`, etc.), then performs the same write as `PATCH …/meta`; `verified`/`resolved`/`done` require `note` (400 otherwise) |
| POST | `/projects/:p/board/reorder` | member | `{ moves: [{ path, order }] }` → updates `board.order` only; no revision, no markdown change |
| GET | `/workspaces/:ws/board?kind=task` | member | Same shape with `swimlanes: [{ projectId, slug, columns }]` — the cross-repo board |
| GET | `/workspaces/:ws/overview` | member | Same counts per project, for the cross-repo view |
| GET | `/projects/:p/activity` | member | SyncEvents + revisions, newest first |

### Sync (used by `journal_sync.py` remote mode)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/sync/push` | api-key | `{ projectSlug, journalRoot, repoUrl?, files: [{ path, markdown, contentHash, baseVersion? }], deleted: string[], changedPaths: string[], stepMap?: object }` → `{ projectId, upserted, unchanged, conflicts: [{ path, serverVersion }], stale: string[] }`. In `local` mode an unknown `projectSlug` is created; in `github` mode the key already pins the project and `projectSlug` must match |
| GET | `/sync/pull?since=<iso>` | api-key | `{ files: [{ path, markdown, contentHash, version }], serverTime }` — documents changed on the server (source ≠ hook) since `since` |
| POST | `/sync/flag` | api-key | `{ changedPaths }` → `{ stale: string[] }` (used when files did not change but code did) |
| GET | `/sync/detect` | api-key | `{ stale: string[] }` — the client formats the SessionStart envelope |
| POST | `/sync/clear` | api-key | `{ path }` → clears server stale flag |
| GET | `/sync/status` | api-key | `{ project, lastSyncAt, staleCount, serverTime }` — used by `--check` |

### Webhooks (Phase 3)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/webhooks/github` | HMAC signature | On `push` to default branch, enqueue `githubPull` for matching projects |

### Realtime
Namespace `/projects/:p` (cookie auth on handshake, membership checked). Events emitted by the
server: `doc.updated { path, version }`, `task.stale { path }`, `sync.completed { type, summary }`.
Clients only refetch; they never apply payloads directly.

### OpenAPI
`apps/api/src/openapi.ts` builds the spec from the zod schemas (`@asteasolutions/zod-to-openapi`).
The web client is generated from it in CI (`openapi-typescript`), so API and UI cannot drift.

## 6. Web application

| Route | Screen | Data |
|-------|--------|------|
| `/login`, `/signup` | GitHub sign-in or email magic link (SaaS); hidden in self-host mode | — |
| `/onboarding` | Wizard: name organisation → choose plan (Checkout if paid) → add first repository (shows `projectSlug`, API key, the `/journal-init` one-liner) → waits for first push via socket → done checklist | workspaces, api-keys, billing routes, socket |
| `/w/:ws/members` | Members and pending invitations, roles, remove | members, invitations |
| `/w/:ws/billing` | Plan, usage vs limits, upgrade (Checkout), manage (Portal), invoices link | billing, usage |
| `/w/:ws/settings` | Name, export all data, audit log, delete organisation | export, audit |
| `/p/:p/assets` | Repository Asset page: snapshots (create, name, download ZIP/HTML), share links (create, copy, revoke, views), badge markdown snippet | snapshots, share-links, export |
| `/s/:token` | Public read-only view: dashboard + document browser of the live journal or a snapshot; no login, no editing, "Powered by" footer | public share routes |
| `/w/:ws` | Workspace overview: one card per project with counts (target progress, stale, open issues) | `GET /workspaces/:ws/overview` |
| `/p/:p` | **Dashboard**: four boards (Target tracker · Pending tasks · Issues · Suggestions), status chips, stale badges, "Last synced" | `GET /projects/:p/dashboard` + socket |
| `/p/:p/docs` | **Journal browser**: left tree (all files, grouped like the README table), right rendered Markdown | `GET /projects/:p/docs`, then `GET …/docs/*path` |
| `/p/:p/docs/*path` | **Document view**: rendered Markdown, status table as chips, stale banner, "Last reviewed", revision list; *Edit* toggles form + CodeMirror | as above + revisions |
| `/p/:p/board` | **Kanban board** (Jira-style): columns 🔴 To do · 🟡 In progress · 🟢 Verified; tabs switch to Issues (open / in progress / resolved) and Suggestions (proposed / accepted / done / declined); drag-and-drop between columns and within a column; filters (owner, stale only, text); card click opens the document view in a side panel; dropping into the last column prompts for a verification note | `GET /projects/:p/board`, `POST …/board/move`, `POST …/board/reorder`, socket |
| `/w/:ws/board` | Workspace board: same columns, one swimlane per project; moves allowed if the user is a member of that project | `GET /workspaces/:ws/board` |
| `/p/:p/tasks`, `/issues`, `/suggestions` | Filtered lists (table view of the same cards) with status/owner/severity filters | dashboard endpoint, filtered client-side |
| `/p/:p/activity` | Sync events and revisions feed | `GET /projects/:p/activity` |
| `/p/:p/settings` | Target milestone, sync mode, API keys (create/revoke), GitHub App link, danger zone | project + api-key routes |

**Markdown rendering rules** (component `MarkdownView`):
- `react-markdown` with `remark-gfm` (tables, task lists, strikethrough) and `rehype-sanitize`
  using the GitHub schema; raw HTML is dropped.
- Code fences with `language-mermaid` render through `mermaid` (`securityLevel: 'strict'`,
  theme dark); render failure shows the source in a code block.
- Relative links are rewritten by `lib/linkRewrite.ts`: resolve against the current document's
  path inside the journal root; if the target exists in the doc tree → `/p/:p/docs/<path>`;
  if it points outside the journal (e.g. `../src/api/x.ts`) → shown as a code path, linking to
  `repoUrl/blob/<branch>/<path>` when `repoUrl` is set. `http(s)` links open externally.
- The status table (`| Status | Owner | Last reviewed |`) is detected by journal-core and rendered
  as a chip row above the body; the raw table still renders in the body.
- Task checklists render as read-only checkboxes in view mode; in edit mode toggling a box
  rewrites the `- [ ]`/`- [x]` line and saves via `PUT`.

**Board rules** (component `KanbanBoard`, shared by tasks / issues / suggestions / workspace):
- Column membership is computed on the server by `columnFor`; the client never guesses a status
  from a colour.
- Drag uses `@dnd-kit` with optimistic updates; on `409 CONFLICT` the card snaps back and a toast
  links to the conflicting revision.
- Moving a card into the final column (Verified / Resolved / Done) opens a dialog requiring a
  one-line note; cancel aborts the move. The note is appended under the document's `## Notes`.
- Reordering inside a column is debounced (500 ms) and sent to `/board/reorder`; it never creates
  a revision.
- Keyboard: cards are focusable; space picks up, arrows move, enter drops (dnd-kit sensors).
- Stale and contradiction badges are shown on the card and cannot be cleared from the board
  (that is the reviewer's job in Claude Code).

**State:** TanStack Query for all server state (keys per project/path), socket events invalidate
queries. No global client store beyond auth. Dark theme by default using the `journal.html`
palette (`#0d1117` bg, `#f85149` red, `#e3b341` amber, `#3fb950` green).

## 7. Tenancy enforcement (the §0 footgun of this service)

```ts
// db/scoped.ts
export function scoped<T>(model: Model<T>, projectId: Types.ObjectId) {
  return {
    find:    (f = {}) => model.find({ ...f, projectId }),
    findOne: (f = {}) => model.findOne({ ...f, projectId }),
    updateOne: (f, u, o?) => model.updateOne({ ...f, projectId }, u, o),
    create:  (d) => model.create({ ...d, projectId }),
    // no deleteMany without filter; no aggregate without a leading $match on projectId
  };
}
```
- Handlers receive `req.ctx = { userId?, apiKeyId?, projectId, workspaceId, role }` from
  `middleware/ctx.ts`, which resolves the project from the URL **and** verifies membership or key
  scope. A route that forgets `requireProject()` fails a startup assertion that walks the router.
- ESLint `no-restricted-syntax` forbids `Document.find(`/`Revision.find(` etc. outside `db/`.
- A test in `apps/api/test/tenancy.test.ts` creates two projects and asserts every project-scoped
  route returns 404 for the other project's ids and paths.

## 8. Plugin sync client changes (`journal_sync.py`)

Stdlib only (`urllib.request`, `json`, `hashlib`). New behaviour is **only** active when both are
present; otherwise the script is byte-for-byte the current behaviour.

- **Zero-config local mode (default after `/journal-serve up`):** if no `.journalrc.json`
  exists, the script probes `http://127.0.0.1:4000/healthz` (300 ms timeout). On success it uses
  that URL, reads the key from `~/.claude-journal/.env` (`LOCAL_API_KEY`), and identifies the
  project by `projectSlug` = the journal folder name minus `_journal`. On failure it behaves
  exactly like today.
- **Explicit config** (team host / managed): `.journalrc.json` at the repo root:
  `{ "apiUrl": "https://journal.example.com", "projectSlug": "myapp" }`, and the key in the
  `JOURNAL_API_KEY` env var or `~/.claude-journal/credentials.json` keyed by `apiUrl`. The key is
  never written into the repo; `.journalrc.json` may be committed.
- State: `{journal}/.sync_state.json` (gitignored; `/journal-init` and `/journal-gitignore` add it):
  `{ "lastSyncAt": iso, "hashes": { path: sha256 } }`.

| Mode | Local (unchanged) | Then, if remote configured |
|------|-------------------|----------------------------|
| `flag` | insert stale markers | `POST /sync/push` with files whose hash changed since `.sync_state.json`, plus `changedPaths` and the step map; update state on success |
| `render` | write `journal.html` | no remote call (skipped entirely if `render.skipWhenRemote` is set in `.journalrc.json`) |
| `detect` | — | first `GET /sync/pull?since=` and write server-edited files locally (skip + add `⚠️ contradiction:` note if local file changed since last sync); then the existing local scan prints the envelope |
| `clear <file>` | remove marker | `POST /sync/clear` |
| `push` (new) | — | force a full push of every journal file (first-time onboarding) |
| `status` (new) | — | prints `GET /sync/status` (used by `/journal-ship` to show "synced N min ago") |

Timeouts: 5 s per request (300 ms for the local probe); any exception → one stderr line, exit 0. Nothing is printed to stdout
except the SessionStart envelope. `/journal-init` gains an optional step that asks for the API URL
and key and writes `.journalrc.json`; `/journal-gitignore` adds `.sync_state.json` to the
baseline ignores.

## 9. Configuration (env, zod-validated at boot)

| Variable | Required | Example | Used by |
|----------|----------|---------|---------|
| `NODE_ENV` | yes | `production` | api |
| `AUTH_MODE` | yes | `saas` \| `github` \| `local` | api (§5); `saas` enables sign-up, plans, billing; `local` forces bind to `127.0.0.1` |
| `PUBLIC_APP_URL` | yes | `https://app.journal.example.com` | share links, badge, emails |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_PRICE_TEAM` / `STRIPE_PRICE_BUSINESS` | when `saas` | — | billing |
| `EMAIL_PROVIDER` / `RESEND_API_KEY` / `EMAIL_FROM` | when `saas` | `resend` | invites, magic links |
| `LOCAL_API_KEY` | when `local` | generated by `/journal-serve` | api bootstrap, sync client |
| `BIND_HOST` | no | `0.0.0.0` | api; ignored (forced loopback) in `local` mode |
| `PORT` | yes | `4000` | api |
| `MONGODB_URI` | yes | `mongodb+srv://…` | api |
| `SESSION_JWT_SECRET` | yes | 64 random bytes, hex | api |
| `WEB_ORIGIN` | yes | `https://journal.example.com` | api (CORS, cookie) |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | when `github` | — | api (OAuth) |
| `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY` / `GITHUB_WEBHOOK_SECRET` | Phase 3 | — | api |
| `LOG_LEVEL` | no | `info` | api |
| `RATE_LIMIT_SYNC_PER_MIN` | no | `60` | api |
| `VITE_API_URL` | yes | `https://api.journal.example.com` | web (build time) |

Secrets come from the platform's secret store; `.env.example` lists every variable with a dummy
value and is the only `.env*` file committed.

## 9a. Plans and quotas (`apps/api/src/plans.ts`)

Placeholders for the owner to price; the code reads this table, nothing else.

| Quota | Free | Team | Business | Self-hosted |
|-------|------|------|----------|-------------|
| Projects (repository assets) | 1 | 10 | unlimited | unlimited |
| Members | 3 | 15 | unlimited | unlimited |
| Revision history | 30 days | 1 year | unlimited | unlimited |
| Snapshots | 3, manual | unlimited, nightly | unlimited, nightly | unlimited |
| Share links | 0 | 10 | unlimited | unlimited |
| Badge | no | yes | yes | yes |
| GitHub App pull sync | no | yes | yes | yes |
| Cloud generation (Phase 6) | no | no | yes | n/a |
| Price | $0 | per seat / month | per seat / month | free |

`enforceQuota(ws, 'projects' | 'members' | 'snapshots' | 'shareLinks')` reads `workspace.usage`
and the plan row; it throws `QuotaExceeded` → HTTP `402` with `{ upgradeUrl }`. A `past_due`
subscription is treated as its plan for reads and as Free for creates. In self-host mode the plan
is fixed to `self_hosted`, and billing routes return 404.

## 10. Testing strategy

| Level | Tool | What | Gate |
|-------|------|------|------|
| Unit (parser) | Vitest | journal-core golden tests vs Python output; property tests for idempotent stale insert/clear | CI, must pass |
| Unit (api) | Vitest | services with mocked models; scoped helper | CI |
| Integration (api) | Vitest + Supertest + mongodb-memory-server | every route incl. auth modes, 409 conflict path, tenancy test (§7), push→stale→clear loop, **quota test** (each create returns 402 at the plan limit), **Stripe webhook replay test** (same event twice → one change), share-link isolation (token for project A never reads project B) | CI |
| Contract | Vitest | `journal_sync.py --remote` against a running test API (spawn Python, assert envelope shape and state file) | CI (needs python3) |
| E2E | Playwright | login (mocked OAuth), dashboard renders four boards from a seeded journal, open a task, edit status, see revision | CI on main + nightly |
| Lint / types | ESLint, `tsc --noEmit` | all packages | CI |

Seed data: `apps/api/test/fixtures/sample_journal/` is a real 15-file journal produced by
`/journal-init` on a small app; it doubles as the golden-test fixture.

## 11. Build, CI, deployment

**Local dev:** `pnpm i && docker compose up -d mongo && pnpm dev` (Turborepo runs api on 4000 and
web on 5173 with a proxy). `pnpm seed` loads the sample journal into a dev project and prints an
API key for testing the plugin against `http://localhost:4000`.

**CI (`.github/workflows/ci.yml`)** on every PR: install → lint → typecheck → unit + integration
tests → regenerate golden expectations with `python3 journal_sync.py` and diff → build web + api →
build Docker image (no push). On `main`: push image tagged with the SHA, run Playwright.

**Image:** one `Dockerfile` at the repo root, multi-stage (`node:22-alpine`): build `journal-core`,
`api`, and `web`; final stage copies `apps/api/dist` + `apps/web/dist` and runs as a non-root user.
The API serves the web bundle at `/` and the API at `/api/v1`, so one container exposes one port.
Published as `ghcr.io/junaiddop/journal-service:<version>` where `<version>` = the plugin's
`plugin.json` version; CI publishes on a git tag `v*` and bumps the tag pinned in the plugin's
Compose file in the same commit.

**SaaS (primary):** the same image on Fly.io or Render with 2+ instances behind the platform's
load balancer, `AUTH_MODE=saas`, MongoDB Atlas M10+ with continuous backup, Socket.IO using the
`@socket.io/mongo-adapter` so events reach every instance, Agenda jobs with a lock so nightly
snapshots and pruning run once. Stripe webhooks point at `/api/v1/webhooks/stripe`. Secrets in the
platform's secret store. Health checks on `/healthz`, `/readyz`. Custom domain `app.<domain>` with
platform-managed TLS; `s.<domain>` optionally for share links.

**Self-host for a team:** same Compose file with `AUTH_MODE=github`, `BIND_HOST=0.0.0.0`, a
reverse proxy for TLS, and a Mongo backup cron. Billing routes are absent; the plan is
`self_hosted`.

## 11a. Containers shipped in the plugin (`/journal-serve`)

This is what makes "install the plugin → the service exists" true (R7).

**Files inside `plugins/claude-journal/docker/`:**

```yaml
# docker-compose.yml  (image tag is rewritten by CI to match plugin.json version)
name: claude-journal
services:
  journal-mongo:
    image: mongo:7
    restart: unless-stopped
    volumes: [ "journal_data:/data/db" ]
    healthcheck:
      test: ["CMD", "mongosh", "--quiet", "--eval", "db.runCommand({ping:1}).ok"]
      interval: 10s
      timeout: 5s
      retries: 10
  journal-api:
    image: ghcr.io/junaiddop/journal-service:0.2.0
    restart: unless-stopped
    depends_on:
      journal-mongo: { condition: service_healthy }
    env_file: [ "${JOURNAL_ENV_FILE:-~/.claude-journal/.env}" ]
    environment:
      MONGODB_URI: mongodb://journal-mongo:27017/journal
      PORT: "4000"
    ports: [ "127.0.0.1:${JOURNAL_PORT:-4000}:4000" ]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:4000/readyz"]
      interval: 10s
      timeout: 3s
      retries: 10
volumes:
  journal_data: {}
```

```
# env.example → copied to ~/.claude-journal/.env by /journal-serve on first run
NODE_ENV=production
AUTH_MODE=local
WEB_ORIGIN=http://localhost:4000
SESSION_JWT_SECRET=<generated: 64 hex>
LOCAL_API_KEY=<generated: jrnl_ + 43 base64url chars>
LOG_LEVEL=info
```

**Command `commands/journal-serve.md`** (`argument-hint: "[up | down | status | logs | upgrade | reset]"`):

| Sub-command | Does | Never does |
|-------------|------|------------|
| `up` (default) | Checks `docker compose version` (v2). Creates `~/.claude-journal/.env` from `env.example` with generated secrets if missing. Runs `docker compose -f "$CLAUDE_PLUGIN_ROOT/docker/docker-compose.yml" up -d --pull missing`. Waits for `/readyz` (max 60 s). Prints the URL and the volume name. | Modify the repo; commit; write secrets anywhere but `~/.claude-journal/` |
| `down` | `docker compose … down` (containers only; volume kept) | Delete data |
| `status` | `docker compose … ps` + `GET /sync/status` for the current repo's project | — |
| `logs` | `docker compose … logs --tail 200 -f journal-api` | — |
| `upgrade` | `docker compose … pull && up -d`; the image tag comes from the freshly installed plugin, so upgrading the plugin then running this upgrades the service | Downgrade schemas (migrations are additive) |
| `reset` | Asks for explicit confirmation, then `down -v` (deletes `journal_data`) | Run without a typed confirmation |

Blockers are surfaced, never worked around (same STOP contract as `journal-automator`): Docker not
installed or daemon not running, port 4000 in use (suggests `JOURNAL_PORT` in the env file),
Compose v1 only, or an image pull failure.

**Data and paths on the host:**

| Path | Purpose | In git? |
|------|---------|---------|
| `~/.claude-journal/.env` | Secrets + `LOCAL_API_KEY` | never |
| `~/.claude-journal/credentials.json` | Keys for non-local instances, keyed by `apiUrl` | never |
| Docker volume `claude-journal_journal_data` | MongoDB data for every repo on the machine | n/a |
| `<repo>/.journalrc.json` | Optional explicit `apiUrl` + `projectSlug` | may be committed |
| `<repo>/{project}_journal/.sync_state.json` | Last-sync hashes | gitignored by `/journal-init` |

**Backup / restore (local):** `docker run --rm -v claude-journal_journal_data:/data -v "$PWD":/backup alpine tar czf /backup/journal-backup.tgz /data` and the reverse for restore; documented in the plugin README, not automated in v1.

**Multi-repo behaviour:** one local instance, one workspace (`local`), one project per repo,
keyed by `projectSlug`. Two repos with the same folder name collide; the sync client detects a
mismatched `repoUrl` on push and refuses with a stderr message telling the user to set
`projectSlug` in `.journalrc.json`.

**Pre-merge checklist for this service** (the `dev.md` §14 this project will get):
1. Every new project-scoped query goes through `scoped()`; tenancy test still passes.
2. New route registered with `requireProject()` / `requireRole()` and added to OpenAPI.
3. Markdown never rendered without `rehype-sanitize`; no `dangerouslySetInnerHTML`.
4. Sync client change keeps "no config → identical behaviour" and "any error → exit 0".
5. Parser change: golden tests updated by regenerating from Python, not by hand.
6. New env var added to `env.ts` schema and `.env.example`.
7. Migrations: additive only; a script under `apps/api/src/migrations/` if data must move.
8. Image still starts with only the variables in `docker/env.example`; `/journal-serve up` on a clean volume reaches `/readyz`.
9. Every new create path for projects / members / snapshots / share links calls `enforceQuota()`; the quota test covers it.
10. Any new Stripe webhook type is deduplicated by `event.id` and covered by the replay test.
11. Public routes (`/s/:token`, `/badge/:token.svg`) resolve the token through `scoped()`; no new unscoped reads.
12. `pnpm lint && pnpm typecheck && pnpm test` green locally.

## 12. Roadmap and acceptance criteria

| Phase | Scope | Done when |
|-------|-------|-----------|
| **0 · Scaffold** (1 wk) | Monorepo, CI, Docker, env, Mongo connect, health routes, `journal-core` with golden tests | CI green; `pnpm dev` boots; golden tests pass against the sample journal |
| **1 · Viewer in a container** (2–3 wk) | `AUTH_MODE=local` bootstrap, `POST /sync/push` with auto-registration, doc tree + Markdown viewer, four-board dashboard; published image, plugin `docker/` + `/journal-serve`, sync client local probe + `push` + push-on-`flag` | Fresh machine: install plugin → `/journal-serve up` → `/journal-init` in a repo → one Stop hook → the journal is in the browser at `localhost:4000`; every one of its 15 files renders; the tracker board links to task docs (R1, R2, R7) |
| **2 · Live sync + board** (2 wk) | Server-side stale via step map, `detect`/`clear` endpoints, Socket.IO, activity feed, cross-repo overview; **kanban board** for tasks with drag-and-drop status moves writing back to Markdown (issues/suggestions tabs and workspace swimlanes included) | Editing a mapped code file and stopping marks the task stale in the browser within seconds; reconcile + `clear` removes it (R3). Dragging a task to In progress changes its status table and tracker row, visible in `git diff` after the next session (R2a) |
| **3 · Editing & history** (2 wk) | Revisions, `PUT`/`PATCH meta`, conflict handling, `pull` on SessionStart, restore | Web edit of a task appears in the repo at the next session; concurrent edit produces a visible conflict, no data loss (R4) |
| **4 · Team** (1–2 wk) | `AUTH_MODE=github`, GitHub login, workspaces, roles, member management, per-project API keys, search, GitHub App pull for committed journals | Same Compose file on a shared host serves a team; viewer role cannot edit; a journal committed to GitHub updates without hooks (R5) |
| **5 · SaaS** (3 wk) | `AUTH_MODE=saas`: sign-up + magic link, onboarding wizard, plans + `enforceQuota`, Stripe Checkout/Portal/webhooks, invitations by email, usage page, audit log, tenant export + delete, **Repository Assets**: snapshots, ZIP/HTML export, share links, badge; multi-instance deploy with the Socket.IO Mongo adapter | A stranger can sign up, pay for Team, invite a colleague, connect a repo, create a snapshot, and send a read-only share link, with every quota enforced and every Stripe event idempotent (R8, R9) |
| **6 · Cloud generation** (3–4 wk) | Generation worker: ephemeral checkout of a GitHub-connected repo, runs investigator + scribe prompts via the Claude API, validates with journal-core, pushes as `source: cloud`; milestone confirmation in the wizard | A repo with no plugin installed gets a complete, valid journal asset from the web app alone (R9) |
| **7 · Hardening** | Rate limits per plan, penetration test of §7 tenancy and public routes, backups/restore drill, Playwright suite, status page, docs | Security review passes; `/journal-audit` on this repo finds no §0 violations |

Estimated total: 14–18 weeks for one engineer with Claude Code. Phases 1–2 alone deliver the
"everything viewable, pending tasks on a board" outcome; phase 5 makes it a sellable SaaS.
