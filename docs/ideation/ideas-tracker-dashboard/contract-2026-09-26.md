# Ideas Tracker Dashboard Contract

**Created**: 2026-09-26
**Readiness**: All 5 gates ready
**Status**: Approved
**Approval**: Express — single consolidated confirmation, no per-artifact review
**Supersedes**: None

## Problem Statement

The ideas tracker's homepage today is purely operational in the narrowest sense — a quick-add form plus a filterable list of every idea. /queue shows status='ready' ideas and /stats shows backward-looking performance analytics, but nothing answers, at a glance, what's about to publish, what just posted, what's freshly added and needs review, or whether the auto-publish pipeline is actually healthy.

This gap already cost real visibility: the auto-publish n8n workflow's first 3 hourly executions (2026-09-25, 15:00/16:00/17:00 UTC) all failed with 401 on a stale Basic Auth credential, discovered by accident while verifying an unrelated credential swap, not through any monitoring (internal-docs/ideas-tracker/auto-publish-credentials.md).

Separately, a 30-idea batch loaded the same day initially produced a 28/2 reframe:observational split against the account's documented ~6:4 target, caught and corrected manually rather than surfaced by the app itself.

## Goals

1. Opening /dashboard shows, without navigating to any other page: the next auto_publish idea due to post and when; the last 5 posts with their cached engagement numbers and a link to view them on Instagram; the last 5 freshly-added ideas; stalled 'scripted' drafts idle 3+ days with direct links; time since the last successful pipeline heartbeat (and its status); the current rolling register balance; backlog size and days since the last post; and an upcoming-week mini-calendar of auto_publish-scheduled ideas.
2. The page refreshes this data automatically roughly every 60 seconds via a JS-polling partial DOM update, without a full page reload.

## Success Criteria

- [ ] An unauthenticated GET to /dashboard redirects to /login, matching every other page route in this app — check: `curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/dashboard` → 303
- [ ] An unauthenticated GET to /dashboard/widgets returns a bare 401 (not an HTML redirect), so the polling JS can detect an expired session and redirect the whole page itself — check: `curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/dashboard/widgets` → 401
- [ ] An authenticated GET to /dashboard renders all 8 named widget sections (next-to-publish, just-posted, freshly-added, needs-review, pipeline-health, register-balance, quick-stats [backlog + days-since-last-post], calendar) — check: `TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard | grep -oP 'data-widget="\K[a-z-]+' | sort -u | wc -l` → 8
- [ ] GET /dashboard/widgets returns the same 8 named sections as a bare HTML fragment (no page chrome), so client-side JS can swap it in without client-side templating — check: `TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard/widgets | grep -oP 'data-widget="\K[a-z-]+' | sort -u | wc -l` → 8
- [ ] The next-to-publish widget shows the actual next auto_publish idea (soonest scheduled_at among non-terminal statuses), or an explicit empty state when none exist — check: `EXPECTED=$(sqlite3 web/pancracio.db "SELECT id FROM ideas WHERE auto_publish=1 AND status NOT IN ('posted','failed','archived') ORDER BY (scheduled_at IS NULL), scheduled_at ASC LIMIT 1"); TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard | grep -q "data-next-idea-id=\"$EXPECTED\""` → exits 0 (if EXPECTED is empty, the widget instead renders an explicit 'nothing scheduled' state)
- [ ] The just-posted widget's 5 entries match the tracker's actual 5 most recent posts, not stale/hardcoded data — check: `TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); A=$(sqlite3 web/pancracio.db "SELECT id FROM posts ORDER BY posted_at DESC LIMIT 5"); B=$(curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard | grep -oP 'data-post-id="\K[0-9]+'); [ "$A" = "$B" ]` → exits 0 (lists match)
- [ ] The freshly-added widget's 5 entries match the 5 most recent status='idea' ideas — check: `TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); A=$(sqlite3 web/pancracio.db "SELECT id FROM ideas WHERE status='idea' ORDER BY created_at DESC LIMIT 5"); B=$(curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard | grep -oP 'data-fresh-idea-id="\K[0-9]+'); [ "$A" = "$B" ]` → exits 0 (lists match)
- [ ] The needs-review widget lists exactly the ideas with status='scripted' untouched (updated_at) for 3+ days — check: `TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); A=$(sqlite3 web/pancracio.db "SELECT id FROM ideas WHERE status='scripted' AND datetime(updated_at) <= datetime('now','-3 days') ORDER BY updated_at ASC"); B=$(curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard | grep -oP 'data-stalled-idea-id="\K[0-9]+'); [ "$A" = "$B" ]` → exits 0 (lists match)
- [ ] The calendar widget shows exactly the auto_publish ideas scheduled in the next 7 days — check: `TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); A=$(sqlite3 web/pancracio.db "SELECT id FROM ideas WHERE auto_publish=1 AND datetime(scheduled_at) BETWEEN datetime('now') AND datetime('now','+7 days') ORDER BY scheduled_at ASC"); B=$(curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard | grep -oP 'data-calendar-idea-id="\K[0-9]+'); [ "$A" = "$B" ]` → exits 0 (lists match)
- [ ] The quick-stats widget's backlog size AND days-since-last-post both match direct DB queries — check: `BACKLOG=$(sqlite3 web/pancracio.db "SELECT COUNT(*) FROM ideas WHERE status NOT IN ('posted','archived')"); DAYS=$(sqlite3 web/pancracio.db "SELECT CAST(julianday('now')-julianday(MAX(posted_at)) AS INT) FROM posts"); TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); PAGE=$(curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard); echo "$PAGE" | grep -q "data-backlog-count=\"$BACKLOG\"" && echo "$PAGE" | grep -q "data-days-since-post=\"$DAYS\""` → exits 0
- [ ] The register-balance widget's counts match the existing GET /internal/register-counts endpoint exactly — check: `TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); A=$(curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/internal/register-counts | jq -S .); B=$(curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard | grep -oP 'data-register-counts="\K[^"]+' | python3 -c 'import json,sys,html; print(json.dumps(json.loads(html.unescape(sys.stdin.read())), sort_keys=True))'); [ "$A" = "$B" ]` → exits 0 (values match)
- [ ] The pipeline-health widget correctly reflects the heartbeat table's state: an explicit 'no data yet' state before any heartbeat exists, and the real status/timestamp after one is recorded — check: `TOKEN=$(curl -s -X POST http://localhost:8000/login -d "username=$DASH_USER" -d "password=$DASH_PASS" | jq -r .token); curl -s -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8000/internal/pipeline-heartbeat -d 'status=success' > /dev/null; curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard | grep -q 'data-pipeline-status="success"'` → exits 0
- [ ] The dashboard refreshes its widgets roughly every 60 seconds via a JS-polling partial DOM update, without a full page reload — judgment call: With the dashboard open and browser devtools' Network tab visible, confirm a GET to /dashboard/widgets fires approximately every 60s, and that the page does not do a full navigation/reload each time.

