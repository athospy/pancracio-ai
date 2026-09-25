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
