# Implementation Spec: Pancracio Monitoring Email - Phase 3: Failure Alert Branch

**Contract**: ./contract.md
**Estimated Effort**: M

## Technical Approach

Add an additive branch to the existing, **live** `n8n/workflows/auto-publish.json` so a pipeline
failure sends an alert email within the hour, instead of only surfacing at the next daily digest
(up to 24h later). This is the phase the user explicitly chose to accept real risk on — editing a
production workflow that just had real 401-authentication debugging on 2026-09-25 — in exchange
for near-real-time failure visibility (contract goal 2).

The contract's original notes for this phase worried about a genuine unknown: what does
`"Run Pipeline For Idea"`'s output item actually look like once it errors under its existing
`onError: "continueRegularOutput"` setting (`n8n/workflows/auto-publish.json:74-75`) — does the
idea's `id`/`title` survive, or does the item degrade to just an error object? **This spec sidesteps
that unknown entirely** rather than requiring a live-inspection step first: instead of parsing
whatever shape the errored item takes, add a follow-up node that asks the tracker directly —
`GET /api/ideas/{idea_id}` (`web/app.py:1466`, already exists, returns the idea's current row
including `status`) — using the idea's id recovered via n8n's node-reference expression
(`$('Split Into Ideas').item.json.id`, which follows per-item lineage back to the original item
regardless of what happened downstream). `_run_auto_publish_pipeline` (`web/app.py:1532`) already
sets `status='failed'` in its `except` block on any exception, so this is checking the same source
of truth the tracker UI itself would show — no dependency on n8n's internal error-item shape.

## Decisions Considered and Rejected

- **Add an immediate failure-alert branch directly to `auto-publish.json`, accepting the risk of
  editing a live, already-fragile production workflow** — rejected: keeping `auto-publish.json`
  untouched and only surfacing failures via the next daily digest (worst case ~24h). User
  explicitly prioritized faster failure detection (~1h, the next hourly run) given the Sep 25
  incident already went unnoticed for hours; this edit is additive (a new branch after the
  existing HTTP node), not a change to existing logic.
- **The daily digest workflow reports queue state only; this branch is the sole failure-detection
  path** — see Phase 2's spec. Keeps the two workflows single-purpose.
- **Both emails are HTML-formatted** — rejected: plain-text emails.
- **Detect failure via a follow-up `GET /api/ideas/{id}` call, not by parsing the errored HTTP
  node's output shape** — this is this spec's own resolution of the contract's named open concern
  (verifying `continueRegularOutput`'s output shape before building). Querying the tracker's
  existing single-idea endpoint for ground truth is simpler and doesn't depend on n8n internals
  that were never confirmed.

## Feedback Strategy

**Inner-loop command**: n8n's own "Execute workflow" against a real (or deliberately broken) idea,
inspecting each node's output in the n8n UI execution panel.

**Playground**: n8n's UI, using its per-node "pin data" / manual execution feature to test the new
branch against both a successful and a forced-failing idea without waiting for the real hourly
schedule.

**Why this approach**: there's no local test runner for a live n8n workflow; the fastest feedback
is n8n's own execution panel, which shows each node's actual input/output for a real run.

## File Changes

### Modified Files

| File Path | Changes |
| --- | --- |
| `n8n/workflows/auto-publish.json` | Add "Get Current Idea Status" (`httpRequest`, GET `/api/ideas/{{ $('Split Into Ideas').item.json.id }}`) and "Alert If Failed" (an `if`/filter node checking `status === 'failed'`) after "Run Pipeline For Idea", then "Send Failure Alert" (`httpRequest` POST to Resend) on the true branch. Re-exported from the live instance after applying via n8n's REST API, per this project's existing convention (commit `fd075e6`). |
| `internal-docs/ideas-tracker/auto-publish-credentials.md` | Note the new branch, its nodes, and that it reuses both the existing tracker bearer-token credential and the new Resend credential from Phase 1. |

No changes to `web/app.py` (success criterion 12) — `GET /api/ideas/{idea_id}` already exists and
already returns `status`.

## Implementation Details

### Get Current Idea Status

**Pattern to follow**: `auto-publish.json`'s existing `httpRequest` nodes for the node shape and
credential wiring.

**Overview**: After `"Run Pipeline For Idea"` (which continues regardless of success/failure), GET
the same idea's current row from the tracker to learn its real status — independent of whatever
the errored HTTP node's own output looks like.

```jsonc
// httpRequest node parameters
{
  "method": "GET",
  "url": "=https://pancracio-ideas.santiagomorel.dev/api/ideas/{{ $('Split Into Ideas').item.json.id }}",
  "authentication": "predefinedCredentialType",
  "nodeCredentialType": "httpHeaderAuth"
  // credentials: same "Pancracio Tracker Bearer Token" (id F8WOkbGlhwKzrIOd) as the other two nodes
}
```

**Key decisions**:

- Recovers the idea id via `$('Split Into Ideas').item.json.id` (node-reference expression,
  follows per-item lineage) rather than trusting the errored item's own fields — this is the
  design choice that avoids needing to first verify `continueRegularOutput`'s exact output shape.

**Implementation steps**:

1. Add the `httpRequest` node above immediately after `"Run Pipeline For Idea"` in the connections
   graph, using the same "Pancracio Tracker Bearer Token" credential.
2. **Before wiring the rest of the branch**, run this single node manually against a known idea id
   in n8n's UI and confirm it returns the expected row shape (`{id, status, title, quote_line,
   ...}`) — this is the one live-verification step this phase genuinely needs, and it's cheap
   because the endpoint already exists and is already used elsewhere in this project.

**Feedback loop**:

- **Playground**: n8n's UI, manual single-node execution.
- **Experiment**: run against a known-good idea id (expect `status: "idea"` or `"posted"`) and,
  later, against an idea deliberately forced to fail (expect `status: "failed"`).
- **Check command**: `curl -s -H "Authorization: Bearer $TRACKER_TOKEN" https://pancracio-ideas.santiagomorel.dev/api/ideas/<id> | jq .status`