## Scope Boundaries

### In Scope

- New GET /dashboard route (index.html and every other existing page/route unchanged) — Lowest-risk placement — nothing that currently works changes; the dashboard becomes an additional entry point, reachable via a new nav link.
- Next-to-publish widget: single soonest idea where auto_publish=1 AND status NOT IN ('posted','failed','archived'), ordered by scheduled_at — Closes the exact gap named in the source doc — /queue's status='ready' filter doesn't show this. Scoped to a single item since the calendar widget covers the multi-day view.
- Just-posted widget: last 5 posts newest-first, with cached engagement numbers (likes/comments/etc.) and a link to the live Instagram post via the existing post_url column — Reuses existing posts table columns; avoids a new live Instagram API call on a page that's otherwise pure local-DB reads.
- Freshly-added widget: last 5 ideas with status='idea', newest-first, reusing the existing _get_ideas(status='idea', sort='newest') helper capped at 5 rows rather than a bespoke query — Directly answers 'what needs review/scheduling' for newly captured ideas (e.g. the 30-idea batch from 2026-09-25), and the exact same query already backs the homepage's own filter — no reason to duplicate it.
- Needs-review widget: ideas with status='scripted' untouched (updated_at) for 3+ days, with direct links to each — Catches a different failure mode than 'freshly added' — drafts that got started and then forgotten.
- Pipeline-health widget: shows time since the last successful pipeline heartbeat and its status (success/failed) — Directly targets the exact incident that already happened (3 silent failures), as a pure local-DB read — no external call, no graceful-degradation branch needed.
- New POST /internal/pipeline-heartbeat endpoint recording the latest heartbeat status + timestamp (a new minimal table, e.g. pipeline_heartbeats, or a settings-table key) — Gives the dashboard a local signal it can always read, instead of reaching out to n8n's (deliberately loopback-only) API.
- One additional node appended to n8n/workflows/auto-publish.json, POSTing to /internal/pipeline-heartbeat at the end of each run (success or failure path) via the existing write-scoped n8n API key, then re-exported and committed per this project's established convention — n8n already calls the tracker every hour in this same direction (outbound from bulbasaur); this adds one more call rather than opening any new inbound network path, and preserves n8n's deliberate loopback-only hardening from the auto-publish project untouched.
- Register-balance widget: reuse the existing _get_recent_register_counts() helper — Already computes exactly this; directly reusable per the source doc, no new query needed.
- Quick-stats widget combining backlog size (count of ideas not in posted/archived) and days since last post (from MAX(posts.posted_at)) in one rendered section — Both are single cheap numbers the user explicitly asked for; grouping them keeps the total widget count at 8 distinct sections instead of 9 near-identical single-number cards.
- Upcoming-week mini-calendar: auto_publish-scheduled ideas over the next 7 days — Scoped to auto_publish only, matching the next-to-publish widget, so the page tells one consistent story about what this app itself controls.
- GET /dashboard/widgets partial-update endpoint, rendering the same 8 widget sections as a bare HTML fragment via the existing Jinja templates, returning 401 (not a login redirect) when unauthenticated — Lets client-side JS refresh data via an innerHTML swap without introducing client-side templating, keeping the app Jinja-only everywhere; a bare 401 lets the polling JS detect an expired session itself.
- Client-side JS polling /dashboard/widgets every 60s and swapping the result into the page — User's explicit choice for a genuinely live-feeling page over a plain reload-to-refresh model, accepting this as the app's first real client-side data-fetching logic.
- Nav link to /dashboard in base.html — Makes the new route discoverable, matching how Queue/Stats/Settings are already linked.
- A dedicated test/fixture account, created via the existing scripts/create_user.py, for verification checks that need an authenticated session — Success-criteria checks need a real, non-placeholder way to authenticate; this matches the project's own established account-provisioning path.

