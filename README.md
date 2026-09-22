# Pancracio AI

AI-assisted character production for **Pancracio** — a capybara plush toy wearing a Paraguayan flag scarf and a Pittsburgh State University badge.

For current status (what's published, what's in progress) see [`CLAUDE.md`](CLAUDE.md) — kept as the single source of truth so status isn't duplicated and going stale in two places.

---

## Directory Map

```
pancracio-ai/
├── character/               Character reference assets (gitignored except top-level refs*)
├── image-post/              Final composited daily image posts (gitignored)
├── posts/                   Per-post video content — voice, video, final output (gitignored)
├── video-images/            Raw ChatGPT concept images + layout mockups (gitignored)
├── remotion/                Programmatic video/image composition (React/Remotion, tracked)
├── internal-docs/           Private runbooks and step-by-step guides (gitignored)
├── .claude/                 Claude Code project settings (tracked)
├── .agents/                 Locally-installed agent skill packs (gitignored)
└── skills-lock.json         Skill provenance lock for .agents/ (tracked)
```

\* `character/highres_*.png` (real-plush references) and `character/template_*.png` (raw
GPT-4o background plates) aren't matched by any `.gitignore` rule — only `character/cartoon/`
is excluded. Worth checking before a broad `git add character/`.

---

## `character/` — Who Pancracio Is

Two character versions are in use, anchored to different reference sets depending on the pipeline:

| File / dir | Description | Used by |
|---|---|---|
| `highres_initial.png` | Real plush, eyes closed, meditation pose | ElevenLabs (Reel video generation) |
| `highres_final.png` | Real plush, eyes open, sitting upright | ElevenLabs (Reel video generation) |
| `cartoon/` (gitignored) | GPT-4o 3D cartoon-render variants, zen room setting | ChatGPT image posts |
| `template_N.png` (gitignored) | Raw GPT-4o background plates, no text | Image post pipeline — copied into `remotion/public/image-posts/` |

**Character token** — paste this into every AI prompt to keep him on-model:
```
chubby capybara plush toy, round body, warm medium-brown fur, darker brown snout/face markings,
Paraguayan flag scarf (red stripe on top, white in the middle, blue on the bottom),
small Pittsburgh State University badge on chest (gold background, black gorilla),
sitting upright pose
```

Full consistency guide: `internal-docs/video-production/character-consistency.md`.

---

## `image-post/` — Daily Image Posts

Final, approved quote-card images ready for Instagram. Gitignored (local only).

Produced by the two-layer pipeline (GPT-4o background plate + Remotion typography) — see
`remotion/` below and `internal-docs/pipeline/quote-card-compositing.md`. Scheduling is
managed via Meta Business Suite; see `internal-docs/social/image-posts.md`.

---

## `posts/` — Reel Content

```
posts/
├── voice/                          Voice assets (ElevenLabs + Voicebox)
├── post-1/ post-2/ post-3/         Per-post video/voice candidates and finals
└── guide-to-being-less-available/  Long-form Reel render
```

All content is gitignored (local only, binary files). See `CLAUDE.md` for per-post status and
`internal-docs/social/next-session-prompt.md` to start a publishing session.

---

## `remotion/` — Programmatic Video & Image Composition

React/TypeScript project used to add captions, overlays, and branding on top of ElevenLabs Reel
clips, and to composite the typography layer on daily quote-card image posts.

```bash
# Preview in browser
cd remotion && npm run dev

# Render a video composition
cd remotion && npx remotion render GuideToBeingLessAvailable output/video.mp4

# Render a quote card (still image)
cd remotion && ./node_modules/.bin/remotion still PancracioQuote out/post-01.png --overwrite
```

Compositions currently registered — see [`remotion/README.md`](remotion/README.md) for the
full table and status of each.

Static assets (images, audio, fonts) live in `remotion/public/`. Source code and rendered
assets Remotion reads at build time are tracked in git; `node_modules/`, `out/`, and `dist/`
are gitignored.

See `internal-docs/integrations/remotion.md` for full documentation.

---

## `internal-docs/` — Private Runbooks

Not tracked in git. Contains all step-by-step guides — see
[`internal-docs/README.md`](internal-docs/README.md) for the full, maintained index.

---

## What's Tracked vs. Gitignored

**Tracked in git:**
- `remotion/src/` — video composition source code
- `remotion/public/` — reference images, fonts, and rendered assets Remotion reads at build time
- `.claude/settings.json`, `skills-lock.json` — Claude Code project config and skill provenance
- `CLAUDE.md`, `README.md`, `.gitignore`

**Gitignored (local only):**
- `character/cartoon/` — ChatGPT cartoon variants (see the directory-map note above for what's *not* covered)
- `image-post/` — final composited image posts
- `video-images/` — raw ChatGPT concept images + layout mockups
- `posts/` — all post audio/video (MP4, MP3)
- `internal-docs/` — private runbooks
- `.agents/` — locally-installed agent skill packs
- `remotion/node_modules/`, `remotion/out/`, `remotion/dist/` — build artifacts

---

## Active Production Pipelines

```
1. Video (Reel) pipeline — ElevenLabs generation, replaced PixVerse
character/highres_initial.png (eyes closed, single reference frame)
  → ElevenLabs video generation (credit-limited: ~2 Reel videos/month on current plan)
  → posts/candidates/ (raw video takes)
  → best candidate + voice (posts/voice/ — Voicebox preferred for new lines, free)
  → Remotion (captions, overlays, branding) — remotion/src/
  → posts/post-N/ (final video)
  → Instagram Reel

2. Image post pipeline (two-layer, batch 3 onward)
Claude drafts the GPT-4o prompt (character token + scene/props)
  → pasted into ChatGPT with character/cartoon/cartoon-seated-front.png (reference)
  → ChatGPT GPT-4o — text-free background plate
  → character/template_N.png → remotion/public/image-posts/
  → Remotion `PancracioQuote` still — composites the quote typography
  → remotion/out/ → image-post/ (final, once approved)
  → Instagram post (scheduled via Meta Business Suite at 10 AM)
```

PixVerse is retired — ElevenLabs now generates the Reel video directly, not just voice; its
credit plan caps this at ~2 videos/month, so pace Reel work accordingly. Historical PixVerse
notes live in `internal-docs/video-production/pixverse-meditation-prompt.md`.

GPT-4o does not typeset text reliably, so image posts split character generation from
typography — see `internal-docs/pipeline/quote-card-compositing.md` for why.
