# Favorites + UI Uplift — Design

**Date:** 2026-05-20
**Status:** Approved for planning
**Component:** Mockups MPC gallery (`app/`) + frontend (`app/templates/gallery.html`, `app/static/style.css`)

## Summary

Add the ability to **favorite (star) mockups** and surface them via a dedicated sidebar filter, plus a focused **UI uplift**: real cross-field search, sort options, feed-item polish, richer viewer chrome, and a refreshed visual direction (lifted background, new type pairing).

Thumbnails were considered and **explicitly deferred** — they require either headless-browser infra or per-item live iframes, and the cost/benefit didn't justify inclusion now.

## Goals

1. Persistently star mockups and view only starred ones.
2. Search across title/description/tags (server-side, across the whole library — not just the loaded page).
3. Sort the feed: newest / oldest / favorites-first.
4. Polish feed items, viewer chrome, and the overall palette/type.

## Non-Goals

- Thumbnail previews (deferred).
- A `favorite_mockup` MCP tool — starring is a human curation action in the gallery, not an AI action. The `favorite` field will still appear in `get_mockup`/`list_mockups` output for free.
- Multi-user / per-user favorites — this is a single-user self-hosted tool; `favorite` is global.

## Architecture (Approach A — server-side)

Search, sort, and favorites filtering all become query parameters on the existing `GET /api/mockups` endpoint, resolved in SQL. The frontend builds a query and renders what it gets back. This is the only approach that handles a large, churning library correctly (client-side filtering only sees the currently-loaded page).

### Data model & migration

Add one column to the `mockups` table:

```sql
favorite INTEGER NOT NULL DEFAULT 0
```

The schema today uses `CREATE TABLE IF NOT EXISTS` with no migration framework, and the production DB already has data. So `init_db()` gains an idempotent migration step:

1. Read `PRAGMA table_info(mockups)`.
2. If `favorite` is absent: `ALTER TABLE mockups ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0`.
3. `CREATE INDEX IF NOT EXISTS idx_mockups_favorite ON mockups(favorite)`.

Existing mockups default to un-starred. Safe to run on every boot.

`_row_to_dict` in `db.py` already returns all columns, so `favorite` flows into every consumer (API responses, MCP tool output) automatically. It will be returned as the integer `0`/`1` from SQLite; the frontend treats it as truthy/falsy. (Models `MockupRecord`/`MockupSummary` are not enforced on these dict returns, but a `favorite: bool = False` field will be added to both for documentation/consistency.)

### DB layer (`app/db.py`)

- New: `set_favorite(db, mockup_id, value: bool) -> bool` — sets `favorite` to 0/1, updates `updated_at`, returns whether a row was affected.
- Extend `list_mockups()` with `q: str | None`, `sort: str`, `favorites_only: bool`:
  - `q`: `WHERE (title LIKE ? OR description LIKE ? OR tags LIKE ?)` with `%q%`. Tags are stored as a JSON string, so a substring `LIKE` on the raw `tags` text is sufficient for this use.
  - `favorites_only`: adds `favorite = 1` to the `WHERE`.
  - `sort`: `newest` → `ORDER BY created_at DESC` (default, current behavior); `oldest` → `created_at ASC`; `favorites` → `favorite DESC, created_at DESC`.
  - All conditions compose with the existing `project_slug`, `limit`, `offset`.

### API layer (`app/routes/api.py`)

- `GET /api/mockups` gains optional params: `q`, `sort` (default `newest`), `favorites_only` (default false). Invalid `sort` values fall back to `newest`. Passed through to `list_mockups()`.
- New: `PUT /api/mockups/{mockup_id}/favorite` accepting JSON body `{"favorite": true|false}`. Returns the updated row (404 if not found). Explicit set (not toggle) → idempotent, so rapid double-clicks can't desync the UI from the server.
- `/api/projects` is unchanged. The favorites **count** for the sidebar is derived from a lightweight query — either a dedicated `GET /api/favorites/count` or reuse `list_mockups(favorites_only=True, limit=...)`. Decision deferred to the plan; a small count endpoint is cleaner than over-fetching.

### MCP layer (`app/mcp_server.py`)

No new tools. `favorite` rides along in `get_mockup`/`list_mockups` output via the row dict. No changes required beyond that being true.

## Frontend (`gallery.html` + `style.css`)

### Visual direction (locked)