### Alert If Failed (branch)

**Overview**: An `if` node testing `{{ $json.status === "failed" }}`; only the true branch
proceeds to sending an alert.

**Key decisions**:

- Branch on the tracker's own `status` field, not on the HTTP node's error/success outcome —
  matches the failure definition already used everywhere else in this project (a pipeline run is
  "failed" exactly when `_run_auto_publish_pipeline`'s `except` block set it so).

**Implementation steps**:

1. Add an `if` node after "Get Current Idea Status" with condition `{{ $json.status }}` equals
   `"failed"`.
2. Wire only the true output to the next node (Send Failure Alert); leave the false branch
   unconnected (workflow simply ends for that item).

**Feedback loop**:

- **Playground**: n8n's UI "pin data" feature — pin a fake `{status: "failed"}` item and a fake
  `{status: "posted"}` item, run the `if` node against both.
- **Experiment**: the two pinned cases above.
- **Check command**: n8n's execution panel showing which output branch fired for each pinned case
  — no CLI equivalent for this node type.

### Send Failure Alert

**Pattern to follow**: Phase 2's "Send Digest Email" node — same Resend `httpRequest` shape and
credential.

**Overview**: POST to Resend with an HTML body naming the specific idea that failed.

```jsonc
// httpRequest node body (Resend /emails)
{
  "from": "Pancracio Monitoring <pancracio@notify.santiagomorel.dev>",
  "to": ["santi.morel@gmail.com"],
  "subject": "=Pancracio: pipeline failed on \"{{ $json.title }}\"",
  "html": "=<h2>Pipeline failure</h2><p>Idea <strong>{{ $json.title }}</strong> (id {{ $json.id }}) failed during auto-publish.</p><p>Check the tracker for details.</p>"
}
```

**Key decisions**:

- Reuses the Phase 1 Resend credential — same account, same domain, one key per project (not a
  second key for this workflow specifically).
- Links back to "check the tracker" rather than embedding pipeline error details in the email —
  the tracker UI (and its audit log) is already the detailed source; the alert's job is just to
  say "look now," matching goal 2's framing.

**Implementation steps**:

1. Add the `httpRequest` node above on the `if` node's true branch, using the Resend credential
   from Phase 1.
2. Apply the whole branch to the **live** n8n instance via its REST API (`PUT
   /api/v1/workflows/{id}`), the same mechanism used for the bearer-credential swap documented in
   `internal-docs/ideas-tracker/auto-publish-credentials.md`.
3. Re-export the live workflow and commit it to `n8n/workflows/auto-publish.json` so the file
   matches what's deployed (success criterion 8).

**Feedback loop**:

- **Playground**: a deliberately forced failure (see Testing below) run end-to-end on the live
  n8n instance.
- **Experiment**: force one idea to fail (e.g. by temporarily renaming/invalidating the tracker
  bearer credential on "Run Pipeline For Idea" only, or pointing at a nonexistent idea id) and
  confirm the alert email arrives with the right idea's title.
- **Check command**: contract success criterion 9's manual test — no CLI equivalent for "email
  arrived"; the closest automatable proxy is `grep -q '<html' n8n/workflows/auto-publish.json`
  confirming HTML construction (success criterion 10).

## Testing Requirements

### Manual Testing

- [ ] Manually run "Get Current Idea Status" against a known idea id first, confirm the response
      shape, before wiring the rest of the branch (the one live-verification step this phase
      needs).
- [ ] Force a real failure (temporarily break the tracker credential on "Run Pipeline For Idea",
      or target an invalid idea id) and confirm: the idea's `status` flips to `failed`, and an
      alert email arrives naming that idea.
- [ ] Confirm a normal successful run does **not** send an alert (the `if` node's false branch).
- [ ] Restore the working credential immediately after the forced-failure test — this touches the
      live, active production workflow.
- [ ] Diff the re-exported `auto-publish.json` against the live n8n workflow to confirm they match
      (success criterion 8).

## Failure Modes

| Component | Failure Mode | Trigger | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| Get Current Idea Status | Idea id lookup fails (404) | The id itself was somehow invalid | This node errors; alert never fires for that item | Rare — the id comes from "Split Into Ideas", which sourced it from the same tracker; acknowledge and accept, since the underlying pipeline call for an invalid id would itself have failed identically before this phase existed |
| Alert If Failed | `status` briefly `"idea"` again if a human manually resets a failed row before this check runs | Human intervention between pipeline failure and this HTTP call (same execution, seconds apart) | Alert silently doesn't fire | Acceptable — the window is seconds within one execution, and a human already actively fixing the row doesn't need the alert |
| Send Failure Alert | Resend rate limit or transient 5xx | High volume or a Resend-side outage | Alert email lost for that one failure | Not retried (matches `auto-publish.json`'s existing `retryOnFail: false` convention) — acknowledged, not mitigated; the next day's digest still surfaces the failed idea's status if it's still `failed` |
| Whole branch | Editing the live workflow breaks the existing publish path | A mistake in the `PUT /api/v1/workflows/{id}` payload touches the pre-existing nodes | Auto-publish itself stops working, not just the new alert | Apply the change additively (new nodes + new connections only), verify the pre-existing three nodes' parameters are byte-identical in the PUT payload, and re-run success criterion 8's diff immediately after |

## Validation Commands

```bash
# Confirm the branch exists and references credentials/HTML correctly
grep -q '"httpHeaderAuth"' n8n/workflows/auto-publish.json && echo "credential OK"
grep -q '<html' n8n/workflows/auto-publish.json && echo "html OK"

# Confirm web/app.py is untouched by THIS branch's own commits (merge-base diff against main,
# not a pinned historical SHA -- other sessions keep committing unrelated work to main throughout
# this project, which made a fixed-SHA check go stale twice; a merge-base diff only sees what
# this branch itself changed, regardless of how much unrelated history lands on main meanwhile)
test -z "$(git diff main...HEAD -- web/app.py 2>/dev/null)" && echo "app.py untouched"
```

## Rollout Considerations

- **Monitoring**: n8n's execution history for `auto-publish.json` now also shows the new nodes'
  per-run outcome.
- **Alerting**: this phase *is* the alerting mechanism — no meta-alert on the alert itself.
- **Rollback plan**: if the branch misbehaves, remove the three new nodes via n8n's REST API and
  re-export, restoring the file to its current committed shape (git history has the pre-Phase-3
  version).

## Open Items

- [ ] Confirm Phase 1's Resend credential is live before starting.
- [ ] Decide the exact forced-failure method for the live test (invalid credential vs. invalid
      idea id) — either works, but only do this against production briefly and restore
      immediately after.

---

_This spec is ready for implementation. Follow the patterns and validate at each step._
