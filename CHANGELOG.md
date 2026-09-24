# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Mockups can now hold version history. `POST /api/upload` and `send_mockup` gain `parent=<id>` (add a version to an existing design instead of creating a new one) and `fold=false` (opt out of auto-fold for that upload). A specific version is directly linkable at `/view/{id}/v/{n}`.
- New MCP tool `split_version(id, version)` pulls one version back out into its own standalone design — reverses a fold, reusing the old id if it has one.
- `delete_mockup` (MCP) and `DELETE /api/mockups/{id}/versions/{n}` (API) accept a `version` to delete just that version instead of the whole design; deleting the last remaining version is refused.
- `get_mockup` and `GET /api/mockups/{id}` now include a `versions` list (number, title, created_at, content_type, view_url per version).
- Opt-in `python -m app.fold --dry-run` / `--apply` command to merge existing near-duplicate mockups — uploaded before this release, or with `fold=false` — into version history. It never runs on its own; see the README's Versions section.
- `POST /api/mockups/{id}/versions/{n}/split` — the HTTP form of `split_version`.
- `set_created_at` gains a `version` parameter to change one version's date (omit it for the latest). Changing the first version's date also moves the design's created date.
- Gallery deep link to one version: `/?mockup={id}&v={n}`. `/?mockup={id}` alone follows the latest version.
- Search (`q` on `GET /api/mockups` and the gallery search box) also matches version titles, so a folded design is findable by any of its drafts' titles.
- An auto-folded upload's response includes `folded: true` and a `note`: `Added as version {n} of '{design title}'. If this was meant to be a separate mockup, split it out with split_version(id, {n}) or POST /api/mockups/{id}/versions/{n}/split.`
- Gallery UI rebuild for versions: a brand bar at the top of the sidebar; a scope picker (all projects or one project, with a favorites toggle beside it) in place of the project list; with the sidebar collapsed, a small brand "eyebrow" above a compact row of viewer-bar buttons, so the 48px bar keeps its height; a `N versions` chip on feed rows that opens the version history; a version pill in the viewer header (`v3 · latest`, or `v2 of 3` when viewing an older version); and a split action on each version in the history. A viewer that follows the latest moves to a new version when one lands.
- Migration: on first startup after upgrading, every existing mockup gets a v1 automatically. Nothing merges and the list looks identical after upgrade; running it again (or restarting) is a no-op.

### Changed
- **Behaviour change for tool callers:** `update_mockup` with `content` now adds a new version instead of overwriting the current one and its file. Metadata-only updates (title, description, tags) are unchanged.
- Auto-fold is on by default: uploading a mockup whose title matches exactly one existing design's title once trailing iteration markers are stripped (`v2`, `draft 3`, `rev 2`, `r5`, or a bare trailing number — e.g. "Screen 1" / "Screen 2") adds it as a new version of that design instead of creating a separate one. Pass `-F fold=false` (or `fold=False` to `send_mockup`) to always create a new design. Variant markers (`option B`, `variant C`, a standalone trailing letter) are never folded together.
- Gallery "newest" sort and `GET /api/projects` order now use each design's latest version time, not its original upload time. The feed's date headers and row times follow the same time ("Oldest" still uses the original upload time).
- Caveat: splitting a version out of a series leaves two designs with the same base title, so later uploads in that series no longer auto-fold (auto-fold needs exactly one match) and each creates a new design. Use `parent=<id>` to add to a specific design, or `fold=false` to make the new-design choice explicit.

### Fixed
- On touch screens the feed row's always-visible action buttons no longer sit over the title and meta line; the row reserves their width. The meta line stays on one line at every width, with a long project badge truncated by an ellipsis instead of wrapping.

## [1.4.3] - 2026-09-23

### Added
- Copy a direct link to a mockup: `/view/{id}` serves the mockup alone, with no gallery UI. Available from the feed row (next to the gallery-link button) and the viewer header.

### Changed
- Compact viewer header. Favorite, copy direct link and pop out sit next to the menu toggle as icons, so the title gets the remaining width instead of a 280px cap. Description, tags, project and created time move into a details popover. The 375 / 768 / Full switch becomes a single device-icon menu labelled with the current size, and is now available on phones too.

### Fixed
- The MCP endpoint works behind a reverse proxy again. FastMCP 3.x rejects any `Host` other than localhost with HTTP 421; the public domain is now allowed via `FASTMCP_HTTP_ALLOWED_HOSTS` / `FASTMCP_HTTP_ALLOWED_ORIGINS`, and uvicorn runs with `--proxy-headers` so `/mcp` redirects keep the `https` scheme.

## [1.4.2] - 2026-07-07

### Added
- Mobile support for the gallery. Below 720px the sidebar becomes an off-canvas drawer with a hamburger toggle, a tap-to-dismiss scrim, and auto-close when a mockup is selected, so the viewer gets the full width instead of a sliver. The meta bar sheds the metadata that can't fit a phone (description, tags, project, time, viewport toggles), keeping the star, title, fullscreen, and pop-out.
- The hamburger toggle is present at every viewport: on desktop it collapses the sidebar (reflow) to give the viewer full width; on mobile it opens the drawer.

## [1.4.1] - 2026-06-05

### Fixed
- The gallery stylesheet is now cache-busted with a `?v=<VERSION>` query, so each release picks up new CSS without a manual hard-refresh. The version is read from the `VERSION` file (now copied into the image) and falls back to `dev` if absent.

## [1.4.0] - 2026-06-05

