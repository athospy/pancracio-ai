# Implementation Spec: Pancracio Monitoring Email - Phase 2: Daily Digest Workflow

**Contract**: ./contract.md
**Estimated Effort**: M

## Technical Approach

Add a new, independent n8n workflow — `n8n/workflows/pancracio-digest.json` — that runs once a
day at 9am UTC, asks the tracker's existing `/api/ideas?auto_publish=true` endpoint what's queued,
decides whether anything is due, and emails an HTML summary via Resend. This follows the exact
shape of the existing `auto-publish.json` workflow (Schedule Trigger → HTTP Request → Code node →
HTTP Request), reusing the already-live "Pancracio Tracker Bearer Token" credential for the GET
and the new Resend credential from Phase 1 for the POST.

This workflow is deliberately scoped to **queue state only** — "nothing queued" or "here's what's
next" — not failure reporting. An earlier draft of this phase's notes also had it check
`/api/ideas?status=failed` for the last 24 hours, but that traced to no stated goal, duplicated
Phase 3's dedicated failure-alert branch, and was removed during contract review (see Decisions
below). Keeping the two workflows single-purpose means a bug in one can't silently swallow the
other's job.

No backend changes: `_get_ideas_api` (`web/app.py:1423`) already returns every field this workflow
needs (`title`, `quote_line`, `scheduled_at`, `status`) via the existing `auto_publish=true` query
parameter.

## Decisions Considered and Rejected

- **The digest reports queue state only; failure visibility stays exclusively Phase 3's job** —
  rejected: also having this workflow's Code node check `/api/ideas?status=failed` for the last
  24h. Plan-critic review (scope-creep and over-engineering lenses, independently) flagged that
  the failed-item check traced to no stated goal or success criterion and duplicated Phase 3's
  dedicated alert branch — removed rather than promoted.
- **Plain n8n HTTP Request node + `httpHeaderAuth` credential, not a dedicated Resend node** —
  confirmed by directly inspecting the n8n VPS (SSH, n8n v2.40.6): no Resend node ships in this
  install.
- **Both emails are HTML-formatted** — rejected: plain-text emails. User wants the digest and
  alert emails to look nicer than plain text.
- **No new backend endpoint** — rejected: a new `/api/failures` or `/api/pipeline-status`
  endpoint. `web/app.py`'s existing `/api/ideas?auto_publish=true` already returns everything this
  workflow needs.

## Feedback Strategy

**Inner-loop command**: `curl -s -H "Authorization: Bearer $TRACKER_TOKEN"
"https://pancracio-ideas.santiagomorel.dev/api/ideas?auto_publish=true" | jq .`

**Playground**: the tracker's live `/api/ideas` endpoint via curl (to see the exact JSON shape
before writing the Code node's parsing logic), then n8n's UI for building and manually triggering
the workflow end-to-end (n8n has no local dev-server equivalent for workflow logic — manual
execution *is* the playground here).

**Why this approach**: there's no test runner for n8n workflow JSON; the fastest feedback is
curling the real endpoint to nail the data shape, then using n8n's own "Execute workflow" button
to run the whole chain against real data before ever touching the schedule trigger.

## File Changes

### New Files

| File Path | Purpose |
| --- | --- |
| `n8n/workflows/pancracio-digest.json` | Exported n8n workflow: daily schedule trigger → GET `/api/ideas?auto_publish=true` → Code node (build digest content) → POST to Resend. Committed to match the live n8n workflow, per this project's existing convention (e.g. commit `fd075e6`'s re-export of `auto-publish.json`). |

### Modified Files

| File Path | Changes |
| --- | --- |
| `internal-docs/ideas-tracker/auto-publish-credentials.md` | Add a short section noting the digest workflow exists, its schedule (9am UTC daily), and that it reuses the existing tracker bearer-token credential plus the new Resend credential from Phase 1. |

No changes to `web/app.py`, `n8n/workflows/auto-publish.json`, or `remotion/` in this phase.

## Implementation Details

### Schedule Trigger + Get Due Ideas

**Pattern to follow**: `n8n/workflows/auto-publish.json`'s "Hourly" + "Get Due Ideas" nodes —
same `scheduleTrigger` and `httpRequest` node types, different interval and query.

