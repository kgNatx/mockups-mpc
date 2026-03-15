# Mockups MPC Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Dockerized FastAPI service that accepts mockups via MCP, stores them on disk with SQLite metadata, and serves a web gallery for browsing. Runs behind Traefik reverse proxy.

**Architecture:** Single FastAPI app serving both the MCP endpoint (via fastmcp mounted at `/mcp/`) and the web gallery. SQLite in WAL mode for metadata, filesystem for mockup files. Jinja2 templates with vanilla JS for the gallery UI.

**Tech Stack:** Python 3.12, FastAPI, fastmcp (v3.x), SQLite (aiosqlite), Jinja2, uvicorn, Docker, Traefik

**Spec:** `docs/superpowers/specs/2026-03-15-mockups-mpc-design.md`

---

## File Structure

```
mockups-mpc/
├── docker-compose.yml          # Single service + Traefik labels + proxy network
├── Dockerfile                  # python:3.12-slim + uvicorn
├── requirements.txt            # Pinned dependencies
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app creation, MCP mount, lifespan, health
│   ├── config.py               # Settings (data dir path, base URL from env)
│   ├── db.py                   # SQLite init (WAL mode), CRUD functions
│   ├── models.py               # Pydantic models (MockupRecord, CreateMockup, etc.)
│   ├── storage.py              # Slug generation, file write/read/delete
│   ├── mcp_server.py           # FastMCP instance + 6 tool definitions
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── api.py              # JSON API: /api/mockups, /api/mockups/{id}, /api/projects
│   │   └── gallery.py          # GET / (gallery page), GET /view/{id} (raw mockup)
│   ├── templates/
│   │   └── gallery.html        # Jinja2 gallery template
│   └── static/
│       └── style.css           # Gallery dark theme styles
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Shared fixtures (tmp data dir, test db, test client)
│   ├── test_storage.py         # Slug generation + file operations
│   ├── test_db.py              # SQLite CRUD
│   ├── test_api.py             # JSON API routes
│   ├── test_mcp_tools.py       # MCP tool logic (unit tests, not transport)
│   └── test_gallery.py         # Gallery + view routes
└── data/                       # Mounted volume (gitignored)
```

---

## Chunk 1: Foundation

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/main.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore`

- [ ] **Step 1: Create `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
data/
*.db
.venv/
.env
```

- [ ] **Step 2: Create `requirements.txt`**

```
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
fastmcp>=3.0.0
aiosqlite>=0.20.0
jinja2>=3.1.0
python-multipart>=0.0.18
pydantic>=2.0.0
pytest>=8.0.0
pytest-asyncio>=0.24.0
httpx>=0.28.0
```

- [ ] **Step 3: Create `app/__init__.py`** (empty file)

- [ ] **Step 4: Create `app/config.py`**

```python
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "mockups.db"
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

def get_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR

def get_db_path() -> Path:
    get_data_dir()
    return DB_PATH
```

- [ ] **Step 5: Create minimal `app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="Mockups MPC")

@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Create `tests/__init__.py`** (empty file)

- [ ] **Step 7: Create `tests/conftest.py`**

The `client` fixture must run the app's lifespan so `app.state.db` gets initialized. Use `app.router.lifespan_context` to ensure lifespan runs within the test:

```python
import pytest
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from app import config

@pytest.fixture
def tmp_data_dir(tmp_path):
    config.DATA_DIR = tmp_path
    config.DB_PATH = tmp_path / "mockups.db"
    return tmp_path

@pytest.fixture
async def client(tmp_data_dir):
    from app.main import app
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
```

Note: In Task 1, the minimal `app/main.py` has no lifespan, so this is a no-op. After Task 6 adds the real lifespan, this fixture will properly initialize the database and set `app.state.db`.

- [ ] **Step 8: Run health check test to verify scaffold**

Create `tests/test_api.py` with:

```python
import pytest

@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

Run: `pytest tests/test_api.py::test_health -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: project scaffold with FastAPI, health endpoint, test harness"
```

---

### Task 2: Pydantic Models

**Files:**
- Create: `app/models.py`

- [ ] **Step 1: Create `app/models.py`**

```python
from datetime import datetime
from pydantic import BaseModel

class MockupRecord(BaseModel):
    id: str
    project: str
    project_slug: str
    title: str
    description: str | None = None
    content_type: str
    file_path: str
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime

class MockupSummary(BaseModel):
    id: str
    project: str
    project_slug: str
    title: str
    description: str | None = None
    content_type: str
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime

class ProjectInfo(BaseModel):
    project: str
    project_slug: str
    count: int
```

No tests needed — these are plain data containers. Validated by usage in later tasks.

- [ ] **Step 2: Commit**

```bash
git add app/models.py
git commit -m "feat: add Pydantic models for mockup records and project info"
```

---

### Task 3: Storage Module (Slug Generation + File Operations)

**Files:**
- Create: `app/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests for slug generation**

Create `tests/test_storage.py`:

```python
import pytest
from app.storage import slugify_project

def test_slugify_basic():
    assert slugify_project("My Project") == "my-project"

def test_slugify_special_chars():
    assert slugify_project("Hello World! @#$") == "hello-world"

def test_slugify_already_clean():
    assert slugify_project("squawk") == "squawk"

def test_slugify_strips_leading_trailing_hyphens():
    assert slugify_project("--test--") == "test"

def test_slugify_collapses_multiple_hyphens():
    assert slugify_project("a---b") == "a-b"

def test_slugify_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        slugify_project("!!!")

def test_slugify_rejects_path_traversal():
    with pytest.raises(ValueError, match="invalid"):
        slugify_project("../etc")

def test_slugify_rejects_absolute_path():
    with pytest.raises(ValueError, match="invalid"):
        slugify_project("/etc/passwd")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL — `slugify_project` not defined

- [ ] **Step 3: Implement `slugify_project` in `app/storage.py`**

```python
import re
from pathlib import Path

def slugify_project(name: str) -> str:
    if ".." in name or name.startswith("/"):
        raise ValueError(f"Invalid project name: {name!r}")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower())
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError(f"Project name produces empty slug: {name!r}")
    return slug
