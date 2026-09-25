# Render Service (Pancracio auto-publish, Phase 3)

Tiny FastAPI service that composites the daily quote card: takes a background-plate URL + quote
text, shells out to the Remotion CLI (`PancracioQuote` still-render), returns the resulting PNG.
Called by the tracker app on charmander (`_render_post_image()` in `web/app.py`), not n8n — see
`docs/ideation/pancracio-auto-publish/spec-phase-3.md` for the full design and why.

**Runs on the render VPS, colocated with n8n** (see `n8n/README.md`) — same box, separate
systemd service, separate deploy path (no CI, unlike the tracker's GitHub Actions pipeline; this
is small enough that a manual `rsync` + restart is simpler than setting one up).

## Redeploying

```bash
rsync -az --exclude=venv -e ssh render-service/ <render-vps-alias>:~/pancracio-render/render-service/
ssh <render-vps-alias> "cd ~/pancracio-render/render-service && venv/bin/pip install -q -r requirements.txt && sudo systemctl restart pancracio-render.service"
```

If `web/src`/`web/public` (the Remotion project itself, not this service) changed, also re-sync
`remotion/` and re-run `npm install` there — see the "Remotion environment" steps below.

## One-time manual setup (already done — for reference / rebuilding)

1. **Node 20 + npm** (the VPS's stock `nodejs` package was 18.x with no `npm` at all):
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
   apt-get install -y nodejs
   ```
2. **Remotion project**, synced separately from this service (it needs the full React source +
   fonts + public assets, not just this thin wrapper):
   ```bash
   rsync -az --exclude=node_modules --exclude=out -e ssh remotion/ <render-vps-alias>:~/pancracio-render/remotion/
   ssh <render-vps-alias> "cd ~/pancracio-render/remotion && npm install"
   ```
   Remotion manages its own headless-Chromium binary — no system Chrome/shared-library packages
   were needed on this VPS (Ubuntu 24.04), confirmed by just attempting a render. If a fresh VPS
   fails here, the error will name whichever shared library is missing
   (`libnss3`/`libatk1.0-0`/`libgbm1` are the classic ones).
3. **This service**:
   ```bash
   python3 -m venv venv   # needs `apt install -y python3.12-venv` first if ensurepip is missing
   venv/bin/pip install -r requirements.txt
   ```
4. **systemd unit** (`pancracio-render.service`, this directory — copy to
   `/etc/systemd/system/`, `systemctl daemon-reload && systemctl enable --now
   pancracio-render.service`). Binds `0.0.0.0:8090` (not loopback — charmander needs to reach it
   over the network) with no auth; safety comes entirely from the firewall rule below, matching
   n8n's own "trust the network boundary" model.
5. **Firewall** — restricts port 8090 to charmander's IP only:
   ```bash
   ufw allow OpenSSH   # do this FIRST, or enabling ufw locks out SSH
   ufw allow from <charmander-ip> to any port 8090 proto tcp comment 'pancracio render service - charmander only'
   ufw enable
   ```

## Adaptive text layout

The generated background plates (OpenAI `gpt-image-1`) don't reliably leave the same clear space
the project's manual ChatGPT-based process did — sometimes the character extends further left
than expected, which used to make the quote text visually overlap/cut off behind him (a real,
confirmed defect, not hypothetical — found testing the first real candidate post).

Fixed by scanning the actual generated image before compositing, instead of trusting fixed
`textWidth`/`quoteFontSize` constants for every render:
- `_find_safe_text_width()` scans the plate for how much genuinely clear space exists to the
  right of the text column's left edge, using local pixel variance (`_is_flat_region` — flat =
  safe, textured/edges = character or prop) rather than a fixed background color, since the
  frame legitimately contains two different flat materials (wall, wood floor) at different tones.
- `_fit_text_layout()` scales font size and wrap width down together from the baseline as
  needed, so the quote also fits vertically — this incidentally fixed a previously-accepted
  Phase 3 limitation too (a long quote overflowing past the bottom of the frame).

This is why Pillow is now a dependency (`requirements.txt`) — needed for the pixel scan, on top
of what Remotion itself needs. See `internal-docs/ideas-tracker/auto-publish-checklist.md`'s
"Post-Phase-4" section for the full investigation and before/after comparisons.

## Notes

- No auth token on `/render` — the firewall rule is the only access control, since only
  charmander can reach the port at all.
- `subprocess.run` is always called with an argument list, never `shell=True` or an interpolated
  string — quote lines are idea-controlled text and must never be able to reach a shell.
- `timeout=120` on the Remotion subprocess so a hung render can't block the pipeline forever;
  Phase 4's orchestrator treats that idea as failed, no retry.
