# Pancracio User Accounts & Login Contract

**Created**: 2026-09-25
**Readiness**: All 5 gates ready
**Status**: Approved
**Approval**: Interactive review
**Supersedes**: None

## Problem Statement

The Pancracio ideas tracker (web/app.py, https://pancracio-ideas.santiagomorel.dev) gates every route behind a single shared HTTP Basic Auth username/password pair, read from PANCRACIO_AUTH_USER/PANCRACIO_AUTH_PASS env vars and compared with secrets.compare_digest — no hashing, no per-user rows, one credential for every caller.

n8n's automated hourly publishing pipeline authenticates against the same routes using an n8n Credential that simply wraps that identical shared pair — there is no distinction today between the human user and the automation from the app's point of view.

There is no login page (the browser's native Basic Auth popup is the only UI), no real logout (only clearing browser-cached credentials achieves that), and no way to tell which account created or later changed a given idea — as the tracker moves toward multiple human users and more automated integrations sharing this one identity, that gap gets worse, not better.

This is a live, production system that already publishes real content to Instagram on a real budget (see docs/ideation/pancracio-auto-publish/) via an hourly n8n workflow with no manual step today — any auth change risks a real lockout of either the human or the automation if done carelessly.

## Goals

1. Every idea, and the key actions taken on it after creation (edit, auto_publish toggle, publish/mark-posted), is attributable to a specific account — verifiable by querying the idea's created_by and its audit_log rows, and by seeing that history rendered on the idea itself.
2. The Basic Auth popup is replaced by a real login page with working logout — verifiable by requesting any gated route with no session and observing a login prompt instead of a browser-native popup, and by confirming a session is invalidated after logout.
3. n8n's hourly auto-publish pipeline keeps running unattended after cutover, authenticated via its own account instead of the shared credential pair — verifiable by a real, successful n8n execution against the new auth mechanism.
4. The cutover from Basic Auth to the new system causes zero lockout incidents for either the human user or n8n — enforced structurally by deploying the new system alongside the still-working Basic Auth, verifying both paths live, and only then removing Basic Auth in a separate, smaller follow-up deploy.

## Success Criteria

- [ ] A password can be hashed and verified without adding a new third-party dependency — check: `web/venv/bin/python3 -c "from web.app import hash_password, verify_password; h = hash_password('test123'); assert verify_password('test123', h); assert not verify_password('wrong', h); print('OK')"` → prints OK and exits 0 — uses web/venv's interpreter, not bare python3, since fastapi/httpx aren't installed at the system level
- [ ] POST /login with valid credentials creates a sessions row, sets a session cookie, and returns a bearer token in the JSON body; invalid credentials return 401 and create no session — check: `code=$(curl -s -o /tmp/r.json -w '%{http_code}' -c /tmp/c.txt -d 'username=<test-user>&password=<test-pass>' http://127.0.0.1:8000/login); test "$code" = 200 && grep -q token /tmp/r.json && test -s /tmp/c.txt; bad=$(curl -s -o /dev/null -w '%{http_code}' -d 'username=<test-user>&password=wrong' http://127.0.0.1:8000/login); test "$bad" = 401` → both compound commands exit 0 — valid login returns 200 with a token in the body and a non-empty cookie jar; wrong password returns 401
- [ ] A previously check_auth-gated route accepts EITHER the new session cookie, a bearer token in the Authorization header, or (only until the final phase) the legacy Basic Auth pair — and rejects a request presenting none of the three — check: `c1=$(curl -s -o /dev/null -w '%{http_code}' -b /tmp/c.txt http://127.0.0.1:8000/api/ideas); c2=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/ideas); c3=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/ideas); test "$c1" = 200 -a "$c2" = 200 -a "$c3" = 401` → exits 0 — cookie and bearer token both return 200, no credential returns 401
- [ ] POST /logout invalidates the session — a subsequent request reusing the same cookie is rejected — check: `curl -s -b /tmp/c.txt -c /tmp/c.txt -X POST http://127.0.0.1:8000/logout -o /dev/null; code=$(curl -s -o /dev/null -w '%{http_code}' -b /tmp/c.txt http://127.0.0.1:8000/api/ideas); test "$code" = 401` → exits 0 — the same cookie is rejected after logout
- [ ] Creating an idea via POST /ideas records created_by as the authenticated user's id, visible via a direct DB query and in the idea's UI — check: `val=$(sqlite3 <scratch-db-copy> "SELECT created_by FROM ideas ORDER BY id DESC LIMIT 1;"); test -n "$val"` → exits 0 — created_by is non-empty (not NULL) for the most recently created idea
- [ ] Editing an idea, toggling auto_publish, and marking an idea posted each write an audit_log row naming the actor, the action, and the idea — check: `count=$(sqlite3 <scratch-db-copy> "SELECT COUNT(*) FROM audit_log WHERE idea_id=<test-idea-id> AND action IN ('edit','auto_publish_toggle','mark_posted');"); test "$count" = 3` → exits 0 — exactly one audit_log row per action type for the test idea
- [ ] The idea edit page's Activity section actually renders the audit_log rows for that idea, not just the underlying table — check: `n=$(curl -s -b /tmp/c.txt http://127.0.0.1:8000/ideas/<test-idea-id>/edit | grep -c 'data-activity-row'); test "$n" -ge 3` → exits 0 — at least 3 activity rows appear in the rendered HTML, matching the 3 audit_log rows from the criterion above (spec defines the data-activity-row marker on each rendered row)
- [ ] n8n's own account has a long-lived bearer token, minted once and stored as a static n8n Credential (mirroring today's static Basic Auth credential), and the workflow completes a real execution end-to-end against the deployed tracker using it — judgment call: trigger the workflow manually in the n8n UI after the static bearer-token Credential is configured, and review its execution log for a successful run with no auth errors on either HTTP Request node
- [ ] After the final phase removes Basic Auth acceptance, a request using the old PANCRACIO_AUTH_USER/PANCRACIO_AUTH_PASS pair is rejected, and the pipeline still runs successfully via the new mechanism alone — check: `code=$(curl -s -o /dev/null -w '%{http_code}' -u '<old-user>:<old-pass>' http://127.0.0.1:8000/api/ideas); test "$code" = 401` → exits 0 — the old pair is no longer accepted
- [ ] No lockout incident occurs during cutover — both the human login and n8n's new flow are confirmed working live before Basic Auth is removed — judgment call: human confirms both the browser login/logout flow and a real n8n execution succeeded in production before approving the final Basic Auth removal phase

## Scope Boundaries

### In Scope

- users table + stdlib-only password hashing (hashlib.pbkdf2_hmac + secrets), no new dependency — Core identity model; stdlib is enough for a 2-3 account tool and avoids adding a dependency to a small production app.
- Account provisioning: a web/scripts/create_user.py script or a documented sqlite3-INSERT runbook step (no self-registration, no admin UI) to create the human account(s) and n8n's account — Phase 1's own login success criteria and n8n's cutover both require these accounts to exist first — a hidden-dependency gap in the first draft of this plan. Matches the SSH/script-based operational model already chosen for password reset.
- sessions table (id/token, user_id, created_at, no expiry) — doubles as n8n's bearer token — Chosen over a signed stateless cookie so sessions are revocable (delete the row) and n8n's token can literally be a sessions row, making 'same mechanism for humans and n8n' concretely true. No TTL/rotation, since nothing in the goals asks for it — see decisions.
- POST /login (sets session cookie + returns bearer token in JSON) and POST /logout — The one endpoint both browsers and n8n use, consumed differently by each — no separate bolted-on API-key system.
- GET /login page (real form, tiny inline fetch-based JS) replacing the Basic Auth popup — The stated UX complaint — no login page, no real logout.
- get_current_user dependency accepting session cookie, bearer token, or (temporarily) legacy Basic Auth; swapped in for every existing Depends(check_auth) site — Backwards-compatible during the phased cutover — nothing existing breaks the moment this deploys.
- n8n's own account with a bearer token minted once and stored as a static n8n httpHeaderAuth Credential (not a per-run login step) — Achieves 'n8n authenticates via its own account, same endpoint as humans' without adding an authentication round-trip (and a new failure mode) to every one of ~24 unattended hourly executions — an over-engineering finding from plan review, folded in.
- created_by column on ideas (added via an ALTER TABLE ADD COLUMN migration guard, following the same PRAGMA table_info pattern _init_db() already uses for posts.ig_media_id), populated at creation, shown in the UI — The core ask — 'check which idea is added by a user.' The migration step is named explicitly after a hidden-dependency finding: schema.sql's CREATE TABLE IF NOT EXISTS alone would not add this column to the live production table.
- audit_log table + logging on edit / auto_publish toggle / publish / mark-posted, surfaced as a per-idea Activity section on the edit page — User explicitly widened scope from creation-only back to 'creation + key later actions' after an initial simpler framing. The UI-rendering half now has its own success criterion after a plan-review finding that the table alone wasn't checked.
- Final phase: remove Basic Auth acceptance from get_current_user, after a live-verified gate — The actual point of the project — the shared credential goes away, but only once nothing depends on it anymore.
- Self-service password reset flow (email-based) — Deferred — no email infrastructure exists; SSH/script-based reset matches the existing operational model for a 1-2 person tool.
- Role-based permissions (e.g. n8n restricted to /internal + /api only) — Deferred — user explicitly chose flat access; nothing in the stated problems (UX, visibility) requires an authorization model.
- Rate-limiting / lockout on repeated failed logins — Deferred — user explicitly called this out of scope; not a regression since today's Basic Auth has none either.

### Out of Scope

- Changing the /static and /image-posts unauthenticated mounts (e.g. to signed/expiring URLs) — Confirmed load-bearing for Instagram's server-side image fetch and the render VPS; user explicitly froze this. Research this session also confirmed Instagram's fetch can't carry auth headers at all, so no auth scheme (only a signed-URL scheme) could ever cover it — moot for this project either way.
- VPS SSH access, n8n's own admin login/UI — Different systems entirely — this project covers only the pancracio-ideas app's own API auth, per explicit scope confirmation.
- Two-factor authentication — Never raised as a need; single/small user base.

### Future Considerations

- Self-service password reset if the account list grows beyond people who already have SSH access
- Role-based permissions if a lower-trust integration is ever added
- Rate limiting if failed-login abuse is ever actually observed
- Session/token expiry and rotation if the account list or trust model ever changes

## Decisions Considered and Rejected

- **DB-backed sessions table for both browser cookies and n8n's bearer token** — rejected: Signed stateless cookie (itsdangerous). Needs real revocation and a natural join target for audit logging; a sessions row is also literally what n8n's bearer token is, which is what makes 'same mechanism for humans and n8n' concretely true rather than just stated.
- **Password reset via SSH/script, no self-service flow** — rejected: Email-based self-service password reset. No email infrastructure exists in this project; matches the SSH-based operational model already used for everything else on this tool.
- **Flat permissions — any authenticated account has full access** — rejected: Role-based permissions (e.g. n8n restricted to /internal + /api only). Not what the stated problems (UX, visibility/attribution) call for; adds an authorization model nobody asked for.
- **No rate-limiting or lockout on failed logins** — rejected: Basic per-IP rate-limiting. Not a regression versus today's Basic Auth, which also has none; user's stated pain points were UX and visibility, not this.
- **n8n gets its own account and authenticates via a bearer token minted once (through the same /login endpoint humans use) and stored as a static n8n Credential — not a per-run login step inside the workflow** — rejected: A Login node inserted into the hourly workflow, capturing a fresh token on every one of ~24 daily executions. Plan review (over-engineering lens) caught that the sessions table has no expiry, so re-authenticating on every run adds a new failure mode to a live pipeline for no benefit. A one-time-minted static token, referenced by an n8n Credential exactly like today's Basic Auth credential, satisfies both 'n8n authenticates via its own account through the same mechanism' and 'don't disrupt what's already working' at once — the two things that were in tension mid-interview.
- **Sessions/tokens don't expire automatically (no TTL column); revocation is manual (logout deletes the row; a lost or compromised n8n token is revoked by deleting its row directly)** — rejected: Time-limited tokens with rotation. Nothing in the goals asks for rotation or expiry; matches the 'keep it simple' instruction and the existing SSH-based manual-recovery model already used for password reset. Named explicitly (rather than left implicit) since it's a real security-relevant absence, not an oversight.
- **Audit coverage extends to edit / auto_publish toggle / publish / mark-posted, not just idea creation** — rejected: Creation-only attribution (a created_by column, no audit_log table). User explicitly widened scope back to 'creation + key later actions' after initially signaling a simpler, creation-only cut.
- **Phased cutover: deploy the new auth system alongside the still-working Basic Auth first, verify both paths live (human login/logout, a real n8n execution), then remove Basic Auth in a separate, smaller follow-up deploy behind an explicit human-verified gate** — rejected: A single deploy that swaps everything at once. Directly matches 'don't disrupt what's already working' — avoids risking a lockout on a live, budget-spending Instagram-publishing pipeline with no fallback if something's wrong.
- **Password hashing via Python's stdlib (hashlib.pbkdf2_hmac + secrets), no new dependency** — rejected: passlib or bcrypt (third-party library). web/requirements.txt currently has zero auth-related dependencies; stdlib PBKDF2 is sufficient for this account volume (2-3 users) and keeps a small production tool's dependency surface unchanged.
- **Attribution surfaced as a per-idea 'Activity' section (audit_log rows filtered to that idea, shown inline on the edit page) instead of a dedicated audit-log page** — rejected: A standalone audit-log/admin page listing actions across all ideas. Matches the 'mostly a UI enhancement' framing — surfaces attribution where the user is already looking (the idea itself) without adding a new page/nav item nothing asked for.
- **internal-docs updates (deployment-runbook.md, auto-publish-credentials.md, a new doc describing the auth model) are folded into each phase's own notes rather than listed as a separate MVP scope item** — rejected: A standalone 'update internal-docs' MVP scope bullet. Plan review (scope-creep lens) correctly noted a standalone doc-update item didn't trace to any stated goal or success criterion. Docs still get updated (matches this project's established convention), just as part of the phase that changes the thing being documented, not as its own goal-justified deliverable.

## Execution Plan

_Added during Phase 5 handoff. Pick up this contract cold and know exactly how to execute._

### Dependency Graph

```
Users, Sessions & Login
  ├── Attribution & Audit Log  (blocked by Users, Sessions & Login)
  └── Verify live cutover before removing Basic Auth  (blocked by Users, Sessions & Login, Attribution & Audit Log)
        └── Remove Legacy Basic Auth  (blocked by Verify live cutover before removing Basic Auth)
```

### Execution Steps

**Run the project** (recommended) — autopilot reads this contract, plans dependency waves, runs independent phases in parallel, and gates on failure:

```bash
/ideation:autopilot docs/ideation/pancracio-user-accounts/contract.md
```

**Or run it unattended** — a `/goal` is a durability wrapper around the same autopilot run: Claude re-checks the condition before it is allowed to stop, so failures get repaired and re-run. Generated by `contract-gen --print-goal`; this is the only copy of that string:

```
/goal Drive the Pancracio User Accounts & Login contract (pancracio-user-accounts) to completion with /ideation:autopilot.

1. Run `/ideation:autopilot docs/ideation/pancracio-user-accounts/contract.md`.
2. It dispatches a BACKGROUND workflow. Wait for the completion notification — never start a second autopilot run while one is in flight.
3. Then run the ideation plugin's `scripts/verify.mjs` against `docs/ideation/pancracio-user-accounts/contract-data.json` and leave its VERIFY line in the conversation. Resolve the plugin's install directory first — `${CLAUDE_PLUGIN_ROOT}/scripts/verify.mjs` is a placeholder, not a shell variable, and bash will not expand it. That line is the only evidence this goal is judged on.
4. If anything failed, fix the spec or the implementation and go back to step 1. Autopilot skips phases that already have commits.

Done when the most recent VERIFY line reads fail=0 and commits=3/3 — or when two consecutive VERIFY lines are identical and still failing, in which case name the failing checks and stop, because a contract whose checks have rotted must not trap the run.
```

**Or run phases manually** in dependency order:

**Strategy**: Sequential

1. **Phase 1** — Users, Sessions & Login _(blocking)_

   ```bash
   /ideation:execute-spec docs/ideation/pancracio-user-accounts/spec-phase-1.md
   ```

2. **Phase 2** — Attribution & Audit Log _(blocked by Users, Sessions & Login)_

   ```bash
   /ideation:execute-spec docs/ideation/pancracio-user-accounts/spec-phase-2.md
   ```

3. **Phase 3** — Verify live cutover before removing Basic Auth _(blocking)_

   ```bash
   # Review: Verify live cutover before removing Basic Auth
   ```

4. **Phase 4** — Remove Legacy Basic Auth _(blocking)_

   ```bash
   /ideation:execute-spec docs/ideation/pancracio-user-accounts/spec-phase-3.md
   ```

---

_This contract was generated from brain dump input. Review and approve before proceeding to specification._
