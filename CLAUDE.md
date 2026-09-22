# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Pancracio AI** is a creative content pipeline for a capybara plush toy character named Pancracio (wearing a Paraguayan flag scarf and a Pittsburgh State University badge). The pipeline produces Instagram Reels and daily image posts.

This is **not** a traditional software project. Most production work is done via external tools (ElevenLabs, ChatGPT, Meta Business Suite), with prompts for image posts drafted in Claude first, and runbooks documented in `internal-docs/` (gitignored, private). The only code in this repo is the `remotion/` video composition project.

## Key Commands

### Remotion — programmatic video composition
```bash
# Preview in browser with hot reload
cd remotion && npm run dev

# Render to MP4
cd remotion && npx remotion render MyComp output/video.mp4

# Render a daily image post (quote card) — text is composited here, not by GPT-4o.
# See internal-docs/pipeline/quote-card-compositing.md
cd remotion && ./node_modules/.bin/remotion still PancracioQuote out/post-01.png --overwrite
```

### Video frame extraction (consistency verification)
```bash
ffmpeg -i posts/post-N/video.mp4 -vf fps=1 frames/frame_%04d.png
```

## Current Status (September 2026)

- Post 1 — published to Instagram as a Reel
- Post 2 — video and voice ready
- Post 3 — voice and video candidates ready
- Daily image posts — **14 published across 2 batches**, all files in `image-post/`
  - Batch 1 (Jun 2026, 7 posts, 4:5) — observational register
  - Batch 2 (Jul 2026, 7 posts, 1:1) — reframe register; lived in `second-posts/` under raw
    ChatGPT filenames until consolidated into `image-post/` on Sep 13 2026
  - Batch 3 (Sep 2026, 10 posts, 4:5) — planned, not yet generated. See
    `internal-docs/sept-2026-image-post/plan.txt`
  - **Voice registers matter** — see `internal-docs/social/image-posts.md`. The observational
    register (concrete modern-life noun + deadpan twist) is the account's differentiator; the
    reframe register reads as generic motivational content. Target ~6 reframe / ~4 observational
    per batch, and search every line before generating (batch 2 shipped a verbatim book title).
- Remotion — `CloseTabs` composition built and registered (not used further — see
  `internal-docs/video-production/lessons-learned.md`)
- "Pancracio's Guide to Being Less Available" (long-form Reel, 2:30–3:00 target,
  published at 1:50) — **published to Instagram**:
  https://www.instagram.com/reels/Da_q4jxpiAy/. Built end-to-end via a new
  `GuideToBeingLessAvailable` Remotion composition + Voicebox voice; full build log in
  `internal-docs/video-production/guide-to-being-less-available.md`

See `internal-docs/social/next-session-prompt.md` to start a Reel publishing session.

## Architecture

Two active pipelines:

**1. Video Pipeline** (ElevenLabs generation, replaced PixVerse — see note below)
```
character/highres_initial.png (eyes closed, single reference frame)
  → ElevenLabs video generation (credit-limited: ~2 Reel videos/month on current plan)
  → posts/candidates/ (raw video takes)
  → best candidate + voice (posts/voice/ — Voicebox preferred for new lines, free;
    older posts used ElevenLabs Eleven v3 voice directly)
  → Remotion (captions, overlays, branding) — remotion/src/
  → posts/post-N/ (final video)
  → Instagram Reel
```
PixVerse is retired — ElevenLabs now generates the Reel video directly rather than just the
voice. ElevenLabs' credit plan caps this at ~2 videos/month, so pace Reel work accordingly.
Historical PixVerse prompts/CLI notes are kept for reference in
`internal-docs/video-production/pixverse-meditation-prompt.md` and
`internal-docs/integrations/pixverse-cli.md`.

**2. Image Post Pipeline** (two-layer, batch 3 onward)
```
Claude drafts the GPT-4o prompt (character token + scene/props)
  → pasted into ChatGPT along with character/cartoon/cartoon-seated-front.png (reference)
  → ChatGPT GPT-4o — TEXT-FREE background plate (Pancracio + props, empty left wall)
  → character/template_N.png → remotion/public/image-posts/
  → Remotion `PancracioQuote` still — composites the quote typography
  → remotion/out/ → image-post/ (final, once approved)
  → Instagram post (scheduled via Meta Business Suite at 10 AM)
```
GPT-4o does not typeset text — asking it for the character and the typography at once
produced mangled words and a layout that re-rolled on every fix. The split makes text
correct by construction. See `internal-docs/pipeline/quote-card-compositing.md`.

