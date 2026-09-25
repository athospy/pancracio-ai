# Implementation Spec: Pancracio Auto-Publish Pipeline - Phase 4

**Contract**: ./contract.md
**PRD**: none
**Estimated Effort**: L

## Technical Approach

This phase wires Phases 2 and 3's individual steps into one thing n8n can trigger per idea, adds
the actual Instagram publish call, and makes the whole thing run on a schedule with clean
failure handling. It also connects back into the metrics-tracking system built earlier this
project: a successfully auto-published idea creates a `posts` row exactly like the manual
`mark_posted()` flow already does, so `/api/posts/tracked-media` and the existing
"Refresh from Instagram" button keep working uniformly regardless of how a post got published.

The key architectural decision made in this phase (not earlier, because it only became clear once
Phases 2-3's granular endpoints existed): rather than have n8n itself orchestrate five separate
HTTP calls per idea with branching error-handling in its visual editor, this phase adds **one**
orchestrating endpoint, `POST /internal/run-pipeline/{idea_id}`, that calls Phase 2 and 3's
functions directly in-process (not over HTTP — they're already plain Python functions) and
handles success/failure as a single unit. n8n's job shrinks to: on a schedule, ask the tracker
which ideas are due, then call this one endpoint once per idea. This keeps all the actual
failure-handling logic in one place (testable with `python3 -m py_compile` and curl, per every
prior phase) instead of spread across n8n nodes that are harder to review as a diff.

Instagram's Content Publishing API needs the final image reachable at a public URL it fetches
itself (not a file upload) — confirmed this phase that `web/app.py`'s `/static` mount is
**not** behind the app's HTTP Basic Auth (`StaticFiles` is mounted directly, `check_auth` is only
applied via `Depends()` on individual routes), so the existing
`https://pancracio-ideas.santiagomorel.dev/static/uploads/...` URLs are already fetchable by
Instagram's servers with no new exposure needed. This is a pre-existing property of the app, not
something this phase changes — named here because it's exactly what makes the publish call
straightforward.

## Decisions Considered and Rejected

- **On any pipeline-step failure, mark the idea 'failed' and stop — no retry** —
  rejected: auto-retry 2-3 times before flagging. Avoids silently burning paid API calls retrying
  a non-transient bug.
- **Publish at the idea's `scheduled_at`, defaulting to 10am when unset** — rejected: publish
  immediately as soon as each idea's pipeline finishes.
- **Target roughly 1 published post per day** — relevant here as the schedule-trigger
  cadence.
- **Keep n8n VPS-local only, no public subdomain** — relevant here since the schedule trigger
  and all HTTP calls it makes are entirely internal to the VPS (n8n → `localhost` tracker app)
  plus outbound calls to Instagram/OpenAI/Anthropic — no inbound traffic needed.

## Feedback Strategy

**Inner-loop command**: `curl -s -u $AUTH -X POST https://pancracio-ideas.santiagomorel.dev/internal/run-pipeline/$TEST_IDEA_ID | jq .`

**Playground**: The orchestrating endpoint itself, called directly with curl against a seeded test
idea — exercises the full chain without needing n8n running at all. n8n is added last, as a
thin scheduler calling this one endpoint.

**Why this approach**: Every failure mode this phase cares about (a bad credential, a timeout, an
originality flag) is exercised the same way whether n8n calls the endpoint or curl does —
building and debugging the orchestrator directly is faster than iterating through n8n's UI for
every test.

## File Changes

### Modified Files

| File Path   | Changes                                                                                                     |
| ------------ | ------------------------------------------------------------------------------------------------------------- |
| `web/app.py` | Add `_default_scheduled_at()`, `_publish_to_instagram()`, `_run_auto_publish_pipeline()`, `POST /internal/run-pipeline/{idea_id}`, extend `GET /api/ideas` with a `due=true` filter. |
| `internal-docs/ideas-tracker/metrics-automation-checklist.md` | Mark Phase E as superseded by this project (started in Phase 1, finished here). |

### New Files

| File Path                                                        | Purpose                                                            |
| -------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `n8n/workflows/auto-publish.json`                                     | The exported n8n workflow: schedule trigger → fetch due ideas → loop → run-pipeline. |
| `internal-docs/ideas-tracker/auto-publish-pipeline.md`                | End-to-end documentation of the whole system, all four phases, for future reference. |

## Implementation Details

### `due=true` filter on `GET /api/ideas`

**Overview**: Extends Phase 1's endpoint so the date logic (what counts as "due now") lives in
the tracker app, not duplicated in n8n's node editor.

```python
if due:
    query += " AND auto_publish = 1 AND status = 'idea' AND (scheduled_at IS NULL OR scheduled_at <= datetime('now'))"
```

**Implementation steps**:

1. Add the `due: Optional[bool]` param and the clause above to `/api/ideas`.

**Feedback loop**:

- **Playground**: seeded test DB with ideas at various `scheduled_at` values (past, future, null).
- **Experiment**: past and null `scheduled_at` with `auto_publish=1` should return; future
  `scheduled_at` should not; `auto_publish=0` should never return regardless of `scheduled_at`.
- **Check command**: `curl -s -u test:test "http://127.0.0.1:8123/api/ideas?due=true" | jq length`

### Default `scheduled_at` (10am)

**Overview**: When an idea is flagged `auto_publish=1` without an explicit `scheduled_at`,
compute and store "next 10am" immediately, rather than leaving it ambiguous.

```python
def _default_scheduled_at() -> str:
    now = datetime.now()
    ten_am = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if now >= ten_am:
        ten_am += timedelta(days=1)
    return ten_am.isoformat()
```

**Implementation steps**:

1. Call this from `update_idea()` (and wherever `auto_publish` can be set) whenever `auto_publish`
   is being set to true and `scheduled_at` is blank.

**Feedback loop**:

- **Playground**: call the function directly at different times of day.
- **Experiment**: called at 9am and at 11am on the same day — first should return today's
  10am, second tomorrow's.
- **Check command**: a quick Python REPL check, no HTTP involved (trivial, pure function).

### Instagram publish

**Pattern to follow**: this session's existing `_fetch_ig_insights()` in `web/app.py` for the
general shape of an authenticated Graph API call using `IG_ACCESS_TOKEN` from the environment.

**Overview**: Two-step Graph API call — create a media container, then publish it.

```python
def _publish_to_instagram(idea: dict) -> dict:
    """Returns {"ig_media_id": str, "permalink": str}"""
    token = os.environ["IG_ACCESS_TOKEN"]  # re-consented, publish-scoped token from Phase 1
    image_url = f"https://pancracio-ideas.santiagomorel.dev{idea['final_image_path']}"
    caption = f"{idea['caption']}\n\n{idea['hashtags']}"
    container = _ig_post("/me/media", {"image_url": image_url, "caption": caption, "access_token": token})
    creation_id = container["id"]
    publish = _ig_post("/me/media_publish", {"creation_id": creation_id, "access_token": token})
    media_id = publish["id"]
    permalink = _ig_get(f"/{media_id}", {"fields": "permalink", "access_token": token})["permalink"]
    return {"ig_media_id": media_id, "permalink": permalink}
```

**Key decisions**:

- Uses the Instagram-scoped `/me/media` endpoint (consistent with how `_fetch_ig_insights()`
  already addresses the account as `/me` via `graph.instagram.com`), not the Business Account ID
  directly — matches this session's own documented "use `user_id` for `/media` list, but the
  Instagram-Login token's own `/me` alias works for posting to itself" pattern.
- On success, also `INSERT INTO posts` (platform='instagram', `post_url`=permalink,
  `ig_media_id`=media_id, `posted_at`=now) — the same table the manual `mark_posted()` flow
  writes to, so metrics refresh (`/posts/{id}/refresh`, built earlier this project) works
  identically for auto-published and manually-published posts.

**Implementation steps**:

1. Implement `_ig_post()`/`_ig_get()` small helpers (or inline, matching `_fetch_ig_insights()`'s
   existing style) using `urllib` — no new HTTP client needed beyond what Phase 2 added for
   OpenAI's multipart upload, since these are simple form-encoded POSTs.
2. Implement `_publish_to_instagram()`.
3. On success, insert the `posts` row and update the idea's `status` to `'posted'`.

**Feedback loop**:

- **Playground**: the real Instagram API, called directly — there's no sandbox for this, so
  the first real test *is* a real post. Coordinate with the user before running it the first time.
- **Experiment**: one real end-to-end run against a real seeded idea (the contract's own success
  criterion).
- **Check command**: `curl -s -u $AUTH https://pancracio-ideas.santiagomorel.dev/api/ideas/$ID | jq -e '.status == "posted"'`

### Orchestrator: `POST /internal/run-pipeline/{idea_id}`

**Overview**: Calls Phase 2/3's functions in sequence; any exception marks the idea `'failed'`
and stops — no retry, no partial-success ambiguity.

```python
@app.post("/internal/run-pipeline/{idea_id}")
def run_pipeline(idea_id: int, _: None = Depends(check_auth)) -> dict:
    idea = _get_idea(idea_id)
    try:
        counts = _get_recent_register_counts()
        draft = _draft_plate_prompt(idea, counts)
        check = _check_originality(draft["quote_line"])
        if check["flagged"]:
            raise RuntimeError(f"originality check flagged: {check['reason']}")
        layout_path = _generate_plate_image(idea_id, draft["prompt"])
        idea = {**idea, "layout_image_path": layout_path, "quote_line": draft["quote_line"],
                "register": draft["register"]}
        final_path = _render_post_image(idea)
        caption = _draft_caption(idea)
        idea = {**idea, "final_image_path": final_path, **caption}
        result = _publish_to_instagram(idea)
        # ... persist final_image_path, caption, hashtags, status='posted', and the posts row
        return {"status": "posted", **result}
    except Exception as e:
        with _connect() as conn:
            conn.execute(
                "UPDATE ideas SET status = 'failed', updated_at = datetime('now') WHERE id = ?",
                (idea_id,),
            )
        raise HTTPException(status_code=500, detail=f"pipeline failed: {e}") from e
```

**Key decisions**:

- One `try`/`except` around the whole chain, not per-step — matches the contract's
  fail-and-stop decision exactly (no partial retry of just the failed step).
- Every intermediate write (layout path, final path, caption) happens only in local variables
  until the very end on success — a failure partway through leaves the idea's DB row
  unchanged except for the `'failed'` status, so there's no half-written state to reason about on
  a later manual look.
- n8n's only job per idea becomes one HTTP call; success/failure is entirely legible from the
  idea's own `status` afterward.

**Implementation steps**:

1. Implement the function above, wiring in the real Phase 2/3 functions.
2. Confirm the n8n execution-log assertion from the contract's no-retry success criterion actually
   holds — n8n itself must not be configured to retry the HTTP Request node on failure
   (n8n's own per-node retry setting defaults to off, but verify explicitly).

**Feedback loop**:

- **Playground**: `POST /internal/run-pipeline/{id}` against seeded test ideas.
- **Experiment**: (a) a normal idea — full success; (b) an idea whose drafted line is forced
  to a known book title — fails at the originality check, no image ever generated; (c) a
  temporarily-invalid `IG_ACCESS_TOKEN` — fails at the publish step, `layout_image_path`
  and `final_image_path` are still saved (generation succeeded, only publish failed) but `status`
  is `'failed'`.
- **Check command**: `curl -s -u test:test -X POST http://127.0.0.1:8123/internal/run-pipeline/2 | jq .`

### n8n workflow

**Overview**: Schedule Trigger (e.g. hourly — frequent enough to catch a 10am `scheduled_at`
without needing minute-level precision) → HTTP Request `GET /api/ideas?due=true` →
Split-in-Batches/Loop → HTTP Request `POST /internal/run-pipeline/{{ $json.id }}` per item,
with the node's own retry-on-fail setting explicitly left off.

**Implementation steps**:

1. Build the workflow in the n8n UI (via the SSH tunnel from Phase 1).
2. Test it against one real due idea.
3. Export via n8n's "Download" workflow-JSON feature to `n8n/workflows/auto-publish.json`, commit
   to git — matching `job-finder/n8n/workflows/*.json`'s convention.
4. Activate the workflow (n8n's own active/inactive toggle).

## Data Model

No new schema beyond Phase 1's `auto_publish`, `register`, and `'failed'` status — this phase
only adds application logic and one new query filter (`due=true`) on the existing table.

## API Design

### New/Modified Endpoints

| Method | Path                              | Description                                                        |
| ------ | ----------------------------------- | ------------------------------------------------------------------------ |
| `GET`  | `/api/ideas?due=true`               | Ideas ready for the pipeline right now (extends Phase 1's endpoint).       |
| `POST` | `/internal/run-pipeline/{idea_id}`  | Runs the full generate-composite-caption-publish chain for one idea.       |

## Testing Requirements

### Manual Testing

- [ ] `due=true` correctly includes/excludes ideas based on `scheduled_at` and `auto_publish`.
- [ ] `_default_scheduled_at()` computes the right day depending on current time vs. 10am.
- [ ] Full pipeline run against one real seeded idea publishes an actual Instagram post; confirm
      via the post's permalink.
- [ ] Originality-flagged idea halts before any image is generated; idea ends up `'failed'`.
- [ ] Invalid-credential test halts at publish; confirm `layout_image_path`/`final_image_path`
      were still saved (generation succeeded) but the idea is `'failed'` and no `posts` row exists.
- [ ] n8n execution log shows exactly one attempt per idea per run — no retry.
- [ ] `n8n/workflows/auto-publish.json` is committed and matches what's actually active in n8n.

## Error Handling

| Error Scenario                                | Handling Strategy                                                          |
| ------------------------------------------------ | -------------------------------------------------------------------------------- |
| Any step in the pipeline raises                    | Idea marked `'failed'`, exception surfaces as the endpoint's 500 response; n8n does not retry. |
| Instagram publish succeeds but the permalink fetch fails | Idea is technically posted (media exists) but not recorded as such — named as an accepted edge case; a manual `/posts/{id}/refresh`-style reconciliation would need to be run by hand if this happens (not built in this phase). |
| n8n itself is down when a scheduled run would fire  | That run simply doesn't happen; the next scheduled run picks up the still-due idea (idempotent — `due=true` only matches `status='idea'`, and a truly-posted idea never reappears). |

## Failure Modes

| Component                | Failure Mode                                              | Trigger                                       | Impact                                                        | Mitigation                                                              |
| --------------------------- | -------------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| Instagram publish            | Container creation succeeds, `media_publish` fails (rate limit, transient API issue) | Instagram-side transient error                 | Idea marked `'failed'` even though partial progress was made; no retry per the accepted tradeoff | User manually reviews `'failed'` ideas and can re-trigger `/internal/run-pipeline/{id}` by hand once the underlying issue clears — the endpoint is idempotent-ish for this case since it regenerates content again (small added API cost, acceptable at ~1/day volume) |
| Publish permalink mismatch    | The permalink-fetch edge case above                          | Rare API inconsistency                          | A real post exists without a tracked `post_url`/`ig_media_id`      | Accepted gap for this phase; visible on Instagram itself, catchable by periodic manual review |
| Schedule drift                | n8n's hourly trigger means a 10am-scheduled post could go out anytime in the 10-11am window | Trigger granularity vs. exact-time expectation | Minor — posting time isn't exact to the minute               | Acceptable given the manual process's own habit was "around 10am," not to-the-second; tighten the trigger interval later if this matters more than expected |

## Validation Commands

```bash
cd web && python3 -m py_compile app.py
curl -s -u $AUTH "https://pancracio-ideas.santiagomorel.dev/api/ideas?due=true" | jq .
curl -s -u $AUTH -X POST https://pancracio-ideas.santiagomorel.dev/internal/run-pipeline/$TEST_IDEA_ID | jq .
git -C /Users/santiagomorel/site/personal/pancracio-ai ls-files n8n/workflows/ | grep -q '\.json$'
```

## Rollout Considerations

- **Feature flag**: `auto_publish` itself is the flag — no idea is touched by this pipeline
  unless explicitly opted in.
- **Monitoring**: check `GET /api/ideas?status=failed` periodically (or add it to the tracker's
  main page filters, already supported) to catch failures without needing to watch n8n directly.
- **Alerting**: none built in this phase — out of scope; the user checks the tracker
  periodically. A future addition (not this phase) could have `run-pipeline` notify on failure.
- **Rollback plan**: deactivate the n8n workflow to stop all automation instantly with zero code
  change; individual ideas can have `auto_publish` unset to exclude them without touching the
  workflow at all.

## Open Items

- [ ] First real end-to-end run is a real Instagram post — coordinate timing with the user
      rather than running it unannounced.
- [ ] Decide whether `run-pipeline`'s "regenerate from scratch on manual re-trigger" behavior
      (Failure Modes, first row) is acceptable, or whether a cheaper "resume from last successful
      step" mode is worth the added complexity — revisit if failures turn out to be common
      enough for the regeneration cost to matter.
- [x] **Resolved 2026-09-25**: this section's `due=true` pseudocode (`scheduled_at <=
      datetime('now')`) is a real bug, not just illustrative — verified against the live
      production DB that a raw string comparison between `scheduled_at`'s 'T'-separated storage
      format and SQLite's space-separated `datetime('now')` silently evaluates "not yet due" for
      any same-day time, regardless of whether it's actually passed. Implemented as
      `datetime(scheduled_at) <= datetime('now')` instead (both sides normalized) — confirmed
      correct against 5 seeded edge cases.
- [x] **Resolved 2026-09-25**: `_default_scheduled_at()` uses `isoformat(timespec="minutes")`
      rather than the pseudocode's full `isoformat()` (which includes seconds) — deliberate, so
      the value round-trips cleanly through the edit form's `<input type="datetime-local">`
      (that input type doesn't carry seconds).

---

_This spec is ready for implementation. Follow the patterns and validate at each step._
