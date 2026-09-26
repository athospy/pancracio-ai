# Pancracio Monitoring Email Contract

**Created**: 2026-09-26
**Readiness**: All 5 gates ready
**Status**: Approved
**Approval**: Interactive review
**Supersedes**: contract-2026-09-26.html

## Problem Statement

The Pancracio auto-publish pipeline (n8n/workflows/auto-publish.json, running hourly against pancracio-ideas.santiagomorel.dev) has no failure or status visibility outside the tracker UI. On 2026-09-25 its first 3 hourly executions (15:00, 16:00, 17:00 UTC) all failed with a silent 401 on the old Basic Auth credential — nobody noticed because nothing surfaces pipeline state anywhere. The only way to know whether anything is queued, about to publish, or has failed is to manually open the tracker.

Separately, there is no reusable email-sending setup for santiagomorel.dev at all — zero mail-related DNS records exist today. Every future project on this domain would otherwise have to re-derive domain verification and API-key strategy from scratch.

## Goals

1. A daily email (9am UTC, from a verified santiagomorel.dev subdomain) arrives without fail and accurately reflects the tracker's real state: either 'nothing queued' or the next auto-publish item's title/quote/scheduled time.
2. A pipeline failure is surfaced within ~1 hour via its own immediate alert email, rather than waiting up to 24h for the next daily digest.
3. The Resend domain verification and API-key pattern are documented in porfolio/internal-docs/ (the repo that actually serves santiagomorel.dev) so a future, unrelated project can reuse them without re-deriving anything.
4. Both the digest and alert emails render as styled HTML rather than plain text.

## Success Criteria

- [ ] notify.santiagomorel.dev is verified in Resend's dashboard — judgment call: User opens the Resend dashboard and confirms the domain's status reads 'Verified'.
- [ ] No Resend API key has ever been committed to git in this repo's history — check: `! git log --all -p | grep -qE "re_[A-Za-z0-9]{20,}"` → exits 0
- [ ] n8n holds a Resend credential (httpHeaderAuth, Bearer key), matching the existing 'Pancracio Tracker Bearer Token' pattern — judgment call: Reviewer lists n8n's credentials (UI or REST API) and confirms a Resend-labeled entry exists, without ever printing the raw key value.
- [ ] Both the digest and alert workflow JSONs reference an httpHeaderAuth credential for the Resend HTTP Request node (not an inline key) — check: `grep -q '"httpHeaderAuth"' n8n/workflows/pancracio-digest.json && grep -q '"httpHeaderAuth"' n8n/workflows/auto-publish.json` → exits 0
- [ ] porfolio/internal-docs/ has a non-trivial doc covering domain-verification scope, API-key strategy, and how a future project onboards to this Resend setup — check: `test -s /Users/santiagomorel/site/personal/porfolio/internal-docs/resend-email-setup.md && grep -qi onboard /Users/santiagomorel/site/personal/porfolio/internal-docs/resend-email-setup.md && grep -qi 'api key' /Users/santiagomorel/site/personal/porfolio/internal-docs/resend-email-setup.md` → exits 0
- [ ] n8n/workflows/pancracio-digest.json exists, is on a daily schedule trigger, and calls /api/ideas?auto_publish=true — check: `test -f n8n/workflows/pancracio-digest.json && grep -q scheduleTrigger n8n/workflows/pancracio-digest.json && grep -q 'auto_publish' n8n/workflows/pancracio-digest.json` → exits 0
- [ ] The digest email's content is correct in both scenarios: nothing due, and a real next-up item (queue state only — the digest does not also report failures, that's the alert branch's job) — judgment call: Reviewer manually triggers the digest workflow once with an empty due set and once with a real queued idea, and confirms each email's content matches the tracker's queue state.
- [ ] auto-publish.json has an added failure-alert branch, and the committed JSON matches what's actually deployed to the n8n instance (this project's usual re-export convention) — judgment call: Reviewer diffs the committed workflow JSON against a fresh export from the live n8n instance and confirms they match, per the pattern used for the bearer-token credential swap (commit fd075e6).
- [ ] A forced pipeline failure (e.g. a temporarily invalid bearer token, or an invalid idea id) results in a real failure-alert email landing in the inbox — judgment call: Reviewer deliberately breaks one run, confirms the idea's status flips to 'failed' and an alert email arrives, then restores the working credential.
- [ ] Both workflow JSONs' email-building nodes construct an HTML body (not a bare string) — check: `grep -q '<html' n8n/workflows/pancracio-digest.json && grep -q '<html' n8n/workflows/auto-publish.json` → exits 0
- [ ] The digest and alert emails visually render as styled HTML in a real mail client, not plain text — judgment call: Reviewer opens both test emails in a mail client and confirms HTML formatting (not a plain-text body).
- [ ] web/app.py is untouched by this project — no new backend endpoint was needed — check: `test -z "$(git diff 58ff3d71388275eb47b7c815231c40f392f19534 -- web/app.py 2>/dev/null)"` → exits 0

