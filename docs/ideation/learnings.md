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