```

- [ ] **Step 4: Run slug tests**

Run: `pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for file operations**

Add to `tests/test_storage.py`:

```python
import base64

@pytest.fixture
def data_dir(tmp_data_dir):
    return tmp_data_dir

def test_write_html(data_dir):
    from app.storage import write_mockup_file
    path = write_mockup_file("test-project", "abc123", "html", "<h1>Hello</h1>")
    full_path = data_dir / path
    assert full_path.exists()
    assert full_path.read_text() == "<h1>Hello</h1>"
    assert path == "test-project/abc123.html"

def test_write_png_base64(data_dir):
    from app.storage import write_mockup_file
    raw = b"\x89PNG\r\n\x1a\nfakedata"
    content = base64.b64encode(raw).decode()
    path = write_mockup_file("test-project", "def456", "png", content)
    full_path = data_dir / path
    assert full_path.exists()
    assert full_path.read_bytes() == raw

def test_write_svg_raw_string(data_dir):
    from app.storage import write_mockup_file
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="10"/></svg>'
    path = write_mockup_file("test-project", "ghi789", "svg", svg)
    full_path = data_dir / path
    assert full_path.read_text() == svg

def test_delete_mockup_file(data_dir):
    from app.storage import write_mockup_file, delete_mockup_file
    path = write_mockup_file("test-project", "del1", "html", "<p>bye</p>")
    assert (data_dir / path).exists()
    delete_mockup_file(path)
    assert not (data_dir / path).exists()

def test_content_too_large(data_dir):
    from app.storage import write_mockup_file, MAX_CONTENT_SIZE
    big = "x" * (MAX_CONTENT_SIZE + 1)
    with pytest.raises(ValueError, match="too large"):
        write_mockup_file("test-project", "big1", "html", big)
```

- [ ] **Step 6: Run to verify failures**

Run: `pytest tests/test_storage.py::test_write_html -v`
Expected: FAIL

- [ ] **Step 7: Implement file operations in `app/storage.py`**

Add to `app/storage.py`:

```python
import base64
from app.config import get_data_dir

MAX_CONTENT_SIZE = 25 * 1024 * 1024  # 25 MB

TEXT_TYPES = {"html", "svg"}
BINARY_TYPES = {"png", "jpg"}
VALID_TYPES = TEXT_TYPES | BINARY_TYPES

def write_mockup_file(project_slug: str, mockup_id: str, content_type: str, content: str) -> str:
    if content_type not in VALID_TYPES:
        raise ValueError(f"Invalid content_type: {content_type!r}")

    data_dir = get_data_dir()
    project_dir = data_dir / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)

    rel_path = f"{project_slug}/{mockup_id}.{content_type}"
    full_path = data_dir / rel_path

    if content_type in TEXT_TYPES:
        data = content.encode("utf-8")
        if len(data) > MAX_CONTENT_SIZE:
            raise ValueError(f"Content too large: {len(data)} bytes (max {MAX_CONTENT_SIZE})")
        full_path.write_bytes(data)
    else:
        data = base64.b64decode(content)
        if len(data) > MAX_CONTENT_SIZE:
            raise ValueError(f"Content too large: {len(data)} bytes (max {MAX_CONTENT_SIZE})")
        full_path.write_bytes(data)

    return rel_path

def delete_mockup_file(rel_path: str) -> None:
    full_path = get_data_dir() / rel_path
    if full_path.exists():
        full_path.unlink()
```

- [ ] **Step 8: Run all storage tests**

Run: `pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add app/storage.py tests/test_storage.py
git commit -m "feat: storage module with slug generation and file operations"
```

---

### Task 4: SQLite Database Module

**Files:**
- Create: `app/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for database operations**

Create `tests/test_db.py`:

```python
import pytest
from datetime import datetime, timezone
from app.db import init_db, insert_mockup, get_mockup, list_mockups, list_projects, update_mockup, delete_mockup

@pytest.fixture
async def db(tmp_data_dir):
    conn = await init_db()
    yield conn
    await conn.close()

@pytest.mark.asyncio
async def test_insert_and_get(db):
    now = datetime.now(timezone.utc)
    await insert_mockup(db, id="m1", project="Test", project_slug="test",
                        title="First", description="A mockup", content_type="html",
                        file_path="test/m1.html", tags=["ui"], created_at=now, updated_at=now)
    row = await get_mockup(db, "m1")
    assert row is not None
    assert row["title"] == "First"
    assert row["project"] == "Test"

@pytest.mark.asyncio
async def test_get_nonexistent(db):
    row = await get_mockup(db, "nope")
    assert row is None

@pytest.mark.asyncio
async def test_list_mockups_reverse_chrono(db):
    for i in range(3):
        ts = datetime(2026, 3, 15, 10, i, 0, tzinfo=timezone.utc)
        await insert_mockup(db, id=f"m{i}", project="P", project_slug="p",
                            title=f"Mock {i}", description=None, content_type="html",
                            file_path=f"p/m{i}.html", tags=[], created_at=ts, updated_at=ts)
    rows = await list_mockups(db, limit=50, offset=0)
    assert len(rows) == 3
    assert rows[0]["id"] == "m2"  # most recent first

@pytest.mark.asyncio
async def test_list_mockups_filter_by_project(db):
    now = datetime.now(timezone.utc)
    await insert_mockup(db, id="a1", project="Alpha", project_slug="alpha",
                        title="A1", description=None, content_type="html",
                        file_path="alpha/a1.html", tags=[], created_at=now, updated_at=now)
    await insert_mockup(db, id="b1", project="Beta", project_slug="beta",
                        title="B1", description=None, content_type="png",
                        file_path="beta/b1.png", tags=[], created_at=now, updated_at=now)
    rows = await list_mockups(db, project_slug="alpha", limit=50, offset=0)
    assert len(rows) == 1
    assert rows[0]["project"] == "Alpha"

