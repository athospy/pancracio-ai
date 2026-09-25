CREATE TABLE IF NOT EXISTS ideas (
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

CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER NOT NULL REFERENCES ideas(id),
  platform TEXT NOT NULL DEFAULT 'instagram',
  post_url TEXT,
  posted_at TEXT,
  likes INTEGER,
  comments INTEGER,
  views INTEGER,
  shares INTEGER,
  saves INTEGER,
  notes TEXT,
  metrics_updated_at TEXT,
  ig_media_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Small global key/value store — currently just the character-consistency
-- reference image, but kept generic so a future n8n workflow (or this app)
-- can read/write other global config without another schema change.
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- id is the credential value itself (a random token), not a surrogate key —
-- a browser's session cookie and n8n's long-lived bearer token are both just
-- rows in this table, looked up the same way. No expiry: revocation is
-- deleting the row (logout, or a manual DB delete for a lost/compromised token).
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per logged action (edit, auto_publish toggle, publish, mark-posted).
-- idea_id is nullable only for future-proofing (a non-idea-scoped action) —
-- every call site today always passes one. No CHECK-constrained action enum:
-- the vocabulary is enforced at the Python call sites instead, since a CHECK
-- change here would need the same table-rebuild dance as ideas.status above,
-- not worth the ceremony for 4 known action types.
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  idea_id INTEGER REFERENCES ideas(id),
  action TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);
CREATE INDEX IF NOT EXISTS idx_posts_idea_id ON posts(idea_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_idea_id ON audit_log(idea_id);
