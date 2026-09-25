# Pancracio Auto-Publish Pipeline Contract

**Created**: 2026-09-24
**Readiness**: All 5 gates ready
**Status**: Approved
**Approval**: Interactive review
**Supersedes**: None

## Problem Statement

The Pancracio image-post pipeline is fully manual end-to-end: for every post, the user personally drafts a GPT-4o prompt, pastes it plus a character reference image into ChatGPT's web app, downloads the resulting plate, runs a local Remotion CLI command to composite the quote text, and manually uploads the final image with a caption into Meta Business Suite to schedule it.

This manual cost is the direct reason posting has happened in batches every couple of months rather than on an ongoing daily cadence — the user wants to post about once a day, but doing every step by hand at that frequency isn't sustainable.

The tracker app (built this session) already automates metrics collection after a post is live, but the creation half of the pipeline — idea to published post — remains entirely manual.

## Goals

1. Sustain roughly 1 published Instagram image post per day sourced from image-content ideas entered in the tracker, with zero manual steps between idea creation and the post going live for any such idea flagged auto_publish. (This first end-to-end build proves the mechanism once; ongoing daily-cadence sustainment is then monitored operationally, not gated on a contract-level check.)
2. Preserve the two quality safeguards the manual process relied on — the originality/plagiarism check and the ~6:4 reframe:observational voice-register balance — as automated equivalents rather than dropping them when the human is removed from the loop.

## Success Criteria

