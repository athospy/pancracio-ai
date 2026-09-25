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
- Third-party API keys (Anthropic, OpenAI, Instagram) are never stored as n8n Credentials — they
  live in the tracker app's own environment on charmander and the render service's environment
  on this VPS. n8n's only job is scheduling + calling `/internal/run-pipeline/{idea_id}` once per
  due idea; see `docs/ideation/pancracio-auto-publish/spec-phase-4.md`.
- One n8n Credential *is* used (Phase 4): an `httpBasicAuth`-type credential holding the
  tracker's own Basic Auth user/pass, so the workflow's HTTP Request nodes can call the
  `check_auth`-gated tracker endpoints. Created via the n8n API, referenced by id/name only —
  the actual secret never appears in the exported `n8n/workflows/*.json`.

## Workflows

`n8n/workflows/auto-publish.json` — Hourly schedule trigger → `GET /api/ideas?due=true` → split
the JSON array response into one item per idea (explicit Code node, not relying on the HTTP
Request node's version-dependent array auto-splitting) → `POST
/internal/run-pipeline/{{ $json.id }}` per idea, with `onError: continueRegularOutput` so one
idea's pipeline failure doesn't block the rest of the batch, and `retryOnFail: false` per the
contract's explicit no-retry decision.

Built via the n8n REST API (not the UI) for reliability/reviewability — see
`internal-docs/ideas-tracker/lessons-learned.md` for the exact technique (including how to read
a freshly-created API key's full value from the network response body when the UI's own
copy-to-clipboard flow isn't available, e.g. in an automated browser).

**Left inactive on purpose** after Phase 4's implementation — activating arms the schedule
trigger for real, and the first time it finds a real due idea it publishes to Instagram. Needs
explicit go-ahead before flipping the active toggle; see
`internal-docs/ideas-tracker/auto-publish-pipeline.md`.
