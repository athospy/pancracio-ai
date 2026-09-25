# Implementation Spec: Pancracio Auto-Publish Pipeline - Phase 2

**Contract**: ./contract.md
**PRD**: none
**Estimated Effort**: L

## Technical Approach

This phase builds the two AI-generation steps that replace the manual "draft a prompt in Claude,
paste into ChatGPT" work: an Anthropic API call that drafts the GPT-4o-style plate prompt (reusing
the exact template documented in `internal-docs/pipeline/chatgpt-image-post-prompt.md`), and an
OpenAI Images API call that turns that prompt plus the character reference image into the
background plate. Sandwiched between them is the originality check — built as a standalone,
independently-callable function specifically so it can be verified in isolation (the success
criteria need to prove it actually blocks a known-bad line, not just trust that it's wired in
correctly somewhere inside a longer chain).

All three pieces are plain HTTP-callable logic added to the tracker app (`web/app.py`), not n8n
JavaScript/Function nodes — n8n's job in this phase is just to call them in order via HTTP
Request nodes and pass data between them. Keeping the actual logic in the already-deployed,
already-tested FastAPI app means it's covered by the same deploy pipeline, is directly curlable
for debugging, and doesn't require writing complex logic inside n8n's own node editor.

The one real technical unknown carried into this phase (flagged in Phase 1's planning, not
resolved yet): the manual process generates plates at an exact 4:5 crop (1122×1402) via
ChatGPT's web app, but OpenAI's Images API (`gpt-image-1`) only supports a small fixed set of
output sizes, none of which is exactly 4:5. This phase resolves it with a real generated image,
not a guess — see the Image Generation component's feedback loop.

## Decisions Considered and Rejected

- **Generate background-plate images via OpenAI's Images API** — rejected: keep pasting
  prompts into ChatGPT's web app by hand. User accepted the new API cost and the small risk of a
  slightly different look than the ChatGPT app produces.
- **Reuse the tracker's existing settings-table `character_reference_image` upload for the OpenAI
  reference image, instead of a new hardcoded server path** — rejected: copy the reference
  image to a new fixed path.
- **Run the originality check using the Anthropic API's native web-search tool** — rejected:
  LLM self-check only, no automated check, or a separate search API (Serper/Bing/Google). Reuses
  the Anthropic credential already needed for prompt-drafting instead of adding a third provider.
- **Track rolling voice-register counts and explicitly instruct the drafting model toward the
  ~6:4 target** — rejected: weighted random register pick with no tracking. Matches the
  documented register-balance intent precisely for a small added DB cost.

## Feedback Strategy

**Inner-loop command**: `curl -s -u $AUTH -X POST https://pancracio-ideas.santiagomorel.dev/internal/originality-check -d 'line=...' | jq .`

**Playground**: Each of the three components (register-aware prompt drafting, originality check,
image generation) gets its own small internal endpoint during development, callable directly with
curl — an API-endpoint playground, per the feedback-loop guide's mapping for API components.
These internal endpoints stay in the codebase afterward (gated behind `check_auth` like everything
else) since they're exactly what the success criteria curl against.

**Why this approach**: All three components are single HTTP calls to an external API with a
text-in/text-or-image-out shape — curl-and-inspect is faster than round-tripping through n8n's
UI for every iteration, and it's the same debugging surface the success criteria use.

## File Changes

### Modified Files

| File Path   | Changes                                                                                                        |
| ------------ | ----------------------------------------------------------------------------------------------------------------- |
| `web/app.py` | Add `_draft_plate_prompt()`, `_check_originality()`, `_generate_plate_image()`, the rolling-register helper, and three thin internal endpoints wrapping them. |
| `web/requirements.txt` | Add an HTTP client capable of multipart uploads for the OpenAI call (stdlib `urllib` can do this but is painful for multipart; add `httpx` — small, no other new transitive deps). |

### New Files

| File Path                                                    | Purpose                                                                 |
| --------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `internal-docs/pipeline/auto-publish-prompt-template.md`         | The exact system/user prompt text sent to the Anthropic API for drafting, versioned separately from the human-facing doc it's adapted from. |

## Implementation Details

### Rolling voice-register tracking

**Pattern to follow**: `web/app.py`'s existing parameterized-query helpers (e.g. `_get_stats_by_category()`).

**Overview**: No new counter table — compute the recent ratio by querying the last N
auto-published ideas' `register` values directly.