**Overview**: A daily (not hourly) schedule trigger, followed by an HTTP GET against
`/api/ideas?auto_publish=true` (not `?due=true` — the digest wants *everything* flagged for
auto-publish, including future-scheduled items, not only what's due right now, so it can report
"next up" even when nothing is due today).

```jsonc
// Schedule Trigger parameters (n8n scheduleTrigger node)
{
  "rule": {
    "interval": [
      { "field": "days", "daysInterval": 1, "triggerAtHour": 9 }
    ]
  }
}
```

**Key decisions**:

- `auto_publish=true`, not `due=true` — the digest needs to see the *next* item even if it's
  scheduled for tomorrow, not just items that are due right now.
- Reuse the existing "Pancracio Tracker Bearer Token" credential (id `F8WOkbGlhwKzrIOd`) — same
  account, same auth, no new tracker-side credential needed.

**Implementation steps**:

1. Add a `scheduleTrigger` node ("Daily 9am") with the daily/triggerAtHour rule above.
2. Add an `httpRequest` node ("Get Auto-Publish Ideas") GET-ing
   `https://pancracio-ideas.santiagomorel.dev/api/ideas` with query param `auto_publish=true`,
   using `predefinedCredentialType` / `httpHeaderAuth` with the existing tracker credential.

**Feedback loop**:

- **Playground**: curl against the live endpoint.
- **Experiment**: run the curl command above with the current (likely empty or single-item)
  `auto_publish=true` set, and separately toggle `auto_publish` on a test idea in the tracker UI
  to get a real second data point.
- **Check command**: `curl -s -H "Authorization: Bearer $TRACKER_TOKEN" "https://pancracio-ideas.santiagomorel.dev/api/ideas?auto_publish=true" | jq 'map({id, title, quote_line, scheduled_at, status})'`

### Build Digest Content (Code node)

**Pattern to follow**: `auto-publish.json`'s "Split Into Ideas" Code node for the general shape of
parsing an HTTP Request node's JSON body in n8n.

**Overview**: A Code node that takes the array from the previous step and decides which of two
cases applies: nothing queued, or a specific next item to report — picking the earliest
`scheduled_at` among `status = 'idea'` rows (items already `posted`/`failed`/`archived` aren't
"next up").

```javascript
// Code node: determine digest content
const body = $input.first().json;
const ideas = Array.isArray(body) ? body : [];
const pending = ideas.filter((i) => i.status === "idea");
pending.sort((a, b) => (a.scheduled_at || "").localeCompare(b.scheduled_at || ""));
const next = pending[0] || null;

const subject = next ? "Pancracio: next up" : "Pancracio: nothing queued";
const bodyHtml = next
  ? `<h2>Next up</h2><p><strong>${next.title}</strong></p><p>${next.quote_line || ""}</p><p>Scheduled: ${next.scheduled_at || "as soon as it's due"}</p>`
  : `<h2>Nothing queued</h2><p>No auto-publish ideas are currently pending.</p>`;

return [{ json: { subject, html: bodyHtml } }];
```

**Key decisions**:

- Picks the single earliest-scheduled pending item, not a list — matches the original ask
  ("here's what's publishing next"), keeps the email short.
- HTML built as a plain template string in the Code node — no templating library needed for two
  short cases.

**Implementation steps**:

