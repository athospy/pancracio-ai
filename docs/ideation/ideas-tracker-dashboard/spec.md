# Implementation Spec: Ideas Tracker Dashboard

**Contract**: ./contract.md
**Estimated Effort**: M

## Technical Approach

Add a new `GET /dashboard` route to the existing FastAPI app (`web/app.py`) that renders 8 small
widgets, each backed by a plain SQL query against `web/pancracio.db` (no ORM, matching every
existing route). The route reuses the app's existing auth (`Depends(get_current_user)`), template
engine (Jinja2, `web/templates/`), and connection helper (`_connect()`).

Live-refresh is done via a second route, `GET /dashboard/widgets`, which renders the exact same 8
widgets as a bare HTML fragment (no `base.html` chrome) using a shared Jinja partial
(`_dashboard_widgets.html`) that both routes include. A small vanilla-JS file
(`web/static/dashboard.js`) polls that endpoint every 60s and swaps it into the page via
`innerHTML` — this app's first client-side data-fetching logic, but it introduces no build step,
no framework, and no client-side templating (the server still renders all HTML).

Pipeline health is a pure local-DB read, not a call to n8n's API: n8n's Docker container binds its
API to `127.0.0.1:5678` (loopback-only) by deliberate design from the auto-publish project, so the
tracker cannot reach it at all. Instead, one node is added to the existing n8n workflow
(`n8n/workflows/auto-publish.json`) that POSTs a heartbeat to a new endpoint,
`POST /internal/pipeline-heartbeat`, after the workflow's due-ideas check runs — using the same
`Authorization: Bearer` credential the workflow already uses for its other two HTTP Request nodes.
The dashboard then just reads the latest row of a new `pipeline_heartbeats` table.

## Decisions Considered and Rejected

_Carried from the contract (docs/ideation/ideas-tracker-dashboard/contract-data.json)._

- **New `/dashboard` route, homepage unchanged** — rejected: replacing `/` with the dashboard. Lowest risk; nothing existing changes.
- **Next-to-publish and calendar widgets scoped to `auto_publish=1` ideas only** — rejected: also including manually-scheduled (Meta Business Suite) posts. Keeps one consistent story about what this app itself controls.
- **Pipeline health via a heartbeat n8n pushes to the tracker after every run** — rejected: querying n8n's REST API directly (firewall change, SSH tunnel, or rebinding n8n's Docker port). n8n's API is deliberately loopback-only (an explicit prior decision in the auto-publish project); a heartbeat push reuses the exact outbound connection direction the pipeline already uses hourly, needing no new network exposure or always-running tunnel.
- **Cached DB engagement values + existing `post_url` link for the just-posted widget** — rejected: live-fetching from the Instagram Graph API on every dashboard load. Zero new dependency or latency risk.
- **JS polling every 60s against `/dashboard/widgets`, swapping in a server-rendered HTML fragment** — rejected: a `<meta http-equiv="refresh">` full-page reload. Smoother, non-flashing page, accepted as the app's first real client-side data-fetching logic.
- **The polling endpoint returns a server-rendered HTML fragment** — rejected: a JSON API with client-side JS building the DOM. Keeps the app Jinja-only everywhere.
- **"Needs review" = `status='scripted'` untouched 3+ days** — rejected: "ready but missing `final_image_path`" (the existing per-card guardrail) or combining both. Catches a distinct failure mode from "freshly added".
- **Next-to-publish widget shows a single item** — rejected: a short list of the next 3-5. The calendar widget already covers the multi-day view.
- **Backlog size and days-since-last-post render together in one "quick stats" section** — rejected: two separate widget sections. Keeps the total distinct widget count at 8.
- **Freshly-added widget reuses the existing `_get_ideas(status="idea", sort="newest")` helper** — rejected: a new bespoke query. It's the exact query the homepage's own filter already runs.
- **Register-balance and pipeline-health success criteria are cmd checks** — rejected: judgment calls. Both compare two mechanically-queryable sources.
- **The n8n workflow edit (heartbeat node) is done via n8n's existing write-scoped REST API** — rejected: treating it as a manual step for the user. This project's own precedent (the Basic-Auth-to-bearer-token credential swap) already did live workflow edits this way.