**Character Consistency System**

Two character versions in use — pick based on the pipeline:

**Real plush (for Reel video generation):** anchor to the highres photos (stored locally, not in git):
- `character/highres_initial.png` — eyes closed, meditation pose (primary reference for ElevenLabs video generation)
- `character/highres_final.png` — eyes open, sitting upright

**3D cartoon render (for ChatGPT image posts):** anchor to `character/cartoon/` (gitignored). These are GPT-4o generated 3D plush-toy style renders in a zen room setting. Key files:
- `cartoon-seated-front.png` — primary reference (front-facing, full body)
- `cartoon-meditation-wide.png` — full scene with props layout
- `cartoon-portrait-face.png` — close-up face detail
- `cartoon-arms-outstretched.png` — standing with arms out (for action poses)
- `cartoon-back-view.png` — back of character (shows scarf drape)

Character traits (consistent across both versions):
- Chubby round body, warm golden-brown fur, darker brown snout
- Paraguayan flag scarf (red on top, white in middle, blue on bottom)
- Big expressive brown eyes, slight serious/contemplative expression
- **PSU badge**: specified in prompts but rarely visible in cartoon outputs — don't worry if missing

Character token (paste into AI prompts):
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
- `remotion/public/fonts/` — Playfair Display woff2 subsets for the quote cards
- `remotion/public/image-posts/`, `remotion/public/guide-to-being-less-available/` — rendered assets Remotion reads at render time
- `.claude/settings.json`, `skills-lock.json` — Claude Code project config and skill provenance
- `CLAUDE.md`, `README.md`, `.gitignore`

**Gitignored (local only):**
- `character/cartoon/` — ChatGPT cartoon variants (note: `character/highres_*.png` and `character/template_*.png` are NOT covered by any rule — double-check before a broad `git add character/`)
- `image-post/` — final composited image posts
- `video-images/` — raw ChatGPT concept images + layout mockups
- `posts/` — all post audio/video (MP4, MP3)
- `internal-docs/` — private runbooks
- `.agents/` — locally-installed agent skill packs
- `remotion/node_modules/`, `remotion/out/`, `remotion/dist/`

## Internal Documentation

`internal-docs/` (not in git) contains step-by-step runbooks. Check there before doing anything in these areas:
- `pipeline/chatgpt-cartoon-prompt.md` — ready-to-use GPT-4o prompt with color codes
- `video-production/character-consistency.md` — character token + per-tool consistency guides
- `video-production/pixverse-meditation-prompt.md` — PixVerse prompts; historical, PixVerse is retired
- `video-production/voice-production.md` — voice history; final voice via ElevenLabs
- `social/next-session-prompt.md` — paste this to start a publishing session
- `social/image-posts.md` — daily image post workflow + published post list
- `pipeline/chatgpt-image-post-prompt.md` — GPT-4o plate prompt + layout template for image posts
- `pipeline/quote-card-compositing.md` — **two-layer quote card pipeline** (GPT-4o plate + Remotion type)
- `integrations/remotion.md` — Remotion APIs, workflow, Claude Code skill setup
- `integrations/playwright-mcp.md` — Playwright MCP setup for browser automation
- `troubleshooting/common-issues.md` — MCP issues and common gotchas

## External Dependencies

- **ElevenLabs** — Reel video generation (replaced PixVerse); credit plan caps this at ~2 videos/month. Also the source of the original Eleven v3 voice track
- **Voicebox** — local voice cloning (free); preferred over ElevenLabs for new voice lines — see `internal-docs/video-production/voicebox-cloning.md`
- **Claude** — drafts image-post prompts before they're pasted into ChatGPT
- **ChatGPT GPT-4o** — image generation for cartoons and image posts
- **Meta Business Suite** — Instagram post scheduling
- **Remotion** — programmatic video composition (`remotion/`, Node.js)
- **PixVerse** — retired, no longer used for video generation. Historical prompts/CLI notes kept in `internal-docs/video-production/pixverse-meditation-prompt.md` and `internal-docs/integrations/pixverse-cli.md`