1. Add a `code` node ("Build Digest Content") with the logic above.
2. Confirm field names against a real curl response first (`title`, `quote_line`, `scheduled_at`,
   `status` — all confirmed present in `web/app.py`'s `ideas` table schema).

**Feedback loop**:

- **Playground**: n8n's Code node has a built-in "Test step" runner against pinned input data.
- **Experiment**: pin one execution's input to an empty array (nothing queued case) and another
  to a single real idea object (next-up case); run the Code node against both.
- **Check command**: n8n's "Test step" output panel showing the expected `subject`/`html` for
  each pinned input — no CLI equivalent for this node type.

### Send via Resend (HTTP Request node)

**Pattern to follow**: `auto-publish.json`'s "Run Pipeline For Idea" node for the `httpRequest`
node shape with a bearer-style credential; Resend's API docs for the request body shape.

**Overview**: POST to Resend's `/emails` endpoint with the Code node's `subject`/`html`, from
`pancracio@notify.santiagomorel.dev` (or a `pancracio@` address at the verified subdomain — the
exact `from` address, since Resend only requires the *domain* be verified, not the mailbox) to the
user's own address.

```jsonc
// HTTP Request node body (Resend /emails)
{
  "from": "Pancracio Monitoring <pancracio@notify.santiagomorel.dev>",
  "to": ["santi.morel@gmail.com"],
  "subject": "={{ $json.subject }}",
  "html": "={{ $json.html }}"
}
```

**Key decisions**:

- `httpHeaderAuth` credential (the new Resend credential from Phase 1), `Authorization: Bearer
  <key>` — matches Resend's documented auth and this project's existing credential pattern.
- Single recipient, hardcoded to the user's own address — multi-recipient is explicitly out of
  scope.

**Implementation steps**:

1. Add an `httpRequest` node ("Send Digest Email") POST-ing to `https://api.resend.com/emails`
   with the body above, using the new Resend `httpHeaderAuth` credential.
2. Wire Schedule Trigger → Get Auto-Publish Ideas → Build Digest Content → Send Digest Email.
3. Set `active: true` once verified (matching `auto-publish.json`'s convention).

**Feedback loop**:

- **Playground**: n8n's "Execute workflow" button, and the destination inbox.
- **Experiment**: manually execute the full workflow once with the tracker in its current (likely
  empty) state, and once after temporarily flipping `auto_publish` on a test idea — confirming the
  email's subject/body match each case (success criterion 6).
- **Check command**: no CLI check for "email arrived correctly formatted" — this is the judgment
  check named in the contract; the closest automatable proxy is
  `grep -q '<html' n8n/workflows/pancracio-digest.json` confirming the workflow constructs HTML
  (contract success criterion 10) before ever manually checking the inbox.

## Testing Requirements

### Manual Testing

- [ ] Execute the workflow manually with the tracker's real (likely empty) auto-publish queue —
      confirm a "nothing queued" email arrives.
- [ ] Flip `auto_publish` on a test idea with a future `scheduled_at`, re-execute — confirm a
      "next up" email arrives with the correct title/quote/date.
- [ ] Confirm the email renders as HTML in a real mail client, not plain text.
- [ ] Activate the schedule trigger and confirm (via n8n's execution history, the next day) that
      it actually fires at 9am UTC unattended.

## Failure Modes

| Component | Failure Mode | Trigger | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| Get Auto-Publish Ideas | Tracker bearer token session expired/deleted | Same failure mode already seen once with the old Basic Auth credential | HTTP node errors, digest never sends | n8n execution history shows the failed run; same token this workflow reuses is already monitored by Phase 3's alert branch on the *other* workflow, so a broken token surfaces there too |
| Build Digest Content | `scheduled_at` is `null` on the picked item | An idea has `auto_publish=1` but no explicit schedule | Digest shows "as soon as it's due" rather than a date | Handled explicitly in the template string above, not left as `undefined` in the email |
| Send Digest Email | Resend API key or domain not yet verified when this phase starts | Phase 2 started before Phase 1 fully completed | 401/403 from Resend, no email sent | Phase 1 is a hard blocking prerequisite in the contract; don't start this phase until Phase 1's success criteria pass |

## Validation Commands

```bash
# Confirm the workflow file exists, is scheduled, and calls the right endpoint
test -f n8n/workflows/pancracio-digest.json \
  && grep -q scheduleTrigger n8n/workflows/pancracio-digest.json \
  && grep -q auto_publish n8n/workflows/pancracio-digest.json \
  && echo OK

# Confirm it references a credential, not an inline key
grep -q '"httpHeaderAuth"' n8n/workflows/pancracio-digest.json && echo OK

# Confirm the email body is HTML
grep -q '<html' n8n/workflows/pancracio-digest.json && echo OK
```

## Rollout Considerations

- **Monitoring**: n8n's own execution history is the monitor for this workflow itself (there's no
  meta-monitor watching the monitor, by design — out of scope per the contract).
- **Rollback plan**: deactivate the workflow in n8n (`active: false`) if it misbehaves; it has no
  side effects on the tracker or Instagram, only reads `/api/ideas` and sends email.

## Open Items

- [ ] Confirm Phase 1's Resend domain + credential are live before starting.
- [ ] Confirm the exact `from` address (`pancracio@notify.santiagomorel.dev` vs. another local
      part) with the user before finalizing the HTTP Request node body.

---

_This spec is ready for implementation. Follow the patterns and validate at each step._