## Feedback Strategy

**Inner-loop command**: `TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard/widgets`

**Playground**: Local dev server (`cd web && venv/bin/uvicorn app:app --reload --port 8000`), driven with curl — this app has no test suite, and every existing route was built and verified this same way (curl + a browser check).

**Why this approach**: Every widget is a SQL query rendered into an HTML fragment; a curl-based loop against the real dev server and real `pancracio.db` is faster and more representative than mocking data, and matches how this codebase's other `/internal/*` endpoints were already built.

## File Changes

### New Files

| File Path | Purpose |
| --- | --- |
| `web/templates/dashboard.html` | Full `/dashboard` page — extends `base.html`, wraps the widgets partial, includes `dashboard.js` |
| `web/templates/_dashboard_widgets.html` | The 8 widget `<section>` blocks, shared by `/dashboard` and `/dashboard/widgets` |
| `web/static/dashboard.js` | Polls `/dashboard/widgets` every 60s, swaps the result into `#dashboard-widgets`, redirects to `/login` on a 401 |

### Modified Files

| File Path | Changes |
| --- | --- |
| `web/app.py` | New routes `GET /dashboard`, `GET /dashboard/widgets`, `POST /internal/pipeline-heartbeat`; new query helpers (below); one added exemption in `redirect_unauthenticated_pages_to_login` so `/dashboard/widgets` gets a bare 401 instead of a login redirect |
| `web/schema.sql` | New `pipeline_heartbeats` table |
| `web/templates/base.html` | Add a `Dashboard` nav link next to `Queue`/`Stats`/`Settings` |
| `n8n/workflows/auto-publish.json` | One new HTTP Request node posting to `/internal/pipeline-heartbeat`, re-exported after editing live via n8n's REST API |

## Implementation Details

### Query helpers (`web/app.py`)

**Pattern to follow**: `_get_ready_queue()` (`web/app.py:410`) and `_get_recent_register_counts()` (`web/app.py:498`) — both open their own connection via `with _connect() as conn:` and return plain dicts/lists, no `conn` parameter threaded in from the caller.

```python
def _get_next_to_publish() -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, title, scheduled_at FROM ideas
            WHERE auto_publish = 1 AND status NOT IN ('posted', 'failed', 'archived')
            ORDER BY (scheduled_at IS NULL), scheduled_at ASC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None

def _get_recent_posts(limit: int = 5) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT posts.id, posts.post_url, posts.likes, posts.comments,
                   posts.views, posts.shares, posts.saves, posts.posted_at,
                   ideas.title
            FROM posts JOIN ideas ON ideas.id = posts.idea_id
            ORDER BY posts.posted_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]

def _get_stalled_drafts(idle_days: int = 3) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, updated_at FROM ideas
            WHERE status = 'scripted' AND datetime(updated_at) <= datetime('now', ?)
            ORDER BY updated_at ASC
            """,
            (f"-{idle_days} days",),
        ).fetchall()
    return [dict(r) for r in rows]

def _get_upcoming_calendar(days: int = 7) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, scheduled_at FROM ideas
            WHERE auto_publish = 1
              AND datetime(scheduled_at) BETWEEN datetime('now') AND datetime('now', ?)
            ORDER BY scheduled_at ASC
            """,
            (f"+{days} days",),
        ).fetchall()
    return [dict(r) for r in rows]

def _get_quick_stats() -> dict:
    with _connect() as conn:
        backlog = conn.execute(
            "SELECT COUNT(*) AS n FROM ideas WHERE status NOT IN ('posted', 'archived')"
        ).fetchone()["n"]
        days_row = conn.execute(
            "SELECT CAST(julianday('now') - julianday(MAX(posted_at)) AS INTEGER) AS n FROM posts"
        ).fetchone()
    return {"backlog": backlog, "days_since_post": days_row["n"]}

def _get_pipeline_health(stale_after_hours: int = 2) -> dict:
    with _connect() as conn:
        row = conn.execute(
            "SELECT status, created_at FROM pipeline_heartbeats ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return {"status": "unknown", "heartbeat_at": None, "stale": True}
    stale_row = conn_stale = None
    with _connect() as conn:
        stale_row = conn.execute(
            "SELECT datetime(?) <= datetime('now', ?) AS stale",
            (row["created_at"], f"-{stale_after_hours} hours"),
        ).fetchone()
    return {"status": row["status"], "heartbeat_at": row["created_at"], "stale": bool(stale_row["stale"])}
```

