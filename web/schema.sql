CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'video' CHECK (content_type IN ('image', 'video')),
  description TEXT,
  category TEXT,
  tags TEXT,
  inspiration_source TEXT,
  status TEXT NOT NULL DEFAULT 'idea'
    CHECK (status IN ('idea', 'scripted', 'ready', 'posted', 'archived')),
  score INTEGER CHECK (score BETWEEN 1 AND 5),
  layout_image_path TEXT,
  final_image_path TEXT,
  image_prompt TEXT,
  scheduled_at TEXT,
  caption TEXT,
  hashtags TEXT,
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

CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);
CREATE INDEX IF NOT EXISTS idx_posts_idea_id ON posts(idea_id);
