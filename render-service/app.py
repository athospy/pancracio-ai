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
from PIL import Image

app = FastAPI(title="Pancracio Render Service")

REMOTION_DIR = Path.home() / "pancracio-render" / "remotion"

# Baseline layout matching PancracioQuote's defaultPancracioQuoteProps — used as the
# starting point/ceiling for the adaptive layout below, not applied unconditionally: the
# OpenAI-generated plate doesn't reliably leave the same clear space the manual ChatGPT
# process did (verified — prompt wording alone didn't fix it across several tries), so the
# text column is sized to whatever space the actual generated image has, per render.
HEADER_TEXT = "Tiny advice from a serious capybara:"
ATTRIBUTION = "— pancracio.capy"
BASE_QUOTE_FONT_SIZE = 76
TEXT_LEFT = 78
BASE_TEXT_WIDTH = 470
TEXT_TOP = 132
BASE_MAX_LINE_CHARS = 28
MIN_QUOTE_FONT_SIZE = 36
MIN_TEXT_WIDTH = 260
WRAP_SAFETY_FACTOR = 0.85  # see _fit_text_layout — char-count wrapping runs wider than intended
RENDER_TIMEOUT = 120

# Vertical band actually SCANNED for obstructions — deliberately not the full frame height.
# The frame legitimately contains two different flat materials (wall above, wood floor below,
# at whatever height the rug/floor line falls in a given generation), and wood grain has real
# local pixel variance even though it's visually safe to put text over. Scanning that low
# produced false "obstructed" reads on the *reference* images that are known to be clean.
# Bounded instead to roughly where text realistically reaches (covers ~6 lines at base font),
# which stays clear of the floor in every generation tested.
TEXT_BAND_TOP = 100
SCAN_BAND_BOTTOM = 700
# Separate, more generous ceiling for the font-fitting math below — this one only bounds how
# much vertical room the algorithm is allowed to use before shrinking the font further; it
# doesn't scan pixels, so the floor-texture problem above doesn't apply to it.
TEXT_BAND_BOTTOM = 1100


def _wrap_quote_line(quote_line: str, max_chars: int) -> list[str]:
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


def _is_flat_region(pixels, x: int, y: int, threshold: int = 20) -> bool:
    """Low local pixel variance = an uncluttered surface (wall or floor, whatever tone), high
    variance = an edge or textured object (character fur, prop silhouette, shadow boundary).
    Deliberately not a fixed-color match — the frame legitimately contains two different flat
    materials (wall, wood floor) at two different base tones, so "matches this one sampled
    color" was the wrong test (verified: it flagged the reference images' own clean wall-floor
    transition as an obstruction)."""
    neighbors = [pixels[x + dx, y + dy] for dx in (-3, 0, 3) for dy in (-3, 0, 3)]
    for channel in range(3):
        values = [p[channel] for p in neighbors]
        if max(values) - min(values) > threshold:
            return False
    return True


def _find_safe_text_width(image_path: Path) -> int:
    """The plate's actual clear space varies per generation (verified: neither more explicit
    composition wording nor more explicit prop-position wording made the character/props land
    in the same place every time) — scan the image itself rather than trusting a fixed layout.

    Scans columns rightward from TEXT_LEFT for the first column with any non-flat pixel in the
    scan band, using local variance (see _is_flat_region) rather than a fixed background color.
    Returns a safe width, capped to BASE_TEXT_WIDTH (never wider than the original design) and
    floored at MIN_TEXT_WIDTH (below that, shrinking further stops helping readability)."""
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    pixels = img.load()

    # -4 margin on both axes so _is_flat_region's dx/dy=+3 neighbor lookups never read past
    # the image edge — only matters for a plate shorter/narrower than today's fixed 1122x1402,
    # but the x-scan already needed this guard, so the y-scan should have it too.
    band_bottom = min(SCAN_BAND_BOTTOM, height - 4)
    safe_right = TEXT_LEFT
    for x in range(TEXT_LEFT, min(width - 4, TEXT_LEFT + BASE_TEXT_WIDTH + 100)):
        column_clear = all(
            _is_flat_region(pixels, x, y) for y in range(TEXT_BAND_TOP, band_bottom, 8)
        )
        if not column_clear:
            break
        safe_right = x

    # Buffer before whatever isn't flat — found too tight at 20px in practice (text still read
    # as crowding the character on a real render, even though pixels technically didn't
    # overlap). Widened after that finding; the wrap-width safety factor in _fit_text_layout
    # below covers the other half of the same problem (line length is estimated by character
    # count, not actual rendered pixel width, so it can run wider than intended too).
    safe_width = safe_right - TEXT_LEFT - 55
    return max(MIN_TEXT_WIDTH, min(BASE_TEXT_WIDTH, safe_width))


def _fit_text_layout(quote_line: str, safe_width: int) -> tuple[int, int, list[str]]:
    """Scales font size and wrap width down from the baseline together (never independently —
    a narrower column needs both smaller text and shorter lines) until the wrapped quote fits
    the vertical band, or MIN_QUOTE_FONT_SIZE is reached. Returns (font_size, text_width, lines)."""
    scale = min(1.0, safe_width / BASE_TEXT_WIDTH)
    font_size = max(MIN_QUOTE_FONT_SIZE, round(BASE_QUOTE_FONT_SIZE * scale))
    # Budget for everything in PancracioQuote.tsx besides the quote lines themselves, so the
    # font-fit loop below doesn't let the quote block push the attribution off the frame:
    # 26 * 1.35 - header text's own line height (fontSize 26, lineHeight 1.35)
    # 50         - Divider's vertical margin between header and quote
    # 38         - gap above the attribution line (its marginTop)
    # 27         - attribution line's own approximate height (its fontSize)
    available_height = TEXT_BAND_BOTTOM - TEXT_TOP - 26 * 1.35 - 50 - 38 - 27

    while True:
        # Characters-per-line scales with width available and inversely with font size —
        # both change together as font_size is reduced below, so recompute each pass.
        # WRAP_SAFETY_FACTOR shrinks the width used here specifically (not safe_width itself,
        # which is still returned as-is for the text box) because char-count wrapping only
        # approximates actual rendered pixel width — found running noticeably wider than
        # intended on a real render (Playfair Display's bold weight averages wider per
        # character than the plain count-based estimate assumes), so lines wrap a bit shorter
        # than the raw detected space to leave real margin instead of a technical non-overlap.
        max_chars = max(10, round(BASE_MAX_LINE_CHARS * (safe_width * WRAP_SAFETY_FACTOR / BASE_TEXT_WIDTH) * (BASE_QUOTE_FONT_SIZE / font_size)))
        lines = _wrap_quote_line(quote_line, max_chars)
        needed_height = len(lines) * font_size * 1.12
        if needed_height <= available_height or font_size <= MIN_QUOTE_FONT_SIZE:
            return font_size, safe_width, lines
        font_size = max(MIN_QUOTE_FONT_SIZE, font_size - 6)


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

    safe_width = _find_safe_text_width(local_bg)
    quote_font_size, text_width, quote_lines = _fit_text_layout(quote_line, safe_width)

    props = {
        "backgroundSrc": f"image-posts/idea-{idea_id}.png",
        "quoteLines": quote_lines,
        "headerText": HEADER_TEXT,
        "attribution": ATTRIBUTION,
        "quoteFontSize": quote_font_size,
        "textLeft": TEXT_LEFT,
        "textWidth": text_width,
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
