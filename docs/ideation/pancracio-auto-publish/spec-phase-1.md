# Implementation Spec: Pancracio Auto-Publish Pipeline - Phase 1

**Contract**: ./contract.md
**Estimated Effort**: M

## Technical Approach

This phase lays every piece of ground the other three phases build on, and nothing else: schema
changes to the tracker DB, two small JSON endpoints so n8n (and this project's own success
criteria) can read/write idea state without scraping HTML, n8n itself running on the VPS, and
every credential the later phases need already obtained and verified reachable. No pipeline
logic (prompt drafting, image generation, compositing, publishing) is built in this phase — it's
purely "can every later phase actually run once it's written."

The tracker app already has a working migration pattern (`_init_db()` in `web/app.py`, which
runs `schema.sql` then does an `ALTER TABLE ADD COLUMN` guard for columns missing from an
already-live production DB — this is exactly how `ig_media_id` was added earlier this project).
Two of this phase's three schema changes (`auto_publish`, `register`) fit that pattern directly.
The third — adding `'failed'` to `ideas.status`'s existing `CHECK` constraint — does not, because
SQLite can't `ALTER` a `CHECK` constraint in place; it needs the standard SQLite table-rebuild
migration (new table, copy rows, drop old, rename), which is new to this codebase and is called
out explicitly below since it's the one non-trivial migration in this phase.

**n8n and Remotion rendering run on a new, separate VPS — not charmander.** charmander (the
tracker's existing box) reports 1 CPU core, ~2GB RAM (with ~250MB actually free before adding
anything), and 84% disk used (5.7GB free), and already runs the tracker app plus, per
`deployment-runbook.md`, Ardu's Node backend, Ollama, and PostgreSQL. The actual resource-heavy
piece of this whole project is headless-Chromium rendering (Phase 3), not n8n itself — so rather
than add any load to charmander, the user provisions a second VPS that runs n8n
(docker-compose, modeled on `job-finder/n8n/docker-compose.yml`) and, colocated on the same box,
the Remotion rendering environment Phase 3 needs. charmander's only change in this entire project
is the schema/endpoint work in this phase — it never gets Docker, n8n, or Chromium installed on
it.

The new VPS's n8n is reachable only via SSH tunnel from its own loopback interface — no nginx
vhost, no public DNS, no TLS cert, per the contract's VPS-local-only decision. n8n talks to the
tracker app over its existing public HTTPS URL (`https://pancracio-ideas.santiagomorel.dev`),
exactly the same way this session's browser or curl calls have all along — cross-VPS communication
needs nothing new, since every tracker endpoint n8n calls was already designed to be reached over
the public internet (behind HTTP Basic Auth), not over a private network.

## Decisions Considered and Rejected

- **Publish fully unattended, no human approval gate before content goes live** — rejected:
  require a one-click approval step after generation before publishing. User explicitly wants
  zero-touch automation and knowingly accepts the quality-control tradeoff.
- **Ideas opt in to automation via an explicit `auto_publish` flag** — rejected: automate every
  new idea with no filter. Keeps a manual-curation escape hatch.
- **Keep n8n VPS-local only, no public subdomain** — rejected: give n8n its own public subdomain
  with nginx+TLS+basic auth, matching the tracker (and matching the earlier, now-superseded
  sketch in `metrics-automation-checklist.md` Phase E). No inbound webhook is required; this
  contract's n8n plan supersedes that checklist's Phase E sketch.
- **Use n8n (docker-compose, VPS-local) rather than a cron script on the existing systemd
  pattern** — rejected: a cron-triggered Python script reusing the tracker's own systemd
  deployment convention. User explicitly asked for n8n by name; its execution-history UI gives
  real debugging value across a 4-external-system pipeline that runs unattended.
- **Reuse the tracker's existing settings-table `character_reference_image` upload for the OpenAI
  reference image, instead of a new hardcoded server path** — rejected: copy the reference image
  to a new fixed path. The app already ships this mechanism with its own upload UI at
  `/settings`.

## Feedback Strategy

**Inner-loop command**: `curl -s -u $AUTH https://pancracio-ideas.santiagomorel.dev/api/ideas | jq .`

**Playground**: The already-deployed FastAPI app (`web/app.py`) plus direct SSH access to the new
render VPS (alias TBD until it exists — see Open Items) for the n8n/Docker provisioning half of
this phase.

