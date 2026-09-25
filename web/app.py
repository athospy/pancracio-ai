"""
FastAPI web app for tracking Pancracio content ideas.

Run from web/:
    uvicorn app:app --reload
Then open http://localhost:8000
"""

import base64
import hashlib
import io
import json
import logging
import os
import secrets
import shutil
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pancracio")

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "pancracio.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Generated plate images live alongside the Remotion project (so Phase 3's rendering step reads
# them with no special-casing vs. manually-produced plates), not under web/static/uploads/ — but
# they still need to be HTTP-fetchable so the render VPS can download them, hence this second
# mount. Created eagerly since StaticFiles checks the directory exists at mount time, and nothing
# else creates this path before the first plate is generated.
REMOTION_IMAGE_POSTS_DIR = BASE_DIR.parent / "remotion" / "public" / "image-posts"
REMOTION_IMAGE_POSTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Pancracio Ideas Tracker")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/image-posts", StaticFiles(directory=REMOTION_IMAGE_POSTS_DIR), name="image-posts")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# PBKDF2 iteration count — OWASP's current minimum for PBKDF2-SHA256. Costs
# ~100-200ms per hash, negligible at this account volume (2-3 users).
PASSWORD_HASH_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PASSWORD_HASH_ITERATIONS
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, _, digest_hex = stored.partition("$")
    if not salt or not digest_hex:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PASSWORD_HASH_ITERATIONS
    ).hex()
    return secrets.compare_digest(candidate, digest_hex)


STATUSES = ["idea", "scripted", "ready", "posted", "archived", "failed"]
CONTENT_TYPES = ["video", "image"]

PAGE_SIZE = 20
SORT_OPTIONS = {
    "score": "(ideas.score IS NULL), ideas.score DESC, ideas.created_at DESC",
    "newest": "ideas.created_at DESC",
    "oldest": "ideas.created_at ASC",
    "title": "ideas.title COLLATE NOCASE ASC",
}
IG_GRAPH_BASE = "https://graph.instagram.com/v21.0"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
# Cheaper model while iterating on Phase 2 — revisit before real production traffic if
# drafting/originality quality needs it (see auto-publish-checklist.md).
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
# The visual quality check needs real vision reasoning, not just text drafting — tested head to
# head against the cheap tier above on two known real images (one confirmed-flawed, one
# confirmed-good): Haiku got BOTH wrong (missed the real defect, flagged the good image),
# Sonnet got both right. Not worth the cost tradeoff for a safety gate specifically. See
# auto-publish-checklist.md's Post-Phase-4 section for the actual test results.
VISUAL_QA_MODEL = "claude-sonnet-5"
OPENAI_IMAGES_EDIT_URL = "https://api.openai.com/v1/images/edits"
# gpt-image-1-mini (tried first for cost) doesn't support input_fidelity, and character
# consistency against the reference image is the whole point of this call — went back to full
# gpt-image-1 + input_fidelity="high" after a real test showed mini drifting noticeably off-model
# (face shape, fur rendering, scarf drape). gpt-image-1 itself retires 2026-10-23 — revisit then.
OPENAI_IMAGE_MODEL = "gpt-image-1"
OPENAI_IMAGE_QUALITY = "medium"
OPENAI_IMAGE_INPUT_FIDELITY = "high"  # preserves reference-image face/detail; gpt-image-1 only
OPENAI_IMAGE_GEN_SIZE = "1024x1536"  # closest supported portrait size to our 4:5 target
PLATE_TARGET_SIZE = (1122, 1402)  # exact 4:5 frame Remotion's PancracioQuote composition expects

# Render service (render-service/app.py) on the dedicated render VPS. Firewalled to only accept
# connections from charmander's IP — see internal-docs/ideas-tracker/auto-publish-credentials.md.
RENDER_VPS_HOST = "bulbasaur.santiagomorel.dev"
RENDER_VPS_PORT = 8090
TRACKER_PUBLIC_BASE = "https://pancracio-ideas.santiagomorel.dev"

# Verbatim source: internal-docs/pipeline/auto-publish-prompt-template.md (not deployed to the
# VPS — internal-docs/ is gitignored — so the real text has to live here; keep both in sync).
PLATE_PROMPT_SYSTEM = """\
You are drafting an image-generation prompt for Pancracio, a capybara plush toy Instagram
character. Your job is to fill in two blanks in a FIXED template — the prop swap and the quote
line — not to redesign the template itself.

## Fixed boilerplate (use word-for-word, only the two bracketed sections change)

Using the attached image as character reference, create a 4:5 portrait image (1122x1402)
of a capybara plush toy character named Pancracio.

ABSOLUTELY NO TEXT. No letters, no words, no writing, no signage, no calligraphy scroll,
no book spines with titles, no labels anywhere in the image. This is a background plate
that text will be added to later.

Composition — this is critical:
- The LEFT 45% of the frame must be clean, empty, warm sandy-beige wall, running from the
  very top of the frame down to roughly three-quarters of the way down. Flat and
  uncluttered. No props, no plants, no hard shadows crossing it, no objects intruding.
  Just softly lit wall with a gentle natural gradient. This is a large area and it must
  stay completely empty.
- Pancracio sits on the RIGHT side of the frame, on a round woven rattan rug, positioned in
  the lower two-thirds of the frame with clear headroom above him — his head and ears must
  not reach the top of the frame. Calm, unhurried, contemplative.
- [PROP SWAP — the objects that express this post's quote. Keep them right of centre.]
- Lower right foreground: a small bonsai in a shallow pot.
- Lower right: an incense stick burning on stacked smooth stones. The thin wisp of smoke must
  rise directly from the tip of this incense stick and nowhere else — no smoke, mist, or steam
  anywhere else in the frame (not from any other prop, even a hot drink).
- Soft natural window light entering from the right.

Style: 3D rendered plush toy, photorealistic fur texture, warm soft lighting, shallow
depth of field. Paraguayan flag scarf — red stripe on top, white in the middle, blue on
the bottom. Warm sandy/beige palette throughout.

4:5 portrait. The empty left wall area is intentional negative space — do not fill it.

## Filling in [PROP SWAP]

Replace the bracketed line with 1-3 concrete objects/props that visually express the idea's
quote. **The line itself must state their position explicitly** — end it with "beside him,"
"to his right on the rug," or similar — never leave position implicit (an image model reads
this line on its own, with no awareness of this instruction; "by the door" or "near the edge"
reads as ambiguous and tends to default to the bottom-left, exactly the zone that must stay
empty). E.g. "a phone face-down on the rug beside him, screen dark" or "a shopping bag tipped
on its side to his right, a receipt spilling out." Pancracio always stays seated on the rug in
this exact pose — never standing, walking, outdoors, or with other characters.

**Text-bearing props need their own explicit callout, not just the generic "no text" line above.**
If the prop swap includes any of the following, append a dedicated blank-out line for each:
- Phone -> "The phone screen must be COMPLETELY BLANK -- a plain dark/glowing rectangle, no icons,
  no app grid, no UI, no notification badges."
- Sticky note / paper -> "The sticky note must be COMPLETELY BLANK -- plain coloured paper, no
  handwriting, no scribbles."
- Book / scroll / receipt -> "No visible text, titles, or printed characters -- treat it as a
  plain blank object of the right shape and colour."

## Choosing the register

Two voices, both valid -- pick whichever genuinely fits the idea, using the counts given to you
only as a tiebreaker:

- Observational: a concrete modern-life noun + a deadpan twist. Has a joke and a POV.
  Example: "There is no wisdom at the bottom of the feed. Pancracio checked."
- Reframe: an abstract aphorism. Example: "Start with why. Otherwise, you may become very
  efficient at the wrong thing."

Target ratio across recent auto-published ideas is roughly 6 reframe : 4 observational -- lean
toward whichever is under-represented, but never force a register that doesn't fit the idea's
actual content just to hit the ratio.

Pancracio observes and reframes; he does not coach. Avoid bare imperatives ("Start today",
"Do the work now") -- that reads as off-voice coaching, not his register.

## Output format

Return ONLY a JSON object, no markdown fencing, no commentary before or after:
{"prompt": "<the complete filled-in plate prompt, boilerplate + prop swap>",
 "register": "reframe" | "observational",
 "quote_line": "<the on-image quote text, not baked into the prompt -- Remotion composites it later>"}
"""


