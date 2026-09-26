# Ideation Learnings

Generalizable spec-gap and interview patterns captured from completed
ideation projects. Intake reads this file so recurring gaps inform future
questioning and spec generation. Each entry is dated and cites its
evidence; treat entries as hints, never as a substitute for gate evidence.

## 2026-09-25 — pancracio-user-accounts

- **Pattern**: A spec step that requires a live deployed instance plus external-system credentials (an API key, SSH access, a real login against production) can't actually be completed during local `execute-spec` — the builder has neither the deployment nor the credentials in scope.
  **Evidence**: Phase 1, "n8n cutover" note — minting a bearer token needed a live `POST /login` against the deployed tracker, and creating the n8n credential needed n8n's REST API; neither was available mid-build. The workflow JSON was correctly left untouched rather than hand-inventing a credential id, matching this project's own "committed file matches exactly what's deployed" convention.
  **Spec/interview implication**: When a phase's technical approach depends on a live deployment or an external system's credentials, name that step explicitly as a manual/post-deploy step in the spec (not just in Rollout Considerations) — so the builder doesn't attempt it and doesn't silently skip documenting why.

- **Pattern**: A spec that asks for request-derived state (auth/session data, a current user, feature flags) to appear in a *shared* template, without naming how it gets from the request into that template's context, leaves a real implementation gap — not a cosmetic one.
  **Evidence**: Phase 1 asked for "logged in as {username}" in `base.html`'s nav, extended by ~14 routes' templates, none of which passed a user into their context. The builder had to introduce a middleware (`request.state.user`, read directly in Jinja since Starlette injects `request`) that wasn't in the spec's code sample.
  **Spec/interview implication**: When a spec's Implementation Details include UI state that spans multiple existing routes/templates, name the propagation mechanism explicitly (middleware/context-processor vs. threading it through every route's context) rather than leaving it to be inferred during the build.

- **Pattern**: Success criteria whose `check.cmd` uses human-readable `<placeholder>` values (e.g. `<scratch-db-copy>`, `<test-idea-id>`, `<old-user>:<old-pass>`) read fine to a person but aren't unattended-verifiable — `scripts/verify.mjs` runs the command literally and the placeholder text itself fails (`sh: scratch-db-copy: No such file or directory`), even when the underlying behavior was manually verified live with real values throughout the build and genuinely passed.
  **Evidence**: `pancracio-user-accounts`'s final `verify.mjs` run reported `pass=1 fail=7` despite all three phases being built, reviewed, and live-verified successfully — every "failure" was a placeholder-substitution artifact, not a real regression.
  **Spec/interview implication**: When a criterion's check genuinely needs a runtime value that doesn't exist until setup time (a fresh scratch DB, a newly-created test record), either give it a setup step `verify.mjs` can run first (a fixture script), or write the criterion as an explicit judgment check instead of a `cmd` with placeholders — a `cmd` should be something `verify.mjs` itself can execute end-to-end, not a template for a human to fill in.

## 2026-09-26 — ideas-tracker-dashboard

- **Pattern**: `scripts/verify.mjs` only checks a `cmd` check's shell exit code — it never compares the command's stdout against the human-readable `expect` string, which is print-only documentation. A `cmd` that pipes through a command whose own exit code doesn't reflect the real outcome (e.g. `curl -w '%{http_code}' | ...` — curl exits 0 on any HTTP status without `-f`; or a pipeline ending in `wc -l`, whose exit code is unrelated to the count it printed) will report PASS regardless of the actual value, silently verifying nothing. Separately, `grep -P` (PCRE, needed for `\K` lookbehind extraction) is unavailable under plain `/bin/sh` on macOS (BSD grep) even when it works fine in an interactive shell with GNU grep on PATH — `verify.mjs` runs every check via `spawnSync('sh', ['-c', cmd])`, so PCRE-dependent checks fail there specifically.
  **Evidence**: `ideas-tracker-dashboard`'s first `verify.mjs` run showed this both ways — 4 checks reported PASS despite testing nothing real (status-code and widget-count checks with no self-assertion), while 5 others reported FAIL with "invalid option -- P" from checks that had worked when run manually in an interactive shell.
  **Spec/interview implication**: Every `cmd` check must assert via its own exit code as the last command in the pipeline (e.g. `[ "$actual" = "$expected" ]`, `grep -q`, `jq -e`) — never rely on `verify.mjs` comparing printed output to `expect`, since it doesn't. Avoid PCRE-only regex (`grep -P`, `\K`) in favor of portable extraction (`grep -o 'attr="[^"]*"' | cut -d'"' -f2`) so checks work under plain `/bin/sh`, not just an interactive dev shell.

- **Pattern**: A spec whose feature reads as primarily backend (new routes/queries) but also adds new template markup (new CSS classes or `data-*` attributes) can omit the stylesheet from its File Changes table — the omission is easy to miss precisely because the feature doesn't feel like a "styling" change.
  **Evidence**: `ideas-tracker-dashboard`'s spec added 8 new `data-widget` `<section>` blocks with no corresponding CSS rule anywhere in `web/static/style.css`, and File Changes didn't list that file; caught by the Scout's context-map pass, not the spec itself.
  **Spec/interview implication**: When a spec's Implementation Details introduce new markup (new classes, new component-level elements), explicitly check whether the project's stylesheet needs a corresponding entry in File Changes, even when the feature is framed around backend logic.
