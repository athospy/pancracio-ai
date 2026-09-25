# Implementation Spec: Pancracio Auto-Publish Pipeline - Phase 3

**Contract**: ./contract.md
**PRD**: none
**Estimated Effort**: M

## Technical Approach

This phase does two independent things: gets Remotion's `PancracioQuote` still-render running as
a small dedicated service on the new render VPS (not charmander, not the user's Mac), and adds an
LLM call that drafts the Instagram caption and hashtags on the tracker app.

`PancracioQuote` already supports exactly the invocation this needs (`remotion still
PancracioQuote out.png --props=props.json --overwrite`, confirmed working this session) — the
work here is wrapping that CLI call in a small standalone service on the render VPS (colocated
with n8n from Phase 1), rather than adding it to the tracker app on charmander. This keeps the
"logic lives in testable code, not n8n visual nodes" principle from Phases 1-2 intact, just
relocates *where the CLI itself runs*: a tiny FastAPI app (`render-service/app.py`).

**The tracker app calls this service directly, not n8n.** Phase 4's orchestrator
(`/internal/run-pipeline/{idea_id}`, on the tracker) needs to call rendering as one step in a
single in-process chain — if n8n owned the download/render/upload dance instead, that chain would
be split across two systems and Phase 4's clean "one HTTP call per idea, one place that decides
success/failure" design would break. So the render service is reachable **from charmander
specifically** (its own IP, firewalled to only that source — not a public bind, but not
loopback-only either), and `web/app.py` gets a new `_render_post_image()` that POSTs to it over
HTTP and saves the returned PNG using the same `_save_idea_image()`-style file-write already used
for manual uploads. n8n's role stays exactly what Phase 4 describes: call
`/internal/run-pipeline/{idea_id}` once per due idea, nothing render-specific in the n8n workflow
itself.

## Decisions Considered and Rejected

- **Run n8n and the Remotion rendering step together on a new, separate VPS, leaving charmander
  untouched** — rejected: run rendering on charmander (the original plan, before the resource
  risk was flagged). Colocating rendering with n8n avoids an extra network hop and keeps
  charmander doing only what it already does.
- **Run Remotion compositing on a VPS (of some kind)** — rejected: webhook back to the user's Mac
  to render locally. A pipeline that only runs when the user's laptop happens to be on isn't
  actually unattended.

## Feedback Strategy

**Inner-loop command**: `ssh <render-vps-alias> "cd ~/pancracio-render/remotion && ./node_modules/.bin/remotion still PancracioQuote /tmp/t.png --props=/tmp/p.json --overwrite"`

**Playground**: Direct SSH access to the render VPS to run the Remotion CLI by hand first, before
wrapping it in a service — confirms the environment (Node, Chromium deps) works at all before
adding any application code on top.

**Why this approach**: A headless-Chromium render either works or fails with an environment-level
error (missing shared library, out of memory) that's much easier to diagnose from a raw SSH
session than through an HTTP 500 three layers removed from the actual failure.

## File Changes

### New Files (on the render VPS, a separate deploy target from `web/`)

| File Path                              | Purpose                                                                   |
| ------------------------------------------ | -------------------------------------------------------------------------- |
| `render-service/app.py`                    | Tiny FastAPI app: `POST /render` takes a background-image URL + quote text + register/caption context, writes props JSON, shells out to Remotion, returns the composited PNG bytes. |
| `render-service/requirements.txt`          | `fastapi`, `uvicorn` — same minimal dependency style as `web/requirements.txt`. |
| `render-service/pancracio-render.service`  | systemd unit running the service via uvicorn, matching the pattern in `deployment-runbook.md` (not docker — this is plain Python, only Remotion itself needs Node/Chromium). |

### Modified Files

| File Path   | Changes                                                                                          |
| ------------ | ----------------------------------------------------------------------------------------------- |
| `web/app.py` | Add `_render_post_image()` (calls the render service over HTTP, saves the result), `_draft_caption()`, and `POST /internal/draft-caption`. |

## Implementation Details

### Render VPS: Remotion environment

**Overview**: Copy the `remotion/` project to the render VPS, `npm install` there, and confirm a
still-render actually launches headless Chromium successfully before writing any service code
around it.

**Key decisions**:

- Remotion's renderer manages its own headless-Chromium binary (it doesn't rely on a system
  Chrome install) — confirm this during setup by just attempting a render and reading whatever
  error comes back, rather than pre-guessing the exact system package list. The classic
  Debian/Ubuntu headless-Chrome shared-library gaps (`libnss3`, `libatk1.0-0`, `libgbm1`, and
  similar) are the most likely issue if it fails to launch at all.
- Reconfirm the documented gotcha from `internal-docs/integrations/remotion.md`: `npx remotion`
  hangs on the Mac and must use the local binary directly. Verify whether this also holds on the
  render VPS before assuming either way.

