"""
FastAPI web app for tracking Pancracio content ideas.

Run from web/:
    uvicorn app:app --reload
Then open http://localhost:8000
"""

import json
import os
import secrets
import shutil
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "pancracio.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

app = FastAPI(title="Pancracio Ideas Tracker")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

security = HTTPBasic()

STATUSES = ["idea", "scripted", "ready", "posted", "archived", "failed"]
CONTENT_TYPES = ["video", "image"]

PAGE_SIZE = 20
SORT_OPTIONS = {
    "score": "(score IS NULL), score DESC, created_at DESC",
    "newest": "created_at DESC",
    "oldest": "created_at ASC",
    "title": "title COLLATE NOCASE ASC",
}
IG_GRAPH_BASE = "https://graph.instagram.com/v21.0"


def check_auth(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    """Gate every route behind HTTP Basic Auth — this is a private, single-user tool."""
    expected_user = os.environ.get("PANCRACIO_AUTH_USER")
    expected_pass = os.environ.get("PANCRACIO_AUTH_PASS")
    if not expected_user or not expected_pass:
        raise HTTPException(
            status_code=500,
            detail="PANCRACIO_AUTH_USER / PANCRACIO_AUTH_PASS not configured",
        )
    user_ok = secrets.compare_digest(credentials.username, expected_user)
    pass_ok = secrets.compare_digest(credentials.password, expected_pass)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
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
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO ideas_new SELECT
          id, title, content_type, description, category, tags, inspiration_source,
          status, score, layout_image_path, final_image_path, image_prompt,
          scheduled_at, caption, hashtags, auto_publish, register, created_at, updated_at
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

        # Must run after the two guards above so ideas_new's INSERT ... SELECT
        # (which names auto_publish/register explicitly) is valid on first deploy too.
        _migrate_ideas_status_check(conn)


@app.on_event("startup")
def on_startup() -> None:
    _init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _save_idea_image(idea_id: int, kind: str, upload: UploadFile) -> str:
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {ext or 'unknown'}")
    # Remove any previous file for this idea/kind in case the extension changed.
    for existing in UPLOAD_DIR.glob(f"idea_{idea_id}_{kind}.*"):
        existing.unlink()
    dest = UPLOAD_DIR / f"idea_{idea_id}_{kind}{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return f"/static/uploads/{dest.name}"


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
            SELECT id, title, content_type, description, category, tags,
                   inspiration_source, status, score, scheduled_at,
                   layout_image_path, final_image_path, created_at, updated_at
            FROM ideas
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
        row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    return dict(row)


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
    _: None = Depends(check_auth),
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
def queue_page(request: Request, _: None = Depends(check_auth)):
    ideas = _get_ready_queue()
    return templates.TemplateResponse(
        request, "queue.html", {"ideas": ideas, "statuses": STATUSES}
    )


@app.get("/stats")
def stats_page(request: Request, _: None = Depends(check_auth)):
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
    _: None = Depends(check_auth),
):
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO ideas (title, content_type, description, category, tags, inspiration_source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, content_type, description, category, tags, inspiration_source),
        )
    return RedirectResponse("/", status_code=303)


@app.get("/ideas/{idea_id}/edit")
def edit_idea_form(idea_id: int, request: Request, _: None = Depends(check_auth)):
    idea = _get_idea(idea_id)
    posts = _get_posts_for_idea(idea_id)
    return templates.TemplateResponse(
        request,
        "edit.html",
        {
            "idea": idea,
            "posts": posts,
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
    _: None = Depends(check_auth),
):
    score_value = int(score) if score else None
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE ideas
            SET title = ?, content_type = ?, description = ?, category = ?, tags = ?,
                inspiration_source = ?, status = ?, score = ?, image_prompt = ?,
                scheduled_at = ?, caption = ?, hashtags = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (title, content_type, description, category, tags, inspiration_source,
             status, score_value, image_prompt, scheduled_at or None, caption, hashtags,
             idea_id),
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Idea not found")
    return RedirectResponse(f"/ideas/{idea_id}/edit", status_code=303)


@app.post("/ideas/{idea_id}/images")
def upload_idea_images(
    idea_id: int,
    layout_image: UploadFile = File(None),
    final_image: UploadFile = File(None),
    _: None = Depends(check_auth),
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
    _: None = Depends(check_auth),
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
def mark_posted_form(idea_id: int, request: Request, _: None = Depends(check_auth)):
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
    _: None = Depends(check_auth),
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
    _: None = Depends(check_auth),
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
    _: None = Depends(check_auth),
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


@app.post("/posts/{post_id}/refresh")
def refresh_post_metrics(post_id: int, _: None = Depends(check_auth)):
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
def tracked_media(_: None = Depends(check_auth)) -> list[dict]:
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
    _: None = Depends(check_auth),
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
    with _connect() as conn:
        rows = conn.execute(f"SELECT * FROM ideas {where}", params).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/ideas")
def api_list_ideas(
    status: Optional[str] = None,
    register: Optional[str] = None,
    auto_publish: Optional[bool] = None,
    _: None = Depends(check_auth),
) -> list[dict]:
    return _get_ideas_api(status=status, register=register, auto_publish=auto_publish)


@app.get("/api/ideas/{idea_id}")
def api_get_idea(idea_id: int, _: None = Depends(check_auth)) -> dict:
    return _get_idea(idea_id)  # 404s if missing


@app.get("/settings")
def settings_page(request: Request, _: None = Depends(check_auth)):
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
    _: None = Depends(check_auth),
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


if __name__ == "__main__":
    import uvicorn

    _init_db()
    print(f"DB: {DB_PATH}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