**Why this approach**: The schema/endpoint changes are best iterated against the same local
uvicorn + sqlite loop already used this session (see Phase D's verification pattern); the n8n/VPS
provisioning half has no code to iterate on, just shell commands run over SSH and checked by
their exit status.

## File Changes

### Modified Files

| File Path            | Changes                                                                                  |
| --------------------- | ----------------------------------------------------------------------------------------- |
| `web/schema.sql`      | Add `auto_publish INTEGER NOT NULL DEFAULT 0` and `register TEXT` to `ideas`; add `'failed'` to the `status` CHECK list. |
| `web/app.py`          | Extend `_init_db()`'s migration guard for the two simple new columns; add the table-rebuild migration for the `status` CHECK; add `GET /api/ideas` and `GET /api/ideas/{id}`. |

### New Files

| File Path                                    | Purpose                                                              |
| --------------------------------------------- | --------------------------------------------------------------------- |
| `n8n/docker-compose.yml`                      | n8n container definition, modeled on `job-finder/n8n/docker-compose.yml`, deployed to the new render VPS, local-only there. |
| `n8n/README.md`                               | How to reach n8n (SSH tunnel to the render VPS), how workflows are exported to git, matching `job-finder/n8n/README.md`'s convention. |
| `internal-docs/ideas-tracker/auto-publish-credentials.md` | Where each new credential (OpenAI key, Anthropic key, re-consented IG token) lives and how to rotate it — gitignored like the rest of `internal-docs/`. |

## Implementation Details

### Schema: `auto_publish` and `register` columns

**Pattern to follow**: `web/app.py`'s existing `_init_db()` migration guard (the `ig_media_id`
addition earlier this project) — same shape, two more columns.

**Overview**: Two nullable/defaulted columns on `ideas`, no `CHECK` constraint needed at the DB
level (validated in the FastAPI route instead, matching how `content_type`'s Python-side
`CONTENT_TYPES` list is already used alongside the DB's own `CHECK`).

```python
existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(ideas)")}
if "auto_publish" not in existing_cols:
    conn.execute("ALTER TABLE ideas ADD COLUMN auto_publish INTEGER NOT NULL DEFAULT 0")
if "register" not in existing_cols:
    conn.execute("ALTER TABLE ideas ADD COLUMN register TEXT")
```

**Key decisions**:

- No DB-level `CHECK` on `register` (`'reframe'`/`'observational'`) — validate in the route
  that sets it, avoiding a second table-rebuild migration in the same phase.
- `auto_publish` is an `INTEGER` (SQLite has no native boolean), read as truthy in Python.

**Implementation steps**:

1. Add both columns to `schema.sql`'s `CREATE TABLE ideas` block (for fresh installs).
2. Add the migration guard above inside `_init_db()`, right after the existing `ig_media_id`
   guard.
3. Verify against a copy of the live DB (see Testing Requirements) before deploying.

### Schema: `'failed'` status (table rebuild)

**Overview**: SQLite cannot `ALTER TABLE ... MODIFY CHECK`. Adding `'failed'` to
`ideas.status`'s allowed values on the already-live production DB requires the standard SQLite
rebuild pattern, run once and made idempotent by checking `sqlite_master` for whether the
current table definition already contains `'failed'`.

```python
def _migrate_ideas_status_check(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ideas'"
    ).fetchone()
    if row and "'failed'" in row["sql"]:
        return  # already migrated
    conn.executescript("""
        CREATE TABLE ideas_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          content_type TEXT NOT NULL DEFAULT 'video' CHECK (content_type IN ('image', 'video')),
          description TEXT,
          category TEXT,
          tags TEXT,
          inspiration_source TEXT,
          status TEXT NOT NULL DEFAULT 'idea'
            CHECK (status IN ('idea', 'scripted', 'ready', 'posted', 'archived', 'failed')),
          score INTEGER CHECK (score BETWEEN 1 AND 5),
          layout_image_path TEXT,
          final_image_path TEXT,
          image_prompt TEXT,
          scheduled_at TEXT,
          caption TEXT,
          hashtags TEXT,
          auto_publish INTEGER NOT NULL DEFAULT 0,
          register TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO ideas_new SELECT
          id, title, content_type, description, category, tags, inspiration_source,
          status, score, layout_image_path, final_image_path, image_prompt,
          scheduled_at, caption, hashtags, auto_publish, register, created_at, updated_at
        FROM ideas;
        DROP TABLE ideas;
        ALTER TABLE ideas_new RENAME TO ideas;
        CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);
    """)
```

**Key decisions**:

- Idempotency check via `sqlite_master.sql` string match, not a separate "migrations applied"
  table — matches this codebase's existing lightweight-migration style (no migration
  framework in use).