- [ ] An idea seeded with only a title and auto_publish=true, content_type=image, results in a real Instagram post published with no manual intervention — check: `curl -s -u $AUTH https://pancracio-ideas.santiagomorel.dev/api/ideas/$TEST_IDEA_ID | jq -e '.status == "posted" and (.ig_media_id != null)'` → exits 0; pair with a human glance at the live Instagram post via its permalink for visual/caption quality
- [ ] The automated originality check (Claude API's native web-search tool) flags a deliberately plagiarized test line before an image is generated for it — check: `curl -sf -u $AUTH -X POST https://pancracio-ideas.santiagomorel.dev/internal/originality-check -d 'line=Start With Why' | jq -e '.flagged == true'` → exits 0
- [ ] The voice-register rolling tracker correctly reflects real counts after several ideas are processed with known registers — check: `for r in reframe reframe observational; do curl -s -u $AUTH -X POST https://pancracio-ideas.santiagomorel.dev/ideas --data-urlencode "title=test-$r-$RANDOM" --data-urlencode "content_type=image" --data-urlencode "register=$r"; done; curl -s -u $AUTH 'https://pancracio-ideas.santiagomorel.dev/api/ideas?register=reframe' | jq -e 'length >= 2'` → exits 0
- [ ] A forced step failure (e.g. an invalid OpenAI credential) marks the idea 'failed' in the tracker and does not retry — check: `curl -s -u $AUTH https://pancracio-ideas.santiagomorel.dev/api/ideas/$TEST_IDEA_ID | jq -e '.status == "failed"'; curl -s -H "X-N8N-API-KEY: $N8N_API_KEY" http://localhost:5678/api/v1/executions?workflowId=$WF_ID | jq -e '(.data | length) == 1'` → both exit 0 after one deliberately-broken run
- [ ] Remotion renders a valid composited PNG on the dedicated render VPS at the correct dimensions, with no dependency on the user's local machine or on charmander — check: `ssh $RENDER_VPS_ALIAS "cd ~/pancracio-render/remotion && ./node_modules/.bin/remotion still PancracioQuote /tmp/test-render.png --props=/tmp/test-props.json --overwrite && identify -format '%wx%h' /tmp/test-render.png"` → command exits 0 and prints 1122x1402 ($RENDER_VPS_ALIAS is the SSH config alias set up in Phase 1 once the new VPS exists)
- [ ] The character reference image (the existing settings-table `character_reference_image` upload, not a new hardcoded path) is present and actually included in the image-generation request — check: `curl -s -u $AUTH https://pancracio-ideas.santiagomorel.dev/settings | grep -q 'character_reference'; ssh charmander-pancracio "grep -q reference_image /home/deploy/pancracio-ai/logs/image-gen-last-request.json"` → both exit 0 — the second asserts the reference was in the actual request, not just present on disk
- [ ] The n8n workflow is exported and committed to git so it's reproducible/auditable outside n8n's own DB if the VPS is rebuilt — check: `git -C /Users/santiagomorel/site/personal/pancracio-ai ls-files n8n/workflows/ | grep -q '\.json$'` → exits 0

## Scope Boundaries

### In Scope

- auto_publish opt-in flag and register field (reframe/observational) on ideas (schema + tracker UI) — Lets the user keep hand-curating some ideas while automating others, and gives the drafting step a place to record which voice register it used.
- Generic JSON endpoints GET /api/ideas (filterable by status/register/auto_publish) and GET /api/ideas/{id} — Small, reusable addition that makes the pipeline's own state machine (and this contract's success criteria) mechanically checkable, instead of scraping HTML.
- n8n provisioned on the VPS via docker-compose, VPS-local only (no public subdomain); reconciles with and supersedes the earlier, conflicting public-subdomain n8n sketch in metrics-automation-checklist.md Phase E — User explicitly asked for n8n by name; its execution-history UI gives visibility into which step failed across four external systems (OpenAI, Anthropic, Instagram, the tracker) in a pipeline nobody is watching live, and reuses a pattern already operated in the job-finder project (/Users/santiagomorel/site/personal/job-finder/n8n/).
- Prompt-drafting via the Anthropic API, encoding the existing plate-prompt template, prop-swap slot, and the text-on-props safety callouts, informed by the rolling register tracker — Replaces the manual 'Claude drafts the prompt' step with the same template already proven to work.
- Automated originality check using the Anthropic API's native web-search tool, run on every drafted quote line before image generation — Directly replaces the human 'search every line' safeguard that already caught one real incident; reuses the same Anthropic credential already needed for prompt-drafting rather than adding a third API provider.
- Background-plate image generation via OpenAI's Images API, reading the existing settings-table character_reference_image (uploaded via the tracker's own /settings page) rather than a new hardcoded path — Replaces the manual ChatGPT-web-app paste step, and reuses the reference-image mechanism the app already ships instead of duplicating it.
- Remotion quote-card compositing running on the VPS (new Chromium/Node renderer dependency there, installed via a one-time manual root session since the `deploy` user has no general sudo), triggered by n8n — A pipeline that depends on the user's laptop being on for rendering isn't actually unattended; installing new system packages is outside deploy's documented scoped-sudo access.
- Caption + hashtag drafting via an LLM call — Completes the content needed to publish; the tracker already has fields for both.
- Regenerate the Instagram access token with instagram_content_publish added (current token only has instagram_business_basic + instagram_business_manage_insights) — Content-publishing requires a scope this project's existing token was deliberately generated without; blocking prerequisite for Phase 4.
- Instagram publish via the Graph API content-publishing endpoints (container + publish), fired at the idea's scheduled_at (default 10am if unset) — Preserves the existing daily-10am posting habit while removing the manual Meta Business Suite step.
- Failure handling: mark the idea 'failed' and stop that idea's run, no automatic retry — A silent retry loop against paid APIs on a real bug could burn money fast; a visible failed state lets the user look at it manually.
- n8n workflow exported to n8n/workflows/ and git-tracked, documented in internal-docs — Reproducible/auditable outside n8n's own DB if the VPS is ever rebuilt.

### Out of Scope

