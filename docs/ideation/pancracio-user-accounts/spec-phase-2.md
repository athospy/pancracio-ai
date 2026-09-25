# Implementation Spec: Pancracio User Accounts & Login - Phase 2

**Contract**: ./contract.md
**Estimated Effort**: M

## Technical Approach

Two additive pieces on top of Phase 1's `users`/`sessions` tables: a `created_by` column on
`ideas` (who created it), and an `audit_log` table (who did what, later). Unlike Phase 1's new
tables, `created_by` is a column on an already-live production table — `schema.sql`'s `CREATE
TABLE IF NOT EXISTS ideas` will **not** retroactively add it, so this needs the same
`PRAGMA table_info` + `ALTER TABLE ADD COLUMN` guard `_init_db()` already uses for
`posts.ig_media_id` (`app.py:256-258`).

Four routes get instrumented: `create_idea` (sets `created_by`), `update_idea` (logs `edit`, and
separately `auto_publish_toggle` when that specific field actually changes), `mark_posted` (logs
`mark_posted`), and `run_pipeline` (logs `publish`, only after `_publish_to_instagram()` actually
succeeds — matching the existing timing of when `idea.status` flips to `posted`). Attribution is
surfaced inline on the idea itself — a per-idea "Activity" section on the edit page — rather than
a separate audit-log page, per the "mostly a UI enhancement" framing from the interview.

Because Phase 1's legacy Basic-Auth fallback stays live through this phase (removed in Phase 3),
`get_current_user()` can still return `None` for a request authenticated the old way. Both
`created_by` and `audit_log.user_id` are nullable to tolerate that — logging simply skips actions
taken through the fallback path rather than crashing.

## Decisions Considered and Rejected

_Carried from the contract._

- **Audit coverage extends to edit / auto_publish toggle / publish / mark-posted, not just idea
  creation** — rejected: creation-only attribution (a `created_by` column, no `audit_log` table).
  User explicitly widened scope back to "creation + key later actions."
- **Attribution surfaced as a per-idea "Activity" section instead of a dedicated audit-log page**
  — rejected: a standalone audit-log/admin page listing actions across all ideas. Matches
  "mostly a UI enhancement" — surfaces attribution where the user is already looking.
- **`created_by` added via an explicit `ALTER TABLE ADD COLUMN` migration guard** — rejected:
  relying on `schema.sql`'s `CREATE TABLE IF NOT EXISTS` alone. A hidden-dependency finding during
  plan review: that alone would silently leave the column absent on the live table.
- **Flat permissions — any authenticated account has full access** — rejected: role-based
  permissions. Not what the stated problems (UX, visibility/attribution) call for. Relevant here
  because it's why `audit_log` has no notion of "who is allowed to do what" — only "who did what."

## Feedback Strategy

**Inner-loop command**: same local scratch instance as Phase 1
(`web/venv/bin/python3 -m uvicorn app:app --port 8000` against a copied `pancracio.db`), plus
`sqlite3` against that same copy for the DB-level checks.

**Playground**: local scratch instance + direct `sqlite3` queries against the scratch DB copy.

**Why this approach**: Same as Phase 1 — no test suite in this repo; curl for the HTTP-visible
behavior (the Activity UI), `sqlite3` for the DB-level behavior (attribution, audit rows).

## File Changes

### Modified Files

| File Path | Changes |
| --- | --- |
| `web/schema.sql` | Add `CREATE TABLE IF NOT EXISTS audit_log (...)` (see Data Model). |
| `web/app.py` | `_init_db()`: add the `created_by` `ALTER TABLE ADD COLUMN` guard, following the `ig_media_id`/`auto_publish` pattern at `app.py:254-266`. Add a `_log_action(conn, user_id, idea_id, action)` helper. Wire it into `create_idea` (`app.py:904`), `update_idea` (`app.py:942`), `mark_posted` (`app.py:1035`), and `run_pipeline` (`app.py:1458`) — each now takes the resolved user from `Depends(get_current_user)` explicitly instead of discarding it as `_`. `_get_idea()`/`_get_ideas()`: join `users` to expose `created_by_username`, and `_get_idea()` additionally fetches that idea's `audit_log` rows (joined to `users` for the actor's username) for the Activity section. |
| `web/templates/edit.html` | Add an "Activity" section: a list of `{action, actor username, timestamp}` rows, each wrapped in an element carrying `data-activity-row` (a stable marker, not tied to any particular CSS class, so it's checkable regardless of styling). |
| `web/templates/_idea_card.html` | Show "added by {{ idea.created_by_username }}" (omit the line entirely when `created_by_username` is null — the transitional legacy-auth case). |

## Implementation Details

### `created_by` migration + population

**Pattern to follow**: `app.py:256-266` (`_init_db()`'s existing `PRAGMA table_info` +
`ALTER TABLE ADD COLUMN` guards for `posts.ig_media_id` and `ideas.auto_publish`/`register`/
`quote_line`) — this is the exact shape to replicate, not a new migration mechanism.

**Overview**: One more `ALTER TABLE ideas ADD COLUMN created_by INTEGER REFERENCES users(id)`
guard, alongside the existing ones. Populated by `create_idea` at insert time from the resolved
`get_current_user()` result (or left `NULL` if that request came through the legacy Basic-Auth
fallback).

```python
existing_idea_cols = {row["name"] for row in conn.execute("PRAGMA table_info(ideas)")}
# ... existing guards for auto_publish/register/quote_line ...
if "created_by" not in existing_idea_cols:
    conn.execute("ALTER TABLE ideas ADD COLUMN created_by INTEGER REFERENCES users(id)")