@pytest.mark.asyncio
async def test_list_projects(db):
    now = datetime.now(timezone.utc)
    for i in range(3):
        await insert_mockup(db, id=f"p{i}", project="Alpha", project_slug="alpha",
                            title=f"A{i}", description=None, content_type="html",
                            file_path=f"alpha/p{i}.html", tags=[], created_at=now, updated_at=now)
    await insert_mockup(db, id="q1", project="Beta", project_slug="beta",
                        title="B1", description=None, content_type="html",
                        file_path="beta/q1.html", tags=[], created_at=now, updated_at=now)
    projects = await list_projects(db)
    assert len(projects) == 2
    alpha = next(p for p in projects if p["project_slug"] == "alpha")
    assert alpha["count"] == 3

@pytest.mark.asyncio
async def test_update_mockup(db):
    now = datetime.now(timezone.utc)
    await insert_mockup(db, id="u1", project="P", project_slug="p",
                        title="Old", description=None, content_type="html",
                        file_path="p/u1.html", tags=[], created_at=now, updated_at=now)
    await update_mockup(db, "u1", title="New Title", description="Updated", tags=["v2"])
    row = await get_mockup(db, "u1")
    assert row["title"] == "New Title"
    assert row["description"] == "Updated"

@pytest.mark.asyncio
async def test_delete_mockup(db):
    now = datetime.now(timezone.utc)
    await insert_mockup(db, id="d1", project="P", project_slug="p",
                        title="Gone", description=None, content_type="html",
                        file_path="p/d1.html", tags=[], created_at=now, updated_at=now)
    deleted = await delete_mockup(db, "d1")
    assert deleted is True
    assert await get_mockup(db, "d1") is None

@pytest.mark.asyncio
async def test_delete_nonexistent(db):
    deleted = await delete_mockup(db, "nope")
    assert deleted is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `init_db` not defined

- [ ] **Step 3: Implement `app/db.py`**

```python
import json
import aiosqlite
from datetime import datetime, timezone
from app.config import get_db_path

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS mockups (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    project_slug TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    content_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mockups_project_slug ON mockups(project_slug);
CREATE INDEX IF NOT EXISTS idx_mockups_created_at ON mockups(created_at);
"""

async def init_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(get_db_path()))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(CREATE_TABLE)
    await db.commit()
    return db

async def insert_mockup(db: aiosqlite.Connection, *, id: str, project: str,
                         project_slug: str, title: str, description: str | None,
                         content_type: str, file_path: str, tags: list[str],
                         created_at: datetime, updated_at: datetime) -> None:
    await db.execute(
        """INSERT INTO mockups (id, project, project_slug, title, description,
           content_type, file_path, tags, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, project, project_slug, title, description, content_type,
         file_path, json.dumps(tags), created_at.isoformat(), updated_at.isoformat())
    )
    await db.commit()

async def get_mockup(db: aiosqlite.Connection, mockup_id: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM mockups WHERE id = ?", (mockup_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)

async def list_mockups(db: aiosqlite.Connection, *, project_slug: str | None = None,
                        limit: int = 50, offset: int = 0) -> list[dict]:
    if project_slug:
        cursor = await db.execute(
            "SELECT * FROM mockups WHERE project_slug = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (project_slug, limit, offset)
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM mockups ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
    return [_row_to_dict(row) for row in await cursor.fetchall()]

async def list_projects(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        """SELECT project, project_slug, COUNT(*) as count
           FROM mockups GROUP BY project_slug ORDER BY project"""
    )
    return [dict(row) for row in await cursor.fetchall()]

_UNSET = object()

async def update_mockup(db: aiosqlite.Connection, mockup_id: str, *,
                         title: str | None = None, description=_UNSET,
                         tags: list[str] | None = None, file_path: str | None = None,
                         content_type: str | None = None) -> bool:
    sets = []
    params = []
    if title is not None:
        sets.append("title = ?")
        params.append(title)
    if description is not _UNSET:
        sets.append("description = ?")
        params.append(description)
    if tags is not None:
        sets.append("tags = ?")
        params.append(json.dumps(tags))
    if file_path is not None:
        sets.append("file_path = ?")
        params.append(file_path)
    if content_type is not None:
        sets.append("content_type = ?")
        params.append(content_type)
    if not sets:
        return False
    sets.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    params.append(mockup_id)
    cursor = await db.execute(
        f"UPDATE mockups SET {', '.join(sets)} WHERE id = ?", params
    )
    await db.commit()
    return cursor.rowcount > 0

async def delete_mockup(db: aiosqlite.Connection, mockup_id: str) -> bool:
    cursor = await db.execute("DELETE FROM mockups WHERE id = ?", (mockup_id,))
    await db.commit()
    return cursor.rowcount > 0

def _row_to_dict(row: aiosqlite.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"]) if d["tags"] else []
    return d
```

- [ ] **Step 4: Run all db tests**

Run: `pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: SQLite database module with CRUD operations"
```

---

## Chunk 2: MCP Tools

### Task 5: MCP Server + Tool Definitions

**Files:**
- Create: `app/mcp_server.py`
- Create: `tests/test_mcp_tools.py`
- Modify: `app/main.py` (mount MCP app)

- [ ] **Step 1: Write failing tests for MCP tool logic**

Create `tests/test_mcp_tools.py`:

