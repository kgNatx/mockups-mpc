# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions follow [Semantic Versioning](https://semver.org/).

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