def _resolve_session_user(request: Request) -> Optional[dict]:
    """Look up the caller's session cookie or bearer token against `sessions`,
    with no fallback and no raising — used by get_current_user() (which 401s on
    failure) and by the nav-bar "logged in as" display (which just wants None on
    anything unresolved, never an error)."""
    token = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
    elif "pancracio_session" in request.cookies:
        token = request.cookies["pancracio_session"]
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE sessions.id = ?",
            (token,),
        ).fetchone()
    return dict(row) if row else None


def get_current_user(request: Request) -> dict:
    """Gate every route. Accepts a session cookie or a bearer token (both
    resolved against `sessions` — a browser session and n8n's long-lived token
    are the same kind of row). The legacy shared Basic Auth fallback that lived
    here through Phase 1/2 is gone — see
    docs/ideation/pancracio-user-accounts/spec-phase-3.md.
    """
    user = _resolve_session_user(request)
    if user:
        return user
    raise HTTPException(status_code=401, detail="Not authenticated")


@app.middleware("http")
async def attach_current_user(request: Request, call_next):
    """Makes request.state.user available to every template (Starlette's
    Jinja2Templates injects `request` automatically) so base.html can show
    "logged in as X" / a logout link without every route threading the user
    through its own context dict. Never raises — unresolved just means None,
    same as an anonymous request on /login itself."""
    request.state.user = _resolve_session_user(request)
    return await call_next(request)


@app.exception_handler(HTTPException)
async def redirect_unauthenticated_pages_to_login(request: Request, exc: HTTPException):
    """A bare 401 (FastAPI's default) is fine for API/internal callers (n8n, the login
    page's own fetch call) — they check the status code, not the page. A human hitting
    a page route with no session should land on the login page, not a raw JSON error.
    Only redirects GET requests to page routes; POST /login's own 401 on a wrong
    password stays JSON so its fetch-based error handling still works."""
    if (
        exc.status_code == 401
        and request.method == "GET"
        and not request.url.path.startswith("/api/")
        and not request.url.path.startswith("/internal/")
        and request.url.path != "/login"
    ):
        return RedirectResponse("/login", status_code=303)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_ideas_status_check(conn: sqlite3.Connection) -> None:
    """SQLite can't ALTER a CHECK constraint in place — rebuild the table to add
    'failed' to ideas.status's allowed values. Idempotent via a string match on
    the live table definition, so re-running _init_db() never repeats this."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ideas'"
    ).fetchone()
    if row and "'failed'" in row["sql"]:
        return  # already migrated
    conn.executescript("""
        CREATE TABLE ideas_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          content_type TEXT NOT NULL DEFAULT 'video' CHECK (content_type IN ('image', 'video')),
          description TEXT,
          category TEXT,
          tags TEXT,
          inspiration_source TEXT,
          status TEXT NOT NULL DEFAULT 'idea'
            CHECK (status IN ('idea', 'scripted', 'ready', 'posted', 'archived', 'failed')),
          score INTEGER CHECK (score BETWEEN 1 AND 5),
          layout_image_path TEXT,
          final_image_path TEXT,
          image_prompt TEXT,
          scheduled_at TEXT,
          caption TEXT,
          hashtags TEXT,
          auto_publish INTEGER NOT NULL DEFAULT 0,
          register TEXT,
          quote_line TEXT,
          created_by INTEGER REFERENCES users(id),
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO ideas_new SELECT
          id, title, content_type, description, category, tags, inspiration_source,
          status, score, layout_image_path, final_image_path, image_prompt,
          scheduled_at, caption, hashtags, auto_publish, register, quote_line,
          created_by, created_at, updated_at
        FROM ideas;
        DROP TABLE ideas;
        ALTER TABLE ideas_new RENAME TO ideas;
        CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);
    """)


def _init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        # schema.sql's CREATE TABLE IF NOT EXISTS won't add columns to a table that
        # already exists (production has a live posts table predating ig_media_id).
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(posts)")}
        if "ig_media_id" not in existing_cols:
            conn.execute("ALTER TABLE posts ADD COLUMN ig_media_id TEXT")

        existing_idea_cols = {row["name"] for row in conn.execute("PRAGMA table_info(ideas)")}
        if "auto_publish" not in existing_idea_cols:
            conn.execute("ALTER TABLE ideas ADD COLUMN auto_publish INTEGER NOT NULL DEFAULT 0")
        if "register" not in existing_idea_cols:
            conn.execute("ALTER TABLE ideas ADD COLUMN register TEXT")
        if "quote_line" not in existing_idea_cols:
            conn.execute("ALTER TABLE ideas ADD COLUMN quote_line TEXT")
        if "created_by" not in existing_idea_cols:
            conn.execute("ALTER TABLE ideas ADD COLUMN created_by INTEGER REFERENCES users(id)")

        # Must run after the guards above so ideas_new's INSERT ... SELECT
        # (which names auto_publish/register/quote_line explicitly) is valid on first deploy too.
        _migrate_ideas_status_check(conn)


@app.on_event("startup")
def on_startup() -> None:
    _init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _write_idea_image(idea_id: int, kind: str, ext: str, data: bytes) -> str:
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {ext or 'unknown'}")
    # Remove any previous file for this idea/kind in case the extension changed.
    for existing in UPLOAD_DIR.glob(f"idea_{idea_id}_{kind}.*"):
        existing.unlink()
    dest = UPLOAD_DIR / f"idea_{idea_id}_{kind}{ext}"
    dest.write_bytes(data)
    return f"/static/uploads/{dest.name}"


def _save_idea_image(idea_id: int, kind: str, upload: UploadFile) -> str:
    ext = Path(upload.filename or "").suffix.lower()
    return _write_idea_image(idea_id, kind, ext, upload.file.read())


def _get_ideas(
    status: Optional[str] = None,
    content_type: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "score",
    page: int = 1,
) -> tuple[list[dict], int]:
    where = "WHERE 1=1"
    params: list = []
    if status:
        where += " AND status = ?"
        params.append(status)
    if content_type:
        where += " AND content_type = ?"
        params.append(content_type)
    if q:
        where += " AND (title LIKE ? OR description LIKE ? OR tags LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like]

    order_by = SORT_OPTIONS.get(sort, SORT_OPTIONS["score"])

    with _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM ideas {where}", params).fetchone()["c"]
        rows = conn.execute(
            f"""
            SELECT ideas.id, ideas.title, ideas.content_type, ideas.description,
                   ideas.category, ideas.tags, ideas.inspiration_source, ideas.status,
                   ideas.score, ideas.scheduled_at, ideas.layout_image_path,
                   ideas.final_image_path, ideas.created_at, ideas.updated_at,
                   users.username AS created_by_username
            FROM ideas
            LEFT JOIN users ON users.id = ideas.created_by
            {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
        ).fetchall()
    return [dict(r) for r in rows], total