```python
import pytest
from app.db import init_db
from app.mcp_server import (
    _send_mockup, _list_mockups, _get_mockup,
    _update_mockup, _delete_mockup, _tag_mockup
)

@pytest.fixture
async def db(tmp_data_dir):
    conn = await init_db()
    yield conn
    await conn.close()

@pytest.mark.asyncio
async def test_send_html_mockup(db, tmp_data_dir):
    result = await _send_mockup(
        db=db, project="Test Project", title="Homepage",
        description="Landing page mockup", content="<h1>Hi</h1>",
        content_type="html", tags=["ui", "landing"]
    )
    assert result["project"] == "Test Project"
    assert result["project_slug"] == "test-project"
    assert result["title"] == "Homepage"
    assert "gallery_url" in result
    assert (tmp_data_dir / result["file_path"]).exists()

@pytest.mark.asyncio
async def test_send_png_mockup(db, tmp_data_dir):
    import base64
    content = base64.b64encode(b"\x89PNG fake").decode()
    result = await _send_mockup(
        db=db, project="Test", title="Screenshot",
        description=None, content=content,
        content_type="png", tags=[]
    )
    assert result["content_type"] == "png"
    assert (tmp_data_dir / result["file_path"]).exists()

@pytest.mark.asyncio
async def test_send_invalid_content_type(db):
    with pytest.raises(ValueError, match="Invalid content_type"):
        await _send_mockup(
            db=db, project="P", title="T",
            description=None, content="x",
            content_type="gif", tags=[]
        )

@pytest.mark.asyncio
async def test_list_mockups_tool(db):
    for i in range(3):
        await _send_mockup(
            db=db, project="P", title=f"Mock {i}",
            description=None, content=f"<p>{i}</p>",
            content_type="html", tags=[]
        )
    result = await _list_mockups(db=db, project=None, limit=50, offset=0)
    assert len(result) == 3

@pytest.mark.asyncio
async def test_get_mockup_tool(db):
    sent = await _send_mockup(
        db=db, project="P", title="T",
        description=None, content="<p>hi</p>",
        content_type="html", tags=[]
    )
    result = await _get_mockup(db=db, id=sent["id"])
    assert result["title"] == "T"
    assert "view_url" in result

@pytest.mark.asyncio
async def test_get_mockup_not_found(db):
    with pytest.raises(ValueError, match="not found"):
        await _get_mockup(db=db, id="nonexistent")

@pytest.mark.asyncio
async def test_update_mockup_metadata(db):
    sent = await _send_mockup(
        db=db, project="P", title="Old",
        description=None, content="<p>v1</p>",
        content_type="html", tags=[]
    )
    result = await _update_mockup(
        db=db, id=sent["id"], title="New",
        description="Updated", tags=["v2"],
        content=None, content_type=None
    )
    assert result["title"] == "New"
    assert result["tags"] == ["v2"]

@pytest.mark.asyncio
async def test_update_mockup_content(db, tmp_data_dir):
    sent = await _send_mockup(
        db=db, project="P", title="T",
        description=None, content="<p>v1</p>",
        content_type="html", tags=[]
    )
    result = await _update_mockup(
        db=db, id=sent["id"], title=None,
        description=None, tags=None,
        content="<p>v2</p>", content_type="html"
    )
    file_content = (tmp_data_dir / result["file_path"]).read_text()
    assert file_content == "<p>v2</p>"

@pytest.mark.asyncio
async def test_delete_mockup_tool(db, tmp_data_dir):
    sent = await _send_mockup(
        db=db, project="P", title="T",
        description=None, content="<p>bye</p>",
        content_type="html", tags=[]
    )
    file_path = tmp_data_dir / sent["file_path"]
    assert file_path.exists()
    result = await _delete_mockup(db=db, id=sent["id"])
    assert result["deleted"] is True
    assert not file_path.exists()

@pytest.mark.asyncio
async def test_tag_mockup_add_remove(db):
    sent = await _send_mockup(
        db=db, project="P", title="T",
        description=None, content="<p>x</p>",
        content_type="html", tags=["a", "b"]
    )
    result = await _tag_mockup(db=db, id=sent["id"], add=["c"], remove=["a"])
    assert "c" in result["tags"]
    assert "a" not in result["tags"]
    assert "b" in result["tags"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_tools.py::test_send_html_mockup -v`
Expected: FAIL

- [ ] **Step 3: Implement `app/mcp_server.py`**

```python
import uuid
from datetime import datetime, timezone
from typing import Annotated

import aiosqlite
from fastmcp import FastMCP
from pydantic import Field

from app import config
from app.db import (
    insert_mockup, get_mockup, list_mockups, list_projects,
    update_mockup as db_update_mockup, delete_mockup as db_delete_mockup
)
from app.storage import slugify_project, write_mockup_file, delete_mockup_file, VALID_TYPES

mcp = FastMCP(
    name="Mockups Gallery",
    instructions=(
        "This server is a permanent mockup gallery. After a successful send_mockup, "
        "delete the local file — this server stores and hosts it. "
        "Give the user the gallery URL so they can view it."
    ),
)

# --- Internal logic (testable without MCP transport) ---

async def _send_mockup(*, db: aiosqlite.Connection, project: str, title: str,
                        description: str | None, content: str, content_type: str,
                        tags: list[str] | None) -> dict:
    if content_type not in VALID_TYPES:
        raise ValueError(f"Invalid content_type: {content_type!r}. Must be one of: {VALID_TYPES}")
    slug = slugify_project(project)
    mockup_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    file_path = write_mockup_file(slug, mockup_id, content_type, content)
    await insert_mockup(
        db, id=mockup_id, project=project, project_slug=slug, title=title,
        description=description, content_type=content_type, file_path=file_path,
        tags=tags or [], created_at=now, updated_at=now
    )
    return {
        "id": mockup_id, "project": project, "project_slug": slug,
        "title": title, "description": description, "content_type": content_type,
        "file_path": file_path, "tags": tags or [],
        "gallery_url": f"{config.BASE_URL}/?mockup={mockup_id}",
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
    }

async def _list_mockups(*, db: aiosqlite.Connection, project: str | None,
                         limit: int, offset: int) -> list[dict]:
    slug = slugify_project(project) if project else None
    return await list_mockups(db, project_slug=slug, limit=limit, offset=offset)

async def _get_mockup(*, db: aiosqlite.Connection, id: str) -> dict:
    row = await get_mockup(db, id)
    if row is None:
        raise ValueError(f"Mockup not found: {id}")
    row["view_url"] = f"{config.BASE_URL}/view/{id}"
    row["gallery_url"] = f"{config.BASE_URL}/?mockup={id}"
    return row

async def _update_mockup(*, db: aiosqlite.Connection, id: str,
                          title: str | None, description: str | None,
                          tags: list[str] | None, content: str | None,
                          content_type: str | None) -> dict:
    existing = await get_mockup(db, id)
    if existing is None:
        raise ValueError(f"Mockup not found: {id}")
    new_file_path = None
    if content is not None:
        ct = content_type or existing["content_type"]
        new_file_path = write_mockup_file(existing["project_slug"], id, ct, content)
        old_path = existing["file_path"]
        if old_path != new_file_path:
            delete_mockup_file(old_path)
    new_ct = content_type if content is not None else None
    await db_update_mockup(db, id, title=title, description=description,
                           tags=tags, file_path=new_file_path, content_type=new_ct)
    return await _get_mockup(db=db, id=id)

async def _delete_mockup(*, db: aiosqlite.Connection, id: str) -> dict:
    existing = await get_mockup(db, id)
    if existing is None:
        raise ValueError(f"Mockup not found: {id}")
    delete_mockup_file(existing["file_path"])
    await db_delete_mockup(db, id)
    return {"deleted": True, "id": id}

async def _tag_mockup(*, db: aiosqlite.Connection, id: str,
                       add: list[str] | None, remove: list[str] | None) -> dict:
    existing = await get_mockup(db, id)
    if existing is None:
        raise ValueError(f"Mockup not found: {id}")
    current = set(existing["tags"])
    if add:
        current.update(add)
    if remove:
        current -= set(remove)
    await db_update_mockup(db, id, tags=sorted(current))
    return await _get_mockup(db=db, id=id)
```