- The explicit `INSERT INTO ideas_new SELECT <named columns>` (not `SELECT *`) so column order
  never silently depends on `CREATE TABLE` order matching between old and new.
- Run this *after* the two simple `ALTER TABLE ADD COLUMN` guards, so `auto_publish`/`register`
  already exist on the live table and the rebuild's `SELECT` list is valid on first deploy too.

**Implementation steps**:

1. Add `_migrate_ideas_status_check()` and call it from `_init_db()`, after the column-add
   guards.
2. Update `STATUSES` in `web/app.py` to include `"failed"`.
3. Update `schema.sql`'s inline `CREATE TABLE ideas` CHECK to include `'failed'` directly (so a
   fresh install never needs the rebuild path at all).

**Feedback loop**:

- **Playground**: `sqlite3` against a throwaway copy of a pre-migration DB (same technique used
  to test the `ig_media_id` migration this session: seed an old-shape table via a `.sql` heredoc,
  then run `_init_db()` against it).
- **Experiment**: run the migration twice in a row against the same file — second run must
  be a no-op (idempotency), and existing rows must survive with all values intact.
- **Check command**: `sqlite3 /tmp/test.db "SELECT sql FROM sqlite_master WHERE name='ideas'" | grep -q "'failed'"`

### `GET /api/ideas` and `GET /api/ideas/{id}`

**Pattern to follow**: `web/app.py`'s existing `GET /api/posts/tracked-media` — same
`check_auth` gate, same `_connect()` + `dict(row)` shape.

**Overview**: Two read-only JSON endpoints so n8n and this project's own success-criteria checks
can query idea state without scraping the HTML edit page.

```python
@app.get("/api/ideas")
def api_list_ideas(
    status: Optional[str] = None,
    register: Optional[str] = None,
    auto_publish: Optional[bool] = None,
    _: None = Depends(check_auth),
) -> list[dict]:
    ...

@app.get("/api/ideas/{idea_id}")
def api_get_idea(idea_id: int, _: None = Depends(check_auth)) -> dict:
    ...  # 404 via the existing _get_idea() helper
```

**Key decisions**:

- Reuses the existing `_get_idea()` helper for the single-idea endpoint (already 404s correctly).
- Query-param filters on `/api/ideas` map directly to `WHERE` clauses, same style as
  `_get_ideas()`'s existing `status`/`content_type` filters — no new query-building
  abstraction introduced.

**Implementation steps**:

1. Add a small `_get_ideas_filtered()` (or extend `_get_ideas()` with `register`/`auto_publish`
   params) reusing the existing parameterized-query pattern.
2. Add both routes near the existing `/api/posts/*` routes.

**Feedback loop**:

- **Playground**: local uvicorn against a seeded test DB (same pattern used to verify the
  `ig_media_id` endpoints this session).
- **Experiment**: seed 3 ideas with different `register`/`auto_publish` values; query with each
  filter individually and combined.
- **Check command**: `curl -s -u test:test "http://127.0.0.1:8123/api/ideas?register=reframe" | jq length`

### n8n provisioning (on the new render VPS, local-only)

**Pattern to follow**: `job-finder/n8n/docker-compose.yml` and `job-finder/n8n/README.md`.

**Overview**: A fresh VPS, provisioned by the user for this project, runs Docker + n8n +
(Phase 3's) Remotion/Chromium. Unlike charmander's constrained `deploy` user (no general sudo,
per `ssh-access-guide.md`), this is a new box — the user sets up SSH access with whatever
account they prefer (root or a sudo-capable user is simplest for a single-purpose box like this).
n8n itself is reachable only on `localhost:5678` on that VPS, never exposed publicly.

```yaml
# n8n/docker-compose.yml
services:
  n8n:
    image: docker.n8n.io/n8nio/n8n
    restart: unless-stopped
    ports:
      - "127.0.0.1:5678:5678"   # loopback only — no public exposure
    environment:
      - GENERIC_TIMEZONE=America/Chicago
      - TZ=America/Chicago
      - N8N_SECURE_COOKIE=false  # http-only over the loopback interface, same as job-finder
    volumes:
      - n8n_data:/home/node/.n8n
volumes:
  n8n_data:
```

**Key decisions**:

- `127.0.0.1:5678:5678` (not `5678:5678`) is the one deliberate deviation from job-finder's
  compose file — binds Docker's port-forward to loopback only, so nothing outside the VPS
  can reach it even if the VPS's firewall rules ever change.
- Access for the user is via `ssh -L 5678:localhost:5678 <render-vps-alias>`, then
  `http://localhost:5678` in a local browser — documented in `n8n/README.md`.
- Enable Docker's systemd service (`systemctl enable docker`) during setup so it survives a
  reboot; n8n's own `restart: unless-stopped` then brings the container back up automatically.
- Once the VPS exists, add an SSH config alias for it (same pattern as this session's
  `charmander-pancracio` alias in `~/.ssh/config`) so every command in this project references a
  stable name instead of a raw IP.

**Implementation steps**:

1. User provisions the new VPS and shares SSH access; add its `~/.ssh/config` alias.
2. Root/sudo session: `apt install -y docker.io docker-compose-v2 && systemctl enable --now docker`.
3. `mkdir -p ~/pancracio-render/n8n && cd $_`, add `docker-compose.yml`, `docker compose up -d`.
4. SSH-tunnel in, complete n8n's first-run owner-account setup (email+password, stored in the
   `n8n_data` volume — same as job-finder).
