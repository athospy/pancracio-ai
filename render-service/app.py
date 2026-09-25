"""
Tiny render service for the Pancracio auto-publish pipeline.

Runs on the dedicated render VPS (bulbasaur), reachable only from charmander's IP
(firewalled — see n8n/README.md). No auth token needed given that network-level
restriction, matching the trust model n8n's own VPS-local-only binding already uses.

Takes a background-plate URL + quote text, shells out to the Remotion CLI to composite
the PancracioQuote still, and returns the resulting PNG.
"""

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse

app = FastAPI(title="Pancracio Render Service")

REMOTION_DIR = Path.home() / "pancracio-render" / "remotion"

# Fixed layout constants matching PancracioQuote's defaultPancracioQuoteProps — not
# reinvented per post, matching how the manual process only varies backgroundSrc/quoteLines.
HEADER_TEXT = "Tiny advice from a serious capybara:"
ATTRIBUTION = "— pancracio.capy"
QUOTE_FONT_SIZE = 76
TEXT_LEFT = 78
TEXT_WIDTH = 470
TEXT_TOP = 132
MAX_LINE_CHARS = 28
RENDER_TIMEOUT = 120


def _wrap_quote_line(quote_line: str, max_chars: int = MAX_LINE_CHARS) -> list[str]:
    """Simple word-wrap by character count — no existing wrapping logic in this codebase
    to follow. max_chars tuned by eye against real renders (see spec-phase-3.md Open Items)."""
    words = quote_line.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


@app.post("/render")
def render(
    background_url: str = Form(...),
    quote_line: str = Form(...),
    idea_id: int = Form(...),
):
    local_bg = REMOTION_DIR / "public" / "image-posts" / f"idea-{idea_id}.png"
    local_bg.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(background_url, local_bg)
    except (urllib.error.URLError, OSError) as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch background image: {e}")

    props = {
        "backgroundSrc": f"image-posts/idea-{idea_id}.png",
        "quoteLines": _wrap_quote_line(quote_line),
        "headerText": HEADER_TEXT,
        "attribution": ATTRIBUTION,
        "quoteFontSize": QUOTE_FONT_SIZE,
        "textLeft": TEXT_LEFT,
        "textWidth": TEXT_WIDTH,
        "textTop": TEXT_TOP,
    }
    props_path = Path(f"/tmp/props-{idea_id}.json")
    props_path.write_text(json.dumps(props))

    out_path = REMOTION_DIR / "out" / f"idea-{idea_id}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Argument-list subprocess.run, never shell=True or an interpolated command string —
    # quote_line is idea-controlled text that could contain shell metacharacters; a malformed
    # idea should be able to break a render, it must never be able to run an arbitrary command.
    try:
        result = subprocess.run(
            [
                "./node_modules/.bin/remotion", "still", "PancracioQuote", str(out_path),
                f"--props={props_path}", "--overwrite",
            ],
            cwd=REMOTION_DIR,
            capture_output=True,
            timeout=RENDER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail=f"Render timed out after {RENDER_TIMEOUT}s")

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")[:2000]
        raise HTTPException(status_code=502, detail=f"Remotion render failed: {stderr}")

    return FileResponse(out_path, media_type="image/png")