- Video Reel automation (ElevenLabs voice/video pipeline) — A different, much more manual and credit-limited (~2/month) pipeline with heavier creative judgment involved; out of scope for this project.
- Any human approval gate before publish — Explicitly declined by the user in favor of fully unattended operation, with the quality-control tradeoff knowingly accepted.
- Public n8n subdomain / internet-reachable n8n UI or inbound webhook — Not needed for a schedule-trigger-plus-outbound-calls workflow; smaller attack surface without it.
- Automatic retry of failed pipeline steps — Explicitly declined — retries against paid, potentially-misconfigured API calls risk unbounded cost.
- Any change to the manual pipeline for ideas not flagged auto_publish — Ideas the user still wants to hand-curate keep working exactly as documented today.
- A mechanically-verified test of sustained ~1/day cadence over time — Not practical to gate contract approval on; the one end-to-end test proves the mechanism, ongoing cadence is an operational concern monitored after launch.

### Future Considerations

- Public n8n subdomain + a 'trigger now' webhook callable from the tracker UI
- Auto-retry with backoff for genuinely transient errors (rate limits, network blips)
- An optional human-approval toggle, revisited if the automated quality checks prove insufficient in practice
- Extending automation to the video Reel pipeline

## Decisions Considered and Rejected

- **Publish fully unattended, no human approval gate before content goes live** — rejected: Require a one-click approval step after generation before publishing. User explicitly wants zero-touch automation and knowingly accepts the quality-control tradeoff, given the past duplicate-content incident happened even with a human in the loop.
- **Generate background-plate images via OpenAI's Images API** — rejected: Keep pasting prompts into ChatGPT's web app by hand. A manual paste step blocks full automation; user accepted the new API cost and the small risk of a slightly different look than the ChatGPT app produces.
- **Ideas opt in to automation via an explicit auto_publish flag** — rejected: Automate every new idea with no filter. Keeps a manual-curation escape hatch for ideas the user wants to handle by hand.
- **Run Remotion compositing on the VPS** — rejected: Webhook back to the user's Mac to render locally. A pipeline that only runs when the user's laptop happens to be on isn't actually unattended.
- **Keep n8n VPS-local only, no public subdomain** — rejected: Give n8n its own public subdomain with nginx+TLS+basic auth, matching the tracker (and matching the earlier, now-superseded sketch in metrics-automation-checklist.md Phase E). No inbound webhook is required for a schedule-trigger-plus-outbound-calls workflow; less setup and smaller attack surface. This contract's n8n plan supersedes that checklist's Phase E sketch rather than running a second, conflicting effort.
- **On any pipeline-step failure, mark the idea 'failed' and stop — no retry** — rejected: Auto-retry the failed step 2-3 times before flagging. Avoids silently burning paid API calls retrying a non-transient bug.
- **Run the originality check using the Anthropic API's native web-search tool** — rejected: LLM self-check only, no automated check, or a separate search API (Serper/Bing/Google). Directly replaces the human safeguard that already caught one real incident; reusing the Anthropic credential already needed for prompt-drafting avoids adding a third external API provider just for this.
- **Track rolling voice-register counts and explicitly instruct the drafting model toward the ~6:4 target** — rejected: Weighted random register pick with no tracking. Matches the documented register-balance intent precisely for a small added DB cost; a random pick can drift noticeably over a small batch.
- **Target roughly 1 published post per day** — rejected: Match the historical batch-every-couple-months pace. Automation's whole value is removing the friction that made batching necessary in the first place.
- **Publish at the idea's scheduled_at, defaulting to 10am when unset** — rejected: Publish immediately as soon as each idea's pipeline finishes. Preserves the existing daily-10am posting convention rather than posting at arbitrary times.
- **Use n8n (docker-compose, VPS-local) rather than a cron script on the existing systemd pattern already proven for the tracker** — rejected: A cron-triggered Python script calling the tracker API directly, reusing the tracker's own systemd deployment convention. User explicitly asked for n8n by name; its execution-history UI gives real debugging value across a 4-external-system pipeline (OpenAI, Anthropic, Instagram, tracker) that runs unattended, and reuses a pattern already operated in the job-finder project.
- **Reuse the tracker's existing settings-table character_reference_image upload for the OpenAI reference image, instead of a new hardcoded server path** — rejected: Copy the reference image to a new fixed path like /home/deploy/pancracio-ai/character-ref/. The app already ships this mechanism with its own upload UI at /settings; introducing a parallel path would duplicate it for no reason.
- **Run n8n and the Remotion rendering step together on a new, separate VPS, leaving charmander untouched** — rejected: Run n8n (and/or Remotion rendering) on charmander alongside the tracker app. charmander is a 1-core/~2GB box already running the tracker, Ardu's backend, Ollama, and PostgreSQL; the actual resource risk is headless-Chromium rendering, not n8n itself. Colocating the render step with n8n avoids an extra network hop and keeps charmander doing only what it already does. The final composited image is uploaded back to the tracker's existing image-upload endpoint, so this needs no new tracker-side storage.