### Out of Scope

- Replacing the homepage ('/') with the dashboard — Explicitly declined — keeps this a strictly additive, lowest-risk change; the quick-add + full list experience stays exactly as it is today.
- Including manually-scheduled (non-auto_publish) ideas in the next-to-publish or calendar widgets — Explicitly declined — keeps this page describing only what the app itself controls via the auto_publish pipeline, avoiding mixing two different scheduling mechanisms in one view.
- Live Instagram Graph API calls on dashboard page load — Explicitly declined — avoids a new dependency, latency, and rate-limit risk on a page meant to be checked frequently; cached values plus the existing manual per-post Refresh button are sufficient.
- Querying n8n's REST API directly from the tracker (via firewall change, SSH tunnel, or rebinding n8n's Docker port) — n8n's API is deliberately loopback-only per the auto-publish project's own hardening decision; a heartbeat push achieves the same visibility goal without touching that decision or adding new network infrastructure.
- A PRD layer between this contract and the implementation spec — Single-developer personal tool with no external stakeholder sign-off step; the spec is sufficient.
- A new automated test suite / pytest for this app — This app has no existing test infrastructure; introducing one is a separate concern from this feature.

### Future Considerations

- A toggle to also show manually-scheduled (non-auto_publish) posts in the calendar/next-to-publish widgets
- Live Instagram engagement refresh directly from the dashboard
- A fuller heartbeat history (last N runs, not just the most recent) if a single latest-status proves insufficient
- Expanding next-to-publish from a single item to a short list if the calendar view proves insufficient on its own

## Decisions Considered and Rejected