5. Enable n8n's REST API (Settings → API in the n8n UI, or `N8N_PUBLIC_API_DISABLED=false` if
   needed) and generate an API key — needed by Phase 4's no-retry success criterion to query
   `/api/v1/executions`.
6. Resource check: `free -h` and `docker stats --no-stream` a few minutes after n8n is up — this
   VPS is dedicated to this project, so the bar is much lower than charmander's, but still worth
   confirming before Phase 3 adds Chromium on top.

**Feedback loop**:

- **Playground**: the new VPS itself over SSH.
- **Experiment**: restart the VPS (or `systemctl restart docker`) and confirm n8n comes back
  without manual intervention.
- **Check command**: `ssh <render-vps-alias> "curl -s -o /dev/null -w '%{http_code}' http://localhost:5678/healthz"` — expect `200`.

### Credentials: OpenAI key, Anthropic key coverage, Instagram publish-scope re-consent

**Overview**: Three credential tasks, none of them code:

1. **OpenAI API key** — the user creates one at platform.openai.com, gives it to this
   session (or adds it directly to n8n's credential store, or the VPS env — finalized in
   Phase 2 depending on whether the call originates from n8n's HTTP Request node or a tracker
   endpoint). Store a reference to where it lives in
   `internal-docs/ideas-tracker/auto-publish-credentials.md`, never the raw key in git.
2. **Anthropic API key** — confirm it has access to the native web-search tool (used for
   both prompt-drafting in Phase 2 and the originality check). This may already exist from
   Claude Code usage but needs to be a *direct API* key, not a Claude subscription — the
   two are billed and issued separately.