### Security
- Stored html/svg served at `/view/{id}` is now sandboxed with `Content-Security-Policy: sandbox allow-scripts` and `X-Content-Type-Options: nosniff`. Popped-out mockups still run their own scripts, but in an opaque origin, so they can no longer reach the same-origin API (closes a stored-XSS path).

### Fixed
- `update_mockup` no longer wipes a mockup's description on a metadata-only update (e.g. a title change).
- Upload and list endpoints return HTTP 400 instead of 500 for invalid project names; uploads are read in bounded chunks so an oversized body can't exhaust memory.
- A failed feed load no longer permanently freezes the gallery feed — it surfaces a retry message and recovers on the next poll.
- Auto-refresh now detects deletions, edits, and favorite toggles made by other clients, not only new uploads.
- A written file is rolled back if its database insert fails (no orphaned files).
- Deleting a mockup surfaces feedback when the server rejects it instead of silently doing nothing.
- The sidebar no longer overflows on very short viewports.

### Added
- Keyboard accessibility: feed rows, the project list, and the sort/viewport controls are focusable and operable with Enter/Space, with visible focus rings; row action buttons reveal on keyboard focus and on touch devices.

### Changed
- Internal hardening: `busy_timeout` PRAGMA on the SQLite connection, consolidated content-type validation, and removed dead code. Test suite expanded to 83 tests.

## [1.3.1] - 2026-05-20

### Fixed
- Favoriting is now discoverable: the feed star is a proper button in the link/delete action cluster (it previously overlapped the delete button and was painted near-invisible), and the viewer meta-bar shows a clickable hollow-star toggle next to the title.

## [1.3.0] - 2026-05-20

### Added
- Favorite (star) mockups; a Favorites filter in the sidebar.
- Server-side search across title, description, and tags.
- Sort options: newest, oldest, favorites-first.
- Viewer chrome: viewport size toggles (375 / 768 / full) and fullscreen for HTML mockups.

### Changed
- Refreshed visual direction: lifted "Graphite" background, Geist type, cyan accent retained.
- `favorite` field added to mockup API/MCP output.

## [1.2.0] - 2026-03-16

### Added
- Pre-built Docker image on GHCR (`ghcr.io/kgnatx/mockups-mpc`)
- GitHub Actions workflow for automated Docker builds on version tags
- `set_created_at` MCP tool for backdating or reordering mockups
- `DELETE /api/mockups/{id}` REST endpoint
- Delete and copy-link action buttons on gallery feed items (hover to reveal)
- Auto-refresh polling (5s) — gallery updates without page reload
- Date separators in the chronological feed
- Long title scroll on hover
- Click-to-deselect in gallery viewer
- Setup Guide link in sidebar header
- Gallery screenshot in README
- CONTRIBUTING.md, issue templates, GitHub Actions CI, pyproject.toml

### Changed
- MCP server name in setup docs changed from `mockups` to `mockups-gallery`
- Projects sorted by mockup count (descending) in sidebar
- Sidebar header renamed to "Mockups MPC"
- `docker-compose.local.yml` defaults to pre-built GHCR image
- UTF-8 decode error handling in upload endpoint
- API delete route reuses `_delete_mockup` instead of duplicating logic

### Removed
- Internal planning docs from repository

## [1.1.0] - 2026-03-15

### Added
- `POST /api/upload` endpoint for curl-based file uploads — keeps large content out of the model context
- `DELETE /api/mockups/{id}` endpoint for gallery-driven deletion
- Delete and copy-link action buttons on feed items (visible on hover)
- Setup Guide link in sidebar header
- Auto-refresh polling (5s) — gallery updates when new mockups arrive
- Scrolling long titles on hover in the sidebar feed
- Date separators in the chronological feed
- `docker-compose.local.yml` for standalone use without Traefik
- MIT LICENSE
- Prerequisites, verification step, and security note in README
- CLAUDE.md setup guidance in README and setup guide for teaching AI clients to use curl upload

### Changed
- MCP server instructions now guide AI clients toward curl upload instead of `send_mockup` for large files
- Softened local file deletion guidance — "safe to clean up when no longer needed" instead of "delete immediately"
- `get_mockup` tool description notes curl `view_url` for reading content
- Projects sorted by mockup count (descending) in sidebar
- Sidebar header renamed to "Mockups MPC"
- `send_mockup` tool description simplified (removed deletion directive)

### Removed
- `include_content` parameter from `get_mockup` (use `curl view_url` instead)
- Internal planning docs from repository

## [1.0.0] - 2026-03-14

### Added
- MCP server with 6 tools: `send_mockup`, `list_mockups`, `get_mockup`, `update_mockup`, `delete_mockup`, `tag_mockup`
- Dual MCP transport: HTTP (`/mcp/`) for Claude Code, SSE (`/mcp/sse/`) for Claude Desktop
- Gallery UI with sidebar navigation, project filter, title filter, infinite scroll, and iframe/image viewer
- JSON API at `/api/mockups`, `/api/mockups/{id}`, `/api/projects`
- SQLite storage in WAL mode with filesystem-backed mockup files
- Auto-seeded Setup Guide on fresh installs (skippable with `SKIP_SEED=1`)
- Techno Chic Minimalist theme (Space Grotesk, JetBrains Mono, cyan accents, zinc backgrounds)
- Docker deployment with Traefik labels and health check
- Copy button with clipboard fallback for sandboxed iframes
- 25 MB file size limit enforced at storage layer
- 41 tests covering storage, database, MCP tools, API routes, and gallery
