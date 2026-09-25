# Implementation Spec: Pancracio User Accounts & Login - Phase 1

**Contract**: ./contract.md
**Estimated Effort**: M

## Technical Approach

Replace the single shared `PANCRACIO_AUTH_USER`/`PANCRACIO_AUTH_PASS` Basic Auth pair with real
per-account rows, without breaking anything that authenticates today. Two new SQLite tables
(`users`, `sessions`) are added via `schema.sql`'s existing `CREATE TABLE IF NOT EXISTS` pattern —
no `ALTER TABLE` migration needed here since these are brand-new tables, not new columns on a
live one (that's Phase 2's problem, for `created_by`).

A new `get_current_user()` dependency replaces `check_auth()` everywhere, but during this phase it
accepts *three* forms of credential: a session cookie, a `Authorization: Bearer <token>` header
(both resolved against the same `sessions` table — a session row and n8n's long-lived token are
the same kind of row), or the legacy Basic Auth pair (kept as a fallback branch so nothing already
authenticating today breaks the moment this deploys). `check_auth()` itself is deleted once every
call site is swapped — its logic is absorbed into `get_current_user()`'s fallback branch, so there
is no dead code left behind.

Password hashing uses stdlib-only `hashlib.pbkdf2_hmac` + `secrets` (no new dependency —
`web/requirements.txt` has none today and doesn't need one for 2-3 accounts). Account creation has
no self-service path; a small script (`web/scripts/create_user.py`) provisions the human and n8n
accounts, matching this project's existing SSH/script-based operational model.

n8n's cutover is a one-time setup step, not a workflow change on every run: mint a token once via
`POST /login`, store it as a static n8n `httpHeaderAuth` Credential (`Authorization: Bearer
<token>`), and point the workflow's two HTTP Request nodes at it instead of the current
`httpBasicAuth` credential. No new node is added to the hourly workflow — this was a plan-review
finding (a per-run login step adds a new failure mode to a live pipeline for no benefit, since
sessions never expire).

## Decisions Considered and Rejected

_Carried from the contract._

- **DB-backed sessions table for both browser cookies and n8n's bearer token** — rejected: a
  signed stateless cookie (itsdangerous). Needs real revocation and a natural join target for
  audit logging (Phase 2); a sessions row is also literally what n8n's bearer token is.
- **n8n gets its own account and authenticates via a bearer token minted once, stored as a static
  n8n Credential** — rejected: a Login node inserted into the hourly workflow, capturing a fresh
  token on every run. The sessions table has no expiry, so per-run re-authentication adds risk to
  a live pipeline for no benefit.
- **Sessions/tokens don't expire automatically; revocation is manual (delete the row)** —
  rejected: time-limited tokens with rotation. Nothing in the goals asks for it; matches the
  "keep it simple" instruction and the existing SSH-based manual-recovery model.
- **Phased cutover: new auth deployed alongside the still-working Basic Auth, verified live, then
  removed in a separate follow-up deploy (Phase 3)** — rejected: a single deploy that swaps
  everything at once. Avoids risking a lockout on a live, budget-spending Instagram-publishing
  pipeline with no fallback.
- **Password hashing via stdlib `hashlib.pbkdf2_hmac` + `secrets`** — rejected: passlib or bcrypt.
  `web/requirements.txt` has zero auth dependencies today; stdlib is sufficient at this account
  volume.
- **Account provisioning via a script, no self-service registration** — rejected: nothing (no
  alternative was seriously considered). Matches the SSH/script-based password-reset model chosen
  in the same interview.

## Feedback Strategy

**Inner-loop command**: `web/venv/bin/python3 -m uvicorn app:app --port 8000` (run from `web/`,
against a copied `pancracio.db`), then `curl` against it.

**Playground**: A local scratch instance — the app's own documented local-run command
(`web/app.py`'s module docstring: `uvicorn app:app --reload`), started against a **copy** of
`pancracio.db` (never the live one) with `PANCRACIO_AUTH_USER`/`PASS` still set in the local
shell env (needed for the Basic-Auth-fallback branch to have something to compare against during
this phase).

**Why this approach**: Every component here is either a curl-able HTTP endpoint or a
directly-callable Python function (`hash_password`/`verify_password`) — matches this project's
established testing convention (no test suite anywhere in the repo; verification is manual
curl/sqlite3 against a scratch copy, same as the auto-publish pipeline's own Phase 2/3 testing).

## File Changes

### New Files

| File Path | Purpose |
| --- | --- |
| `web/scripts/create_user.py` | CLI: `python create_user.py <username> <password>` — inserts a hashed-password row into `users`. Used to provision the human and n8n accounts. No self-service equivalent exists. |
| `web/templates/login.html` | Real login page (form + a small inline `fetch`-based script) replacing the Basic Auth popup for browsers. |

### Modified Files

| File Path | Changes |
| --- | --- |
| `web/schema.sql` | Add `CREATE TABLE IF NOT EXISTS users (...)` and `CREATE TABLE IF NOT EXISTS sessions (...)` blocks (see Data Model), plus the matching index. |
| `web/app.py` | Add `hash_password`/`verify_password`; add `users`/`sessions` helpers; add `get_current_user()`; delete `check_auth()`, `security = HTTPBasic()`, and the now-unused `HTTPBasic`/`HTTPBasicCredentials` import (keep the `import secrets` — still used for token generation and timing-safe compares); add `POST /login`, `GET /login`, `POST /logout`; swap every existing `Depends(check_auth)` site (~26 routes, e.g. `app.py:849`, `876`, `884`, `912`, `926`, `958`, `987`, `1006`, `1027`, `1035`, ... through `1477`) to `Depends(get_current_user)`. |
| `web/templates/base.html` | Add a logout link (and "logged in as {username}") to the `nav-links` block, alongside the existing Queue/Stats/Settings links. |
| `n8n/workflows/auto-publish.json` | `Get Due Ideas` and `Run Pipeline For Idea` nodes: swap `authentication`/`nodeCredentialType`/`credentials` from the `httpBasicAuth` shape to `httpHeaderAuth`, referencing the new bearer-token credential by id/name (same by-reference pattern the file already uses — see `web/app.py`'s doc string reference at `auto-publish-credentials.md:90-95` for the existing convention). |
| `internal-docs/ideas-tracker/deployment-runbook.md` | Document the new account/credential model (still notes `PANCRACIO_AUTH_USER`/`PASS` as active during this phase — removed in Phase 3). |
| `internal-docs/ideas-tracker/auto-publish-credentials.md` | Document n8n's new bearer-token credential alongside (not yet replacing) the existing Basic Auth credential entry. |

## Implementation Details

### Password hashing

**Overview**: Stdlib-only PBKDF2. No feedback loop needed beyond the one-line check below — this
is a pure function, write-once.

```python
import hashlib
import secrets

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return f"{salt}${digest.hex()}"

def verify_password(password: str, stored: str) -> bool:
    salt, _, digest_hex = stored.partition("$")
    if not salt or not digest_hex:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
    return secrets.compare_digest(candidate, digest_hex)
```

**Key decisions**:

- 200,000 PBKDF2 iterations — OWASP's current minimum recommendation for PBKDF2-SHA256; costs
  ~100-200ms per hash, negligible at login-time volume for 2-3 accounts.
- `secrets.compare_digest` for the final comparison (timing-safe), matching the pattern
  `check_auth()` already used for the old Basic Auth compare.

**Feedback loop**:

- **Playground**: `web/venv/bin/python3 -i` (or a one-off script), no server needed.
- **Experiment**: hash a password, verify the correct password succeeds, verify a wrong password
  fails, verify a malformed `stored` value (no `$`) fails closed rather than raising.
- **Check command**: `web/venv/bin/python3 -c "from web.app import hash_password, verify_password; h=hash_password('test123'); assert verify_password('test123', h); assert not verify_password('wrong', h); print('OK')"`

### `users` / `sessions` tables + `create_user.py`

**Pattern to follow**: `web/app.py`'s `_init_db()` (`app.py:251-270`) for how `schema.sql` is
applied at startup — these are new tables, so the plain `CREATE TABLE IF NOT EXISTS` in
`schema.sql` is sufficient; no `PRAGMA table_info` guard is needed (that pattern is for adding a
*column* to an already-live table, which is Phase 2's job for `ideas.created_by`).

**Overview**: `users(id, username UNIQUE, password_hash, created_at)`. `sessions(id TEXT PRIMARY
KEY, user_id, created_at)` — `id` is the token itself (`secrets.token_urlsafe(32)`), used directly
as both the cookie value and the bearer token, so a session row and n8n's long-lived token are
literally the same object.

```python
# web/scripts/create_user.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app import _connect, hash_password

def main(username: str, password: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
    print(f"Created user: {username}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

**Key decisions**:

- No `UNIQUE` conflict handling beyond letting SQLite's constraint raise — this is a manual,
  operator-run script, not an API endpoint; a clear traceback on a duplicate username is fine.
- `sessions.id` doubles as the credential value itself (not a separate opaque "token" column) —
  simplest shape that satisfies "n8n's bearer token IS a sessions row."

**Feedback loop**:

- **Playground**: scratch DB copy + `create_user.py` run directly.
- **Experiment**: create a user, confirm the row exists with a non-plaintext `password_hash`;
  attempt a duplicate username, confirm it fails loudly rather than silently overwriting.
- **Check command**: `web/venv/bin/python3 web/scripts/create_user.py testuser testpass && sqlite3 <scratch-db> "SELECT username, password_hash FROM users;"`

### `get_current_user()` dependency

**Pattern to follow**: `check_auth()` (`app.py:181-197`) for the Basic-Auth-fallback branch's
exact comparison logic — reuse it verbatim inside the new function rather than rewriting it.

**Overview**: Tries, in order: (1) `Authorization: Bearer <token>` header → look up `sessions`;
(2) a session cookie (name: `pancracio_session`) → look up `sessions`; (3) Basic Auth, compared
against `PANCRACIO_AUTH_USER`/`PASS` exactly as `check_auth()` did. Raises 401 if none match. On
success via (1) or (2), returns the resolved `users` row (as a dict); on success via (3), returns
`None` (no real user row exists for the legacy path — Phase 2's audit-logging code must tolerate
this, since the fallback stays live through Phase 2).

```python
def get_current_user(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(HTTPBasic(auto_error=False)),
) -> Optional[dict]:
    token = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
    elif "pancracio_session" in request.cookies:
        token = request.cookies["pancracio_session"]

    if token:
        with _connect() as conn:
            row = conn.execute(
                "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
                "WHERE sessions.id = ?",
                (token,),
            ).fetchone()
        if row:
            return dict(row)
        raise HTTPException(status_code=401, detail="Invalid or revoked session")

    # Legacy fallback — removed entirely in Phase 3.
    expected_user = os.environ.get("PANCRACIO_AUTH_USER")
    expected_pass = os.environ.get("PANCRACIO_AUTH_PASS")
    if credentials and expected_user and expected_pass:
        user_ok = secrets.compare_digest(credentials.username, expected_user)
        pass_ok = secrets.compare_digest(credentials.password, expected_pass)
        if user_ok and pass_ok:
            return None
    raise HTTPException(status_code=401, detail="Not authenticated")
```

**Key decisions**:

- If `PANCRACIO_AUTH_USER`/`PASS` are unset, the fallback branch is silently skipped (not a 500
  like the old `check_auth()`) — this phase is explicitly transitional, and Phase 3 removes the
  env vars entirely, so treating "unset" as "fallback unavailable" rather than a hard error is the
  correct end state to be moving toward.
- `HTTPBasic(auto_error=False)` (not the module-level `security = HTTPBasic()` the old code used)
  so a request presenting no credentials at all doesn't itself 401 before the bearer/cookie checks
  run.

**Feedback loop**:

- **Playground**: local scratch instance (see Feedback Strategy above).
- **Experiment**: request a gated route with (a) a valid session cookie, (b) a valid bearer token,
  (c) the legacy Basic Auth pair, (d) nothing — first three succeed, last one 401s.
- **Check command**: the four-branch curl matrix from the contract's success criteria:
  `c1=$(curl -s -o /dev/null -w '%{http_code}' -b /tmp/c.txt http://127.0.0.1:8000/api/ideas); c2=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/ideas); c3=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/ideas); echo "$c1 $c2 $c3"`

### `POST /login`, `GET /login`, `POST /logout`

**Overview**: One endpoint (`POST /login`) serves both browsers and n8n identically — it always
sets a `Set-Cookie` header AND returns `{"token": "..."}` in the JSON body, regardless of caller.
The login *page* (`GET /login`) is a real HTML form whose tiny inline script does a `fetch` to
`POST /login` and redirects to `/` on success, rather than a native form POST — this keeps the
server-side handler single-shaped (always JSON) instead of forking behavior by caller type.

```python
@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        # Compare against a dummy hash when the user doesn't exist, so a nonexistent
        # username and a wrong password take the same amount of time.
        stored_hash = row["password_hash"] if row else hash_password("dummy")
        if not row or not verify_password(password, stored_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessions (id, user_id) VALUES (?, ?)", (token, row["id"]))
        conn.commit()
    response = JSONResponse({"token": token, "ok": True})
    response.set_cookie(
        "pancracio_session", token, httponly=True, samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response

@app.post("/logout")
def logout(request: Request):
    token = request.cookies.get("pancracio_session") or ""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (token,))
        conn.commit()
    response = JSONResponse({"ok": True})
    response.delete_cookie("pancracio_session")
    return response
```

**Key decisions**:

- Timing-safe user lookup (compare against a dummy hash when the username doesn't exist) — carries
  forward the timing-safety principle `check_auth()` already applied via `compare_digest`.
  401 doesn't distinguish "no such user" from "wrong password" in the response body either.
- `secure=request.url.scheme == "https"` rather than a hardcoded `True` — local curl testing over
  plain HTTP still gets a cookie; production (behind nginx TLS per `deployment-runbook.md`) gets a
  secure one automatically.
- `login.html`'s JS, not a server-side redirect-vs-JSON fork — a single response shape for every
  caller is simpler to reason about and test than content-negotiation logic.

**Feedback loop**:

- **Playground**: local scratch instance.
- **Experiment**: valid login (cookie set + token in body), invalid password (401, no session
  row created), logout then reuse the old cookie (401).
- **Check command**: the three curl checks from the contract's success criteria 2-4 (see Testing
  Requirements below for the exact commands).

### n8n cutover

**Overview**: Not a code change to `web/app.py` — an operational + `n8n/workflows/auto-publish.json`
change, done once after `POST /login` is deployed and verified.

**Implementation steps**:

1. Run `create_user.py` for both the human account and an `n8n` account.
2. `curl -c - -d 'username=n8n&password=<n8n-password>' https://pancracio-ideas.santiagomorel.dev/login`
   once, capture the returned token from the JSON body.
3. Via n8n's REST API (same technique already used for the existing `httpBasicAuth` credential,
   per `internal-docs/ideas-tracker/auto-publish-credentials.md:90-95` and the API-key creation
   pattern in `lessons-learned.md`), create a new `httpHeaderAuth` Credential named e.g. "Pancracio
   Tracker Bearer Token" with header name `Authorization`, value `Bearer <token>`.
4. Update `Get Due Ideas` and `Run Pipeline For Idea` in `n8n/workflows/auto-publish.json` to
   reference the new credential (swap the `authentication`/`nodeCredentialType`/`credentials`
   block from `httpBasicAuth` to `httpHeaderAuth`, by id/name, matching the existing
   by-reference-only convention).
5. Leave the old `httpBasicAuth` credential in place, unreferenced, until Phase 3 (no reason to
   delete it before Basic Auth itself is removed server-side).

**Feedback loop**:

- **Playground**: n8n's UI ("Execute workflow" on the updated workflow), against the deployed
  tracker.
- **Experiment**: trigger a manual execution, inspect both HTTP Request nodes' output for a 200
  and no auth error.
- **Check command**: none (judgment call — see the contract's success criterion for this step).

## Data Model

### Schema Changes

```sql
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
```

No `ALTER TABLE` guard needed in `_init_db()` for these — `CREATE TABLE IF NOT EXISTS` is
sufficient since both tables are wholly new (unlike Phase 2's `ideas.created_by`, which adds a
column to an already-live table).

## API Design

### New Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/login` | Serves the login page. No auth required. |
| `POST` | `/login` | Validates credentials, creates a session, sets a cookie, returns a bearer token. |
| `POST` | `/logout` | Deletes the current session (by cookie or bearer token), clears the cookie. |

### Request/Response Examples

```
POST /login
Content-Type: application/x-www-form-urlencoded

username=santi&password=<password>

# Response: 200
Set-Cookie: pancracio_session=<token>; HttpOnly; SameSite=Lax
{"token": "<token>", "ok": true}
```

```
POST /login  (wrong password)
# Response: 401
{"detail": "Invalid credentials"}
```

## Testing Requirements

### Manual Testing

- [ ] `create_user.py` creates a user with a hashed (not plaintext) password; duplicate username fails loudly.
- [ ] `hash_password`/`verify_password` round-trip correctly; wrong password fails; malformed stored value fails closed.
- [ ] `POST /login` with valid credentials: 200, `Set-Cookie` present, JSON body has `token`.
- [ ] `POST /login` with a wrong password: 401, no new `sessions` row created.
- [ ] A gated route (e.g. `GET /api/ideas`) succeeds with the session cookie, succeeds with the bearer token as `Authorization: Bearer`, succeeds with the legacy Basic Auth pair, and 401s with none of the three.
- [ ] `POST /logout` then reusing the same cookie against a gated route: 401.
- [ ] `GET /login` renders a real form (not a Basic Auth popup) in a browser.
- [ ] n8n's updated workflow, using the new static bearer-token credential, completes a real execution with no auth errors.

## Failure Modes

| Component | Failure Mode | Trigger | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| `get_current_user` | Legacy fallback silently unavailable | `PANCRACIO_AUTH_USER`/`PASS` unset (expected once Phase 3 removes them) | Any caller still using Basic Auth gets a plain 401 instead of the old 500 | Deliberate — this is the correct end-state behavior to be moving toward, not a bug. |
| `get_current_user` | Revoked/deleted session reused | A `sessions` row is deleted (logout, or a manual DB delete) but the caller retries with the old cookie/token | 401 | Expected behavior — this IS how revocation works in this design; no special handling needed. |
| `POST /login` | Username enumeration via timing | An attacker probes usernames and measures response time | Could reveal which usernames exist | Mitigated by comparing against a dummy hash when the user doesn't exist, keeping the two failure paths' timing similar. |
| n8n cutover | Bearer-token credential misconfigured (wrong header format/value) | Manual error during the one-time n8n Credential setup | The hourly pipeline halts with 401s, no publish occurs | Caught by the live-execution verification step before this phase is considered done; the old Basic Auth credential is left intact and can be swapped back in immediately if needed. |
| Session cookie | `Secure` flag set over a plain-HTTP local dev request | Testing locally without HTTPS | Cookie wouldn't be sent back by a real browser in that setup (curl ignores `Secure`, so curl-based checks still pass) | `secure=request.url.scheme == "https"` derives the flag from the actual request instead of hardcoding it. |

## Validation Commands

```bash
# No linter/typechecker/test suite configured in this repo (matches existing project convention)
web/venv/bin/python3 -m py_compile web/app.py web/scripts/create_user.py
```

## Rollout Considerations

- **Feature flag**: none needed — the dual-scheme `get_current_user()` dependency IS the rollout
  mechanism; Basic Auth keeps working throughout this phase, so there's no cutover moment here.
- **Monitoring**: none new; watch n8n's execution log after the credential swap (manual, per the
  Feedback Loop above).
- **Rollback plan**: this phase is purely additive (new tables, new endpoints, a swapped
  dependency that still accepts the old credential) — reverting the deploy removes the new code
  paths but the new tables sit harmlessly unused; no data migration to undo.

## Open Items

- [ ] Exact `login.html` styling/copy — not specified here, low-stakes, decide during build.
- [ ] Whether `GET /login` should redirect straight to `/` if already logged in — small UX nicety, decide during build.
