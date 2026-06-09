# Pancracio AI

AI-assisted character production for **Pancracio** — a capybara plush toy wearing a Paraguayan flag scarf and a Pittsburgh State University badge.

## What's here

```
pancracio-photos/          # 28 iPhone HEIC photos (source for 3D scan)
pancracio-web/             # Static web AR viewer (model-viewer, iOS AR Quick Look)
pancracio-ai-model/        # Reference images, renders, generated videos
  highres_initial.png      # Canonical reference: meditation pose (eyes closed)
  highres_final.png        # Canonical reference: alert pose (eyes open)
  renders/                 # 4-angle renders from the 3D model
photogrammetry-output/     # USDZ + OBJ from Apple RealityKit Object Capture
midjourney-screenshots/    # Midjourney session captures
internal-docs/             # Private runbooks and pipeline notes (not tracked)
```

## Running the web viewer

```bash
cd pancracio-web && python3 -m http.server 8080
# open http://localhost:8080
```

Open on iPhone for AR Quick Look.

## Character reference

Always anchor generations to these two images:

- `pancracio-ai-model/highres_initial.png` — eyes closed, mudra hand, meditation pose
- `pancracio-ai-model/highres_final.png` — eyes open, sitting upright, alert pose

See `internal-docs/video-production/character-consistency.md` for the full generation guide.