**Implementation steps**:

1. `rsync` (or `git clone` + `npm install`, whichever is simpler given the render VPS's own git
   access) the `remotion/` directory to `~/pancracio-render/remotion` on the new VPS.
2. `npm install`, then attempt one `remotion still` render with a minimal test props file.
3. If Chromium fails to launch, install the missing shared libraries the error names and retry.
4. Once a render succeeds by hand, proceed to the service wrapper below.
5. Confirm resource headroom (`free -h`, `docker stats` if n8n is already running) immediately
   after a real render — Chromium's memory footprint *during* rendering is the actual worst case,
   not idle.

**Feedback loop**:

- **Playground**: raw SSH session on the render VPS, no application code involved yet.
- **Experiment**: render the same test props file 3 times in a row, confirm each succeeds and no
  orphaned Chromium processes are left behind.
- **Check command**: `ssh <render-vps-alias> "ps aux | grep -i chrom | grep -v grep"` after a
  render completes — expect no lingering processes.

### `POST /render` (render-service, on the render VPS)

**Pattern to follow**: `web/app.py`'s general FastAPI style (thin route, logic in a plain
function), scaled down — this service has no auth, no DB, no templates, just one real endpoint.

**Overview**: Given a background-image URL, the quote line, and the fixed layout constants,
writes a props JSON file, shells out to the Remotion CLI via `subprocess.run` with an argument
list, and returns the resulting PNG.

```python
# render-service/app.py
from fastapi import FastAPI
from fastapi.responses import FileResponse
import subprocess, json, urllib.request
from pathlib import Path

app = FastAPI()
REMOTION_DIR = Path.home() / "pancracio-render/remotion"

@app.post("/render")
def render(background_url: str, quote_line: str, idea_id: int):
    local_bg = REMOTION_DIR / "public/image-posts" / f"idea-{idea_id}.png"
    urllib.request.urlretrieve(background_url, local_bg)
    props = {
        "backgroundSrc": f"image-posts/idea-{idea_id}.png",
        "quoteLines": _wrap_quote_line(quote_line, max_chars=28),
        "headerText": "Tiny advice from a serious capybara:",
        "attribution": "— pancracio.capy",
        "quoteFontSize": 76, "textLeft": 78, "textWidth": 470, "textTop": 132,
    }
    props_path = Path(f"/tmp/props-{idea_id}.json")
    props_path.write_text(json.dumps(props))
    out_path = REMOTION_DIR / "out" / f"idea-{idea_id}.png"
    result = subprocess.run(
        ["./node_modules/.bin/remotion", "still", "PancracioQuote", str(out_path),
         f"--props={props_path}", "--overwrite"],
        cwd=REMOTION_DIR, capture_output=True, timeout=120,
    )
    if result.returncode != 0:
        return {"error": result.stderr.decode()}, 502
    return FileResponse(out_path, media_type="image/png")
```

**Key decisions**:

- **Argument-list `subprocess.run`, never `shell=True` or an interpolated command string** — quote
  lines and titles are idea-controlled text that could contain shell metacharacters; a malformed
  idea title should be able to break a render, it must never be able to run an arbitrary command.
- **Reachable from charmander's IP specifically, not publicly bound and not loopback-only** —
  firewalled (e.g. `ufw allow from <charmander-ip> to any port 8090`) so only the tracker app can
  call it, since the tracker's own `/internal/run-pipeline/{idea_id}` (Phase 4) is what calls this
  endpoint, not n8n directly. No auth token needed given the network-level restriction, matching
  the trust model n8n's own VPS-local-only binding already uses.
- `timeout=120` on the Remotion subprocess — bounded so a hung render doesn't block the whole
  pipeline indefinitely (Phase 4's failure handling marks that idea `'failed'` if this call never
  returns).
- Fixed layout constants match `PancracioQuote`'s existing `defaultPancracioQuoteProps` — not
  reinvented per post, matching how the manual process only varies `backgroundSrc` and
  `quoteLines` per post today.

**Implementation steps**:

1. Implement `_wrap_quote_line()` — a simple word-wrap by character count (no existing wrapping
   logic in this codebase to follow; start simple, adjust `max_chars` after visually checking a
   few real renders).
2. Implement the `/render` endpoint as above.
3. Add the systemd unit, `systemctl enable --now pancracio-render.service`.
4. Configure the firewall rule restricting inbound port 8090 to charmander's IP only.

**Feedback loop**:

- **Playground**: `curl -X POST http://localhost:8090/render` on the render VPS itself first
  (bypassing the firewall rule for local testing), against a real background-plate URL from the
  tracker.
