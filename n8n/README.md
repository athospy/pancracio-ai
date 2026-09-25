# n8n (Pancracio auto-publish automation)

Runs the daily auto-publish pipeline: schedule trigger → ask the tracker which ideas are due →
call `/internal/run-pipeline/{idea_id}` for each. See
`docs/ideation/pancracio-auto-publish/` for the full design (contract + phase specs) and
`internal-docs/ideas-tracker/auto-publish-pipeline.md` for the end-to-end runbook once built.

**Runs on its own dedicated VPS, not charmander** (the tracker's box) — see
`docs/ideation/pancracio-auto-publish/spec-phase-1.md` for why: the resource-heavy piece is
Remotion's headless-Chromium rendering (Phase 3), not n8n itself, and charmander is already
tight running the tracker, Ardu, Ollama, and PostgreSQL. This VPS is dedicated to n8n +
rendering only.

## Start / stop

```bash
cd n8n
docker compose up -d      # start (detached)
docker compose logs -f    # follow logs
docker compose down       # stop (data persists in the n8n_data Docker volume)
```

UI: `ssh -L 5678:localhost:5678 <render-vps-alias>`, then `http://localhost:5678` in a local
browser — first visit asks you to create a local owner account (email + password, stored only
in the `n8n_data` volume, not sent anywhere). n8n is never exposed beyond this VPS's own
loopback interface (see `docker-compose.yml`'s port binding).

## One-time manual setup

1. Provision the render VPS (recommend at least 2 CPU / 4GB RAM given Phase 3's Chromium
   rendering) and share SSH access.
2. Install Docker: `apt install -y docker.io docker-compose-v2 && systemctl enable --now docker`.
3. `docker compose up -d` in this directory (rsync'd or cloned onto that VPS).
4. Create the n8n owner account on first UI visit (via the SSH tunnel above).
5. Enable n8n's REST API (Settings → API in the n8n UI) and generate an API key — needed for
   Phase 4's no-retry verification (`GET /api/v1/executions`).

## Notes

- `n8n_data` is a named Docker volume, not a bind mount — nothing here needs to be gitignored
  for it. Workflows get exported to `n8n/workflows/*.json` and committed explicitly instead,
  matching `job-finder/n8n/`'s own convention.
- `N8N_SECURE_COOKIE=false` is set because this is only ever accessed over `http://localhost`
  via the SSH tunnel, never HTTPS.
- No credentials are stored as n8n Credentials for this project — the pipeline logic (and every
  API key it needs) lives in the tracker app's own environment on charmander, and the Remotion
  render service on this same VPS. n8n's only job is scheduling + calling
  `/internal/run-pipeline/{idea_id}` once per due idea; see
  `docs/ideation/pancracio-auto-publish/spec-phase-4.md`.