3. **Instagram publish-scope re-consent** — **blocking prerequisite for Phase 4.** The
   current long-lived token (from this session's `internal-docs/credentials/instagram-acceess-token.txt`)
   was deliberately generated with only `instagram_business_basic` +
   `instagram_business_manage_insights`; publish requires `instagram_content_publish`.
   Re-run the same dashboard "Generate token" flow from this session (Use cases →
   Instagram API → API setup with Instagram login → Generate access tokens), this time
   leaving `instagram_content_publish` checked on the consent screen, and exchange/save the new
   token the same way. Expect the same repeated-OAuth-login quirk documented in
   `ideas-tracker/lessons-learned.md`.

**Key decisions**:

- No new credential-storage mechanism invented — reuse `internal-docs/credentials/` (already
  gitignored) for the pattern established this session.

**Implementation steps**:

1. User obtains OpenAI key; confirm Anthropic key's web-search tool access.
2. Re-run the IG token generation flow with `instagram_content_publish` included; save via the
   same process as this session's `internal-docs/credentials/instagram-acceess-token.txt`.
3. Verify the new token has publish scope: `curl -s "https://graph.instagram.com/v21.0/me?fields=id,user_id&access_token=$TOKEN"` still works, and note the scope for Phase 4 to actually exercise via a real (or dry-run) publish call.

### Reconcile with `metrics-automation-checklist.md` Phase E

**Overview**: That checklist's Phase E (steps 10-14) sketched a *different*, now-superseded n8n
topology (public subdomain). Update it to point at this project instead of leaving two
conflicting plans on file.

**Implementation steps**:

1. Edit `internal-docs/ideas-tracker/metrics-automation-checklist.md` Phase E: replace steps
   10-14 with a pointer to `docs/ideation/pancracio-auto-publish/` and a one-line note that this
   project's metrics-refresh need (the original Phase E goal) is now folded into the larger
   auto-publish pipeline's Phase 4.

## Data Model

### Schema Changes

```sql
-- ideas table additions (see Implementation Details for the full rebuild needed for the
-- status CHECK; auto_publish/register are simple ADD COLUMN)
ALTER TABLE ideas ADD COLUMN auto_publish INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ideas ADD COLUMN register TEXT;
-- status CHECK gains 'failed' via the table-rebuild function, not a plain ALTER
```

## API Design

### New Endpoints

| Method | Path              | Description                                                    |
| ------ | ----------------- | ---------------------------------------------------------------- |
| `GET`  | `/api/ideas`      | List ideas, filterable by `status`, `register`, `auto_publish`.  |
| `GET`  | `/api/ideas/{id}` | Single idea as JSON (404 if missing), reusing `_get_idea()`.      |

### Request/Response Examples

```
GET /api/ideas?register=reframe
[
  { "id": 12, "title": "...", "status": "idea", "register": "reframe", "auto_publish": 1, ... }
]

GET /api/ideas/12
{ "id": 12, "title": "...", "status": "failed", "register": "reframe", "auto_publish": 1, ... }
```

## Testing Requirements

### Manual Testing

- [ ] Copy production `pancracio.db` to a scratch file, run the new `_init_db()` against it,
      confirm all 8 existing posts/ideas survive with every value intact.
- [ ] Run the migration twice in a row against the same scratch file — second run is a no-op.
- [ ] `GET /api/ideas` and `/api/ideas/{id}` against the scratch DB, all three filters.
- [ ] SSH-tunnel to n8n on the new render VPS, log in, confirm the UI loads.
- [ ] Reboot that VPS (or `systemctl restart docker`), confirm n8n auto-recovers.
- [ ] Re-consent the IG token with publish scope; confirm `/me` still works with the new token.

## Failure Modes

| Component                    | Failure Mode                                      | Trigger                                    | Impact                                              | Mitigation                                                                 |
| ------------------------------ | ---------------------------------------------------- | --------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------ |
| Status-CHECK migration         | Rebuild runs against a DB with rows the `INSERT ... SELECT` doesn't expect (schema drift) | Someone hand-edited the DB outside `_init_db()` between sessions | Migration fails loudly (SQLite raises on the `INSERT`), app won't start | Test against a fresh copy of the *actual* production DB before deploying, not a synthetic one |
| New render VPS sizing           | User under-provisions the new VPS (picks something too small for Chromium rendering) | Sizing decided before Phase 3's actual memory needs are known | Same resource-starvation risk this split was meant to avoid, just on a new box | Confirm the VPS has at least 2 CPU / 4GB RAM before Phase 3 (Chromium's actual footprint) — check with the user at provisioning time, not after |
| IG token re-consent             | New token accidentally omits `instagram_content_publish` again (same UI defaults/quirks as this session) | Consent-screen toggle defaults, or the "reconnect" screen's all-or-nothing Allow (no per-scope toggle) seen this session | Phase 4 blocked at the last step, discovered late | Verify the new token's actual granted scopes before calling this task done — don't assume the checkbox state from the consent screen was honored |

## Validation Commands

```bash
# Local: syntax + migration test
cd web && python3 -m py_compile app.py
# (migration correctness verified via the scratch-DB tests in Manual Testing, not an automated suite —
#  this codebase has no test runner configured)

# Production verification after deploy
curl -s -u $AUTH https://pancracio-ideas.santiagomorel.dev/api/ideas | jq length
ssh <render-vps-alias> "curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5678/healthz"
```

## Rollout Considerations

- **Deploy path**: schema/endpoint changes ride the existing `deploy-ideas-tracker.yml` GitHub
  Actions pipeline (charmander only), same as every change this session. n8n/Docker provisioning
  is a manual one-time SSH/root session on the new render VPS, a separate deploy target entirely.
- **Monitoring**: after n8n is up, watch `free -h` / `df -h` on the render VPS for a day before
  starting Phase 2's real workload — charmander itself needs no new monitoring since it gets no
  new load from this project.
- **Rollback plan**: the schema migration only adds columns/loosens a CHECK — no data loss
  on rollback (older app code simply ignores the new columns). The entire render VPS can be
  destroyed with zero effect on the tracker app, which has no dependency on it existing at all
  outside of ideas actually flagged `auto_publish`.

## Open Items

- [ ] User provisions the new VPS (recommend at least 2 CPU / 4GB RAM given Phase 3's Chromium
      rendering) and shares SSH access before this phase's n8n work can start.
- [ ] Add the new VPS's SSH config alias once it exists (referenced throughout this and later
      phases as `<render-vps-alias>` / `$RENDER_VPS_ALIAS`).

---

_This spec is ready for implementation. Follow the patterns and validate at each step._
