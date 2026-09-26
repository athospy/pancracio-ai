# Implementation Spec: Pancracio Monitoring Email - Phase 1: General Resend Setup

**Contract**: ./contract.md
**Estimated Effort**: S

## Technical Approach

Verify a dedicated subdomain (`notify.santiagomorel.dev`) with Resend, create one API key scoped
to this project, and wire that key into n8n as a credential the later workflows reference by
id/name — never as a value committed to git. In parallel, write the reusable "how to add Resend
to any future project on this domain" doc in `porfolio/internal-docs/`, since `porfolio` is the
repo that actually serves `santiagomorel.dev` (confirmed via its nginx config in
`porfolio/internal-docs/internal-info.md`) and already holds this domain's other infra notes.

This phase is almost entirely live, external-system work — a Resend account signup, DNS records
on santiagomorel.dev's DigitalOcean-hosted nameservers, and n8n's REST API against the deployed
instance on `bulbasaur.santiagomorel.dev`. None of it can be completed or verified end-to-end from
a local build session alone (per this project's own recorded learning about phases that depend on
live deployments or external credentials — see `docs/ideation/learnings.md`, 2026-09-25 entry).
The spec's job is to make every manual step explicit enough that whoever executes it (human or
agent with live access) doesn't have to improvise the sequence.

**Two prerequisites, name them before starting**:

1. **DigitalOcean access.** santiagomorel.dev's nameservers are DigitalOcean's
   (`ns1/ns2/ns3.digitalocean.com`) — adding Resend's verification records needs DigitalOcean
   console or API access for this domain. This is not yet documented anywhere in
   `internal-docs/credentials/`, unlike every other external credential this project uses
   (Instagram, OpenAI, Anthropic, n8n). Confirm access exists before starting; if a DigitalOcean
   API token gets created for this, document it in `internal-docs/credentials/README.md` following
   the existing convention.
2. **n8n write access.** Creating the Resend credential needs n8n's write-scoped API key
   (`pancracio-auto-publish-workflow-mgmt`, see `internal-docs/ideas-tracker/auto-publish-credentials.md`) —
   the read-only key returns 403 on writes (confirmed empirically in that doc). That key expires
   **2026-10-25**. If this phase starts after that date, generate a fresh write-scoped key first
   (Settings → n8n API in the n8n UI, same steps as the existing key).

## Decisions Considered and Rejected

- **Verify a dedicated subdomain (`notify.santiagomorel.dev`)** — rejected: verifying the bare
  `santiagomorel.dev` root domain. Isolates transactional-email sending reputation from the root
  domain (which also serves the portfolio site), and matches the account's existing convention of
  one subdomain per service (`bulbasaur.*`, `pancracio-ideas.*`).
- **One Resend API key per project** — rejected: a single shared account-wide key reused across
  all future projects. Matches the account's existing per-service credential pattern; smaller
  blast radius if one key leaks or needs rotating.
- **Document the general Resend setup in `porfolio/internal-docs/`** — no concrete alternative was
  seriously on the table. `porfolio` is the repo that actually serves `santiagomorel.dev` and
  already holds this domain's other infra notes (`deployment-notes.md`, `internal-info.md`).
- **Plain n8n HTTP Request node + `httpHeaderAuth` credential, not a dedicated Resend node** —
  confirmed by directly inspecting the n8n VPS (SSH, n8n v2.40.6): no Resend node ships in this
  install. This decision is Phase 2/3's concern more than Phase 1's, but the credential this phase
  creates must be an `httpHeaderAuth` type (Bearer key) to match.

## Feedback Strategy