- [ ] **Step 4: Run all MCP tool tests**

Run: `pytest tests/test_mcp_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/mcp_server.py tests/test_mcp_tools.py
git commit -m "feat: MCP tool logic with send, list, get, update, delete, tag operations"
```

---

### Task 6: Wire MCP Tools to FastMCP + Mount in App

**Files:**
- Modify: `app/mcp_server.py` (add @mcp.tool wrappers)
- Modify: `app/main.py` (lifespan, db state, mount MCP)

- [ ] **Step 1: Add MCP tool wrappers to bottom of `app/mcp_server.py`**

```python
from fastmcp import Context
from fastmcp.exceptions import ToolError

def register_tools(get_db):
    """Register MCP tools. `get_db` is a callable that returns the db connection."""

    @mcp.tool(
        description="Sends a mockup to the gallery for permanent storage. "
                    "The local file can be deleted after a successful send."
    )
    async def send_mockup(
        project: Annotated[str, Field(description="Project name")],
        title: Annotated[str, Field(description="Mockup title")],
        content: Annotated[str, Field(description="HTML/SVG as raw string, PNG/JPG as base64")],
        content_type: Annotated[str, Field(description="File type: html, png, jpg, or svg")],
        description: Annotated[str | None, Field(description="Optional description")] = None,
        tags: Annotated[list[str] | None, Field(description="Optional tags")] = None,
    ) -> dict:
        try:
            return await _send_mockup(
                db=get_db(), project=project, title=title,
                description=description, content=content,
                content_type=content_type, tags=tags
            )
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="list_mockups", description="List mockups, optionally filtered by project. Returns reverse-chronological order.")
    async def list_mockups_tool(
        project: Annotated[str | None, Field(description="Filter by project name")] = None,
        limit: Annotated[int, Field(description="Max results", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Offset for pagination", ge=0)] = 0,
    ) -> list[dict]:
        return await _list_mockups(db=get_db(), project=project, limit=limit, offset=offset)

    @mcp.tool(name="get_mockup", description="Get a specific mockup by ID, including its view URL.")
    async def get_mockup_tool(
        id: Annotated[str, Field(description="Mockup UUID")],
    ) -> dict:
        try:
            return await _get_mockup(db=get_db(), id=id)
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="update_mockup", description="Update mockup metadata or replace its content.")
    async def update_mockup_tool(
        id: Annotated[str, Field(description="Mockup UUID")],
        title: Annotated[str | None, Field(description="New title")] = None,
        description: Annotated[str | None, Field(description="New description")] = None,
        tags: Annotated[list[str] | None, Field(description="Replace all tags")] = None,
        content: Annotated[str | None, Field(description="New content (replaces file)")] = None,
        content_type: Annotated[str | None, Field(description="Required if content provided")] = None,
    ) -> dict:
        try:
            return await _update_mockup(
                db=get_db(), id=id, title=title, description=description,
                tags=tags, content=content, content_type=content_type
            )
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="delete_mockup", description="Delete a mockup by ID. Removes both the database record and file.")
    async def delete_mockup_tool(
        id: Annotated[str, Field(description="Mockup UUID")],
    ) -> dict:
        try:
            return await _delete_mockup(db=get_db(), id=id)
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="tag_mockup", description="Add or remove tags on a mockup.")
    async def tag_mockup_tool(
        id: Annotated[str, Field(description="Mockup UUID")],
        add: Annotated[list[str] | None, Field(description="Tags to add")] = None,
        remove: Annotated[list[str] | None, Field(description="Tags to remove")] = None,
    ) -> dict:
        try:
            return await _tag_mockup(db=get_db(), id=id, add=add, remove=remove)
        except ValueError as e:
            raise ToolError(str(e))
```

- [ ] **Step 2: Update `app/main.py` with lifespan and MCP mount**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.db import init_db
from app.mcp_server import mcp, register_tools

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    db = await init_db()
    app.state.db = db
    register_tools(lambda: app.state.db)
    yield
    await db.close()

mcp_app = mcp.http_app(path="/")

from fastmcp.utilities.lifespan import combine_lifespans
app = FastAPI(title="Mockups MPC", lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan))

app.mount("/mcp", mcp_app)

@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 3: Verify `tests/conftest.py` still works**

The conftest from Task 1 already uses `app.router.lifespan_context(app)` which will now run the real lifespan (init_db, register_tools). No changes needed to conftest — verify existing tests pass.

- [ ] **Step 4: Run existing tests to verify nothing broke**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add app/mcp_server.py app/main.py tests/conftest.py
git commit -m "feat: wire MCP tools to FastMCP server, mount in FastAPI with shared lifespan"
```

---

## Chunk 3: Web Layer

### Task 7: JSON API Routes

**Files:**
- Create: `app/routes/__init__.py`
- Create: `app/routes/api.py`
- Modify: `app/main.py` (include router)
- Modify: `tests/test_api.py` (add API tests)

- [ ] **Step 1: Write failing API tests**

Add to `tests/test_api.py`:

```python
@pytest.mark.asyncio
async def test_list_mockups_empty(client):
    resp = await client.get("/api/mockups")
    assert resp.status_code == 200
    assert resp.json() == []

