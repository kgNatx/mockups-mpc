# Mockups MPC

A self-hosted MCP server and gallery for AI-generated mockups. AI tools send mockups via MCP tool calls, the server stores and catalogs them, and you browse everything in a clean web gallery.

## Why

Every time an AI tool generates a mockup, there's no consistent place for it to go. Files get scattered, sessions lose context, and there's no history. Mockups MPC solves this: the AI sends the mockup to the server, you view it in the gallery, and the local file gets cleaned up. One place for everything.

## Architecture

```
┌─────────────────┐     MCP (HTTP/SSE)     ┌──────────────────────┐
│  Claude Code /  │ ◄───────────────────── │                      │
│  Claude Desktop │  send/list/get/update  │    Mockups MPC       │
│  Any MCP Client │  delete/tag            │    (FastAPI)         │
└─────────────────┘                        │                      │
                                           │  ┌────────────────┐  │
       Browser                             │  │  MCP Server    │  │
    ┌──────────┐      GET /                │  │  (fastmcp)     │  │
    │ Gallery  │ ◄──────────────────────── │  └────────────────┘  │
    │ Viewer   │                           │  ┌────────────────┐  │
    └──────────┘                           │  │  JSON API      │  │
                                           │  │  /api/*        │  │
                                           │  └────────────────┘  │
                                           │  ┌────────────────┐  │
                                           │  │  SQLite (WAL)  │  │
                                           │  │  + Filesystem   │  │
                                           │  └────────────────┘  │
                                           └──────────────────────┘
```

Single Docker container running a FastAPI app that serves two roles:

1. **MCP Server** — mounted at `/mcp/` (HTTP transport) and `/mcp/sse` (SSE transport). AI tools connect here to send and manage mockups.
2. **Web Gallery** — served at `/`. Sidebar with project list and chronological feed, main viewer with iframe/image display.

### Data Layer

- **SQLite** in WAL mode — metadata catalog (project, title, description, tags, content type, timestamps)
- **Filesystem** — mockup files stored in `data/{project_slug}/{uuid}.{ext}`
- **Storage** is a bind-mounted `data/` directory next to the compose file

## Tech Stack

- Python 3.12
- FastAPI + uvicorn
- fastmcp v3.x (standalone)
- SQLite via aiosqlite
- Jinja2 templates + vanilla JS
- Docker + Traefik

## MCP Tools

| Tool | Description |
|------|-------------|
| `send_mockup` | Send HTML/SVG (raw string) or PNG/JPG (base64) to the gallery. Returns a gallery URL. |
| `list_mockups` | List mockups reverse-chronologically, optionally filtered by project. |
| `get_mockup` | Get a specific mockup by UUID with view and gallery URLs. |
| `update_mockup` | Update metadata (title, description, tags) or replace content. |
| `delete_mockup` | Delete a mockup — removes both the DB record and file on disk. |
| `tag_mockup` | Add or remove tags on an existing mockup. |

The server instruction tells connecting AI tools: *"After a successful send_mockup, delete the local file — this server stores and hosts it."*

## API Routes

| Route | Purpose |
|-------|---------|
| `GET /` | Gallery UI |
| `GET /view/{id}` | Raw mockup (HTML rendered, images served with correct MIME type) |
| `GET /api/mockups` | JSON listing with `limit`, `offset`, `project` filter |
| `GET /api/mockups/{id}` | Single mockup metadata |
| `GET /api/projects` | Project list with counts |
| `GET /health` | Health check |

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/kgNatx/mockups-mpc.git
cd mockups-mpc
cp .env.example .env
# Edit .env with your domain and Traefik network name
```

### 2. Deploy

```bash
docker compose up -d --build
```

### 3. Connect Claude Code

```bash
claude mcp add-json mockups '{"type":"http","url":"https://your-domain.com/mcp"}'
```

Or add to `.mcp.json` (project-level) or `~/.claude/.mcp.json` (global):

```json
{
  "mcpServers": {
    "mockups": {
      "type": "http",
      "url": "https://your-domain.com/mcp"
    }
  }
}
```

### 4. Connect Claude Desktop

Add to your Claude Desktop config file:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mockups": {
      "type": "sse",
      "url": "https://your-domain.com/mcp/sse"
    }
  }
}
```

## Gallery UI

The gallery auto-seeds a Setup Guide as the first entry on fresh installs. The guide covers all configuration methods with copy-able code blocks.

**Layout:** Sidebar (project list + chronological feed with title filter + infinite scroll) + main viewer (iframe for HTML, img for images/SVG) + metadata bar + pop-out link.

**Theme:** Techno Chic Minimalist — Space Grotesk, cyan accents, zinc/neutral dark backgrounds.

## Project Structure

```
app/
├── main.py          # FastAPI app, lifespan, MCP mount, router includes
├── config.py        # Settings (DATA_DIR, DB_PATH, BASE_URL from env)
├── db.py            # SQLite init + CRUD (WAL mode, aiosqlite)
├── models.py        # Pydantic models
├── storage.py       # Slug generation, file write/read/delete, 25MB limit
├── mcp_server.py    # FastMCP instance, tool logic, tool wrappers
├── seed.py          # Auto-seed setup guide on empty DB
├── routes/
│   ├── api.py       # JSON API endpoints
│   └── gallery.py   # Gallery page + raw mockup serving
├── templates/
│   └── gallery.html # Jinja2 gallery template
└── static/
    ├── style.css         # Gallery theme
    └── setup-guide.html  # Self-contained setup guide page
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
uvicorn app.main:app --reload
```

41 tests covering storage, database, MCP tools, API routes, and gallery.