**Key decisions**:
- Each helper opens its own connection, matching every existing `_get_*` helper — no shared-connection refactor.
- `_get_pipeline_health()` treats "no heartbeat row exists" and "latest heartbeat too old" as distinct-but-related states (`status="unknown"` vs. a `stale: true` flag on a real status) so the template can show "no data yet" before the n8n workflow edit ships, and "stale, last seen success 5h ago" after it ships but the pipeline stops reporting in.

**Feedback loop**:
- **Playground**: dev server + curl (see Feedback Strategy above).
- **Experiment**: seed one `auto_publish=1` idea with `scheduled_at` in the past and one in the future; confirm `_get_next_to_publish()` picks the past one. Seed zero, confirm it returns `None`.
- **Check command**: `sqlite3 web/pancracio.db "SELECT id FROM ideas WHERE auto_publish=1 AND status NOT IN ('posted','failed','archived') ORDER BY (scheduled_at IS NULL), scheduled_at ASC LIMIT 1"`

### Routes (`web/app.py`)

**Pattern to follow**: `index()` (`web/app.py:954`) and `queue_page()` (`web/app.py:988`) for the `TemplateResponse` shape; `_get_idea_activity` / `/internal/run-pipeline/{id}` for an `/internal/*` POST endpoint's shape.

```python
def _dashboard_context() -> dict:
    register_counts = _get_recent_register_counts()
    return {
        "next_idea": _get_next_to_publish(),
        "recent_posts": _get_recent_posts(limit=5),
        "fresh_ideas": _get_ideas(status="idea", sort="newest", page=1)[0][:5],
        "stalled": _get_stalled_drafts(),
        "calendar_ideas": _get_upcoming_calendar(),
        "quick_stats": _get_quick_stats(),
        "register_counts": register_counts,
        "register_counts_json": json.dumps(register_counts),
        "pipeline_health": _get_pipeline_health(),
    }

@app.get("/dashboard")
def dashboard_page(request: Request, _: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "dashboard.html", _dashboard_context())

@app.get("/dashboard/widgets")
def dashboard_widgets(request: Request, _: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "_dashboard_widgets.html", _dashboard_context())

@app.post("/internal/pipeline-heartbeat")
def pipeline_heartbeat(status: str = Form(...), _: dict = Depends(get_current_user)):
    if status not in ("success", "failed"):
        raise HTTPException(400, "status must be 'success' or 'failed'")
    with _connect() as conn:
        conn.execute("INSERT INTO pipeline_heartbeats (status) VALUES (?)", (status,))
        conn.commit()
    return {"ok": True}
```