```python
def _get_recent_register_counts(window: int = 10) -> dict[str, int]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT register, COUNT(*) AS n FROM (
                SELECT register FROM ideas
                WHERE auto_publish = 1 AND register IS NOT NULL
                ORDER BY created_at DESC LIMIT ?
            ) GROUP BY register
            """,
            (window,),
        ).fetchall()
    return {r["register"]: r["n"] for r in rows}
```

**Key decisions**:

- Query-based, not a maintained counter — simpler, always consistent with actual data, and
  the volume (~1/day) makes a `LIMIT 10` scan trivial.
- Window of 10 approximates "recent batch" from the manual process's own per-batch framing.

**Implementation steps**:

1. Add the function above.
2. Call it from the prompt-drafting step and pass the counts into the model's instructions (e.g.
   "of the last 10 auto-published ideas, N were reframe and M were observational; the target is
   roughly 6:4 reframe:observational — lean toward whichever is under-represented").

**Feedback loop**:

- **Playground**: local uvicorn + seeded test DB.
- **Experiment**: seed 6 reframe + 2 observational, confirm the function returns
  `{"reframe": 6, "observational": 2}`; seed zero and confirm it returns `{}` without erroring.
- **Check command**: `curl -s -u test:test http://127.0.0.1:8123/internal/register-counts | jq .`

### Prompt drafting (Anthropic API)

**Overview**: One Anthropic Messages API call per idea, given the idea's title/description and
the current register counts, returns a filled-in plate prompt (the fixed template from
`chatgpt-image-post-prompt.md` with `[PROP SWAP]` completed) plus the chosen register and the
on-image quote line.

```python
def _draft_plate_prompt(idea: dict, register_counts: dict[str, int]) -> dict:
    """Returns {"prompt": str, "register": "reframe"|"observational", "quote_line": str}"""
    ...
```

**Key decisions**:

- The system prompt given to Claude must encode, verbatim, the fixed boilerplate from
  `chatgpt-image-post-prompt.md` (the "ABSOLUTELY NO TEXT" block, the left-45%-empty-wall
  composition rule) — only `[PROP SWAP]` and the quote line are model-generated per idea.
  This is not the model's judgment call to make; it's a template fill.
  See `internal-docs/pipeline/auto-publish-prompt-template.md` for the exact text to use.
- The system prompt must also encode the text-on-props gotcha explicitly: a generic "no text"
  instruction isn't enough — any prop that could plausibly carry text (phone, sticky note,
  book, scroll) needs its own "completely blank" callout, per
  `internal-docs/video-production/character-consistency.md`'s documented failure mode.
  The generated quote line is what gets baked into the image later by Remotion, not by this
  prompt — the plate itself must stay genuinely text-free.
- Register selection: instruct the model with the current counts and the ~6:4 target, but let it
  make the actual pick based on which register better fits the idea's content — don't force a
  register that doesn't fit the idea just to hit the ratio exactly.

**Implementation steps**:

1. Write the system prompt in `auto-publish-prompt-template.md`, adapted from
   `chatgpt-image-post-prompt.md` — keep the fixed boilerplate word-for-word.
2. Implement `_draft_plate_prompt()` calling the Anthropic Messages API, parsing a structured
   response (ask the model to return JSON: `{"prompt": ..., "register": ..., "quote_line": ...}`).
3. Add `POST /internal/draft-prompt` wrapping it, gated behind `check_auth`.

**Feedback loop**:

- **Playground**: `POST /internal/draft-prompt` against a few real idea titles from the tracker.
- **Experiment**: one idea that clearly fits "observational" (a concrete modern-life noun) and one
  that clearly fits "reframe" (an abstract aphorism) — confirm the model's register pick
  matches the obvious read for each, not just whichever the ratio currently favors.
- **Check command**: `curl -s -u test:test -X POST http://127.0.0.1:8123/internal/draft-prompt -d 'idea_id=3' | jq .`

### Originality check (Anthropic web-search tool)

**Overview**: A standalone function taking the drafted quote line, calling the Anthropic API with
its native web-search tool enabled, and returning whether the line is a near-exact match to a
known quote/book title/famous phrase.

```python
def _check_originality(line: str) -> dict:
    """Returns {"flagged": bool, "reason": str | None}"""
    ...

@app.post("/internal/originality-check")
def internal_originality_check(line: str = Form(...), _: None = Depends(check_auth)) -> dict:
    return _check_originality(line)
```