## Scope Boundaries

### In Scope

- Verify notify.santiagomorel.dev with Resend — Nothing else can send until the domain is verified; this is the hard dependency for both email paths.
- Create a Pancracio-scoped Resend API key and store it only as an n8n httpHeaderAuth credential — Matches the account's existing per-project credential convention; needed before any workflow can send.
- Document the general Resend setup in porfolio/internal-docs/ — Explicitly the point of doing this once, generally, instead of re-deriving it per project.
- New n8n workflow (pancracio-digest.json): daily schedule -> GET /api/ideas?auto_publish=true -> build digest -> POST to Resend, HTML-formatted — This is the originally-asked-for daily digest and the first real user of the Resend setup.
- Add a failure-alert branch to the existing auto-publish.json workflow, HTML-formatted — User explicitly chose near-real-time failure detection over the simpler, lower-risk 'wait for the daily digest' option; it's an additive branch on the live production workflow, not a rewrite of its existing logic.

### Out of Scope

- Multi-recipient support — Only one recipient (the user) exists today; explicitly deferred.
- A general/reusable notifications framework beyond this one Resend setup and these two emails — User confirmed this is out of scope — build the two emails that are needed, not a framework for hypothetical future ones.
- Any change to how the Instagram publish step itself works — This project is purely about visibility into the existing pipeline, not changing its publishing behavior.
- A new backend endpoint in web/app.py — Research during the interview confirmed the existing /api/ideas?auto_publish=true and status='failed' rows already carry everything both emails need.

### Future Considerations

- Multi-recipient / team distribution of the digest (only relevant if more than one person ever watches the pipeline)
- Richer pipeline-health content in the digest, e.g. a weekly success-rate trend (today's scope is 'what's next' + the separate real-time failure alert; historical analytics is a natural but separate extension)

## Decisions Considered and Rejected