**Inner-loop command**: `dig TXT notify.santiagomorel.dev +short` (DNS propagation) and
`curl -s -H "Authorization: Bearer $RESEND_API_KEY" https://api.resend.com/domains | jq '.data[] | select(.name=="notify.santiagomorel.dev")'`
(Resend's own view of verification status).

**Playground**: Resend's dashboard (for adding the domain and creating the key) plus a terminal
for DNS record management and the curl checks above. No dev server, no test suite — this phase
has no application code.

**Why this approach**: Every step here is state living in an external system (DNS, Resend,
n8n's live credential store) — the fastest feedback is asking each system directly rather than
inferring state from code.

## File Changes

### New Files

| File Path | Purpose |
| --- | --- |
| `porfolio/internal-docs/resend-email-setup.md` | Reusable doc: domain-verification scope decision, API-key-per-project strategy, and step-by-step instructions for a future project to get its own Resend API key + n8n credential without re-verifying the domain. |

### Modified Files

| File Path | Changes |
| --- | --- |
| `internal-docs/ideas-tracker/auto-publish-credentials.md` | Add a new section documenting the Resend API key: where it lives (n8n credential only, never in git), the credential's id/name once created, and a pointer to `porfolio/internal-docs/resend-email-setup.md` for the general pattern. |
| `internal-docs/credentials/README.md` | If a DigitalOcean API token was created for DNS automation, document it here following the existing per-credential convention. Skip this file if DNS records were added manually through the DigitalOcean dashboard instead. |

No changes to any file inside `remotion/`, `web/`, or `n8n/workflows/` in this phase — this phase
only sets up the account/DNS/credential layer that Phases 2 and 3 build on.

## Implementation Details

### Resend account + domain verification

**Overview**: Sign up for Resend (if not already), add `notify.santiagomorel.dev` as a domain,
and add the DNS records Resend provides to santiagomorel.dev's DigitalOcean DNS zone.

**Key decisions**:

- Subdomain, not root domain (see Decisions above).
- Check Resend's own current best-practice guidance for the exact record set (MX/SPF/DKIM) during
  the build rather than assuming a fixed set — Resend's requirements can change and the doc
  originating this project deliberately left this to "confirm during the build."

**Implementation steps**:

1. In Resend's dashboard, add domain `notify.santiagomorel.dev`.
2. Copy the DNS records Resend shows (typically MX + TXT for SPF + one or more TXT/CNAME for
   DKIM) into DigitalOcean's DNS management for `santiagomorel.dev`, as records under the
   `notify` subdomain.
3. Wait for propagation, then trigger verification in Resend's dashboard.
4. Confirm via `curl`/dashboard that the domain's status reads "Verified" — this is success
   criterion 1 and cannot be faked by a local check.

**Feedback loop**:

- **Playground**: Resend's dashboard + terminal.
- **Experiment**: `dig TXT notify.santiagomorel.dev +short` immediately after adding records
  (expect the SPF/DKIM TXT values to show up, possibly after a propagation delay), then repeat
  after Resend's verification step.
- **Check command**: `curl -s -H "Authorization: Bearer $RESEND_API_KEY" https://api.resend.com/domains | jq '.data[] | select(.name=="notify.santiagomorel.dev") | .status'`
  — expect `"verified"`.

### Resend API key + n8n credential

**Pattern to follow**: `internal-docs/ideas-tracker/auto-publish-credentials.md`'s "Pancracio
Tracker Bearer Token" section — same shape (an `httpHeaderAuth` n8n Credential holding
`Authorization: Bearer <key>`, created live via n8n's REST API, referenced by id/name from
workflow JSON, never embedded in git).

**Overview**: Create one Resend API key scoped to this project (Resend supports multiple named
keys per account), then create a matching n8n credential.

**Key decisions**:

- Per-project key, not a shared account-wide key (see Decisions above) — name it something like
  `pancracio-monitoring` in Resend's dashboard so a future project's key is visibly separate.

**Implementation steps**:

1. In Resend's dashboard, create an API key named for this project (e.g.
   `pancracio-monitoring`), full send permission, scoped to the verified domain if Resend's UI
   offers per-domain scoping.
2. Via n8n's write-scoped REST API (`POST /api/v1/credentials`, same mechanism used for the
   tracker's bearer-token credential), create an `httpHeaderAuth` credential named e.g.
   `"Resend API Key"` holding header `Authorization: Bearer <key>`. Do this via the API, not by
   hand-typing into the exported workflow JSON — the credential id/value must never appear in git.
3. Record the credential's id/name (not its value) in
   `internal-docs/ideas-tracker/auto-publish-credentials.md`, matching how the bearer-token
   credential's id (`F8WOkbGlhwKzrIOd`) is documented there today.

**Feedback loop**:

- **Playground**: n8n's REST API via curl, or the n8n UI's Credentials page.
- **Experiment**: after creating the credential, do a one-off `curl -X POST
  https://api.resend.com/emails` using the same key value directly (test send to yourself) to
  confirm the key itself works before wiring it into any workflow.