@pytest.mark.asyncio
async def test_create_and_list_via_api(client):
    from app.db import init_db, insert_mockup
    from app.storage import write_mockup_file
    from datetime import datetime, timezone
    db = await init_db()
    now = datetime.now(timezone.utc)
    write_mockup_file("test", "m1", "html", "<p>hi</p>")
    await insert_mockup(db, id="m1", project="Test", project_slug="test",
                        title="First", description=None, content_type="html",
                        file_path="test/m1.html", tags=["ui"], created_at=now, updated_at=now)
    resp = await client.get("/api/mockups")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "First"

@pytest.mark.asyncio
async def test_get_mockup_api(client):
    from app.db import init_db, insert_mockup
    from app.storage import write_mockup_file
    from datetime import datetime, timezone
    db = await init_db()
    now = datetime.now(timezone.utc)
    write_mockup_file("test", "m2", "html", "<p>hello</p>")
    await insert_mockup(db, id="m2", project="Test", project_slug="test",
                        title="Second", description="desc", content_type="html",
                        file_path="test/m2.html", tags=[], created_at=now, updated_at=now)
    resp = await client.get("/api/mockups/m2")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Second"

@pytest.mark.asyncio
async def test_get_mockup_not_found(client):
    resp = await client.get("/api/mockups/nonexistent")
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_list_projects(client):
    from app.db import init_db, insert_mockup
    from app.storage import write_mockup_file
    from datetime import datetime, timezone
    db = await init_db()
    now = datetime.now(timezone.utc)
    write_mockup_file("alpha", "a1", "html", "<p>a</p>")
    await insert_mockup(db, id="a1", project="Alpha", project_slug="alpha",
                        title="A1", description=None, content_type="html",
                        file_path="alpha/a1.html", tags=[], created_at=now, updated_at=now)
    resp = await client.get("/api/projects")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["project"] == "Alpha"
    assert data[0]["count"] == 1
```

- [ ] **Step 2: Run to verify failures**

Run: `pytest tests/test_api.py::test_list_mockups_empty -v`
Expected: FAIL (404 — route doesn't exist)

- [ ] **Step 3: Create `app/routes/__init__.py`** (empty file)

- [ ] **Step 4: Implement `app/routes/api.py`**

```python
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.db import get_mockup, list_mockups, list_projects

router = APIRouter(prefix="/api")

@router.get("/mockups")
async def api_list_mockups(request: Request, project: str | None = None,
                           limit: int = 50, offset: int = 0):
    # project param accepts either slug or display name
    from app.storage import slugify_project
    slug = slugify_project(project) if project else None
    rows = await list_mockups(request.app.state.db, project_slug=slug,
                              limit=limit, offset=offset)
    return rows

@router.get("/mockups/{mockup_id}")
async def api_get_mockup(request: Request, mockup_id: str):
    row = await get_mockup(request.app.state.db, mockup_id)
    if row is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return row

@router.get("/projects")
async def api_list_projects(request: Request):
    return await list_projects(request.app.state.db)
