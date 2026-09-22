<p align="center">
  <a href="https://github.com/remotion-dev/logo">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://github.com/remotion-dev/logo/raw/main/animated-logo-banner-dark.apng">
      <img alt="Animated Remotion Logo" src="https://github.com/remotion-dev/logo/raw/main/animated-logo-banner-light.gif">
    </picture>
  </a>
</p>

# Pancracio — Remotion

Programmatic video/image compositing for [Pancracio](../README.md)'s Instagram content:
captions and branding on top of PixVerse Reel clips, and the typography layer for daily
quote-card image posts.

## Setup

```bash
npm i
```

## Compositions

| ID | Type | Frame size | Status |
|---|---|---|---|
| [`MyComposition`](src/Composition.tsx) | Composition | 1280×720 | Remotion starter template — unused |
| [`CloseTabs`](src/CloseTabs.tsx) | Composition | 1080×1920 | Retired — wrong avatar, off-brand concept. See [lessons-learned.md](../internal-docs/video-production/lessons-learned.md) |
| [`GuideToBeingLessAvailable`](src/GuideToBeingLessAvailable.tsx) | Composition | 1080×1920 | **Published** — [Reel](https://www.instagram.com/reels/Da_q4jxpiAy/). Build log: [guide-to-being-less-available.md](../internal-docs/video-production/guide-to-being-less-available.md) |
| [`PancracioQuote`](src/PancracioQuote.tsx) | Still | 1122×1402 | **Active** — typography layer for every daily image post batch. See [quote-card-compositing.md](../internal-docs/pipeline/quote-card-compositing.md) |

## Commands

**Preview in browser (hot reload)**

```bash
npm run dev
```

**Render a video composition**

```bash
npx remotion render GuideToBeingLessAvailable output/video.mp4
```

**Render a quote card (still image)**

```bash
./node_modules/.bin/remotion still PancracioQuote out/post-01.png --overwrite
```

**Upgrade Remotion**

```bash
npx remotion upgrade
```

## Docs

- [`internal-docs/integrations/remotion.md`](../internal-docs/integrations/remotion.md) — project-specific Remotion notes and Claude Code skill setup
- [Remotion fundamentals](https://www.remotion.dev/docs/the-fundamentals) — official getting-started guide
- [Discord](https://discord.gg/6VzzNDwUwV) — Remotion community help
- [File an issue](https://github.com/remotion-dev/remotion/issues/new) — Remotion framework bugs
- [License](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md) — a company license may be required for some entities