- **One ideation project with two/three sequenced phases, not two separate ideation contracts** — rejected: Splitting the general Resend setup and the Pancracio digest into two separate ideation projects. The digest phase has a hard dependency on the Resend phase, and the combined scope is small enough that two contracts would mostly duplicate ceremony.
- **Verify a dedicated subdomain (notify.santiagomorel.dev) with Resend** — rejected: Verifying the bare santiagomorel.dev root domain. Isolates transactional-email sending reputation from the root domain (which also serves the portfolio site), and matches the account's existing convention of one subdomain per service (bulbasaur.*, pancracio-ideas.*).
- **One Resend API key per project** — rejected: A single shared account-wide API key reused across all future projects. Matches the account's existing per-service credential pattern (separate n8n read/write keys, per-project bearer tokens); smaller blast radius if one key leaks or needs rotating.
- **Document the general Resend setup in porfolio/internal-docs/** — porfolio is the actual repo serving santiagomorel.dev and already holds this domain's other infra notes (deployment-notes.md, internal-info.md) — confirmed by reading its nginx config, which shows it deploys to /var/www/profile on the box serving santiagomorel.dev.
- **Send via a plain n8n HTTP Request node calling Resend's REST API, authenticated with an httpHeaderAuth credential** — rejected: n8n's dedicated Resend node. Confirmed by direct inspection (SSH into the n8n VPS, n8n v2.40.6): no Resend node ships in this n8n install. Matches the exact shape already used by the 'Pancracio Tracker Bearer Token' credential.
- **No new backend endpoint for failure/status data** — rejected: A new /api/failures or /api/pipeline-status endpoint. Confirmed by reading web/app.py: _run_auto_publish_pipeline already sets status='failed' on any exception, so the existing /api/ideas?status=failed (and ?auto_publish=true) already expose everything both emails need.
- **Add an immediate failure-alert branch directly to auto-publish.json, accepting the risk of editing a live, already-fragile production workflow** — rejected: Keep auto-publish.json untouched and only surface failures via the next daily digest (worst case ~24h). User explicitly prioritized faster failure detection (~1h, the next hourly run) over the lower-risk option, given the Sep 25 incident already went unnoticed for hours; the edit is additive (a new branch after the existing HTTP node), not a change to existing logic.
- **Both emails are HTML-formatted** — rejected: Plain-text emails. User wants the digest and alert emails to look nicer than plain text.
- **The daily digest workflow reports queue state only (nothing-queued vs. next-up); failure visibility stays exclusively the alert branch's job** — rejected: Also having the digest's Code node check /api/ideas?status=failed for the last 24h. Plan-critic review (scope-creep and over-engineering lenses, independently) flagged that the failed-item check traced to no stated goal or success criterion, duplicated the dedicated Full-tier alert branch, and edged into the explicitly-deferred 'richer pipeline-health content' future item — removed rather than promoted, since goal 2's ~1h alert already covers failure visibility faster than a daily check could.

## Execution Plan

_Added during Phase 5 handoff. Pick up this contract cold and know exactly how to execute._

### Dependency Graph

```
General Resend Setup
  ├── Daily Digest Workflow  (blocked by General Resend Setup)
  └── Failure Alert Branch  (blocked by General Resend Setup)
```

### Execution Steps

**Run the project** (recommended) — autopilot reads this contract, plans dependency waves, runs independent phases in parallel, and gates on failure:

```bash
/ideation:autopilot docs/ideation/pancracio-monitoring-email/contract.md
```

**Or run it unattended** — a `/goal` is a durability wrapper around the same autopilot run: Claude re-checks the condition before it is allowed to stop, so failures get repaired and re-run. Generated by `contract-gen --print-goal`; this is the only copy of that string:

```
/goal Drive the Pancracio Monitoring Email contract (pancracio-monitoring-email) to completion with /ideation:autopilot.

1. Run `/ideation:autopilot docs/ideation/pancracio-monitoring-email/contract.md`.
2. It dispatches a BACKGROUND workflow. Wait for the completion notification — never start a second autopilot run while one is in flight.
3. Then run the ideation plugin's `scripts/verify.mjs` against `docs/ideation/pancracio-monitoring-email/contract-data.json` and leave its VERIFY line in the conversation. Resolve the plugin's install directory first — `${CLAUDE_PLUGIN_ROOT}/scripts/verify.mjs` is a placeholder, not a shell variable, and bash will not expand it. That line is the only evidence this goal is judged on.
4. If anything failed, fix the spec or the implementation and go back to step 1. Autopilot skips phases that already have commits.

Done when the most recent VERIFY line reads fail=0 and commits=3/3 — or when two consecutive VERIFY lines are identical and still failing, in which case name the failing checks and stop, because a contract whose checks have rotted must not trap the run.
```

**Or run phases manually** in dependency order:

**Strategy**: Hybrid

1. **Phase 1** — General Resend Setup _(blocking)_

   ```bash
   /ideation:execute-spec docs/ideation/pancracio-monitoring-email/spec-phase-1.md
   ```

2. **Phase 2** — Daily Digest Workflow _(blocked by General Resend Setup)_

   ```bash
   /ideation:execute-spec docs/ideation/pancracio-monitoring-email/spec-phase-2.md
   ```

3. **Phase 3** — Failure Alert Branch _(blocked by General Resend Setup)_

   ```bash
   /ideation:execute-spec docs/ideation/pancracio-monitoring-email/spec-phase-3.md
   ```

---

_This contract was generated from brain dump input. Review and approve before proceeding to specification._
