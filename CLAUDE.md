# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Pancracio AI** is a creative content pipeline for a capybara plush toy character named Pancracio (wearing a Paraguayan flag scarf and a Pittsburgh State University badge). The pipeline produces Instagram Reels and daily image posts.

This is **not** a traditional software project. Most production work is done via external tools (PixVerse, ElevenLabs, ChatGPT, Meta Business Suite), with runbooks documented in `internal-docs/` (gitignored, private). The only code in this repo is the `remotion/` video composition project.

## Key Commands

### Remotion — programmatic video composition
```bash
# Preview in browser with hot reload
cd remotion && npm run dev

# Render to MP4
cd remotion && npx remotion render MyComp output/video.mp4
```

### Video frame extraction (consistency verification)
```bash
ffmpeg -i posts/post-N/video.mp4 -vf fps=1 frames/frame_%04d.png
```

## Current Status (June 2026)

- Post 1 — published to Instagram as a Reel
- Post 2 — video and voice ready
- Post 3 — voice and video candidates ready
- Daily image posts — active, scheduled through Meta Business Suite
- Remotion — installed and working; next step is building a real composition for a post

See `internal-docs/social/next-session-prompt.md` to start a Reel publishing session.

## Architecture

Two active pipelines:

**1. Video Pipeline**
```
character/highres_initial.png (eyes closed, single reference frame)
  → PixVerse (Reference mode, V6, Low motion, 8s)
  → posts/candidates/ (raw video takes)
  → best candidate + ElevenLabs voice (posts/voice/pancracio_voice.mp3, Eleven v3)
  → Remotion (captions, overlays, branding) — remotion/src/
  → posts/post-N/ (final video)
  → Instagram Reel
```

**2. Image Post Pipeline**
```
character/highres_final.png + character/cartoon/ (cartoon variants)
  → ChatGPT GPT-4o image generation (character token + color codes)
  → image-post/ (output images)
  → Instagram post (scheduled via Meta Business Suite at 10 AM)
```

**Character Consistency System**
All AI generation is anchored to the canonical reference images (stored locally, not in git):
- `character/highres_initial.png` — eyes closed, meditation pose
- `character/highres_final.png` — eyes open, sitting upright

Character token (paste into every AI prompt):
```
chubby capybara plush toy, round body, warm medium-brown fur, darker brown snout/face markings,
Paraguayan flag scarf (red stripe on top, white in the middle, blue on the bottom),
small Pittsburgh State University badge on chest (gold background, black gorilla),
sitting upright pose
```

## What's Tracked vs. Gitignored

**Tracked:**
- `remotion/src/` — video composition source code
- `remotion/public/pancracio.png` — reference image for Remotion
- `CLAUDE.md`, `README.md`, `.gitignore`

**Gitignored (local only):**
- `character/cartoon/` — ChatGPT cartoon variants
- `image-post/` — ChatGPT image posts
- `posts/` — all post audio/video (MP4, MP3)
- `internal-docs/` — private runbooks
- `remotion/node_modules/`, `remotion/out/`

## Internal Documentation

`internal-docs/` (not in git) contains step-by-step runbooks. Check there before doing anything in these areas:
- `pipeline/chatgpt-cartoon-prompt.md` — ready-to-use GPT-4o prompt with color codes
- `video-production/character-consistency.md` — character token + per-tool consistency guides
- `video-production/pixverse-meditation-prompt.md` — PixVerse prompts; confirmed working baseline
- `video-production/voice-production.md` — voice history; final voice via ElevenLabs
- `social/next-session-prompt.md` — paste this to start a publishing session
- `social/image-posts.md` — daily image post workflow
- `integrations/remotion.md` — Remotion APIs, workflow, Claude Code skill setup
- `integrations/playwright-mcp.md` — Playwright MCP setup for browser automation
- `troubleshooting/common-issues.md` — MCP issues and common gotchas

## External Dependencies

- **PixVerse** — AI video generation (web app, paid)
- **ElevenLabs** — voice synthesis (Eleven v3, calm male voice)
- **ChatGPT GPT-4o** — image generation for cartoons and image posts
- **Meta Business Suite** — Instagram post scheduling
- **Remotion** — programmatic video composition (`remotion/`, Node.js)