- **Experiment**: a short quote line, a long one that needs wrapping onto 3+ lines, and a
  malformed idea title/quote containing a shell metacharacter (e.g. `` `; rm -rf /` `` as a
  literal string) — confirm the third case renders garbage-but-harmless text, never executes
  anything.
- **Check command**: `identify -format '%wx%h' /tmp/out.png` — expect `1122x1402`.

### `_render_post_image()` (on the tracker, charmander)

**Pattern to follow**: Phase 2's `_generate_plate_image()` (the general shape of "call an external
service, save the returned bytes via the existing image-save convention").

**Overview**: The one piece of Phase 4's orchestrator that talks to the render VPS. Called
in-process from `/internal/run-pipeline/{idea_id}`, not exposed as its own internal HTTP endpoint
(there's nothing useful to test in isolation here beyond what the render service's own feedback
loop already covers).

```python
def _render_post_image(idea: dict) -> str:
    resp = httpx.post(
        f"http://{RENDER_VPS_HOST}:8090/render",
        data={
            "background_url": f"https://pancracio-ideas.santiagomorel.dev{idea['layout_image_path']}",
            "quote_line": idea["quote_line"],
            "idea_id": idea["id"],
        },
        timeout=150,  # a little over the render service's own 120s subprocess timeout
    )
    resp.raise_for_status()
    return _save_idea_image(idea["id"], "final", resp.content)  # existing save convention
```

**Key decisions**:

- `httpx` (already added in Phase 2 for OpenAI's multipart upload) covers this plain POST too —
  no new dependency.
- Reuses the existing `_save_idea_image()` file-naming/storage convention (`idea_{id}_final.png`
  under `static/uploads/`) so a render-service-produced image is indistinguishable in storage from
  one uploaded by hand via the edit page.

**Implementation steps**:

1. Add `RENDER_VPS_HOST` as a small config constant (or env var) once the render VPS's address is
   known.
2. Implement `_render_post_image()` as above, called from Phase 4's orchestrator.

**Feedback loop**:

- **Playground**: call `_render_post_image()` directly against a seeded idea with a real
  `layout_image_path`, via a throwaway Python REPL or a temporary debug endpoint during
  development.
- **Experiment**: confirm the idea's `final_image_path` updates and the file exists on disk at the
  expected path.
- **Check command**: `ls web/static/uploads/idea_{id}_final.png`

### Caption + hashtag drafting (on the tracker, charmander)

**Overview**: An Anthropic API call, reusing the same client setup as Phase 2's prompt-drafting
(same box, same credential), given the idea's title/register/quote line, returns a caption (the
"openly motivational" register per `internal-docs/social/image-posts.md`, distinct from the
deadpan on-image quote) and a hashtag list. This stays on the tracker app since it's a plain text
API call with no rendering involved — no reason to add it to the render VPS.

```python
def _draft_caption(idea: dict) -> dict:
    """Returns {"caption": str, "hashtags": str}"""
    ...
```

**Key decisions**:

- Encode the documented distinction explicitly in the prompt: the caption is *not* a repeat of
  the on-image quote — it's the separately-motivational extension, per `image-posts.md` and this
  project's own `caption-register-motivational` memory note.

**Implementation steps**:

1. Implement `_draft_caption()` in `web/app.py`.
2. Add `POST /internal/draft-caption`, write `caption`/`hashtags` back onto the idea (existing
   columns, no schema change).

**Feedback loop**:

- **Playground**: `POST /internal/draft-caption` against a couple of real ideas.
- **Experiment**: confirm the caption text is genuinely different from the quote line, not a
  near-duplicate.
- **Check command**: `curl -s -u test:test -X POST http://127.0.0.1:8123/internal/draft-caption -d 'idea_id=1' | jq .`

## Data Model

No schema changes — `final_image_path`, `caption`, `hashtags` already exist on `ideas`.

## API Design

### New Endpoints

| Service        | Method | Path                    | Description                                                  |
| ---------------- | ------ | -------------------------- | ---------------------------------------------------------------- |
| Render VPS (firewalled to charmander's IP) | `POST` | `/render` | Composite the quote card given a background URL + quote text; returns PNG. Called by the tracker, not n8n. |
| Tracker (charmander) | `POST` | `/internal/draft-caption` | Draft caption + hashtags for an idea.                             |

`_render_post_image()` saves the render service's response via the tracker's existing
`_save_idea_image()` convention directly (no HTTP round-trip through `/ideas/{id}/images` needed
since this runs in-process on the tracker, not from an external caller like n8n).

## Testing Requirements

### Manual Testing

- [ ] Render succeeds for a short quote, a long (wrapping) quote, and confirm output is always
      exactly 1122×1402.
- [ ] Render with a deliberately malformed title (shell metacharacters) — confirm no shell
      execution occurs and the process fails safely if it fails at all.
- [ ] Three consecutive renders don't leak Chromium processes or measurably degrade the render
      VPS's free memory.
- [ ] The firewall rule actually restricts port 8090 to charmander's IP (confirm a request from
      elsewhere is refused).