- **Background:** "Graphite" — lift `--bg-deep` from `#09090b` to `#18181a`, with the full neutral ramp lifted proportionally so layering depth and the blueprint grid survive. Borders and ghost text lift to preserve contrast. Exact hex values to be fine-tuned against the running gallery during implementation; the approved direction and relationships are fixed.
  - Approved reference ramp: `--bg-deep:#18181a`, `--bg-surface:#1d1d20`, `--bg-raised:#242428`, `--bg-hover:#2c2c31`, `--bg-active:#34343a`, `--border-dim:#2a2a2f`, `--border-subtle:#3a3a40`, `--border-focus:#4d4d55`, `--text-tertiary:#7c7c85`, `--text-ghost:#56565e`. The blueprint grid opacity rises (~0.18 → ~0.5) to stay visible on the lighter floor.
- **Type:** Geist (heading/sans) + Geist Mono (mono), replacing Space Grotesk + JetBrains Mono. Loaded via the existing Google Fonts `@import`.
- **Accent:** Cyan, unchanged. Amber (`--star:#fbbf24`) is reserved exclusively for favorites so "starred" never blurs with "selected" (cyan).
- **Type badges** (html/png/jpg/svg colors): unchanged — semantic, not accent.

### Sidebar — Favorites filter

- A `★ Favorites` pseudo-item pinned at the top of the project list, above "All", rendered in amber with a starred count, followed by a divider before the real projects.
- Selection model stays single-valued: `state.activeProject` gains a sentinel value (e.g. `"__favorites__"`) rather than a parallel boolean. Selecting Favorites sets `favorites_only=true`; selecting any project or "All" clears it.

### Search & sort controls

- The existing filter input becomes a real search box (icon + "Search title, description, tags…" placeholder). On input (debounced ~200ms) it sets `q` and reloads from the server via the existing `loadMockups(reset)` path, instead of filtering `state.mockups` client-side. The client-side `getFilteredMockups()` title filter is removed (superseded by server `q`).
- A compact segmented control below the search box: `Newest · Oldest · ★ First`. Changing it sets `state.sort`, resets offset, and reloads. `★ First` highlights amber.

### Feed item polish

- **Star button** added as the leftmost element of each feed item. Filled amber `★` when favorited (always visible, parked at the left edge so favorites scan down the left side), outline `☆` on hover otherwise. Click toggles via `PUT .../favorite` with optimistic UI update and rollback on failure. `e.stopPropagation()` so it doesn't select the item.
- Copy/delete actions continue to hover-reveal on the right.
- Refine spacing, hover states, the action row, and badge treatment to match the new palette.

### Viewer chrome

- **Viewport toggles** in the meta-bar for HTML mockups: `375 (Mobile) · 768 (Tablet) · Full (Desktop)` segmented control with device glyphs; constrains the iframe width. Hidden for image content types.
- **Fullscreen** button using the Fullscreen API on the viewer pane.
- An amber `★` shown next to the title in the meta-bar when the open mockup is favorited.
- Slightly warmer empty state.

### Auto-refresh interaction

The existing 5s poll (`pollForUpdates`) must preserve the active `q`, `sort`, and `favorites_only` state when it reloads, and its "newest item changed" check must remain correct under non-`newest` sorts (e.g. compare by id-set or fetch with the current sort). To be handled in the plan.

## Testing

- **`test_db.py`:** `set_favorite` (set true/false, returns affected); `list_mockups` with `q` (matches title, description, tags; non-match excluded), each `sort` mode ordering, `favorites_only` filtering, and composition with `project_slug`.
- **`test_db.py` (migration):** opening an old-schema DB (no `favorite` column) and running `init_db()` adds the column and defaults existing rows to 0.
- **`test_api.py`:** `PUT /api/mockups/{id}/favorite` sets state and returns updated row; 404 on unknown id; idempotent repeat; `GET /api/mockups` honors `q`/`sort`/`favorites_only`.
- **Frontend:** no JS test harness — manual verification against the running gallery, tracing each path end-to-end (star toggle + rollback, favorites filter, server-side search, each sort mode, viewport toggles, fullscreen, auto-refresh preserving state). Report will distinguish automated vs manually-verified.

## Rollout

- Single deployable change. Migration is automatic on container boot.
- Version bump (next: 1.3.0 — new user-facing features) across `VERSION`, `pyproject.toml`, `server.json`, with a CHANGELOG entry. GHCR image + registry republish per existing release process.

## Open questions for the plan

1. Favorites-count endpoint vs. derived count (lean toward a small dedicated endpoint).
2. Exact debounce for server-side search (start ~200ms).
3. Final fine-tuned hex values for the Graphite ramp against real content.