```

- [ ] **Step 5: Add router to `app/main.py`**

Add after the health endpoint:

```python
from app.routes.api import router as api_router
app.include_router(api_router)
```

- [ ] **Step 6: Run all API tests**

Run: `pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/routes/ tests/test_api.py app/main.py
git commit -m "feat: JSON API routes for mockups and projects"
```

---

### Task 8: Gallery + View Routes

**Files:**
- Create: `app/routes/gallery.py`
- Create: `app/templates/gallery.html`
- Create: `app/static/style.css`
- Create: `tests/test_gallery.py`
- Modify: `app/main.py` (include gallery router, mount static, add templates)

- [ ] **Step 1: Write failing gallery tests**

Create `tests/test_gallery.py`:

```python
import pytest
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_gallery_loads(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Mockups" in resp.text

@pytest.mark.asyncio
async def test_view_html_mockup(client):
    from app.db import init_db, insert_mockup
    from app.storage import write_mockup_file
    db = await init_db()
    now = datetime.now(timezone.utc)
    write_mockup_file("test", "v1", "html", "<h1>View Test</h1>")
    await insert_mockup(db, id="v1", project="Test", project_slug="test",
                        title="View", description=None, content_type="html",
                        file_path="test/v1.html", tags=[], created_at=now, updated_at=now)
    resp = await client.get("/view/v1")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "<h1>View Test</h1>" in resp.text

@pytest.mark.asyncio
async def test_view_image_mockup(client):
    from app.db import init_db, insert_mockup
    from app.storage import write_mockup_file
    import base64
    db = await init_db()
    now = datetime.now(timezone.utc)
    raw = b"\x89PNG\r\n\x1a\nfakedata"
    write_mockup_file("test", "img1", "png", base64.b64encode(raw).decode())
    await insert_mockup(db, id="img1", project="Test", project_slug="test",
                        title="Image", description=None, content_type="png",
                        file_path="test/img1.png", tags=[], created_at=now, updated_at=now)
    resp = await client.get("/view/img1")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")

@pytest.mark.asyncio
async def test_view_not_found(client):
    resp = await client.get("/view/nonexistent")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failures**

Run: `pytest tests/test_gallery.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `app/routes/gallery.py`**

```python
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.db import get_mockup
from app.config import get_data_dir

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

MIME_MAP = {
    "html": "text/html",
    "png": "image/png",
    "jpg": "image/jpeg",
    "svg": "image/svg+xml",
}

@router.get("/", response_class=HTMLResponse)
async def gallery(request: Request):
    return templates.TemplateResponse("gallery.html", {"request": request})

@router.get("/view/{mockup_id}")
async def view_mockup(request: Request, mockup_id: str):
    row = await get_mockup(request.app.state.db, mockup_id)
    if row is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    file_path = get_data_dir() / row["file_path"]
    if not file_path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    mime = MIME_MAP.get(row["content_type"], "application/octet-stream")
    return FileResponse(str(file_path), media_type=mime)
```

- [ ] **Step 4: Create `app/templates/gallery.html`**

The gallery uses safe DOM methods (createElement, textContent) instead of innerHTML to prevent XSS. Full template:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mockups Gallery</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <h1>Mockups</h1>
      </div>
      <div class="projects" id="projects"></div>
      <div class="filter-bar">
        <input type="text" id="filter" placeholder="Filter by title..." />
      </div>
      <div class="feed" id="feed"></div>
    </aside>
    <main class="viewer">
      <div class="meta-bar" id="meta-bar">
        <span class="meta-title" id="meta-title"></span>
        <span class="meta-desc" id="meta-desc"></span>
        <span class="meta-tags" id="meta-tags"></span>
        <span class="meta-project" id="meta-project"></span>
        <span class="meta-time" id="meta-time"></span>
        <a class="pop-out" id="pop-out" href="#" target="_blank">Pop out</a>
      </div>
      <div class="viewer-content" id="viewer-content">
        <div class="empty-state">No mockups yet</div>
      </div>
    </main>
  </div>
  <script>
    const state = { project: null, filter: '', mockups: [], offset: 0, loading: false, done: false };
    const LIMIT = 50;

    function createEl(tag, className, textContent) {
      const el = document.createElement(tag);
      if (className) el.className = className;
      if (textContent) el.textContent = textContent;
      return el;
    }

    async function loadProjects() {
      const resp = await fetch('/api/projects');
      const projects = await resp.json();
      const container = document.getElementById('projects');
      container.textContent = '';

      const allItem = createEl('div', 'project-item active', 'All');
      allItem.dataset.slug = '';
      container.appendChild(allItem);

      projects.forEach(p => {
        const el = createEl('div', 'project-item', p.project + ' (' + p.count + ')');
        el.dataset.slug = p.project_slug;
        container.appendChild(el);
      });

      container.addEventListener('click', e => {
        const item = e.target.closest('.project-item');
        if (!item) return;
        container.querySelectorAll('.project-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        state.project = item.dataset.slug || null;
        state.mockups = [];
        state.offset = 0;
        state.done = false;
        document.getElementById('feed').textContent = '';
        loadMockups();
      });
    }

    async function loadMockups() {
      if (state.loading || state.done) return;
      state.loading = true;
      let url = '/api/mockups?limit=' + LIMIT + '&offset=' + state.offset;
      if (state.project) url += '&project=' + encodeURIComponent(state.project);
      const resp = await fetch(url);
      const items = await resp.json();
      if (items.length < LIMIT) state.done = true;
      state.mockups.push(...items);
      state.offset += items.length;
      renderFeed();
      if (state.mockups.length > 0 && state.offset === items.length) {
        selectMockup(state.mockups[0]);
      }
      state.loading = false;
    }

    function renderFeed() {
      const feed = document.getElementById('feed');
      const filter = state.filter.toLowerCase();
      feed.textContent = '';
      state.mockups.forEach(m => {
        if (filter && !m.title.toLowerCase().includes(filter)) return;
        const el = createEl('div', 'feed-item');
        el.dataset.id = m.id;

        el.appendChild(createEl('span', 'feed-title', m.title));
        el.appendChild(createEl('span', 'feed-badge', m.project));
        el.appendChild(createEl('span', 'feed-time', new Date(m.created_at).toLocaleDateString()));

        el.addEventListener('click', () => selectMockup(m));
        feed.appendChild(el);
      });
    }

    function selectMockup(m) {
      const params = new URLSearchParams(window.location.search);
      params.set('mockup', m.id);
      history.replaceState(null, '', '?' + params.toString());

      document.getElementById('meta-title').textContent = m.title;
      document.getElementById('meta-desc').textContent = m.description || '';
      document.getElementById('meta-tags').textContent = (m.tags || []).join(', ');
      document.getElementById('meta-project').textContent = m.project;
      document.getElementById('meta-time').textContent = new Date(m.created_at).toLocaleString();
      document.getElementById('pop-out').href = '/view/' + m.id;

      const viewer = document.getElementById('viewer-content');
      viewer.textContent = '';

      if (m.content_type === 'html') {
        const iframe = document.createElement('iframe');
        iframe.src = '/view/' + m.id;
        iframe.sandbox = 'allow-scripts';
        viewer.appendChild(iframe);
      } else {
        const img = document.createElement('img');
        img.src = '/view/' + m.id;
        img.alt = m.title;
        viewer.appendChild(img);
      }

      document.querySelectorAll('.feed-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === m.id);
      });
    }

    // Filter input
    document.getElementById('filter').addEventListener('input', e => {
      state.filter = e.target.value;
      renderFeed();
    });

    // Infinite scroll on feed
    document.getElementById('feed').addEventListener('scroll', e => {
      const el = e.target;
      if (el.scrollTop + el.clientHeight >= el.scrollHeight - 100) {
        loadMockups();
      }
    });

    // Init
    (async () => {
      await loadProjects();
      const params = new URLSearchParams(window.location.search);
      const directId = params.get('mockup');
      await loadMockups();
      if (directId) {
        const found = state.mockups.find(m => m.id === directId);
        if (found) {
          selectMockup(found);
        } else {
          try {
            const resp = await fetch('/api/mockups/' + directId);
            if (resp.ok) selectMockup(await resp.json());
          } catch (e) { /* ignore */ }
        }
      }
    })();
  </script>
</body>
</html>
```

- [ ] **Step 5: Create `app/static/style.css`**

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #0f1115;
  --bg-sidebar: #161920;
  --bg-hover: #1e2230;
  --bg-active: #252a3a;
  --border: #2a2f3e;
  --text: #e0e0e6;
  --text-dim: #8b8fa3;
  --text-bright: #ffffff;
  --accent: #6c8aff;
  --accent-dim: #4a5f99;
  --badge-bg: #1e2a40;
  --badge-text: #7aa2f7;
}

html, body { height: 100%; background: var(--bg); color: var(--text); font-family: 'Inter', -apple-system, system-ui, sans-serif; }

