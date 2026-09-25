# Implementation Spec: Pancracio User Accounts & Login - Phase 3

**Contract**: ./contract.md
**Estimated Effort**: S

## Technical Approach

The smallest phase, and the one with the most consequence: delete the legacy Basic-Auth-fallback
branch from `get_current_user()`, so the old shared `PANCRACIO_AUTH_USER`/`PANCRACIO_AUTH_PASS`
pair stops being accepted anywhere. This phase only runs after the "Verify live cutover" gate has
been explicitly confirmed by a human — browser login/logout working in production, and n8n's
static bearer-token credential having completed at least one real hourly run with no auth errors.
There is no code reason this phase couldn't run immediately after Phase 1 — the entire reason it's
separate and gated is the phased-cutover decision from the interview: don't remove the only
working fallback until the replacement is actually proven live.

## Decisions Considered and Rejected

_Carried from the contract._

- **Phased cutover: deploy the new auth system alongside the still-working Basic Auth first,
  verify both paths live, then remove Basic Auth in a separate follow-up deploy behind an explicit
  human-verified gate** — rejected: a single deploy that swaps everything at once. This entire
  phase exists because of this decision — it IS the "separate follow-up deploy."

## Feedback Strategy

**Inner-loop command**: `curl -o /dev/null -w '%{http_code}\n' -u '<old-user>:<old-pass>' https://pancracio-ideas.santiagomorel.dev/api/ideas` against the live production URL, post-deploy.

**Playground**: production, post-deploy — this phase's entire point is a live behavior change, so
the meaningful check happens against the real deployed app, not a scratch instance (unlike Phases
1-2). A local scratch-instance check with the fallback branch deleted is still useful as a quick
sanity check before deploying, but doesn't substitute for the live one.

**Why this approach**: The criterion this phase exists to satisfy ("the old pair is rejected") is
only meaningful once verified against the actual deployed environment where the old credential
lived.

## File Changes

### Modified Files

| File Path | Changes |
| --- | --- |
| `web/app.py` | Delete the Basic-Auth-fallback branch inside `get_current_user()` (the `expected_user`/`expected_pass`/`credentials` block added in Phase 1); delete the now-unused `HTTPBasic(auto_error=False)` parameter from its signature; delete the `HTTPBasic`/`HTTPBasicCredentials` import if nothing else references it. |
| `internal-docs/ideas-tracker/deployment-runbook.md` | Remove `PANCRACIO_AUTH_USER`/`PANCRACIO_AUTH_PASS` from the documented env file contents; note they can be deleted from `/home/deploy/pancracio-ai/pancracio-ai.env` on charmander (a manual SSH edit — outside the automated deploy, same as their original addition was). |
| `internal-docs/ideas-tracker/auto-publish-credentials.md` | Mark the old `httpBasicAuth` n8n Credential (id `HGAAA7C2wrsj5ySp`) as retired/unused; the bearer-token credential documented in Phase 1 is now the only one referenced by the workflow. |

## Implementation Details

### Remove the legacy fallback branch

**Pattern to follow**: `get_current_user()` as built in Phase 1 (spec-phase-1.md's
Implementation Details) — this phase deletes exactly the block added there, nothing else.

**Overview**: The function shrinks to just the bearer-token and session-cookie checks; anything
presenting neither now hits the final `raise HTTPException(status_code=401, ...)` unconditionally.

```python
def get_current_user(request: Request) -> dict:
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
    raise HTTPException(status_code=401, detail="Not authenticated")
```

Note the return type tightens from `Optional[dict]` to `dict` — every caller now always gets a
real user row, so Phase 2's `_log_action(conn, user, ...)` `if user is None: return` guard becomes
dead code (harmless to leave, since it's a no-op check that will simply never trigger — removing
it is optional cleanup, not required for correctness).

**Key decisions**:

- No `HTTPBasic` parameter at all anymore — not even `auto_error=False` — since there's nothing
  left to check it against.

**Feedback loop**:

- **Playground**: local scratch instance first (quick sanity check), then production post-deploy
  (the real check).
- **Experiment**: the old Basic Auth pair against a gated route, before and after this deploy.
- **Check command**: `curl -o /dev/null -w '%{http_code}\n' -u '<old-user>:<old-pass>' https://pancracio-ideas.santiagomorel.dev/api/ideas` — expect `401` after deploy (would have been `200` before).

## Testing Requirements

### Manual Testing

- [ ] Local scratch instance: the old Basic Auth pair now returns 401 on a previously-gated route.
- [ ] Local scratch instance: session cookie and bearer token auth still work exactly as in Phase 1/2 (this phase should change nothing about them).
- [ ] **Post-deploy, against production**: the old `PANCRACIO_AUTH_USER`/`PASS` pair returns 401.
- [ ] **Post-deploy, against production**: your own browser login still works; n8n's next scheduled hourly run still succeeds (check its execution log).

## Failure Modes

| Component | Failure Mode | Trigger | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| `get_current_user` | The "Verify live cutover" gate was skipped or wrong, and something still depends on Basic Auth | A caller (human or automation) that was never actually migrated off Basic Auth | That caller is locked out of a live, budget-spending Instagram-publishing tool | This is exactly what the gate phase exists to prevent — do not skip it. If it happens anyway: `git revert` the commit that removed the fallback branch and redeploy; this restores dual-scheme support immediately (Phase 1's code, not a new implementation). |

## Validation Commands

```bash
web/venv/bin/python3 -m py_compile web/app.py
```

## Rollout Considerations

- **Feature flag**: none.
- **Monitoring**: watch n8n's next scheduled execution after this deploys — it's the one caller
  with no human in the loop to notice a problem immediately.
- **Rollback plan**: `git revert <this-phase's-commit>` + redeploy restores the Basic-Auth-fallback
  branch exactly as it was in Phase 1/2. No DB changes in this phase, so nothing to roll back
  there.

## Open Items

None.