**Key decisions**:

- Built and exposed as its own endpoint *specifically* so it can be tested in isolation against a
  known-bad line (the Simon Sinek book title from the documented incident) without needing to run
  the whole pipeline — this is what the contract's success criterion actually checks.
- Fails closed: if the web-search call itself errors (rate limit, API down), treat as `flagged:
  true` rather than silently proceeding to generate an image for an unchecked line. A failed
  safety check should never look identical to a passed one.

**Implementation steps**:

1. Implement `_check_originality()` using the Anthropic Messages API with the `web_search` tool,
   prompting it to search for the exact line and report back whether it's a known quote/title.
2. Add the endpoint above.
3. Wire the pipeline (Phase 2's n8n workflow) to call this *before* the image-generation step and
   halt that idea (mark `'failed'`, per Phase 4's failure handling) if `flagged: true`.

**Feedback loop**:

- **Playground**: `POST /internal/originality-check` directly.
- **Experiment**: test with `"Start With Why"` (must flag), a clearly original made-up line (must
  not flag), and a short common phrase like `"one step at a time"` (edge case — decide during
  implementation whether common idioms should flag; document the decision here once made).
- **Check command**: `curl -sf -u test:test -X POST http://127.0.0.1:8123/internal/originality-check -d 'line=Start With Why' | jq -e '.flagged == true'`

### Image generation (OpenAI Images API)

**Overview**: Sends the drafted prompt plus the reference image (read from the tracker's own
`character_reference_image` setting) to OpenAI's Images API, saves the result as this idea's
`layout_image_path`, following the same file-naming convention as the existing manual
`character/template_N.png` → `remotion/public/image-posts/` flow, but automated.

```python
def _generate_plate_image(idea_id: int, prompt: str) -> str:
    """Fetches the reference image, calls OpenAI's Images API, saves the result,
    returns the saved path."""
    ...
```

**Key decisions — including the one open technical question**:

- Reference image source: read the `character_reference_image` setting (already a
  `/static/uploads/character_reference.*` path on this same server), load it from disk directly
  (the tracker app and this new code run in the same process/filesystem) rather than fetching it
  over HTTP.
- **Aspect ratio is not yet settled and needs a real test, not a guess.** The manual process
  produces an exact 4:5 (1122×1402) crop via ChatGPT's web app; OpenAI's `gpt-image-1` Images
  API only offers a small fixed set of output sizes (none of them exactly 4:5). The plan: generate
  at the closest supported portrait size, then server-side crop/pad to exactly 1122×1402
  before handing off to Remotion (which expects that exact frame). **Do this as a real experiment
  first** (generate one actual test image, inspect it, decide the crop math) rather than assuming
  a formula works — see the feedback loop below.
- Save the result at a path mirroring the existing manual convention
  (`remotion/public/image-posts/idea-{id}.png`) so Phase 3's Remotion step needs no special-casing
  between manually-produced and auto-generated plates.

**Implementation steps**:

1. Implement the OpenAI API call (multipart upload of the reference image + the prompt text).
2. Run one real test generation, inspect the output size against OpenAI's actual returned
   dimensions, and implement the crop/pad step to reach exactly 1122×1402.
3. Save to `remotion/public/image-posts/`, update the idea's `layout_image_path` via the DB.
4. Add `POST /internal/generate-plate` wrapping it.

**Feedback loop**:

- **Playground**: `POST /internal/generate-plate` against one real idea, output inspected
  visually.
- **Experiment**: generate 2-3 test plates with different prop-swap prompts, check (a) no visible
  text renders anywhere in the image (the documented text-on-props failure mode), (b) the
  character resembles the reference image, (c) the final crop is exactly 1122×1402.
- **Check command**: `identify -format '%wx%h' remotion/public/image-posts/idea-{id}.png` —
  expect `1122x1402`.

## Data Model

No schema changes beyond Phase 1's `register` column (already added there).

## API Design

### New Endpoints (internal, `check_auth`-gated, same as the rest of the app)

| Method | Path                          | Description                                          |
| ------ | ------------------------------- | ------------------------------------------------------- |
| `POST` | `/internal/draft-prompt`        | Draft the plate prompt + register + quote line for an idea. |
| `POST` | `/internal/originality-check`   | Check a line for near-exact matches to known quotes/titles. |
| `POST` | `/internal/generate-plate`      | Generate and save the background plate image for an idea. |
| `GET`  | `/internal/register-counts`     | Current rolling register counts (debugging aid).       |

## Testing Requirements

### Manual Testing

- [ ] Draft a prompt for a real idea title, confirm the fixed boilerplate is present verbatim and
      only the prop-swap/quote line vary.
- [ ] Originality check flags `"Start With Why"` and a couple of other known book titles/famous
      quotes; does not flag a clearly original test line.
- [ ] Generate one real plate image end-to-end; visually confirm character consistency against the
      reference image and confirm no text appears anywhere in the plate.
- [ ] Confirm the final saved image is exactly 1122×1402.

## Error Handling

| Error Scenario                         | Handling Strategy                                                        |
| ----------------------------------------- | ---------------------------------------------------------------------------- |
| Anthropic API error during prompt drafting | Propagate as a failure for that idea (Phase 4 marks it `'failed'`), no retry. |
| Originality-check API call itself fails    | Fail closed — treat as `flagged: true`, do not proceed to image generation. |
| OpenAI API error or content-policy rejection | Propagate as a failure for that idea, no retry.                          |
| Generated image isn't text-free despite the prompt | Not auto-detected in this phase (no OCR step) — named as an accepted gap, see Failure Modes. |

## Failure Modes

| Component            | Failure Mode                                             | Trigger                                             | Impact                                                          | Mitigation                                                                 |
| ----------------------- | ------------------------------------------------------------ | -------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Image generation        | Generated plate still contains visible text on a prop        | Model ignores the per-object "completely blank" callouts (documented as happening even with generic instructions) | A post could ship with unintended text, same class as the past incident | No automated OCR check in this phase (out of scope) — accepted gap; flagged here so it's a known limitation, not a surprise |
| Image generation        | Output aspect ratio doesn't match 1122×1402 after crop/pad | OpenAI's supported sizes don't map cleanly to 4:5      | Remotion's compositing step (expects an exact frame) renders text in the wrong position | Resolved via the real-image experiment in this phase, not assumed — if crop math can't produce a clean result, escalate before Phase 3 |
| Originality check        | False negative — a genuinely non-original line the web search doesn't catch | Search-based detection has limits; not every source is indexed | Same risk as the original human process, not worse — the check is an improvement over "no check for AI-drafted lines," not a guarantee | Documented as a known limitation, not silently assumed perfect |
| Prompt drafting          | Model drifts from the fixed boilerplate over time (paraphrases instead of using it verbatim) | LLM non-determinism across many calls                 | Plate composition (the empty-left-wall rule, etc.) degrades gradually | Consider periodic spot-checks of drafted prompts against the template; not automated in this phase |

## Validation Commands

```bash
cd web && python3 -m py_compile app.py
curl -s -u test:test -X POST http://127.0.0.1:8123/internal/draft-prompt -d 'idea_id=1' | jq .
curl -sf -u test:test -X POST http://127.0.0.1:8123/internal/originality-check -d 'line=Start With Why' | jq -e '.flagged == true'
```

## Rollout Considerations

- **Feature flag**: none needed — these are internal endpoints only called by ideas flagged
  `auto_publish`, which is itself the opt-in mechanism.
- **Monitoring**: log every originality-check result (flagged or not) so a human can spot-check
  the safeguard is actually running, not just trust it silently.
- **Rollback plan**: these are additive endpoints; disabling them (or the n8n workflow calling
  them) has no effect on the existing manual pipeline or any non-`auto_publish` idea.

## Open Items

- [x] Finalize the exact crop/pad math from OpenAI's actual output size to 1122×1402 once
      the first real test image is generated — cannot be settled from documentation alone.
      **Resolved 2026-09-24**: generate at 1024×1536 (closest supported portrait size),
      center-crop height to the 1122:1402 aspect ratio, resize to the exact target. Verified
      against real generated images, landed at exactly 1122×1402 both times.
- [x] Decide whether short common idioms should flag in the originality check (see Feedback loop
      above) — resolve during implementation testing, document the decision here.
      **Resolved 2026-09-24**: common idioms/generic phrasing with no single attributable
      source do NOT flag — only near-exact matches to a specific, identifiable quote/title.
      Verified live: "one step at a time" does not flag, "Start With Why" does.

---

_This spec is ready for implementation. Follow the patterns and validate at each step._