.layout { display: flex; height: 100vh; }

/* Sidebar */
.sidebar {
  width: 300px; min-width: 300px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  overflow: hidden;
}
.sidebar-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
.sidebar-header h1 { font-size: 16px; font-weight: 600; color: var(--text-bright); letter-spacing: 0.02em; }

.projects { padding: 8px 0; border-bottom: 1px solid var(--border); }
.project-item {
  padding: 6px 16px; font-size: 13px; color: var(--text-dim);
  cursor: pointer; transition: background 0.15s, color 0.15s;
}
.project-item:hover { background: var(--bg-hover); color: var(--text); }
.project-item.active { background: var(--bg-active); color: var(--accent); font-weight: 500; }

.filter-bar { padding: 8px 12px; border-bottom: 1px solid var(--border); }
.filter-bar input {
  width: 100%; padding: 6px 10px; font-size: 12px;
  background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
  color: var(--text); outline: none;
}
.filter-bar input:focus { border-color: var(--accent-dim); }
.filter-bar input::placeholder { color: var(--text-dim); }

.feed { flex: 1; overflow-y: auto; padding: 4px 0; }
.feed-item {
  display: flex; flex-wrap: wrap; gap: 4px; align-items: baseline;
  padding: 8px 16px; cursor: pointer;
  border-left: 2px solid transparent;
  transition: background 0.15s, border-color 0.15s;
}
.feed-item:hover { background: var(--bg-hover); }
.feed-item.active { background: var(--bg-active); border-left-color: var(--accent); }
.feed-title { font-size: 13px; color: var(--text); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.feed-badge {
  font-size: 10px; padding: 1px 6px; border-radius: 3px;
  background: var(--badge-bg); color: var(--badge-text);
  font-weight: 500; text-transform: uppercase; letter-spacing: 0.03em;
}
.feed-time { font-size: 11px; color: var(--text-dim); width: 100%; }

/* Viewer */
.viewer { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.meta-bar {
  display: flex; align-items: center; gap: 12px;
  padding: 8px 16px; min-height: 40px;
  background: var(--bg-sidebar); border-bottom: 1px solid var(--border);
  font-size: 12px; flex-wrap: wrap;
}
.meta-title { font-weight: 600; color: var(--text-bright); font-size: 13px; }
.meta-desc { color: var(--text-dim); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta-tags { color: var(--accent-dim); font-size: 11px; }
.meta-project { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: var(--badge-bg); color: var(--badge-text); }
.meta-time { color: var(--text-dim); font-size: 11px; }
.pop-out { color: var(--accent); text-decoration: none; font-size: 12px; font-weight: 500; white-space: nowrap; }
.pop-out:hover { text-decoration: underline; }

.viewer-content { flex: 1; overflow: hidden; position: relative; }
.viewer-content iframe { width: 100%; height: 100%; border: none; background: #fff; }
.viewer-content img { max-width: 100%; max-height: 100%; object-fit: contain; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); }
.empty-state { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: var(--text-dim); font-size: 14px; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }
```

- [ ] **Step 6: Mount gallery router and static files in `app/main.py`**

Add to `app/main.py`:

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.routes.api import router as api_router
from app.routes.gallery import router as gallery_router

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(api_router)
app.include_router(gallery_router)
```

Note: `gallery_router` must be included AFTER `api_router` so `/api/*` routes match first.

- [ ] **Step 7: Run all gallery tests**

Run: `pytest tests/test_gallery.py -v`
Expected: PASS

- [ ] **Step 8: Run full test suite**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add app/routes/gallery.py app/templates/ app/static/ tests/test_gallery.py app/main.py
git commit -m "feat: gallery UI with sidebar navigation, viewer, and raw mockup serving"
```

---

## Chunk 4: Deployment

### Task 9: Docker + Traefik

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `.env`**

```
SITE_DOMAIN=mockups.yourdomain.com
TRAEFIK_NETWORK=frontend
BASE_URL=https://mockups.yourdomain.com
```

Replace `yourdomain.com` with your actual domain and `frontend` with your Traefik network name.

- [ ] **Step 3: Create `docker-compose.yml`**

Uses the project's standard Traefik labels template (`/home/kyleg/containers/traefik-labels-template.yaml`):

```yaml
services:
  mockups-mpc:
    build: .
    container_name: mockups-mpc
    restart: unless-stopped
    volumes:
      - ./data:/app/data
    environment:
      - BASE_URL=${BASE_URL}
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=${TRAEFIK_NETWORK}"

      - "traefik.http.routers.mockups-http.rule=Host(`${SITE_DOMAIN}`)"
      - "traefik.http.routers.mockups-http.entrypoints=web"
      - "traefik.http.routers.mockups-http.service=mockups"

      - "traefik.http.routers.mockups-https.rule=Host(`${SITE_DOMAIN}`)"
      - "traefik.http.routers.mockups-https.entrypoints=websecure"
      - "traefik.http.routers.mockups-https.tls.certresolver=cloudflare"
      - "traefik.http.routers.mockups-https.service=mockups"

      - "traefik.http.services.mockups.loadbalancer.server.port=8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - traefik

networks:
  traefik:
    name: ${TRAEFIK_NETWORK}
    external: true
```

- [ ] **Step 4: Run full test suite one final time**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml .env .gitignore
git commit -m "feat: Docker + Traefik deployment with health check and proxy network"
```

---

### Task 10: Integration Smoke Test

- [ ] **Step 1: Build and start the container**

```bash
docker compose up --build -d
```

- [ ] **Step 2: Verify health endpoint**

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 3: Verify gallery loads**

Open `http://localhost:8000` in browser. Should see the dark-themed gallery with "No mockups yet" empty state.

- [ ] **Step 4: Verify MCP endpoint responds**

```bash
curl http://localhost:8000/mcp/
```

Should return an MCP-related response (not 404).

- [ ] **Step 5: Stop container**

```bash
docker compose down
```

- [ ] **Step 6: Commit any fixes from smoke test**

```bash
git add -A
git commit -m "fix: smoke test adjustments"
```

(Skip this commit if no fixes needed.)