- **New /dashboard route, homepage unchanged** — rejected: Replace '/' with the dashboard, moving quick-add elsewhere. Lowest risk — nothing existing changes; the dashboard is purely additive.
- **Next-to-publish and calendar widgets scoped to auto_publish=1 ideas only** — rejected: Also include manually-scheduled (Meta Business Suite) posts. Keeps one consistent story on the page — what this app itself controls — rather than mixing two different scheduling mechanisms.
- **Pipeline health via a heartbeat n8n pushes to the tracker after every run** — rejected: Querying n8n's REST API directly from the tracker — via a firewall change, a persistent SSH tunnel, or rebinding n8n's Docker port off loopback. A hidden-dependency critic pass found n8n's API is deliberately loopback-only (an explicit prior decision in the auto-publish project, made so nothing outside the VPS could ever reach it). A heartbeat push reuses the exact outbound connection direction the pipeline already uses every hour, so it needs no new network exposure and no new always-running tunnel process, and it leaves that prior hardening decision completely untouched.
- **Cached DB engagement values + existing post_url link for the just-posted widget** — rejected: Live-fetch engagement from the Instagram Graph API on every dashboard load. Zero new dependency or latency risk; matches the app's existing manual-refresh-per-post pattern.
- **JS polling every 60s against a new /dashboard/widgets endpoint, swapping in a server-rendered HTML fragment** — rejected: A simple <meta http-equiv="refresh"> full-page reload. User wanted a smoother, non-flashing live-feeling page over the simplest zero-JS option, accepting this as the app's first real client-side data-fetching logic.
- **The polling endpoint returns a server-rendered HTML fragment (reusing existing Jinja templates)** — rejected: A JSON API with client-side JS building the DOM/HTML. Keeps the app Jinja-only everywhere, avoiding introducing client-side templating for the first time.
- **"Needs review" = status='scripted' untouched 3+ days** — rejected: "Ready but missing final_image_path" (the existing per-card guardrail) or combining both conditions. Catches a distinct failure mode (stalled drafts) that the 'freshly added' widget can't see, without duplicating the guardrail already shown per-card on Queue.
- **Next-to-publish widget shows a single item** — rejected: A short list of the next 3-5 upcoming auto_publish ideas. The upcoming-week calendar widget already covers the multi-day view, so a list here would duplicate it.
- **Backlog size and days-since-last-post render together in one 'quick stats' widget section** — rejected: Two separate widget sections. Both are single cheap numbers; combining them keeps the total distinct widget count at 8 instead of 9 near-identical single-number cards.
- **Freshly-added widget reuses the existing _get_ideas(status='idea', sort='newest') helper capped at 5 rows** — rejected: A new bespoke query. A success-criteria critic pass noted this is the exact same query the homepage's own filter already runs; no reason to duplicate it.
- **Register-balance and pipeline-health success criteria are written as cmd checks** — rejected: Judgment calls for both. A success-criteria critic pass found both compare two already-curlable/queryable sources mechanically — no human eyeballing needed.
- **Modifying the live n8n workflow (adding the heartbeat node) is done via n8n's existing write-scoped REST API as part of the build, then re-exported to git** — rejected: Treat it as a manual step for the user to do by hand in the n8n UI. This project's own established precedent (the Basic-Auth-to-bearer-token credential swap) already did live workflow edits this way; it's an application-level workflow change, not a system/security-setting change like the firewall step it replaces.

## Execution Plan

_Added during Phase 5 handoff. Pick up this contract cold and know exactly how to execute._

### Dependency Graph

```
Dashboard route, widgets, heartbeat, and polling
```

### Execution Steps

**Run the project** (recommended) — autopilot reads this contract, plans dependency waves, runs independent phases in parallel, and gates on failure:

```bash
/ideation:autopilot docs/ideation/ideas-tracker-dashboard/contract.md
```

**Or run it unattended** — a `/goal` is a durability wrapper around the same autopilot run: Claude re-checks the condition before it is allowed to stop, so failures get repaired and re-run. Generated by `contract-gen --print-goal`; this is the only copy of that string:

```
/goal Drive the Ideas Tracker Dashboard contract (ideas-tracker-dashboard) to completion with /ideation:autopilot.

1. Run `/ideation:autopilot docs/ideation/ideas-tracker-dashboard/contract.md`. All commits belong on branch worktree-ideation+ideas-tracker-dashboard — switch to it before any run.
2. It dispatches a BACKGROUND workflow. Wait for the completion notification — never start a second autopilot run while one is in flight.
3. Then run the ideation plugin's `scripts/verify.mjs` against `docs/ideation/ideas-tracker-dashboard/contract-data.json` and leave its VERIFY line in the conversation. Resolve the plugin's install directory first — `${CLAUDE_PLUGIN_ROOT}/scripts/verify.mjs` is a placeholder, not a shell variable, and bash will not expand it. That line is the only evidence this goal is judged on.
4. If anything failed, fix the spec or the implementation and go back to step 1. Autopilot skips phases that already have commits.

Done when the most recent VERIFY line reads fail=0 and commits=1/1 — or when two consecutive VERIFY lines are identical and still failing, in which case name the failing checks and stop, because a contract whose checks have rotted must not trap the run.
```

**Or run phases manually** in dependency order:

**Strategy**: Sequential

1. **Phase 1** — Dashboard route, widgets, heartbeat, and polling _(blocking)_

   ```bash
   /ideation:execute-spec docs/ideation/ideas-tracker-dashboard/spec.md
   ```

---

_This contract was generated from brain dump input. Review and approve before proceeding to specification._