```

**Key decisions**:

- Nullable, no `NOT NULL` constraint — must tolerate ideas created via the still-live legacy
  Basic-Auth fallback during this phase (no real `users` row exists for that path).

**Feedback loop**:

- **Playground**: scratch DB copy, run `_init_db()` against it (via starting the app once).
- **Experiment**: run against a copy of the *current* production schema (no `created_by` column
  yet) and confirm the column appears; run again (already migrated) and confirm no error.
- **Check command**: `sqlite3 <scratch-db-copy> "PRAGMA table_info(ideas);" | grep -q created_by`

### `audit_log` table + `_log_action` helper

**Overview**: One row per logged action. `idea_id` nullable (future-proofing only — every call
site in this phase always passes one) so the schema doesn't need to change if a non-idea-scoped
action is ever logged later.

```python
def _log_action(conn: sqlite3.Connection, user: Optional[dict], idea_id: int, action: str) -> None:
    if user is None:
        return  # legacy Basic-Auth fallback — no real user row to attribute to
    conn.execute(
        "INSERT INTO audit_log (user_id, idea_id, action) VALUES (?, ?, ?)",
        (user["id"], idea_id, action),
    )
```

**Key decisions**:

- Silently skips logging (rather than raising) when `user is None` — the legacy-fallback case is
  expected and tolerated through this phase, not an error condition.
- `action` is a free-text column, not a `CHECK`-constrained enum — this project's existing
  `ideas.status`/`content_type` columns DO use `CHECK`, but a fixed action vocabulary
  (`'edit'`, `'auto_publish_toggle'`, `'publish'`, `'mark_posted'`) is enforced at the Python call
  sites instead, since a `CHECK` constraint here would need the same SQLite table-rebuild dance
  (`_migrate_ideas_status_check`, `app.py:206-248`) every time a new action type is added — not
  worth the ceremony for an append-only log with 4 known call sites.

**Implementation steps**:

1. `create_idea`: after insert, call `_log_action(conn, user, idea_id, "create")` — wait, per the
   contract this is `created_by` (a column), not a logged action; do not double-log creation in
   `audit_log` — the `created_by` column already covers it, and the Activity section reads
   `created_at`/`created_by_username` for the "created" line separately from `audit_log` rows.
2. `update_idea`: before writing changes, fetch the idea's current `auto_publish` value; after the
   update, call `_log_action(conn, user, idea_id, "edit")` always, and additionally
   `_log_action(conn, user, idea_id, "auto_publish_toggle")` only if `auto_publish`'s value
   actually changed.
3. `mark_posted`: after the status update succeeds, `_log_action(conn, user, idea_id, "mark_posted")`.
4. `run_pipeline`: after `_publish_to_instagram()` returns successfully (not before — matches the
   existing point where `idea.status` flips to `posted`), `_log_action(conn, user, idea_id, "publish")`.

**Feedback loop**:

- **Playground**: local scratch instance + `sqlite3` against the same scratch DB.
- **Experiment**: log in as the test user, create an idea, edit it (change title only — expect one
  `edit` row), edit it again toggling `auto_publish` (expect both `edit` and
  `auto_publish_toggle` rows), mark it posted (expect `mark_posted`).
- **Check command**: `sqlite3 <scratch-db-copy> "SELECT user_id, action, idea_id FROM audit_log ORDER BY id DESC LIMIT 5;"`

### Activity UI section + `created_by` on cards

**Overview**: `edit.html` renders the idea's `audit_log` rows (newest first), each inside an
element with `data-activity-row`. `_idea_card.html` shows a one-line "added by X" when
`created_by_username` is present.

**Implementation steps**:

1. `edit_idea_form` (`app.py:926`): fetch the idea's audit rows (joined to `users.username`)
   alongside the idea itself, pass to the template as `activity`.
2. `edit.html`: iterate `activity`, rendering each as e.g.
   `<div data-activity-row>{{ row.action }} by {{ row.username }} — {{ row.created_at }}</div>`.
3. `_idea_card.html`: `{% if idea.created_by_username %}<span class="added-by">added by {{ idea.created_by_username }}</span>{% endif %}`.

**Feedback loop**:

- **Playground**: local scratch instance, browser pointed at `/ideas/<id>/edit`.
- **Experiment**: an idea with 3 audit rows (edit, auto_publish_toggle, mark_posted) — confirm all
  3 render; an idea with zero audit rows — confirm the section renders without erroring (empty
  state, not a template crash).
- **Check command**: `n=$(curl -s -b /tmp/c.txt http://127.0.0.1:8000/ideas/<test-idea-id>/edit | grep -c 'data-activity-row'); echo "$n"`

## Data Model

### Schema Changes

```sql
-- Existing ideas table gets a new column via the ALTER TABLE guard in _init_db(), not here.

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  idea_id INTEGER REFERENCES ideas(id),
  action TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_log_idea_id ON audit_log(idea_id);
```

## Testing Requirements

### Manual Testing

- [ ] A fresh scratch DB (copied from a pre-`created_by` production snapshot) gets the column added on startup, with no error on a second startup (idempotent).
- [ ] Creating an idea while logged in records `created_by` as the logged-in user's id.
- [ ] Editing an idea (non-`auto_publish` fields) logs exactly one `edit` audit row.
- [ ] Toggling `auto_publish` in the same edit logs both an `edit` row and an `auto_publish_toggle` row.
- [ ] Marking an idea posted logs a `mark_posted` row.
- [ ] A successful `run_pipeline` call (real or monkeypatched `_publish_to_instagram`, matching the auto-publish project's own testing technique) logs a `publish` row only after the publish succeeds — a monkeypatched *failure* logs nothing.
- [ ] The idea edit page renders an Activity section listing all of the above, each marked with `data-activity-row`.
- [ ] An idea created via the legacy Basic-Auth fallback (still live this phase) has a `NULL` `created_by` and doesn't crash the card/edit page rendering.

## Failure Modes

| Component | Failure Mode | Trigger | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| `_log_action` | Actor is the legacy-fallback `None` | A caller still using Basic Auth (transitional, until Phase 3) | No audit row is written for that action | Deliberate and acceptable for this phase — by Phase 3 the fallback is gone entirely, closing this gap. |
| `run_pipeline` | Idea fails partway (existing failure-halt behavior, unchanged) | Any step before `_publish_to_instagram()` raises | No `publish` row is logged — correct, since nothing was published | Logging call sits strictly after the existing success point (`idea.status` → `posted`), not before. |
| `update_idea` | `auto_publish` compared before vs. after using a stale read (race between two concurrent edits) | Extremely unlikely for a 1-2 user tool with no concurrent-write handling anywhere else in this codebase | A toggle could theoretically go unlogged or double-logged | Not mitigated — matches this codebase's existing lack of any concurrency handling elsewhere; not worth adding here alone. |
| Activity UI | Idea has zero audit rows (created before this phase shipped, or never edited) | Any idea created in Phase 1 or earlier | Empty Activity section | Template renders an empty list gracefully, not a crash — verified in Testing Requirements. |

## Validation Commands

```bash
web/venv/bin/python3 -m py_compile web/app.py
```

## Rollout Considerations

- **Feature flag**: none — additive column + table, additive UI section.
- **Rollback plan**: reverting the deploy leaves `created_by`/`audit_log` populated-but-unused;
  no destructive migration to undo (SQLite can't easily drop a column, but an unused nullable
  column is harmless).

## Open Items

- [ ] Whether `mark_posted` and `run_pipeline`'s `publish` action should be merged into one action
      name or kept distinct — kept distinct here since they're triggered by different callers
      (a human vs. n8n) and that distinction is itself useful attribution information; revisit if
      it turns out confusing in practice.