## Execution Plan

_Added during Phase 5 handoff. Pick up this contract cold and know exactly how to execute._

### Dependency Graph

```
VPS infrastructure & credentials
  └── Prompt drafting & image generation  (blocked by VPS infrastructure & credentials)
        └── Compositing & caption  (blocked by Prompt drafting & image generation)
              └── Publishing, scheduling & failure handling  (blocked by Compositing & caption)
```

### Execution Steps

**Run the project** (recommended) — autopilot reads this contract, plans dependency waves, runs independent phases in parallel, and gates on failure:

```bash
/ideation:autopilot docs/ideation/pancracio-auto-publish/contract.md
```

**Or run it unattended** — a `/goal` is a durability wrapper around the same autopilot run: Claude re-checks the condition before it is allowed to stop, so failures get repaired and re-run. Generated by `contract-gen --print-goal`; this is the only copy of that string:

```
/goal Drive the Pancracio Auto-Publish Pipeline contract (pancracio-auto-publish) to completion with /ideation:autopilot.

1. Run `/ideation:autopilot docs/ideation/pancracio-auto-publish/contract.md`.
2. It dispatches a BACKGROUND workflow. Wait for the completion notification — never start a second autopilot run while one is in flight.
3. Then run the ideation plugin's `scripts/verify.mjs` against `docs/ideation/pancracio-auto-publish/contract-data.json` and leave its VERIFY line in the conversation. Resolve the plugin's install directory first — `${CLAUDE_PLUGIN_ROOT}/scripts/verify.mjs` is a placeholder, not a shell variable, and bash will not expand it. That line is the only evidence this goal is judged on.
4. If anything failed, fix the spec or the implementation and go back to step 1. Autopilot skips phases that already have commits.

Done when the most recent VERIFY line reads fail=0 and commits=4/4 — or when two consecutive VERIFY lines are identical and still failing, in which case name the failing checks and stop, because a contract whose checks have rotted must not trap the run.
```

**Or run phases manually** in dependency order:

**Strategy**: Sequential

1. **Phase 1** — VPS infrastructure & credentials _(blocking)_

   ```bash
   /ideation:execute-spec docs/ideation/pancracio-auto-publish/spec-phase-1.md
   ```

2. **Phase 2** — Prompt drafting & image generation _(blocking)_

   ```bash
   /ideation:execute-spec docs/ideation/pancracio-auto-publish/spec-phase-2.md
   ```

3. **Phase 3** — Compositing & caption _(blocking)_

   ```bash
   /ideation:execute-spec docs/ideation/pancracio-auto-publish/spec-phase-3.md
   ```

4. **Phase 4** — Publishing, scheduling & failure handling _(blocking)_

   ```bash
   /ideation:execute-spec docs/ideation/pancracio-auto-publish/spec-phase-4.md
   ```

---

_This contract was generated from brain dump input. Review and approve before proceeding to specification._
