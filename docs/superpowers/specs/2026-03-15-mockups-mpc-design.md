# Mockups MPC — Design Spec

A Dockerized service that AI tools (Claude Code, etc.) can send mockups to via MCP. Hosts and catalogs mockups by project with a web gallery for browsing.

## Problem

Claude Code can generate HTML mockups and images, but there's no consistent place for them to land. Every session reinvents where to write the file, how to serve it, and how the user views it. Mockups get lost between sessions with no history or organization.

## Solution

A single Docker container running a FastAPI app that:

1. Accepts mockups over MCP (SSE transport) — HTML, PNG, JPG, SVG
2. Catalogs them by project, title, description, tags, and timestamp in SQLite
3. Stores files on a mounted volume
4. Serves a web gallery UI for browsing and viewing

## Architecture

### Single Container

- **FastAPI** application serving both the MCP SSE endpoint and the web gallery
- **SQLite** database (`mockups.db`) in WAL mode for safe concurrent access
- **Filesystem** storage in a `data/` volume, organized as `data/{project_slug}/{uuid}.{ext}`
- **Traefik-routed** on a subdomain (e.g., `mockups.yourdomain.com`)
- **Docker Compose** with a mounted `data/` directory next to the compose file
- **No authentication** — network-level only (Traefik, LAN). This is an internal tool on a private network.

### Data Model

```
mockups table:
  id           TEXT PRIMARY KEY (UUID)
  project      TEXT NOT NULL (display name, e.g. "Squawk")
  project_slug TEXT NOT NULL (sanitized: lowercase, alphanumeric + hyphens only)
  title        TEXT NOT NULL
  description  TEXT
  content_type TEXT NOT NULL (html, png, jpg, svg — file extensions, not MIME types)
  file_path    TEXT NOT NULL (relative path within data/)
  tags         TEXT (JSON array)
  created_at   DATETIME NOT NULL
  updated_at   DATETIME NOT NULL (set to created_at on insert, updated on any metadata change)
```

Project names are sanitized to slugs for filesystem paths: lowercased, non-alphanumeric characters replaced with hyphens, leading/trailing hyphens stripped, `..` and absolute paths rejected. The original display name is preserved in the `project` column. Different display names that produce the same slug are treated as the same project (intentional — "My Project" and "my-project" merge).

### MCP Transport

- Uses the Python `mcp` SDK (FastMCP)
- SSE endpoint at `/mcp/sse`, message POST at `/mcp/messages`
- Standard MCP SSE handshake
- Claude Code config snippet:

```json
{
  "mcpServers": {
    "mockups": {
      "type": "sse",
      "url": "http://mockups.yourdomain.com/mcp/sse"
    }
  }
}
```

### MCP Tools

| Tool | Params | Returns |
|------|--------|---------|
| `send_mockup` | `project` (required), `title` (required), `description`, `content` (required), `content_type` (required: html/png/jpg/svg), `tags[]` (optional) | Mockup metadata + gallery URL (`/?mockup={id}`) |
| `list_mockups` | `project` (optional), `limit` (default 50), `offset` (default 0) | Metadata list, reverse-chronological |
| `get_mockup` | `id` | Metadata + content URL |
| `update_mockup` | `id`, `title` (optional), `description` (optional), `tags[]` (optional, full replace), `content` (optional — replaces file on disk), `content_type` (required if `content` provided) | Updated metadata |
| `delete_mockup` | `id` | Confirmation (deletes both DB row and file on disk) |
| `tag_mockup` | `id`, `add[]` (optional), `remove[]` (optional) | Updated tags (additive/subtractive only) |

**Content encoding:** If `content_type` is `html` or `svg`, `content` is a raw UTF-8 string. If `content_type` is `png` or `jpg`, `content` is base64-encoded. Server detects based on `content_type`.

Content size limit: 25 MB per mockup. Server rejects larger payloads with a clear error.

**Error responses:** MCP tool errors return `is_error: true` with a human-readable message. Common cases: not found (invalid ID), bad content type, base64 decode failure, payload too large.

All tools that modify metadata update the `updated_at` timestamp.

### Flow

1. Claude Code calls `send_mockup` over MCP with project name, title, description, content, and content type
2. FastAPI sanitizes project name to slug, decodes content (base64 for images, raw string for HTML), writes file to `data/{project_slug}/{uuid}.{ext}`
3. Metadata inserted into SQLite
4. Returns mockup ID and gallery URL
5. User opens gallery, sees the latest mockup loaded in the viewer

## Web Gallery UI

### Layout

Two-panel layout: sidebar + main viewer.

**Sidebar:**
- Top section: project list, collapsible, with mockup counts per project. "All" option at top.
- Bottom section: reverse-chronological feed of all mockups (or filtered by selected project). Each entry shows title, project badge, and timestamp. Click to load in viewer. Paginated with infinite scroll (load 50 at a time).

**Main Viewer:**
- Full width (minus sidebar), full height
- HTML mockups render in a sandboxed iframe (`sandbox="allow-scripts"` — scripts allowed for interactive mockups; no `allow-same-origin` since mockups are untrusted content, no `allow-top-navigation`, no `allow-popups`). Mockups that need full browser context can be opened via "pop out".
- Images render directly, scaled to fit
- Slim metadata bar above the viewer: title, description, tags, project, timestamp, "pop out" link
- "Pop out" link opens the raw mockup in a new browser tab at `/view/{id}`

**On landing:** The most recent mockup is auto-loaded in the viewer.

**Sidebar filtering:** A text input at the top of the chronological feed filters entries by title substring match. Not full-text search — just a quick filter.

### Design

- Dark theme
- Clean typography, generous whitespace, subtle borders
- Minimal and elegant — no framework bloat
- Server-rendered HTML (Jinja2 templates) with vanilla JS for sidebar interactions, iframe loading, and infinite scroll

### Routes

| Route | Purpose |
|-------|---------|
| `GET /` | Gallery UI (sidebar + viewer) |
| `GET /view/{id}` | Raw mockup served directly (HTML rendered, images served with correct MIME type) |
| `GET /api/mockups` | JSON API for mockup listing with `limit`, `offset`, `project` filter |
| `GET /api/mockups/{id}` | JSON API for single mockup metadata |
| `GET /api/projects` | JSON API for project list with counts |

Content types for `/view/{id}`: `text/html` for HTML, `image/png` for PNG, `image/jpeg` for JPG, `image/svg+xml` for SVG.

## Storage

- Files stored on disk in a `data/` directory mapped as a Docker volume
- Directory next to the `docker-compose.yml` file
- Organized as `data/{project_slug}/{uuid}.{ext}`
- SQLite database stored in the same `data/` directory
- Future: migrate to MinIO/S3 if storage needs grow

## Deployment

- `docker-compose.yml` with a single service
- Traefik labels for subdomain routing
- `data/` directory mounted as a bind mount
- `Dockerfile` based on `python:3.12-slim` with FastAPI + uvicorn
- `GET /health` endpoint for Traefik health checks
- Logs to stdout (standard Docker logging)

## Future Considerations (Not V1)

- MinIO/S3 storage backend
- Versioning (multiple versions of the same mockup)
- Diffing/comparison view between mockups
- Full-text search on titles/descriptions (v1 has sidebar title filter)
- Annotations or comments on mockups
- Sharing links (public/private toggle)
- Authentication (if exposed beyond LAN)