**Key decisions**:
- `_dashboard_context()` is one function shared by both GET routes so the full page and the polling fragment can never drift apart.
- `/internal/pipeline-heartbeat` uses the same `Depends(get_current_user)` as every other route — n8n authenticates with its existing "Pancracio Tracker Bearer Token" credential (already wired to the workflow's other two HTTP Request nodes), so no new credential is needed.
- In `redirect_unauthenticated_pages_to_login` (`web/app.py:248`), add `and request.url.path != "/dashboard/widgets"` to the `if` condition so an expired session on a poll gets a bare 401 (which `dashboard.js` can detect) instead of a login-page redirect body being swapped into the widgets container.

**Implementation steps**:
1. Add `_get_next_to_publish`, `_get_recent_posts`, `_get_stalled_drafts`, `_get_upcoming_calendar`, `_get_quick_stats`, `_get_pipeline_health` near the other `_get_*` helpers.
2. Add `_dashboard_context()`, the two GET routes, and the heartbeat POST route.
3. Add the `/dashboard/widgets` exemption to the exception handler.
4. Add the nav link in `base.html`.

**Feedback loop**:
- **Playground**: dev server + curl.
- **Experiment**: hit `/dashboard` and `/dashboard/widgets` unauthenticated (expect 303 vs. 401 respectively); hit them authenticated and grep for all 8 `data-widget="..."` values.
- **Check command**: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/dashboard/widgets` (expect `401` with no cookie/token).

### Templates (`web/templates/`)

**Pattern to follow**: `queue.html` for the extends/block structure; `_idea_card.html` for how this app writes a reusable Jinja partial (though the widgets here use their own compact markup, not the `idea_card` macro, since they show different fields than a full idea card).

`dashboard.html`:
```jinja
{% extends "base.html" %}
{% block title %}Dashboard — Pancracio Ideas{% endblock %}
{% block content %}
<div id="dashboard-widgets">
  {% include "_dashboard_widgets.html" %}
</div>
<script src="/static/dashboard.js"></script>
{% endblock %}
```

`_dashboard_widgets.html` (no `extends` — rendered standalone by `/dashboard/widgets`, and via `include` by `dashboard.html`):
```jinja
<section class="widget" data-widget="next-to-publish">
  <h3>Next to publish</h3>
  {% if next_idea %}
  <p data-next-idea-id="{{ next_idea.id }}">
    <a href="/ideas/{{ next_idea.id }}/edit">{{ next_idea.title }}</a> — {{ next_idea.scheduled_at or "unscheduled" }}
  </p>
  {% else %}
  <p class="empty" data-next-idea-id="">Nothing scheduled.</p>
  {% endif %}
</section>

<section class="widget" data-widget="just-posted">
  <h3>Just posted</h3>
  {% if not recent_posts %}<p class="empty">No posts yet.</p>{% endif %}
  {% for p in recent_posts %}
  <p data-post-id="{{ p.id }}">
    <a href="{{ p.post_url }}" target="_blank" rel="noopener">{{ p.title }}</a>
    — {{ p.likes if p.likes is not none else "—" }} likes, {{ p.comments if p.comments is not none else "—" }} comments
  </p>
  {% endfor %}
</section>

<section class="widget" data-widget="freshly-added">
  <h3>Freshly added</h3>
  {% if not fresh_ideas %}<p class="empty">Nothing new.</p>{% endif %}
  {% for idea in fresh_ideas %}
  <p data-fresh-idea-id="{{ idea.id }}"><a href="/ideas/{{ idea.id }}/edit">{{ idea.title }}</a></p>
  {% endfor %}
</section>

<section class="widget" data-widget="needs-review">
  <h3>Needs review</h3>
  {% if not stalled %}<p class="empty">Nothing stalled.</p>{% endif %}
  {% for idea in stalled %}
  <p data-stalled-idea-id="{{ idea.id }}"><a href="/ideas/{{ idea.id }}/edit">{{ idea.title }}</a> — idle since {{ idea.updated_at }}</p>
  {% endfor %}
</section>

<section class="widget" data-widget="pipeline-health" data-pipeline-status="{{ pipeline_health.status }}">
  <h3>Pipeline health</h3>
  {% if pipeline_health.status == "unknown" %}
  <p class="empty">No pipeline data yet.</p>
  {% else %}
  <p>{{ pipeline_health.status }} — last heartbeat {{ pipeline_health.heartbeat_at }}{% if pipeline_health.stale %} (stale){% endif %}</p>
  {% endif %}
</section>

<section class="widget" data-widget="register-balance" data-register-counts="{{ register_counts_json | e }}">
  <h3>Register balance</h3>
  <p>Reframe: {{ register_counts.get("reframe", 0) }} · Observational: {{ register_counts.get("observational", 0) }}</p>
</section>

<section class="widget" data-widget="quick-stats" data-backlog-count="{{ quick_stats.backlog }}" data-days-since-post="{{ quick_stats.days_since_post if quick_stats.days_since_post is not none else '' }}">
  <h3>Quick stats</h3>
  <p>{{ quick_stats.backlog }} in backlog · {{ quick_stats.days_since_post if quick_stats.days_since_post is not none else "no posts yet" }} days since last post</p>
</section>

<section class="widget" data-widget="calendar">
  <h3>Upcoming week</h3>
  {% if not calendar_ideas %}<p class="empty">Nothing scheduled this week.</p>{% endif %}
  {% for idea in calendar_ideas %}
  <p data-calendar-idea-id="{{ idea.id }}">{{ idea.scheduled_at }} — <a href="/ideas/{{ idea.id }}/edit">{{ idea.title }}</a></p>
  {% endfor %}
</section>
```

In `base.html`, add inside `<nav class="nav-links">`, before the `Queue` link:
```jinja
<a href="/dashboard" class="settings-link">Dashboard</a>
```

**Feedback loop**:
- **Playground**: dev server, browser at `http://localhost:8000/dashboard`.
- **Experiment**: with 0 rows in every relevant table, confirm all 8 widgets show their empty state instead of erroring; with real data, confirm each widget's data-attributes are present and non-empty.
- **Check command**: `curl -s http://localhost:8000/dashboard/widgets | grep -c 'class="widget"'` (expect `8`, using an authenticated session).

### Client-side polling (`web/static/dashboard.js`)

**Overview**: Vanilla JS, no build step, no dependency — matches every other script in this app (`base.html`'s inline logout script, `login.html`'s inline script).

```javascript
(function () {
  const container = document.getElementById("dashboard-widgets");
  if (!container) return;

  async function refresh() {
    let res;
    try {
      res = await fetch("/dashboard/widgets");
    } catch (err) {
      return; // network hiccup — leave the last-rendered widgets in place
    }
    if (res.status === 401) {
      window.location = "/login";
      return;
    }
    if (!res.ok) return; // transient server error — leave stale content rather than blank the page
    container.innerHTML = await res.text();
  }

  setInterval(refresh, 60000);
})();
```

**Key decisions**:
- A failed poll (network error or non-2xx other than 401) leaves the last-good widgets on screen rather than clearing them — a dashboard that blanks itself on a transient hiccup is worse than one showing slightly-stale data.
- A 401 forces a full navigation to `/login` rather than trying to re-render an error state inline, since an expired session needs a real re-login, not a widget update.

**Feedback loop**:
- **Playground**: browser devtools (Network + Console tabs) against the dev server.
- **Experiment**: load `/dashboard`, confirm a `/dashboard/widgets` request fires ~60s later; stop the dev server mid-poll, confirm the page doesn't blank or throw; delete the session cookie via devtools, confirm the next poll redirects to `/login`.
- **Check command**: none automatable — this is the spec's one judgment-checked criterion (see contract).

## Data Model

### Schema Changes (`web/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS pipeline_heartbeats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

No `ALTER`/table-rebuild is needed (unlike `_migrate_ideas_status_check`) since this is a brand-new
table — `CREATE TABLE IF NOT EXISTS` in `schema.sql` is picked up idempotently the same way this
app's existing DB-initialization step already handles every other table.

## API Design

### New Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/dashboard` | Full dashboard page (auth-gated, redirects to `/login` on 401) |
| `GET` | `/dashboard/widgets` | The 8 widgets as a bare HTML fragment, for polling (auth-gated, bare 401 on unauth) |
| `POST` | `/internal/pipeline-heartbeat` | Records a heartbeat (`status=success` or `status=failed`); called by n8n |

### Request/Response Example

```
POST /internal/pipeline-heartbeat
Authorization: Bearer <n8n's existing tracker token>
Content-Type: application/x-www-form-urlencoded

status=success

# Response
{"ok": true}
```

## Testing Requirements

This app has no automated test suite (confirmed: no pytest, no `test_*.py`, no CI config anywhere
in the repo) — every existing route was hand-verified against the real dev server, and this feature
follows the same convention. Verification is the 13 success criteria in
`docs/ideation/ideas-tracker-dashboard/contract-data.json`, runnable via
`scripts/verify.mjs docs/ideation/ideas-tracker-dashboard/contract-data.json` once a
`$DASH_USER`/`$DASH_PASS` fixture account exists (see Rollout Considerations).

**Key scenarios covered by those criteria**: unauthenticated access to both new GET routes; all 8
widgets present and individually correct against direct DB queries; the heartbeat endpoint's effect
on the pipeline-health widget in both the "no data yet" and "has data" states; the polling cadence
(the one judgment check).

## Failure Modes

| Component | Failure Mode | Trigger | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| Next-to-publish widget | No `auto_publish` ideas pending | Nothing currently scheduled | Widget would render blank | Explicit "Nothing scheduled." empty state |
| Just-posted / freshly-added / needs-review / calendar widgets | Zero matching rows | New install, or a genuinely quiet week | Same as above | Each widget has its own explicit empty-state message |
| Quick-stats widget | No posts ever recorded | `MAX(posted_at)` is `NULL` | `days_since_post` would render as `None`/blank | Template falls back to "no posts yet" text when `quick_stats.days_since_post is none` |
| Pipeline-health widget | No heartbeat row exists yet (before the n8n workflow edit ships) | Fresh deploy, or the n8n node hasn't been added yet | Widget would have nothing to show | `_get_pipeline_health()` returns `status="unknown"`; template shows "No pipeline data yet." |
| Pipeline-health widget | Heartbeat exists but is stale (n8n stopped reporting in) | n8n itself goes down, or its cron stops firing | Widget would silently show an old "success" with no indication it's stale | `stale` flag computed from `created_at` age; template appends "(stale)" |
| `/internal/pipeline-heartbeat` | Called with an invalid `status` value | A bug in the n8n node's body, or a stray manual call | Bad data would land in the table and corrupt the health widget | Endpoint validates `status in ("success", "failed")`, returns 400 otherwise |
| `dashboard.js` polling | `/dashboard/widgets` returns a non-2xx, non-401 error, or the network call throws | Server restart mid-poll, transient network blip | A naive implementation would blank the page or throw an unhandled rejection | Both paths leave the existing DOM untouched and simply retry on the next 60s tick |
| `dashboard.js` polling | Session expires while the tab is open | Cookie/token deleted or session row removed server-side | A naive implementation would swap in the login page's HTML inside the widgets container | 401 response is detected explicitly and forces `window.location = "/login"` |

## Validation Commands

```bash
# No typecheck/lint/build tooling exists for this Python app (confirmed via web/requirements.txt
# and repo-wide search) — validation is the success-criteria commands themselves.
cd web && venv/bin/uvicorn app:app --reload --port 8000 &
node ../scripts/verify.mjs ../docs/ideation/ideas-tracker-dashboard/contract-data.json
```

## Rollout Considerations

- **Fixture account**: create a dedicated test account via the existing provisioning path —
  `ssh deploy@charmander.santiagomorel.dev "cd /home/deploy/pancracio-ai/web && venv/bin/python3 scripts/create_user.py <DASH_USER> <DASH_PASS>"` locally, or the equivalent against the local dev DB
  during implementation — so `$DASH_USER`/`$DASH_PASS` in the success criteria resolve to a real,
  non-placeholder account.
- **Live n8n workflow edit (not completable by a local build session)**: the render VPS (`bulbasaur`)
  and n8n itself are only reachable via SSH/its own REST API from a live session with the
  documented credentials (`internal-docs/ideas-tracker/auto-publish-credentials.md`), not from a
  sandboxed local build. Whoever runs this step should: (1) use n8n's write-scoped API key
  (`pancracio-auto-publish-workflow-mgmt`, expires 2026-10-25 — regenerate if needed) to add one
  HTTP Request node after the workflow's "Get Due Ideas" step, POSTing `status=success` using the
  existing "Pancracio Tracker Bearer Token" credential; (2) wire a failure path (e.g. that node's
  "Continue On Fail" plus an error branch, or an attached Error Trigger workflow) to POST
  `status=failed` instead when "Get Due Ideas" itself errors — this is the exact step that failed
  silently in the incident this project is closing the gap on; (3) re-export the workflow to
  `n8n/workflows/auto-publish.json` and commit it, per this project's established convention.
- **Deployment**: standard restart of `pancracio-ai.service` on charmander picks up the schema
  change and new routes; no migration script needed since `pipeline_heartbeats` is additive.
- **Monitoring**: the dashboard *is* the monitoring for this feature — once live, watch
  `data-pipeline-status` after the next scheduled hourly run to confirm the heartbeat node fired.

## Open Items

- [ ] Whoever implements this needs live SSH/n8n API access to add the heartbeat node — flag this to the user rather than attempting it from a sandboxed session with no network path to bulbasaur.

---

_This spec is ready for implementation. Follow the patterns and validate at each step._