def _get_ready_queue() -> list[dict]:
    """Ideas marked 'ready', soonest scheduled first (unscheduled ones last)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, content_type, description, category, tags,
                   inspiration_source, status, score, scheduled_at,
                   layout_image_path, final_image_path, created_at, updated_at
            FROM ideas
            WHERE status = 'ready'
            ORDER BY (scheduled_at IS NULL), scheduled_at ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def _get_idea(idea_id: int) -> dict:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT ideas.*, users.username AS created_by_username
            FROM ideas
            LEFT JOIN users ON users.id = ideas.created_by
            WHERE ideas.id = ?
            """,
            (idea_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    return dict(row)


def _get_idea_activity(idea_id: int) -> list[dict]:
    """audit_log rows for one idea's Activity section, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT audit_log.action, audit_log.created_at, users.username
            FROM audit_log
            JOIN users ON users.id = audit_log.user_id
            WHERE audit_log.idea_id = ?
            ORDER BY audit_log.id DESC
            """,
            (idea_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _log_action(conn: sqlite3.Connection, user: Optional[dict], idea_id: int, action: str) -> None:
    """Records one audit_log row. Silently no-ops (not an error) when `user` is
    None — the legacy Basic-Auth fallback (removed in Phase 3) has no real user
    row to attribute to."""
    if user is None:
        return
    conn.execute(
        "INSERT INTO audit_log (user_id, idea_id, action) VALUES (?, ?, ?)",
        (user["id"], idea_id, action),
    )


def _get_setting(key: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """,
            (key, value),
        )


def _default_scheduled_at() -> str:
    """Next 10am — the server runs in UTC (confirmed), matching the manual process's own loose
    'around 10am' habit. Returned in datetime-local input format (no seconds) so it round-trips
    cleanly through the edit form's <input type="datetime-local">."""
    now = datetime.now()
    ten_am = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if now >= ten_am:
        ten_am += timedelta(days=1)
    return ten_am.isoformat(timespec="minutes")


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


def _anthropic_messages(
    system: str,
    user: "str | list",
    tools: Optional[list] = None,
    max_tokens: int = 1500,
    model: Optional[str] = None,
) -> dict:
    """`user` may be a plain string, or a list of Anthropic content blocks (e.g. image + text)
    for vision calls — passed straight through as `content` since the Messages API accepts
    either shape. `model` overrides the default ANTHROPIC_MODEL for calls that need stronger
    reasoning than the cheap tier reliably gives (see VISUAL_QA_MODEL)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured on the server")
    body: dict = {
        "model": model or ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if tools:
        body["tools"] = tools
    resp = httpx.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=90,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Anthropic API error: {resp.text}")
    return resp.json()


def _extract_json_object(text: str) -> dict:
    """Models sometimes wrap JSON in markdown code fences, or (for tool-augmented calls like
    the originality check's web search) narrate their search process before the final JSON
    despite explicit instructions not to — a plain "first { to last }" span breaks if that
    narration itself contains a brace. Tries "last { to end" first (correct when narration with
    its own braces precedes a clean trailing JSON object), then falls back to "first { to last
    }" (correct for a bare object wrapped only in a markdown fence). Raises ValueError on no
    match, same as a bare json.loads would, so callers can catch both the same way."""
    if "{" not in text:
        raise ValueError("no '{' found in text")
    candidates = [(text.rindex("{"), len(text))]
    if "}" in text:
        candidates.append((text.index("{"), text.rindex("}") + 1))
    for start, end in candidates:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
    raise ValueError(f"no valid JSON object found in text: {text[:300]!r}")


def _draft_plate_prompt(idea: dict, register_counts: dict[str, int]) -> dict:
    """Returns {"prompt": str, "register": "reframe"|"observational", "quote_line": str}"""
    reframe_n = register_counts.get("reframe", 0)
    observational_n = register_counts.get("observational", 0)
    user = (
        f"Idea title: {idea['title']}\n"
        f"Idea description: {idea.get('description') or '(none)'}\n\n"
        f"Of the last {reframe_n + observational_n} auto-published ideas, {reframe_n} were "
        f"reframe register and {observational_n} were observational.\n\n"
        "Return ONLY the JSON object described in your instructions, no markdown fencing, "
        "no other text."
    )
    result = _anthropic_messages(system=PLATE_PROMPT_SYSTEM, user=user)
    text = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")
    try:
        parsed = _extract_json_object(text)
        if (
            not isinstance(parsed, dict)
            or not isinstance(parsed.get("prompt"), str)
            or parsed.get("register") not in ("reframe", "observational")
            or not isinstance(parsed.get("quote_line"), str)
        ):
            raise ValueError("missing/invalid required keys")
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=502, detail=f"Anthropic returned unexpected shape: {text[:500]}")
    return parsed


# Verbatim source: internal-docs/social/image-posts.md's "Caption Format" section — same
# not-deployed-to-the-VPS reasoning as PLATE_PROMPT_SYSTEM above.
CAPTION_SYSTEM = """\
You draft Instagram captions for Pancracio, a capybara plush toy character. Each post's IMAGE
already carries a dry, deadpan quote in the on-image typography — the caption you write is a
DIFFERENT, separate piece of text with a different register.

Key rule: the caption is openly motivational -- forward-driving, imperatives are fine, it pushes
the reader toward action. This is a deliberate contrast with the dry on-image quote. Do not write
cozy/withdrawn captions ("stay home, drink tea") -- that reads as passive. Motivational means
agency and direction.

Do NOT repeat the on-image quote verbatim -- the image already carries it. Extend the idea: one
line that adds a beat the image doesn't (a small concrete example, or the thought that comes
right after the quote).

Always use this exact hashtag set, unchanged:
#capybara #pancracio #mindfulness #calm #plushie #wisdom #zen #capybaras

Return ONLY a JSON object, no markdown fencing, no other text:
{"caption": "<the one-line caption text, no hashtags in this field>",
 "hashtags": "#capybara #pancracio #mindfulness #calm #plushie #wisdom #zen #capybaras"}
"""


def _draft_caption(idea: dict) -> dict:
    """Returns {"caption": str, "hashtags": str}"""
    user = (
        f"Idea title: {idea['title']}\n"
        f"On-image quote (the caption must NOT repeat this): {idea.get('quote_line') or '(none)'}\n"
        f"Register: {idea.get('register') or '(unknown)'}\n\n"
        "Return ONLY the JSON object described in your instructions, no markdown fencing, "
        "no other text."
    )
    result = _anthropic_messages(system=CAPTION_SYSTEM, user=user)
    text = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")
    try:
        parsed = _extract_json_object(text)
        if (
            not isinstance(parsed, dict)
            or not isinstance(parsed.get("caption"), str)
            or not isinstance(parsed.get("hashtags"), str)
        ):
            raise ValueError("missing/invalid required keys")
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=502, detail=f"Anthropic returned unexpected shape: {text[:500]}")
    return parsed


def _check_originality(line: str) -> dict:
    """Returns {"flagged": bool, "reason": str | None}. Fails closed on API error."""
    user = (
        f'Search the web to check whether this exact line is a near-exact match to a known '
        f'quote, book title, or famous phrase attributable to a specific source:\n\n"{line}"\n\n'
        "Common idioms or generic phrasing with no single attributable source should NOT flag — "
        "only near-exact matches to something specific and identifiable.\n\n"
        "After searching, respond with ONLY the JSON object below as your final answer — no "
        "explanation, no summary of what you found, no markdown fencing, nothing before or "
        "after it:\n"
        '{"flagged": true|false, "reason": "..." or null}'
    )
    try:
        result = _anthropic_messages(
            system=(
                "You are an originality checker for social-media quote copy. Be precise: only "
                "flag near-exact matches to a specific known quote/title, not loose thematic "
                "similarity or common idioms. Keep your final answer to just the requested JSON "
                "— do not narrate your search process or reasoning in the response."
            ),
            user=user,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            # Web search results themselves consume output-token budget alongside the model's
            # own text — 1500 (the default) was observed truncating before the final JSON on a
            # multi-result search, which fails closed but incorrectly on a genuinely original line.
            max_tokens=4096,
        )
        text = "".join(
            b["text"] for b in result.get("content", []) if b.get("type") == "text"
        ).strip()
        parsed = _extract_json_object(text)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("flagged"), bool):
            raise ValueError("missing/invalid 'flagged' key")
        flagged = parsed["flagged"]
        reason = parsed.get("reason")
    except HTTPException as e:
        # Anthropic returned a non-200 (bad key, rate limit, etc.) — _anthropic_messages
        # already turned that into an HTTPException.
        logger.warning("originality-check API call failed, failing closed: %s", e.detail)
        return {"flagged": True, "reason": f"originality check API call failed: {e.detail}"}
    except httpx.HTTPError as e:
        # Transport-level failure (timeout, connection error) — httpx raises these directly,
        # they don't go through _anthropic_messages' HTTPException path.
        logger.warning("originality-check network error, failing closed: %s", e)
        return {"flagged": True, "reason": f"originality check network error: {e}"}
    except (ValueError, json.JSONDecodeError):
        logger.warning("originality-check response unparseable, failing closed: %r", text[:300])
        return {"flagged": True, "reason": f"could not parse originality response: {text[:300]}"}

    logger.info("originality-check line=%r flagged=%s reason=%s", line, flagged, reason)
    return {"flagged": flagged, "reason": reason}


VISUAL_QA_SYSTEM = (
    "You are a visual QA checker for a finished Instagram post image (a composited quote card). "
    "Check for exactly two specific defect categories only, both found in real past generations:\n"
    "1. The quote text visually overlapping, touching, or crowding the character or any prop —\n"
    "   not just nearby, genuinely touching or crowding with little to no margin.\n"
    "2. A disconnected or illogical visual element — most commonly smoke/steam/mist rising from\n"
    "   empty space or the wrong object instead of its stated source (e.g. incense smoke that\n"
    "   doesn't connect to the incense stick), but also any other prop that looks physically\n"
    "   wrong or disconnected from what it's resting on/attached to.\n\n"
    "Do NOT flag general aesthetic opinions, composition taste, minor prop placement you'd do\n"
    "differently, or anything outside these two specific categories — those are accepted\n"
    "limitations of the pipeline, not defects this check exists to catch."
)


def _check_visual_quality(image_url: str) -> dict:
    """Returns {"flagged": bool, "reason": str | None}. Fails closed on API error — same
    contract as _check_originality. Vision-based gate added after two real defects (text
    overlapping the character, incense smoke disconnected from its source) shipped past manual
    review on the first real end-to-end test; see auto-publish-checklist.md's Post-Phase-4
    section. Deliberately narrow scope (two named categories) rather than open-ended "does this
    look good" — general aesthetic judgment from a vision model risks false positives that would
    fail real, fine posts closed for no good reason."""
    user = [
        {"type": "image", "source": {"type": "url", "url": image_url}},
        {
            "type": "text",
            "text": (
                "Check this image for the two defect categories in your instructions. Return "
                "ONLY a JSON object, no markdown fencing, no other text:\n"
                '{"flagged": true|false, "reason": "..." or null}'
            ),
        },
    ]
    try:
        result = _anthropic_messages(
            system=VISUAL_QA_SYSTEM, user=user, max_tokens=1024, model=VISUAL_QA_MODEL
        )
        text = "".join(
            b["text"] for b in result.get("content", []) if b.get("type") == "text"
        ).strip()
        parsed = _extract_json_object(text)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("flagged"), bool):
            raise ValueError("missing/invalid 'flagged' key")
        flagged = parsed["flagged"]
        reason = parsed.get("reason")
    except HTTPException as e:
        logger.warning("visual-quality-check API call failed, failing closed: %s", e.detail)
        return {"flagged": True, "reason": f"visual quality check API call failed: {e.detail}"}
    except httpx.HTTPError as e:
        logger.warning("visual-quality-check network error, failing closed: %s", e)
        return {"flagged": True, "reason": f"visual quality check network error: {e}"}
    except (ValueError, json.JSONDecodeError):
        logger.warning("visual-quality-check response unparseable, failing closed: %r", text[:300])
        return {"flagged": True, "reason": f"could not parse visual quality response: {text[:300]}"}

    logger.info("visual-quality-check image_url=%r flagged=%s reason=%s", image_url, flagged, reason)
    return {"flagged": flagged, "reason": reason}


def _crop_to_target(image_bytes: bytes, target_size: tuple[int, int] = PLATE_TARGET_SIZE) -> bytes:
    """OpenAI's gpt-image-1 has no exact 4:5 output size — the closest portrait option
    (1024x1536) is taller/narrower than our 1122x1402 target. Center-crop to the target
    aspect ratio first (preserves framing better than a naive stretch), then resize to the
    exact pixel dimensions Remotion's PancracioQuote composition expects."""
    img = Image.open(io.BytesIO(image_bytes))
    target_w, target_h = target_size
    target_ratio = target_w / target_h
    w, h = img.size
    if w / h > target_ratio:
        new_w = round(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = round(w / target_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    img = img.resize(target_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _generate_plate_image(idea_id: int, prompt: str) -> str:
    """Fetches the reference image, calls OpenAI's Images API, saves the result,
    returns the saved path (relative to the repo root)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured on the server")

    ref_setting = _get_setting("character_reference_image")
    if not ref_setting:
        raise HTTPException(
            status_code=400, detail="No character_reference_image configured — set one in Settings"
        )
    ref_path = BASE_DIR / ref_setting.removeprefix("/")
    if not ref_path.exists():
        raise HTTPException(status_code=400, detail=f"Reference image not found on disk: {ref_path}")

    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    content_type = mime.get(ref_path.suffix.lower(), "image/png")

    resp = httpx.post(
        OPENAI_IMAGES_EDIT_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        data={
            "model": OPENAI_IMAGE_MODEL,
            "prompt": prompt,
            "size": OPENAI_IMAGE_GEN_SIZE,
            "quality": OPENAI_IMAGE_QUALITY,
            "input_fidelity": OPENAI_IMAGE_INPUT_FIDELITY,
            "n": "1",
        },
        files={"image": (ref_path.name, ref_path.read_bytes(), content_type)},
        timeout=180,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {resp.text}")
    data = resp.json()
    raw = base64.b64decode(data["data"][0]["b64_json"])
    cropped = _crop_to_target(raw)

    dest = REMOTION_IMAGE_POSTS_DIR / f"idea-{idea_id}.png"
    dest.write_bytes(cropped)
    rel_path = f"remotion/public/image-posts/idea-{idea_id}.png"

    with _connect() as conn:
        conn.execute(
            "UPDATE ideas SET layout_image_path = ?, updated_at = datetime('now') WHERE id = ?",
            (rel_path, idea_id),
        )
    return rel_path


def _render_post_image(idea: dict) -> str:
    """Calls the render service to composite the quote card over the plate image, saves the
    result via the existing image-save convention. Called in-process from Phase 4's
    orchestrator, not exposed as its own internal endpoint — nothing to test in isolation here
    beyond what the render service's own feedback loop already covers."""
    if not idea.get("quote_line"):
        raise HTTPException(
            status_code=500,
            detail=f"Idea {idea['id']} has no quote_line — /internal/draft-prompt must run first",
        )
    background_url = f"{TRACKER_PUBLIC_BASE}/image-posts/idea-{idea['id']}.png"
    resp = httpx.post(
        f"http://{RENDER_VPS_HOST}:{RENDER_VPS_PORT}/render",
        data={
            "background_url": background_url,
            "quote_line": idea["quote_line"],
            "idea_id": idea["id"],
        },
        timeout=150,  # a little over the render service's own 120s subprocess timeout
    )
    resp.raise_for_status()
    path = _write_idea_image(idea["id"], "final", ".png", resp.content)
    with _connect() as conn:
        conn.execute(
            "UPDATE ideas SET final_image_path = ?, updated_at = datetime('now') WHERE id = ?",
            (path, idea["id"]),
        )
    return path


def _get_posts_for_idea(idea_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE idea_id = ? ORDER BY created_at DESC", (idea_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# --- Stats: all queries below only consider posts with metrics actually
# logged (likes IS NOT NULL) so unlogged posts don't skew averages to zero. ---

def _get_stats_summary() -> dict:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS post_count,
                   SUM(likes) AS total_likes, SUM(comments) AS total_comments,
                   SUM(views) AS total_views, SUM(shares) AS total_shares,
                   SUM(saves) AS total_saves,
                   AVG(likes) AS avg_likes, AVG(comments) AS avg_comments
            FROM posts
            WHERE likes IS NOT NULL
            """
        ).fetchone()
    return dict(row)


def _get_top_posts(limit: int = 10) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT i.id AS idea_id, i.title, i.category, i.content_type, i.score,
                   p.likes, p.comments, p.views, p.shares, p.saves, p.posted_at, p.post_url
            FROM posts p
            JOIN ideas i ON i.id = p.idea_id
            WHERE p.likes IS NOT NULL
            ORDER BY p.likes DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _get_stats_by_category() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(i.category, 'Uncategorized') AS label,
                   COUNT(*) AS post_count, AVG(p.likes) AS avg_likes
            FROM posts p JOIN ideas i ON i.id = p.idea_id
            WHERE p.likes IS NOT NULL
            GROUP BY label
            ORDER BY avg_likes DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def _get_stats_by_content_type() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT i.content_type AS label, COUNT(*) AS post_count,
                   AVG(p.likes) AS avg_likes
            FROM posts p JOIN ideas i ON i.id = p.idea_id
            WHERE p.likes IS NOT NULL
            GROUP BY i.content_type
            ORDER BY avg_likes DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def _get_stats_by_score() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT i.score AS label, COUNT(*) AS post_count, AVG(p.likes) AS avg_likes
            FROM posts p JOIN ideas i ON i.id = p.idea_id
            WHERE p.likes IS NOT NULL AND i.score IS NOT NULL
            GROUP BY i.score
            ORDER BY i.score DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/")
def index(
    request: Request,
    status: Optional[str] = None,
    content_type: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "score",
    page: int = 1,
    _: dict = Depends(get_current_user),
):
    page = max(page, 1)
    ideas, total = _get_ideas(
        status=status, content_type=content_type, q=q, sort=sort, page=page
    )
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "ideas": ideas,
            "statuses": STATUSES,
            "content_types": CONTENT_TYPES,
            "active_status": status or "",
            "active_content_type": content_type or "",
            "q": q or "",
            "sort": sort,
            "sort_options": list(SORT_OPTIONS.keys()),
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@app.get("/queue")
def queue_page(request: Request, _: dict = Depends(get_current_user)):
    ideas = _get_ready_queue()
    return templates.TemplateResponse(
        request, "queue.html", {"ideas": ideas, "statuses": STATUSES}
    )


@app.get("/stats")
def stats_page(request: Request, _: dict = Depends(get_current_user)):
    by_category = _get_stats_by_category()
    by_content_type = _get_stats_by_content_type()
    by_score = _get_stats_by_score()
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "summary": _get_stats_summary(),
            "top_posts": _get_top_posts(),
            "by_category": by_category,
            "by_content_type": by_content_type,
            "by_score": by_score,
            "max_category_likes": max((r["avg_likes"] or 0 for r in by_category), default=0),
            "max_content_type_likes": max((r["avg_likes"] or 0 for r in by_content_type), default=0),
            "max_score_likes": max((r["avg_likes"] or 0 for r in by_score), default=0),
        },
    )


@app.post("/ideas")
def create_idea(
    title: str = Form(...),
    content_type: str = Form("video"),
    description: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    inspiration_source: str = Form(""),
    user: dict = Depends(get_current_user),
):
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO ideas
                (title, content_type, description, category, tags, inspiration_source, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                content_type,
                description,
                category,
                tags,
                inspiration_source,
                user["id"] if user else None,
            ),
        )
    return RedirectResponse("/", status_code=303)


@app.get("/ideas/{idea_id}/edit")
def edit_idea_form(idea_id: int, request: Request, _: dict = Depends(get_current_user)):
    idea = _get_idea(idea_id)
    posts = _get_posts_for_idea(idea_id)
    activity = _get_idea_activity(idea_id)
    return templates.TemplateResponse(
        request,
        "edit.html",
        {
            "idea": idea,
            "posts": posts,
            "activity": activity,
            "statuses": STATUSES,
            "content_types": CONTENT_TYPES,
            "character_reference_image": _get_setting("character_reference_image"),
        },
    )


@app.post("/ideas/{idea_id}")
def update_idea(
    idea_id: int,
    title: str = Form(...),
    content_type: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    inspiration_source: str = Form(""),
    status: str = Form(...),
    score: str = Form(""),
    image_prompt: str = Form(""),
    scheduled_at: str = Form(""),
    caption: str = Form(""),
    hashtags: str = Form(""),
    auto_publish: bool = Form(False),
    user: dict = Depends(get_current_user),
):
    score_value = int(score) if score else None
    if auto_publish and not scheduled_at:
        scheduled_at = _default_scheduled_at()
    with _connect() as conn:
        prior = conn.execute(
            "SELECT auto_publish FROM ideas WHERE id = ?", (idea_id,)
        ).fetchone()
        if prior is None:
            raise HTTPException(status_code=404, detail="Idea not found")
        auto_publish_changed = bool(prior["auto_publish"]) != auto_publish

        cur = conn.execute(
            """
            UPDATE ideas
            SET title = ?, content_type = ?, description = ?, category = ?, tags = ?,
                inspiration_source = ?, status = ?, score = ?, image_prompt = ?,
                scheduled_at = ?, caption = ?, hashtags = ?, auto_publish = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (title, content_type, description, category, tags, inspiration_source,
             status, score_value, image_prompt, scheduled_at or None, caption, hashtags,
             1 if auto_publish else 0, idea_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Idea not found")
        _log_action(conn, user, idea_id, "edit")
        if auto_publish_changed:
            _log_action(conn, user, idea_id, "auto_publish_toggle")
    return RedirectResponse(f"/ideas/{idea_id}/edit", status_code=303)


@app.post("/ideas/{idea_id}/images")
def upload_idea_images(
    idea_id: int,
    layout_image: UploadFile = File(None),
    final_image: UploadFile = File(None),
    _: dict = Depends(get_current_user),
):
    _get_idea(idea_id)  # 404s if missing
    updates: dict[str, str] = {}
    if layout_image is not None and layout_image.filename:
        updates["layout_image_path"] = _save_idea_image(idea_id, "layout", layout_image)
    if final_image is not None and final_image.filename:
        updates["final_image_path"] = _save_idea_image(idea_id, "final", final_image)

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with _connect() as conn:
            conn.execute(
                f"UPDATE ideas SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
                list(updates.values()) + [idea_id],
            )
    return RedirectResponse(f"/ideas/{idea_id}/edit", status_code=303)


@app.post("/ideas/{idea_id}/status")
def bump_status(
    idea_id: int,
    status: str = Form(...),
    redirect_to: str = Form("/"),
    _: dict = Depends(get_current_user),
):
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE ideas SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, idea_id),
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Idea not found")
    # Only ever redirect to a same-app path — never an external URL.
    target = redirect_to if redirect_to.startswith("/") else "/"
    return RedirectResponse(target, status_code=303)


@app.get("/ideas/{idea_id}/post")
def mark_posted_form(idea_id: int, request: Request, _: dict = Depends(get_current_user)):
    idea = _get_idea(idea_id)
    return templates.TemplateResponse(
        request, "log_post.html", {"idea": idea}
    )


@app.post("/ideas/{idea_id}/post")
def mark_posted(
    idea_id: int,
    platform: str = Form("instagram"),
    post_url: str = Form(""),
    posted_at: str = Form(""),
    user: dict = Depends(get_current_user),
):
    _get_idea(idea_id)  # 404s if missing
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO posts (idea_id, platform, post_url, posted_at)
            VALUES (?, ?, ?, ?)
            """,
            (idea_id, platform, post_url, posted_at or None),
        )
        conn.execute(
            "UPDATE ideas SET status = 'posted', updated_at = datetime('now') WHERE id = ?",
            (idea_id,),
        )
        _log_action(conn, user, idea_id, "mark_posted")
    return RedirectResponse(f"/ideas/{idea_id}/edit", status_code=303)


def _int_or_none(v: str) -> Optional[int]:
    return int(v) if v.strip() else None


def _str_or_none(v: str) -> Optional[str]:
    return v.strip() if v.strip() else None


@app.post("/posts/{post_id}/metrics")
def update_metrics(
    post_id: int,
    post_url: str = Form(""),
    ig_media_id: str = Form(""),
    likes: str = Form(""),
    comments: str = Form(""),
    views: str = Form(""),
    shares: str = Form(""),
    saves: str = Form(""),
    notes: str = Form(""),
    _: dict = Depends(get_current_user),
):
    with _connect() as conn:
        row = conn.execute("SELECT idea_id FROM posts WHERE id = ?", (post_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        conn.execute(
            """
            UPDATE posts
            SET post_url = ?, ig_media_id = ?, likes = ?, comments = ?, views = ?,
                shares = ?, saves = ?, notes = ?, metrics_updated_at = datetime('now')
            WHERE id = ?
            """,
            (_str_or_none(post_url), _str_or_none(ig_media_id), _int_or_none(likes),
             _int_or_none(comments), _int_or_none(views), _int_or_none(shares),
             _int_or_none(saves), notes, post_id),
        )
        idea_id = row["idea_id"]
    return RedirectResponse(f"/ideas/{idea_id}/edit", status_code=303)


@app.post("/posts/{post_id}/notes")
def update_post_notes(
    post_id: int,
    notes: str = Form(""),
    _: dict = Depends(get_current_user),
):
    """Notes are the one thing on a post still edited by hand — everything else
    (metrics, ig_media_id) comes from the API/automation, never this form."""
    with _connect() as conn:
        row = conn.execute("SELECT idea_id FROM posts WHERE id = ?", (post_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        conn.execute("UPDATE posts SET notes = ? WHERE id = ?", (notes, post_id))
        idea_id = row["idea_id"]
    return RedirectResponse(f"/ideas/{idea_id}/edit", status_code=303)


def _fetch_ig_insights(media_id: str) -> dict[str, int]:
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="IG_ACCESS_TOKEN not configured on the server")
    params = urllib.parse.urlencode(
        {"metric": "likes,comments,saved,shares,views", "access_token": token}
    )
    url = f"{IG_GRAPH_BASE}/{media_id}/insights?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Instagram API error: {e.read().decode()}")
    return {item["name"]: item["values"][0]["value"] for item in data.get("data", [])}


def _ig_get(path: str, params: dict) -> dict:
    url = f"{IG_GRAPH_BASE}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Instagram API error: {e.read().decode()}")
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"Instagram API unreachable: {e}")


def _ig_post(path: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{IG_GRAPH_BASE}{path}", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Instagram API error: {e.read().decode()}")
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"Instagram API unreachable: {e}")


def _wait_for_container_ready(creation_id: str, token: str, timeout: float = 60, interval: float = 3) -> None:
    """New media containers process asynchronously on Instagram's side (fetching/validating
    image_url) — publishing immediately after creation can fail with 'Media ID is not
    available... please wait for a moment' (confirmed on a real publish attempt, not
    hypothetical). Polls status_code until FINISHED, raises on ERROR/EXPIRED or timeout."""
    deadline = time.monotonic() + timeout
    while True:
        status = _ig_get(f"/{creation_id}", {"fields": "status_code", "access_token": token})
        code = status.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise HTTPException(
                status_code=502, detail=f"Instagram media container {code}: {status}"
            )
        if time.monotonic() >= deadline:
            raise HTTPException(
                status_code=504,
                detail=f"Instagram media container not ready after {timeout}s (status={code})",
            )
        time.sleep(interval)


def _publish_to_instagram(idea: dict) -> dict:
    """Returns {"ig_media_id": str, "permalink": str}. Two-step Graph API call: create a media
    container, then publish it. On success, inserts a posts row and marks the idea 'posted' —
    same table/status the manual mark_posted() flow uses, so metrics refresh
    (POST /posts/{id}/refresh) works identically for auto- and manually-published posts."""
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="IG_ACCESS_TOKEN not configured on the server")
    image_url = f"{TRACKER_PUBLIC_BASE}{idea['final_image_path']}"
    caption = f"{idea['caption']}\n\n{idea['hashtags']}"
    container = _ig_post(
        "/me/media", {"image_url": image_url, "caption": caption, "access_token": token}
    )
    creation_id = container["id"]
    _wait_for_container_ready(creation_id, token)
    publish = _ig_post(
        "/me/media_publish", {"creation_id": creation_id, "access_token": token}
    )
    media_id = publish["id"]
    # Logged before the permalink fetch specifically: if that next call fails, the post is
    # already live on Instagram but untracked here (accepted edge case per spec-phase-4.md's
    # Error Handling table) — this is the one handle a human would need to reconcile it by hand.
    logger.info("instagram media published, media_id=%s, fetching permalink next", media_id)
    permalink = _ig_get(f"/{media_id}", {"fields": "permalink", "access_token": token})["permalink"]

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO posts (idea_id, platform, post_url, posted_at, ig_media_id)
            VALUES (?, 'instagram', ?, datetime('now'), ?)
            """,
            (idea["id"], permalink, media_id),
        )
        conn.execute(
            "UPDATE ideas SET status = 'posted', updated_at = datetime('now') WHERE id = ?",
            (idea["id"],),
        )
    return {"ig_media_id": media_id, "permalink": permalink}


@app.post("/posts/{post_id}/refresh")
def refresh_post_metrics(post_id: int, _: dict = Depends(get_current_user)):
    """Manual on-demand refresh — pulls current numbers straight from Instagram
    for this one post, using the same long-lived token the automation will use."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, idea_id, ig_media_id FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        if not row["ig_media_id"]:
            raise HTTPException(status_code=400, detail="This post has no ig_media_id set yet")
        metrics = _fetch_ig_insights(row["ig_media_id"])
        conn.execute(
            """
            UPDATE posts
            SET likes = ?, comments = ?, views = ?, shares = ?, saves = ?,
                metrics_updated_at = datetime('now')
            WHERE id = ?
            """,
            (metrics.get("likes"), metrics.get("comments"), metrics.get("views"),
             metrics.get("shares"), metrics.get("saved"), post_id),
        )
        idea_id = row["idea_id"]
    return RedirectResponse(f"/ideas/{idea_id}/edit", status_code=303)


class MediaMetricsPayload(BaseModel):
    likes: Optional[int] = None
    comments: Optional[int] = None
    views: Optional[int] = None
    shares: Optional[int] = None
    saves: Optional[int] = None


@app.get("/api/posts/tracked-media")
def tracked_media(_: dict = Depends(get_current_user)) -> list[dict]:
    """Posts with a known ig_media_id — what the automation should refresh metrics for."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id AS post_id, ig_media_id FROM posts WHERE ig_media_id IS NOT NULL"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/posts/by-media/{media_id}/metrics")
def update_metrics_by_media_id(
    media_id: str,
    payload: MediaMetricsPayload,
    _: dict = Depends(get_current_user),
) -> dict:
    """Automation writes metrics here by Instagram media ID — updates only, never creates."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM posts WHERE ig_media_id = ?", (media_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Unknown ig_media_id — skipped")
        conn.execute(
            """
            UPDATE posts
            SET likes = ?, comments = ?, views = ?, shares = ?, saves = ?,
                metrics_updated_at = datetime('now')
            WHERE id = ?
            """,
            (payload.likes, payload.comments, payload.views, payload.shares,
             payload.saves, row["id"]),
        )
    return {"status": "updated", "post_id": row["id"]}


def _get_ideas_api(
    status: Optional[str] = None,
    register: Optional[str] = None,
    auto_publish: Optional[bool] = None,
    due: Optional[bool] = None,
) -> list[dict]:
    where = "WHERE 1=1"
    params: list = []
    if status:
        where += " AND status = ?"
        params.append(status)
    if register:
        where += " AND register = ?"
        params.append(register)
    if auto_publish is not None:
        where += " AND auto_publish = ?"
        params.append(1 if auto_publish else 0)
    if due:
        # datetime(...) on both sides, not a raw string compare: scheduled_at is stored
        # 'T'-separated (HTML datetime-local / _default_scheduled_at()'s isoformat()) while
        # SQLite's datetime('now') is space-separated — a raw `scheduled_at <= datetime('now')`
        # silently compares 'T' vs ' ' lexicographically and is wrong for same-day times
        # (verified against production: a clearly-past 10:00 came back as not-yet-due).
        where += (
            " AND auto_publish = 1 AND status = 'idea'"
            " AND (scheduled_at IS NULL OR datetime(scheduled_at) <= datetime('now'))"
        )
    with _connect() as conn:
        rows = conn.execute(f"SELECT * FROM ideas {where}", params).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/ideas")
def api_list_ideas(
    status: Optional[str] = None,
    register: Optional[str] = None,
    auto_publish: Optional[bool] = None,
    due: Optional[bool] = None,
    _: dict = Depends(get_current_user),
) -> list[dict]:
    return _get_ideas_api(status=status, register=register, auto_publish=auto_publish, due=due)


@app.get("/api/ideas/{idea_id}")
def api_get_idea(idea_id: int, _: dict = Depends(get_current_user)) -> dict:
    return _get_idea(idea_id)  # 404s if missing


@app.get("/internal/register-counts")
def internal_register_counts(_: dict = Depends(get_current_user)) -> dict:
    """Debugging aid — current rolling reframe/observational counts."""
    return _get_recent_register_counts()


@app.post("/internal/draft-prompt")
def internal_draft_prompt(idea_id: int = Form(...), _: dict = Depends(get_current_user)) -> dict:
    idea = _get_idea(idea_id)  # 404s if missing
    counts = _get_recent_register_counts()
    drafted = _draft_plate_prompt(idea, counts)
    # Persisted so later pipeline steps (rendering, Phase 4's orchestrator) can read
    # register/quote_line/image_prompt straight off the idea row instead of threading them
    # through as call arguments across a chain of separate HTTP calls.
    with _connect() as conn:
        conn.execute(
            """
            UPDATE ideas SET register = ?, quote_line = ?, image_prompt = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (drafted["register"], drafted["quote_line"], drafted["prompt"], idea_id),
        )
    return drafted


@app.post("/internal/originality-check")
def internal_originality_check(line: str = Form(...), _: dict = Depends(get_current_user)) -> dict:
    return _check_originality(line)


@app.post("/internal/visual-quality-check")
def internal_visual_quality_check(idea_id: int = Form(...), _: dict = Depends(get_current_user)) -> dict:
    idea = _get_idea(idea_id)  # 404s if missing
    if not idea.get("final_image_path"):
        raise HTTPException(status_code=400, detail="Idea has no final_image_path yet")
    image_url = f"{TRACKER_PUBLIC_BASE}{idea['final_image_path']}"
    return _check_visual_quality(image_url)


@app.post("/internal/generate-plate")
def internal_generate_plate(
    idea_id: int = Form(...), prompt: str = Form(...), _: dict = Depends(get_current_user)
) -> dict:
    _get_idea(idea_id)  # 404s if missing
    path = _generate_plate_image(idea_id, prompt)
    return {"idea_id": idea_id, "layout_image_path": path}


@app.post("/internal/draft-caption")
def internal_draft_caption(idea_id: int = Form(...), _: dict = Depends(get_current_user)) -> dict:
    idea = _get_idea(idea_id)  # 404s if missing
    drafted = _draft_caption(idea)
    with _connect() as conn:
        conn.execute(
            "UPDATE ideas SET caption = ?, hashtags = ?, updated_at = datetime('now') WHERE id = ?",
            (drafted["caption"], drafted["hashtags"], idea_id),
        )
    return drafted


def _run_auto_publish_pipeline(idea_id: int, user: Optional[dict] = None) -> dict:
    """Draft -> originality check -> generate plate -> render -> visual quality check -> draft
    caption -> publish, as one unit: any exception marks the idea 'failed' and stops, no retry,
    no partial-success ambiguity. Called in-process from Phase 2/3's plain functions (not their
    HTTP endpoints), so their own persistence (layout/final image paths) still happens as each
    step completes — deliberately, so a failure partway through still leaves visible partial
    progress on the idea row for debugging, same as a human would want to see."""
    idea = _get_idea(idea_id)
    try:
        counts = _get_recent_register_counts()
        draft = _draft_plate_prompt(idea, counts)
        with _connect() as conn:
            conn.execute(
                """
                UPDATE ideas SET register = ?, quote_line = ?, image_prompt = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (draft["register"], draft["quote_line"], draft["prompt"], idea_id),
            )
        idea = {
            **idea,
            "register": draft["register"],
            "quote_line": draft["quote_line"],
            "image_prompt": draft["prompt"],
        }

        check = _check_originality(draft["quote_line"])
        if check["flagged"]:
            raise RuntimeError(f"originality check flagged: {check['reason']}")

        layout_path = _generate_plate_image(idea_id, draft["prompt"])
        idea = {**idea, "layout_image_path": layout_path}

        final_path = _render_post_image(idea)
        idea = {**idea, "final_image_path": final_path}

        visual_check = _check_visual_quality(f"{TRACKER_PUBLIC_BASE}{final_path}")
        if visual_check["flagged"]:
            raise RuntimeError(f"visual quality check flagged: {visual_check['reason']}")

        caption = _draft_caption(idea)
        with _connect() as conn:
            conn.execute(
                "UPDATE ideas SET caption = ?, hashtags = ?, updated_at = datetime('now') WHERE id = ?",
                (caption["caption"], caption["hashtags"], idea_id),
            )
        idea = {**idea, **caption}

        result = _publish_to_instagram(idea)
        with _connect() as conn:
            _log_action(conn, user, idea_id, "publish")
        return {"status": "posted", **result}
    except Exception as e:
        with _connect() as conn:
            conn.execute(
                "UPDATE ideas SET status = 'failed', updated_at = datetime('now') WHERE id = ?",
                (idea_id,),
            )
        raise HTTPException(status_code=500, detail=f"pipeline failed: {e}") from e


@app.post("/internal/run-pipeline/{idea_id}")
def run_pipeline(idea_id: int, user: dict = Depends(get_current_user)) -> dict:
    return _run_auto_publish_pipeline(idea_id, user)


@app.get("/settings")
def settings_page(request: Request, _: dict = Depends(get_current_user)):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "character_reference_image": _get_setting("character_reference_image"),
        },
    )


@app.post("/settings/character-reference")
def upload_character_reference(
    reference_image: UploadFile = File(...),
    _: dict = Depends(get_current_user),
):
    ext = Path(reference_image.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {ext or 'unknown'}")
    # Fixed filename — there's only ever one active reference image, so each
    # upload replaces the last one rather than accumulating orphaned files.
    for existing in UPLOAD_DIR.glob("character_reference.*"):
        existing.unlink()
    dest = UPLOAD_DIR / f"character_reference{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(reference_image.file, f)
    _set_setting("character_reference_image", f"/static/uploads/{dest.name}")
    return RedirectResponse("/settings", status_code=303)


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        # Compare against a dummy hash when the user doesn't exist, so a
        # nonexistent username and a wrong password take about the same time.
        stored_hash = row["password_hash"] if row else hash_password("dummy")
        if not row or not verify_password(password, stored_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessions (id, user_id) VALUES (?, ?)", (token, row["id"]))
        conn.commit()
    response = JSONResponse({"token": token, "ok": True})
    response.set_cookie(
        "pancracio_session",
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@app.post("/logout")
def logout(request: Request):
    token = request.cookies.get("pancracio_session") or ""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (token,))
        conn.commit()
    response = JSONResponse({"ok": True})
    response.delete_cookie("pancracio_session")
    return response


if __name__ == "__main__":
    import uvicorn

    _init_db()
    print(f"DB: {DB_PATH}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