- [ ] `_render_post_image()` called against one real idea actually updates `final_image_path` on
      the tracker and the image is publicly fetchable afterward.
- [ ] Caption drafted for 2-3 ideas reads as genuinely distinct from the on-image quote line.

## Error Handling

| Error Scenario                          | Handling Strategy                                                    |
| ------------------------------------------ | -------------------------------------------------------------------------- |
| Remotion process exits non-zero             | `/render` returns a non-2xx status; `_render_post_image()`'s `raise_for_status()` propagates it, Phase 4's orchestrator marks the idea `'failed'`, no retry. |
| Remotion process hangs past `timeout=120`   | `subprocess.run` raises `TimeoutExpired` inside the render service; surfaces as a request timeout to `_render_post_image()`, handled the same way. |
| Render VPS runs out of memory mid-render    | Process gets OOM-killed by the kernel; surfaces as a non-2xx/timeout, handled the same way. |
| Render service unreachable (firewall misconfigured, VPS down) | `httpx.post()` raises a connection error, same failure path. |
| Caption-drafting API call fails             | Propagate as a failure for that idea, no retry.                             |

## Failure Modes

| Component          | Failure Mode                                  | Trigger                                          | Impact                                             | Mitigation                                                          |
| --------------------- | -------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------ |
| Render VPS Chromium   | Fails to launch at all                              | Missing system shared libraries on a fresh install     | Every render fails immediately, blocking Phase 3 entirely | Diagnosed and fixed during this phase's manual setup, before any service code depends on it |
| Render VPS memory     | Memory pressure during a render                     | Single Chromium instance, plus n8n running alongside on the same dedicated box | Slower renders or, at worst, an OOM-killed render | This VPS is dedicated to this project (unlike charmander) — if still tight, it's a sizing question for a single-purpose box, not a shared-resource contention problem |
| Quote line wrapping   | Word-wrap heuristic produces an awkward line break for a specific quote | Long words, unusual punctuation                    | A live post has slightly odd text layout — not broken, just not ideal | No automated fix in this phase; accepted as a minor quality gap given no human reviews before publish |
| Cross-VPS image hop    | Render service's internal download of the plate URL fails (network blip between the two VPSs) | Transient network issue                            | That idea's render fails                                | Surfaces as a normal `/render` failure; Phase 4's no-retry handling applies the same as any other step |
| Firewall rule           | Charmander's IP changes (VPS migration, provider reassignment) and the firewall rule goes stale | Infrastructure change outside this project's control | Every render silently starts failing with a connection error | Not auto-detected in this phase; would show up immediately as every `run-pipeline` call failing at the render step, which is a loud, easy-to-diagnose signal, not a silent one |

## Validation Commands

```bash
cd web && python3 -m py_compile app.py
ssh <render-vps-alias> "cd ~/pancracio-render/remotion && ./node_modules/.bin/remotion still PancracioQuote /tmp/test.png --props=/tmp/test-props.json --overwrite && identify -format '%wx%h\n' /tmp/test.png"
# From the render VPS itself (bypasses the firewall rule, for local testing):
ssh <render-vps-alias> "curl -s -X POST http://localhost:8090/render -d 'background_url=...&quote_line=test&idea_id=999' -o /tmp/out.png"
# From charmander, once the firewall rule is in place:
ssh charmander-pancracio "curl -s -X POST http://<render-vps-ip>:8090/render -d 'background_url=...&quote_line=test&idea_id=999' -o /tmp/out.png"
```

## Rollout Considerations

- **Deploy path**: `render-service/` deploys to the new VPS via its own systemd unit — a separate,
  simpler deploy target than the tracker's GitHub Actions pipeline (no CI needed for a
  single-file service at this scale; a manual `rsync` + `systemctl restart` is enough, documented
  in `n8n/README.md` alongside the n8n setup).
- **Monitoring**: watch the render VPS's memory during the first several real (not test) renders
  once Phase 4 is live and actually posting daily.
- **Rollback plan**: `/render` is a standalone service; if VPS rendering proves unworkable, the
  contract's out-of-scope "webhook back to the Mac" alternative remains available as a fallback
  without redesigning anything upstream (Phase 2 still produces the same plate image either way).

## Open Items

- [ ] Confirm the exact system package list Chromium needs on the render VPS — can only be known
      by attempting a render and reading the actual error, not from documentation.
- [ ] Tune `_wrap_quote_line()`'s `max_chars` after visually checking a handful of real renders.
- [ ] Decide the render service's port (8090 used as a placeholder above) once the render VPS's
      other services, if any, are known.

---

_This spec is ready for implementation. Follow the patterns and validate at each step._
