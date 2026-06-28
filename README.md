# Pancracio AI

AI-assisted character production for **Pancracio** — a capybara plush toy wearing a Paraguayan flag scarf and a Pittsburgh State University badge.

---

## Directory Map

```
pancracio-ai/
├── character/               Character assets — cartoon variants (local only, gitignored)
├── image-post/              ChatGPT-generated image posts (local only, gitignored)
├── posts/                   Per-post content — voice, video, final output (local only, gitignored)
├── remotion/                Programmatic video composition (React/Remotion, tracked)
└── internal-docs/           Private runbooks and step-by-step guides (gitignored)
```

---

## `character/` — Who Pancracio Is

**Canonical reference images** are stored locally (not in git). The key ones:

| File | Description |
|------|-------------|
| `highres_initial.png` | **Canonical #1** — eyes closed, meditation pose, mudra hands |
| `highres_final.png` | **Canonical #2** — eyes open, sitting upright, alert pose |

**Subdirectories (gitignored, local only):**

| Directory | Contents |
|-----------|----------|
| `cartoon/` | ChatGPT-generated 2D cartoon variants (7 PNGs, Jun 20 2026 session) |

**Character token** — paste this into every AI prompt to keep him on-model:
```
chubby capybara plush toy, round body, warm medium-brown fur, darker brown snout/face markings,
Paraguayan flag scarf (red stripe on top, white in the middle, blue on the bottom),
small Pittsburgh State University badge on chest (gold background, black gorilla),
sitting upright pose
```

---

## `image-post/` — Daily Image Posts

ChatGPT-generated images for daily Instagram posts. Gitignored (local only).

Workflow and scheduling managed via Meta Business Suite. See `internal-docs/social/image-posts.md`.

---

## `posts/` — Video Content

```
posts/
├── voice/          Shared voice assets
│   └── pancracio_voice.mp3   ← master ElevenLabs voice (Eleven v3)
├── post-1/         PUBLISHED
├── post-2/         Video and voice ready
└── post-3/         Voice and video candidates ready
```

All content is gitignored (local only, binary files).

**Current status (June 2026):**
- Post 1 — published to Instagram as a Reel
- Post 2 — video and voice ready
- Post 3 — voice and video candidates ready

See `internal-docs/social/next-session-prompt.md` to start a Reel publishing session.

---

## `remotion/` — Programmatic Video Composition

React/TypeScript project for compositing video programmatically. Used to add captions, overlays, animated text, and branding on top of PixVerse character clips.

```bash
# Preview in browser
cd remotion && npm run dev

# Render to MP4
cd remotion && npx remotion render MyComp output/video.mp4
```

Static assets (images, audio) go in `remotion/public/`. Source code is tracked in git; `node_modules` and render output are gitignored.

See `internal-docs/integrations/remotion.md` for full documentation.

---

## `internal-docs/` — Private Runbooks

Not tracked in git. Contains all step-by-step guides:

| File | What it covers |
|------|----------------|
| `pipeline/chatgpt-cartoon-prompt.md` | Ready-to-paste GPT-4o prompt with Pancracio color codes |
| `video-production/character-consistency.md` | Character token + per-tool consistency guides |
| `video-production/pixverse-meditation-prompt.md` | PixVerse prompts + confirmed working baseline |
| `video-production/voice-production.md` | Voice history; final voice via ElevenLabs |
| `social/instagram-post-1.md` | Post 1 caption, hashtags, publishing checklist |
| `social/next-session-prompt.md` | Paste this at the start of an Instagram publishing session |
| `social/image-posts.md` | Daily image post workflow |
| `integrations/remotion.md` | Remotion APIs, workflow, and Claude Code skill setup |
| `integrations/playwright-mcp.md` | Playwright MCP setup for browser automation |
| `troubleshooting/common-issues.md` | MCP issues and common gotchas |

---

## What's Tracked vs. Gitignored

**Tracked in git:**
- `remotion/src/` — video composition source code
- `remotion/public/pancracio.png` — reference image for Remotion compositions

**Gitignored (local only):**
- `character/cartoon/` — ChatGPT cartoon variants
- `image-post/` — ChatGPT image posts
- `posts/` — all post audio/video (MP4, MP3)
- `internal-docs/` — private runbooks
- `remotion/node_modules/`, `remotion/out/` — build artifacts

---

## Active Production Pipeline

```
character/highres_initial.png  ← start from this for video
  → PixVerse (Reference mode, V6, Low motion, 8s)
  → best candidate + ElevenLabs voice (posts/voice/pancracio_voice.mp3)
  → Remotion (captions, overlays, branding) — remotion/
  → posts/post-N/ (final video)
  → Instagram Reel

character/highres_final.png + character/cartoon/
  → ChatGPT (GPT-4o image gen, character token)
  → image-post/ (daily image posts)
  → Instagram post (scheduled via Meta Business Suite)
```