- **Check command**: `curl -s -H "X-N8N-API-KEY: $N8N_KEY" http://localhost:5678/api/v1/credentials | jq '.data[] | select(.name | test("Resend"))'`
  (run from the render VPS, or via the SSH tunnel) — expect one matching entry.

### Reusable setup doc

**Overview**: `porfolio/internal-docs/resend-email-setup.md`, written so a future, unrelated
project on this domain can onboard without re-deriving anything.

**Key decisions**: None beyond what's already decided above — this is documentation, not code.

**Implementation steps**:

1. Write the doc covering: why `notify.santiagomorel.dev` (not the root domain) was chosen, the
   per-project API key strategy and why, and a step-by-step "how a new project gets its own key"
   section (create a named key in Resend's dashboard scoped to the already-verified domain, no
   new DNS work needed).
2. Cross-link it from `internal-docs/ideas-tracker/auto-publish-credentials.md` (this project's
   own credential doc) so a reader lands on the general pattern from either side.

No feedback loop needed — this is a documentation file, not iterative code.

## Testing Requirements

### Manual Testing

- [ ] Resend dashboard shows `notify.santiagomorel.dev` as "Verified".
- [ ] `dig TXT notify.santiagomorel.dev +short` and `dig MX notify.santiagomorel.dev +short` show
      the records Resend provided.
- [ ] A test send via `curl -X POST https://api.resend.com/emails` with the new key, `from:
      test@notify.santiagomorel.dev`, lands in the inbox.
- [ ] n8n's Credentials page (or `GET /api/v1/credentials`) shows the new Resend credential, and
      no raw key value appears in `git log -p` or the working tree (success criterion 2).
- [ ] `porfolio/internal-docs/resend-email-setup.md` exists and covers domain scope, key strategy,
      and onboarding steps (success criterion 5).

## Failure Modes

| Component | Failure Mode | Trigger | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| DNS verification | Records added to the wrong zone or with a typo | Manual DNS entry in DigitalOcean | Resend never shows "Verified"; Phases 2/3 have nothing to send with | Use the curl/dig check above before moving on; DigitalOcean's DNS UI shows the zone name to catch a wrong-domain mistake |
| n8n credential creation | Write-scoped API key expired (2026-10-25) | Phase starts after that date | `POST /api/v1/credentials` returns 403/401 | Generate a fresh write-scoped key first (named prerequisite above) |
| Resend API key | Key created without send permission or wrong domain scope | Misconfigured in Resend's dashboard | Test send fails with a permission error, not a DNS error | The one-off curl test-send in the credential step catches this before any workflow is built on top of it |

## Validation Commands

```bash
# Domain verification status
curl -s -H "Authorization: Bearer $RESEND_API_KEY" https://api.resend.com/domains | jq '.data[] | select(.name=="notify.santiagomorel.dev")'

# n8n credential exists
curl -s -H "X-N8N-API-KEY: $N8N_KEY" http://localhost:5678/api/v1/credentials | jq '.data[] | select(.name | test("Resend"))'

# No key ever committed
git log --all -p | grep -E "re_[A-Za-z0-9]{20,}" ; echo "exit code: $?"   # expect exit code 1 (no match)

# Doc exists and covers the right topics
test -s /Users/santiagomorel/site/personal/porfolio/internal-docs/resend-email-setup.md \
  && grep -qi onboard /Users/santiagomorel/site/personal/porfolio/internal-docs/resend-email-setup.md \
  && grep -qi "api key" /Users/santiagomorel/site/personal/porfolio/internal-docs/resend-email-setup.md \
  && echo OK
```

## Rollout Considerations

- **Monitoring**: none needed for this phase itself — Phase 2/3 are what get monitored.
- **Rollback plan**: if verification goes wrong, Resend lets you remove and re-add a domain; no
  DNS record here is destructive to existing santiagomorel.dev services (the domain currently has
  zero mail records, confirmed at intake).

## Open Items

- [ ] Confirm DigitalOcean console/API access for santiagomorel.dev exists before starting.
- [ ] Confirm the n8n write-scoped key is still valid (expires 2026-10-25) or regenerate it first.
- [ ] Confirm Resend's current documented DNS-record requirements at build time rather than
      assuming the MX+SPF+DKIM set described above is still exactly right.

---

_This spec is ready for implementation. Follow the patterns and validate at each step._
