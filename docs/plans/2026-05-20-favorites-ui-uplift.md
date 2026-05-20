# Favorites + UI Uplift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent favoriting of mockups with a sidebar filter, plus a UI uplift — server-side cross-field search, sort options, feed-item polish, viewer chrome, and a refreshed visual direction (Graphite background, Geist type, cyan accent).

**Architecture:** Search, sort, and favorites filtering become query parameters on `GET /api/mockups`, resolved in SQL. A `favorite` integer column is added to the `mockups` table via an idempotent boot-time migration. The frontend (vanilla JS, no build step) builds queries from UI state and renders results. Visual changes are CSS-token + template edits.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite (SQLite WAL), pytest + pytest-asyncio, Jinja2, vanilla JS, plain CSS.

**Spec:** `docs/specs/2026-05-20-favorites-ui-uplift-design.md`

**Branch:** `feat/favorites-ui-uplift` (already created; spec already committed).

---

## File Map

- `app/db.py` — Modify: add `favorite` to schema + migration in `init_db`; add `set_favorite`, `count_favorites`; extend `list_mockups` with `q`/`sort`/`favorites_only`.
- `app/routes/api.py` — Modify: add `q`/`sort`/`favorites_only` to `GET /api/mockups`; add `PUT /api/mockups/{id}/favorite`; add `GET /api/favorites/count`.
- `app/models.py` — Modify: add `favorite: bool = False` to `MockupRecord` and `MockupSummary`.
- `app/static/style.css` — Modify: Graphite palette tokens, Geist fonts, grid opacity, and new component styles.
- `app/templates/gallery.html` — Modify: sidebar favorites item, search/sort controls markup, feed star button, viewport toggles + fullscreen, and the JS to drive all of it.
- `tests/test_db.py` — Modify: tests for migration, `set_favorite`, `count_favorites`, and `list_mockups` search/sort/favorites.
- `tests/test_api.py` — Modify: tests for the favorite endpoint, count endpoint, and query params.
- `VERSION`, `pyproject.toml`, `server.json`, `CHANGELOG.md` — Modify: bump to 1.3.0.

---

## Task 1: Schema migration — add `favorite` column

**Files:**
- Modify: `app/db.py` (CREATE_TABLE constant + `init_db`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
import aiosqlite
from app import config

@pytest.mark.asyncio
async def test_init_db_adds_favorite_column_to_legacy_db(tmp_data_dir):
    # Simulate a pre-favorite database: create the old schema by hand.
    legacy = await aiosqlite.connect(str(config.DB_PATH))
    await legacy.execute("""
        CREATE TABLE mockups (
            id TEXT PRIMARY KEY, project TEXT NOT NULL, project_slug TEXT NOT NULL,
            title TEXT NOT NULL, description TEXT, content_type TEXT NOT NULL,
            file_path TEXT NOT NULL, tags TEXT DEFAULT '[]',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
    await legacy.execute(
        "INSERT INTO mockups (id, project, project_slug, title, content_type, file_path, created_at, updated_at) "
        "VALUES ('old1','P','p','Legacy','html','p/old1.html','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')")
    await legacy.commit()
    await legacy.close()

    # init_db must migrate the existing DB in place.
    db = await init_db()
    cursor = await db.execute("PRAGMA table_info(mockups)")
    cols = {row["name"] for row in await cursor.fetchall()}
    assert "favorite" in cols
    row = await get_mockup(db, "old1")
    assert row["favorite"] == 0
    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_init_db_adds_favorite_column_to_legacy_db -v`
Expected: FAIL — `assert "favorite" in cols` fails (column not added).

- [ ] **Step 3: Add the column to the schema and a migration step**

In `app/db.py`, update the `CREATE_TABLE` constant to include the column and a favorite index:

```python
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
    favorite INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mockups_project_slug ON mockups(project_slug);
CREATE INDEX IF NOT EXISTS idx_mockups_created_at ON mockups(created_at);
CREATE INDEX IF NOT EXISTS idx_mockups_favorite ON mockups(favorite);
"""


async def _migrate_favorite_column(db: aiosqlite.Connection) -> None:
    """Add the favorite column to databases created before it existed."""
    cursor = await db.execute("PRAGMA table_info(mockups)")
    cols = {row["name"] for row in await cursor.fetchall()}
    if "favorite" not in cols:
        await db.execute("ALTER TABLE mockups ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_mockups_favorite ON mockups(favorite)")
        await db.commit()
```

Then call it from `init_db`, after `executescript(CREATE_TABLE)`:

```python
async def init_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(get_db_path()))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(CREATE_TABLE)
    await db.commit()
    await _migrate_favorite_column(db)
    return db
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_init_db_adds_favorite_column_to_legacy_db -v`
Expected: PASS

- [ ] **Step 5: Run the full db test file to confirm no regressions**

Run: `pytest tests/test_db.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add favorite column with idempotent migration"
```

---

## Task 2: `set_favorite` and `count_favorites` in db layer

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py` (add `set_favorite, count_favorites` to the existing `from app.db import ...` line):

```python
@pytest.mark.asyncio
async def test_set_favorite(db):
    now = datetime.now(timezone.utc)
    await insert_mockup(db, id="f1", project="P", project_slug="p",
                        title="Star me", description=None, content_type="html",
                        file_path="p/f1.html", tags=[], created_at=now, updated_at=now)
    assert await set_favorite(db, "f1", True) is True
    assert (await get_mockup(db, "f1"))["favorite"] == 1
    assert await set_favorite(db, "f1", False) is True
    assert (await get_mockup(db, "f1"))["favorite"] == 0

@pytest.mark.asyncio
async def test_set_favorite_nonexistent(db):
    assert await set_favorite(db, "nope", True) is False

@pytest.mark.asyncio
async def test_count_favorites(db):
    now = datetime.now(timezone.utc)
    for i in range(3):
        await insert_mockup(db, id=f"c{i}", project="P", project_slug="p",
                            title=f"M{i}", description=None, content_type="html",
                            file_path=f"p/c{i}.html", tags=[], created_at=now, updated_at=now)
    await set_favorite(db, "c0", True)
    await set_favorite(db, "c2", True)
    assert await count_favorites(db) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py::test_set_favorite tests/test_db.py::test_count_favorites -v`
Expected: FAIL — `ImportError: cannot import name 'set_favorite'`.

- [ ] **Step 3: Implement `set_favorite` and `count_favorites`**

Add to `app/db.py` (after `update_mockup`):

```python
async def set_favorite(db: aiosqlite.Connection, mockup_id: str, value: bool) -> bool:
    cursor = await db.execute(
        "UPDATE mockups SET favorite = ?, updated_at = ? WHERE id = ?",
        (1 if value else 0, datetime.now(timezone.utc).isoformat(), mockup_id)
    )
    await db.commit()
    return cursor.rowcount > 0


async def count_favorites(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COUNT(*) AS n FROM mockups WHERE favorite = 1")
    row = await cursor.fetchone()
    return row["n"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py::test_set_favorite tests/test_db.py::test_set_favorite_nonexistent tests/test_db.py::test_count_favorites -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add set_favorite and count_favorites db helpers"
```

---

## Task 3: Extend `list_mockups` with search, sort, favorites filter

**Files:**
- Modify: `app/db.py` (`list_mockups`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
async def _seed_search(db):
    """Three mockups with distinct titles/descriptions/tags and timestamps."""
    rows = [
        ("s0", "Login screen", "auth flow entry", ["auth", "ui"],   datetime(2026, 3, 1, tzinfo=timezone.utc)),
        ("s1", "Dashboard",    "metrics overview", ["charts"],      datetime(2026, 3, 2, tzinfo=timezone.utc)),
        ("s2", "Pricing page", "plans and tiers",  ["marketing"],   datetime(2026, 3, 3, tzinfo=timezone.utc)),
    ]
    for id_, title, desc, tags, ts in rows:
        await insert_mockup(db, id=id_, project="P", project_slug="p",
                            title=title, description=desc, content_type="html",
                            file_path=f"p/{id_}.html", tags=tags, created_at=ts, updated_at=ts)

@pytest.mark.asyncio
async def test_list_mockups_search_title(db):
    await _seed_search(db)
    rows = await list_mockups(db, q="dashboard")
    assert [r["id"] for r in rows] == ["s1"]

@pytest.mark.asyncio
async def test_list_mockups_search_description(db):
    await _seed_search(db)
    rows = await list_mockups(db, q="tiers")
    assert [r["id"] for r in rows] == ["s2"]

@pytest.mark.asyncio
async def test_list_mockups_search_tags(db):
    await _seed_search(db)
    rows = await list_mockups(db, q="auth")
    assert [r["id"] for r in rows] == ["s0"]  # matches title "auth flow"? no — desc "auth flow entry" & tag "auth"

@pytest.mark.asyncio
async def test_list_mockups_search_no_match(db):
    await _seed_search(db)
    assert await list_mockups(db, q="zzzznope") == []

@pytest.mark.asyncio
async def test_list_mockups_sort_oldest(db):
    await _seed_search(db)
    rows = await list_mockups(db, sort="oldest")
    assert [r["id"] for r in rows] == ["s0", "s1", "s2"]

@pytest.mark.asyncio
async def test_list_mockups_sort_newest_default(db):
    await _seed_search(db)
    rows = await list_mockups(db)
    assert [r["id"] for r in rows] == ["s2", "s1", "s0"]

@pytest.mark.asyncio
async def test_list_mockups_sort_favorites_first(db):
    await _seed_search(db)
    await set_favorite(db, "s0", True)  # oldest, but favorited
    rows = await list_mockups(db, sort="favorites")
    assert rows[0]["id"] == "s0"           # favorite floats to top
    assert [r["id"] for r in rows[1:]] == ["s2", "s1"]  # rest newest-first

@pytest.mark.asyncio
async def test_list_mockups_favorites_only(db):
    await _seed_search(db)
    await set_favorite(db, "s1", True)
    rows = await list_mockups(db, favorites_only=True)
    assert [r["id"] for r in rows] == ["s1"]

@pytest.mark.asyncio
async def test_list_mockups_invalid_sort_falls_back_to_newest(db):
    await _seed_search(db)
    rows = await list_mockups(db, sort="bogus")
    assert [r["id"] for r in rows] == ["s2", "s1", "s0"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -k "search or sort or favorites_only" -v`
Expected: FAIL — `list_mockups() got an unexpected keyword argument 'q'`.

- [ ] **Step 3: Rewrite `list_mockups`**

Replace the existing `list_mockups` in `app/db.py` with:

```python
_SORT_ORDERS = {
    "newest": "created_at DESC",
    "oldest": "created_at ASC",
    "favorites": "favorite DESC, created_at DESC",
}


async def list_mockups(db: aiosqlite.Connection, *, project_slug: str | None = None,
                        q: str | None = None, sort: str = "newest",
                        favorites_only: bool = False,
                        limit: int = 50, offset: int = 0) -> list[dict]:
    conditions = []
    params: list = []
    if project_slug:
        conditions.append("project_slug = ?")
        params.append(project_slug)
    if favorites_only:
        conditions.append("favorite = 1")
    if q:
        like = f"%{q}%"
        conditions.append("(title LIKE ? OR description LIKE ? OR tags LIKE ?)")
        params.extend([like, like, like])

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order = _SORT_ORDERS.get(sort, _SORT_ORDERS["newest"])
    params.extend([limit, offset])

    cursor = await db.execute(
        f"SELECT * FROM mockups {where} ORDER BY {order} LIMIT ? OFFSET ?", params
    )
    return [_row_to_dict(row) for row in await cursor.fetchall()]
```

Note: `_row_to_dict` already returns every column, so `favorite` is included automatically (as `0`/`1`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: all PASS (including the existing `test_list_mockups_reverse_chrono` and `test_list_mockups_filter_by_project`, which use the unchanged defaults).

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add search, sort, and favorites filtering to list_mockups"
```

---

## Task 4: API — query params, favorite endpoint, count endpoint

**Files:**
- Modify: `app/routes/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api.py`:

```python
async def _seed_api(client):
    """Insert two mockups via a shared db connection; return their ids."""
    from app.db import init_db, insert_mockup
    from app.storage import write_mockup_file
    from datetime import datetime, timezone
    db = await init_db()
    t0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 2, tzinfo=timezone.utc)
    write_mockup_file("p", "api0", "html", "<p>0</p>")
    write_mockup_file("p", "api1", "html", "<p>1</p>")
    await insert_mockup(db, id="api0", project="P", project_slug="p",
                        title="Login screen", description="auth", content_type="html",
                        file_path="p/api0.html", tags=["auth"], created_at=t0, updated_at=t0)
    await insert_mockup(db, id="api1", project="P", project_slug="p",
                        title="Dashboard", description="metrics", content_type="html",
                        file_path="p/api1.html", tags=["charts"], created_at=t1, updated_at=t1)

@pytest.mark.asyncio
async def test_api_search(client):
    await _seed_api(client)
    resp = await client.get("/api/mockups?q=dashboard")
    data = resp.json()
    assert [m["id"] for m in data] == ["api1"]

@pytest.mark.asyncio
async def test_api_sort_oldest(client):
    await _seed_api(client)
    resp = await client.get("/api/mockups?sort=oldest")
    assert [m["id"] for m in resp.json()] == ["api0", "api1"]

@pytest.mark.asyncio
async def test_api_set_favorite(client):
    await _seed_api(client)
    resp = await client.put("/api/mockups/api0/favorite", json={"favorite": True})
    assert resp.status_code == 200
    assert resp.json()["favorite"] == 1
    # favorites_only now returns it
    resp = await client.get("/api/mockups?favorites_only=true")
    assert [m["id"] for m in resp.json()] == ["api0"]

@pytest.mark.asyncio
async def test_api_set_favorite_idempotent(client):
    await _seed_api(client)
    await client.put("/api/mockups/api0/favorite", json={"favorite": True})
    resp = await client.put("/api/mockups/api0/favorite", json={"favorite": True})
    assert resp.status_code == 200
    assert resp.json()["favorite"] == 1

@pytest.mark.asyncio
async def test_api_set_favorite_not_found(client):
    resp = await client.put("/api/mockups/nope/favorite", json={"favorite": True})
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_api_favorites_count(client):
    await _seed_api(client)
    await client.put("/api/mockups/api0/favorite", json={"favorite": True})
    resp = await client.get("/api/favorites/count")
    assert resp.status_code == 200
    assert resp.json() == {"count": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -k "search or sort_oldest or favorite or favorites_count" -v`
Expected: FAIL — query params ignored / `PUT` route returns 405 / count route 404.

- [ ] **Step 3: Update `GET /api/mockups` and add the new routes**

In `app/routes/api.py`, replace the `api_list_mockups` handler with one that passes the new params:

```python
@router.get("/mockups")
async def api_list_mockups(request: Request, project: str | None = None,
                           q: str | None = None, sort: str = "newest",
                           favorites_only: bool = False,
                           limit: int = 50, offset: int = 0):
    # project param accepts either slug or display name
    from app.storage import slugify_project
    slug = slugify_project(project) if project else None
    rows = await list_mockups(request.app.state.db, project_slug=slug, q=q,
                              sort=sort, favorites_only=favorites_only,
                              limit=limit, offset=offset)
    return rows
```

Add a Pydantic body model and the two new routes (place after `api_get_mockup`). Add `from pydantic import BaseModel` at the top of the file and `from app.db import get_mockup, list_mockups, list_projects, set_favorite, count_favorites`:

```python
class FavoriteBody(BaseModel):
    favorite: bool


@router.put("/mockups/{mockup_id}/favorite")
async def api_set_favorite(request: Request, mockup_id: str, body: FavoriteBody):
    ok = await set_favorite(request.app.state.db, mockup_id, body.favorite)
    if not ok:
        return JSONResponse({"error": "Not found"}, status_code=404)
    row = await get_mockup(request.app.state.db, mockup_id)
    return row


@router.get("/favorites/count")
async def api_favorites_count(request: Request):
    return {"count": await count_favorites(request.app.state.db)}
```

Note: register `/favorites/count` is distinct from `/mockups/{id}` so there is no route collision.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes/api.py tests/test_api.py
git commit -m "feat: add search/sort/favorites params, favorite + count endpoints"
```

---

## Task 5: Add `favorite` to Pydantic models

**Files:**
- Modify: `app/models.py`
- Test: `tests/test_db.py` (a small assertion that the field round-trips)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
from app.models import MockupRecord

@pytest.mark.asyncio
async def test_mockup_record_has_favorite(db):
    now = datetime.now(timezone.utc)
    await insert_mockup(db, id="r1", project="P", project_slug="p",
                        title="R", description=None, content_type="html",
                        file_path="p/r1.html", tags=[], created_at=now, updated_at=now)
    await set_favorite(db, "r1", True)
    row = await get_mockup(db, "r1")
    record = MockupRecord(**row)
    assert record.favorite is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_mockup_record_has_favorite -v`
Expected: FAIL — `MockupRecord` rejects/drops `favorite` (no such field; `record.favorite` AttributeError).

- [ ] **Step 3: Add the field to both models**

In `app/models.py`, add `favorite: bool = False` to `MockupRecord` and `MockupSummary` (after `tags`):

```python
class MockupRecord(BaseModel):
    id: str
    project: str
    project_slug: str
    title: str
    description: str | None = None
    content_type: str
    file_path: str
    tags: list[str] = []
    favorite: bool = False
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
    favorite: bool = False
    created_at: datetime
    updated_at: datetime
```

(SQLite returns `favorite` as `0`/`1`; Pydantic coerces int → bool.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_mockup_record_has_favorite -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add app/models.py tests/test_db.py
git commit -m "feat: add favorite field to mockup models"
```

---

## Task 6: CSS — Graphite palette, Geist fonts, grid

**Files:**
- Modify: `app/static/style.css`

No automated test (CSS). Verification is visual against the running gallery (see Task 12 final verify).

- [ ] **Step 1: Swap the font import**

Replace the `@import` line at the top of `style.css`:

```css
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@300;400;500&display=swap');
```

- [ ] **Step 2: Update the font token values**

In `:root`, change the font tokens (keep the variable names — they are used throughout):

```css
  --font-mono:     'Geist Mono', 'JetBrains Mono', 'SF Mono', monospace;
  --font-heading:  'Geist', 'Inter', system-ui, sans-serif;
  --font-sans:     'Geist', 'Inter', system-ui, sans-serif;
```

- [ ] **Step 3: Update the background + border + text-ghost/tertiary tokens to Graphite**

In `:root`, replace these token values (leave accent, star, type-* untouched):

```css
  --bg-deep:       #18181a;
  --bg-surface:    #1d1d20;
  --bg-raised:     #242428;
  --bg-hover:      #2c2c31;
  --bg-active:     #34343a;

  --border-dim:    #2a2a2f;
  --border-subtle: #3a3a40;
  --border-focus:  #4d4d55;

  --text-primary:  #fafafa;
  --text-secondary:#a8a8b0;
  --text-tertiary: #7c7c85;
  --text-ghost:    #56565e;
```

Add a star token to `:root` (used by favorites UI in later tasks):

```css
  --star:          #fbbf24;
  --star-dim:      #b45309;
  --star-glow:     rgba(251, 191, 36, 0.12);
```

- [ ] **Step 4: Raise the blueprint grid opacity so it survives the lighter floor**

Find the `.main::before` rule and change `opacity: 0.18;` to:

```css
  opacity: 0.5;
```

- [ ] **Step 5: Commit**

```bash
git add app/static/style.css
git commit -m "feat: Graphite palette and Geist type direction"
```

---

## Task 7: CSS — new component styles

**Files:**
- Modify: `app/static/style.css`

Add these new rules to `style.css` (append near related sections; order does not matter for correctness). All use existing tokens plus the `--star*` tokens from Task 6.

- [ ] **Step 1: Favorites sidebar item**

```css
/* Favorites pseudo-project */
.project-item.favorites .project-name { color: var(--star); display: flex; align-items: center; gap: 7px; }
.project-item.favorites .fav-star { font-size: 12px; line-height: 1; }
.project-item.favorites.active { background: var(--star-glow); }
.project-item.favorites.active .project-name,
.project-item.favorites.active .project-count { color: var(--star); }
.project-divider { height: 1px; background: var(--border-dim); margin: 8px 8px; }
```

- [ ] **Step 2: Search icon + sort segmented control**

```css
/* Search input gets a leading icon */
.search-wrap { position: relative; display: flex; align-items: center; }
.search-wrap .search-icon {
  position: absolute; left: 10px; width: 13px; height: 13px;
  stroke: var(--text-ghost); fill: none; stroke-width: 1.6; pointer-events: none;
}
.search-wrap .filter-input { padding-left: 30px; }

/* Sort segmented control */
.sort-seg {
  display: flex; margin-top: 8px; background: var(--bg-raised);
  border: 1px solid var(--border-dim); border-radius: var(--radius); padding: 2px; gap: 2px;
}
.sort-opt {
  flex: 1; text-align: center; font-family: var(--font-mono); font-size: 9.5px;
  font-weight: 500; letter-spacing: 0.03em; text-transform: uppercase;
  color: var(--text-tertiary); padding: 5px 4px; border-radius: var(--radius-sm);
  cursor: pointer; transition: all 0.12s ease; user-select: none;
}
.sort-opt:hover { color: var(--text-secondary); }
.sort-opt.active { background: var(--bg-active); color: var(--accent); }
.sort-opt.active.fav-sort { color: var(--star); }
```

- [ ] **Step 3: Feed star button**

```css
/* Star button on feed items */
.feed-star {
  position: absolute; right: 10px; top: 9px; width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  background: transparent; border: none; cursor: pointer; font-size: 13px;
  line-height: 1; padding: 0; color: var(--text-ghost); z-index: 3;
  opacity: 0; transition: opacity 0.12s ease, color 0.12s ease, transform 0.12s var(--ease-spring);
}
.feed-item:hover .feed-star { opacity: 0.55; }
.feed-item:hover .feed-star:hover { opacity: 1; color: var(--star); transform: scale(1.15); }
.feed-star.starred { opacity: 1; color: var(--star); }
/* When starred, park the star on the left so favorites scan down the left edge */
.feed-star.starred { right: auto; left: 4px; top: 50%; transform: translateY(-50%); }
.feed-item:hover .feed-star.starred { opacity: 1; }
.feed-item .feed-title { transition: padding 0.12s ease; }
.feed-item.has-fav .feed-title { padding-left: 14px; }
```

- [ ] **Step 4: Viewer chrome — viewport toggles + fullscreen + meta star**

```css
/* Viewport size toggles in the meta bar */
.viewport-seg {
  display: flex; background: var(--bg-raised); border: 1px solid var(--border-dim);
  border-radius: var(--radius-sm); padding: 2px; gap: 2px; flex-shrink: 0;
}
.vp-opt {
  display: flex; align-items: center; gap: 4px; font-family: var(--font-mono);
  font-size: 9px; font-weight: 500; letter-spacing: 0.03em; text-transform: uppercase;
  color: var(--text-tertiary); padding: 4px 8px; border-radius: 3px; cursor: pointer;
  transition: all 0.12s ease; user-select: none;
}
.vp-opt:hover { color: var(--text-secondary); }
.vp-opt.active { background: var(--bg-active); color: var(--accent); }
.vp-opt svg { width: 11px; height: 11px; stroke: currentColor; fill: none; stroke-width: 1.6; }

.meta-icon-btn {
  display: flex; align-items: center; justify-content: center; width: 28px; height: 24px;
  border: 1px solid var(--border-dim); border-radius: var(--radius-sm);
  background: var(--bg-raised); color: var(--text-tertiary); cursor: pointer;
  flex-shrink: 0; transition: all 0.12s ease;
}
.meta-icon-btn:hover { color: var(--accent); border-color: var(--accent-dim); background: var(--accent-glow); }
.meta-icon-btn svg { width: 13px; height: 13px; stroke: currentColor; fill: none; stroke-width: 1.6; }

.meta-title .meta-star { color: var(--star); font-size: 12px; margin-right: 5px; }

/* Constrain the iframe width for viewport preview */
.viewer.vp-mobile .viewer-iframe  { width: 375px; }
.viewer.vp-tablet .viewer-iframe  { width: 768px; }
.viewer .viewer-iframe { transition: width 0.3s var(--ease-out); }
```

- [ ] **Step 5: Commit**

```bash
git add app/static/style.css
git commit -m "feat: styles for favorites, search/sort, star button, viewer chrome"
```

---

## Task 8: Frontend state + query building

**Files:**
- Modify: `app/templates/gallery.html` (the inline `<script>`)

Vanilla JS, no test harness — verify by reading and by the end-to-end manual checks in Task 12.

- [ ] **Step 1: Extend the state object and add a sentinel constant**

In the `<script>`, update the `state` object and add a constant above it:

```javascript
  var FAVORITES = "__favorites__";   // sentinel for state.activeProject

  var state = {
    projects: [],
    mockups: [],
    activeProject: null,   // null = all, FAVORITES = favorites filter, else a project slug
    activeMockupId: null,
    filterText: "",
    sort: "newest",
    offset: 0,
    limit: 50,
    loading: false,
    exhausted: false
  };
```

- [ ] **Step 2: Build the query URL from state in `loadMockups`**

Replace the URL-building lines in `loadMockups` (currently building `/api/mockups?limit=...&offset=...&project=...`) with:

```javascript
    var url = "/api/mockups?limit=" + state.limit + "&offset=" + state.offset
            + "&sort=" + encodeURIComponent(state.sort);
    if (state.activeProject === FAVORITES) {
      url += "&favorites_only=true";
    } else if (state.activeProject) {
      url += "&project=" + encodeURIComponent(state.activeProject);
    }
    if (state.filterText) {
      url += "&q=" + encodeURIComponent(state.filterText);
    }
```

- [ ] **Step 3: Remove the now-obsolete client-side title filter**

Search is server-side now. In `renderFeed`, replace `var filtered = getFilteredMockups();` with `var filtered = state.mockups;` and delete the `getFilteredMockups` function. (Leave the `feedStatusEl` "No matches" branch — it still applies when the server returns nothing.)

- [ ] **Step 4: Update the filter input handler to reload from the server**

Replace the existing `filterInput` input handler with:

```javascript
  var filterTimer = null;
  filterInput.addEventListener("input", function () {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(function () {
      state.filterText = filterInput.value.trim();
      loadMockups(true);
    }, 200);
  });
```

- [ ] **Step 5: Commit**

```bash
git add app/templates/gallery.html
git commit -m "feat: state and server-side query building for search/sort/favorites"
```

---

## Task 9: Frontend — favorites sidebar item + sort control markup/wiring

**Files:**
- Modify: `app/templates/gallery.html`

- [ ] **Step 1: Wrap the search input and add the sort control markup**

Replace the `.sidebar-filter` block in the HTML with:

```html
      <div class="sidebar-filter">
        <div class="search-wrap">
          <svg class="search-icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/></svg>
          <input
            type="text" class="filter-input" id="filter-input"
            placeholder="Search title, description, tags…"
            autocomplete="off" spellcheck="false"
          >
        </div>
        <div class="sort-seg" id="sort-seg">
          <div class="sort-opt active" data-sort="newest">Newest</div>
          <div class="sort-opt" data-sort="oldest">Oldest</div>
          <div class="sort-opt fav-sort" data-sort="favorites">★ First</div>
        </div>
      </div>
```

- [ ] **Step 2: Render the Favorites pseudo-item in `renderProjects`**

In `renderProjects`, after `clearChildren(projectListEl);` and before the "All" item, insert the Favorites item. Also track favorites count in state (set in Task 9 Step 4). Add:

```javascript
    // Favorites pseudo-item
    var favItem = el("li", "project-item favorites" + (state.activeProject === FAVORITES ? " active" : ""));
    favItem.addEventListener("click", function () { selectProject(FAVORITES); });
    var favName = el("span", "project-name");
    var favStar = el("span", "fav-star");
    favStar.appendChild(text("★"));
    favName.appendChild(favStar);
    favName.appendChild(text("Favorites"));
    var favCount = el("span", "project-count");
    favCount.appendChild(text(String(state.favoritesCount || 0)));
    favItem.appendChild(favName);
    favItem.appendChild(favCount);
    projectListEl.appendChild(favItem);
```

Then after the existing "All" item is appended, add a divider before the real projects:

```javascript
    projectListEl.appendChild(el("div", "project-divider"));
```

- [ ] **Step 3: Add `favoritesCount` to state and a loader**

Add `favoritesCount: 0,` to the `state` object. Add a loader function near `loadProjects`:

```javascript
  async function loadFavoritesCount() {
    try {
      var resp = await fetch("/api/favorites/count");
      var data = await resp.json();
      state.favoritesCount = data.count || 0;
    } catch (e) { /* leave previous value */ }
  }
```

- [ ] **Step 4: Wire the sort control**

Add near the filter input handler:

```javascript
  var sortSeg = document.getElementById("sort-seg");
  sortSeg.addEventListener("click", function (e) {
    var opt = e.target.closest(".sort-opt");
    if (!opt) return;
    sortSeg.querySelectorAll(".sort-opt").forEach(function (o) { o.classList.remove("active"); });
    opt.classList.add("active");
    state.sort = opt.getAttribute("data-sort");
    loadMockups(true);
  });
```

- [ ] **Step 5: Call `loadFavoritesCount` in `init` and after favorite toggles/deletes**

In `init`, add `await loadFavoritesCount();` before `renderProjects` is first triggered (i.e. right after `loadProjects()`). It will also be called from Task 10's toggle handler and the existing `deleteMockup`. Update `init`:

```javascript
  async function init() {
    await loadProjects();
    await loadFavoritesCount();
    renderProjects();
    await loadMockups(true);
    updateGuideLink();

    var initialId = getInitialMockupId();
    if (initialId) {
      selectMockup(initialId);
    } else if (state.mockups.length > 0) {
      selectMockup(state.mockups[0].id);
    }
  }
```

(`loadProjects` already calls `renderProjects`; the extra call ensures the favorites count shows once loaded. Calling `renderProjects` twice is cheap and idempotent.)

- [ ] **Step 6: Commit**

```bash
git add app/templates/gallery.html
git commit -m "feat: favorites sidebar item and sort control"
```

---

## Task 10: Frontend — feed star button + optimistic toggle

**Files:**
- Modify: `app/templates/gallery.html`

- [ ] **Step 1: Render the star button in `createFeedItem`**

In `createFeedItem`, after `item.setAttribute("data-id", mockup.id);`, add a `has-fav` class toggle and the star button. Insert before the title is appended:

```javascript
    if (mockup.favorite) item.classList.add("has-fav");

    var star = el("button", "feed-star" + (mockup.favorite ? " starred" : ""),
                  { title: mockup.favorite ? "Unfavorite" : "Favorite", type: "button" });
    star.appendChild(text(mockup.favorite ? "★" : "☆"));  // ★ / ☆
    star.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleFavorite(mockup, star, item);
    });
    item.appendChild(star);
```

- [ ] **Step 2: Implement `toggleFavorite` with optimistic update + rollback**

Add this function (near `deleteMockup`):

```javascript
  async function toggleFavorite(mockup, starEl, itemEl) {
    var next = !mockup.favorite;
    // optimistic UI
    applyFavoriteUI(mockup, starEl, itemEl, next);
    try {
      var resp = await fetch("/api/mockups/" + encodeURIComponent(mockup.id) + "/favorite", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ favorite: next })
      });
      if (!resp.ok) throw new Error("request failed");
      await loadFavoritesCount();
      renderProjects();
      // If we're viewing the favorites filter and just unfavorited, drop it from the feed
      if (state.activeProject === FAVORITES && !next) {
        state.mockups = state.mockups.filter(function (m) { return m.id !== mockup.id; });
        renderFeed(true);
      }
      // keep meta-bar star in sync if this is the open mockup
      if (state.activeMockupId === mockup.id) renderMetaBar(mockup);
    } catch (e) {
      // rollback
      applyFavoriteUI(mockup, starEl, itemEl, !next);
    }
  }

  function applyFavoriteUI(mockup, starEl, itemEl, value) {
    mockup.favorite = value;
    starEl.textContent = value ? "★" : "☆";
    starEl.title = value ? "Unfavorite" : "Favorite";
    starEl.classList.toggle("starred", value);
    if (itemEl) itemEl.classList.toggle("has-fav", value);
  }
```

- [ ] **Step 2b: Refresh favorites count after deletes**

In `deleteMockup`, after the existing `loadProjects();` call, add:

```javascript
    loadFavoritesCount().then(renderProjects);
```

- [ ] **Step 3: Commit**

```bash
git add app/templates/gallery.html
git commit -m "feat: feed star button with optimistic favorite toggle"
```

---

## Task 11: Frontend — viewer chrome (viewport toggles, fullscreen, meta star)

**Files:**
- Modify: `app/templates/gallery.html`

- [ ] **Step 1: Add a meta-bar star when the open mockup is favorited**

In `renderMetaBar`, after `metaBar.classList.remove("empty");` and before the title is created, prepend a star if favorited:

```javascript
    if (mockup.favorite) {
      var metaStar = el("span", "meta-star");
      metaStar.appendChild(text("★"));
      metaBar.appendChild(metaStar);
    }
```

- [ ] **Step 2: Add viewport toggles + fullscreen for HTML mockups**

In `renderMetaBar`, replace the trailing `popout` block with viewport controls (only for HTML), the fullscreen button, then the popout. Replace from `// spacer` through the `popout` append with:

```javascript
    // spacer
    var spacer = el("span", "");
    spacer.style.flex = "1";
    metaBar.appendChild(spacer);

    if (mockup.content_type === "html") {
      var vpSeg = el("div", "viewport-seg");
      [["mobile", "375"], ["tablet", "768"], ["desktop", "Full"]].forEach(function (pair) {
        var opt = el("div", "vp-opt" + (pair[0] === "desktop" ? " active" : ""), { "data-vp": pair[0] });
        opt.appendChild(text(pair[1]));
        opt.addEventListener("click", function () { setViewport(pair[0], vpSeg); });
        vpSeg.appendChild(opt);
      });
      metaBar.appendChild(vpSeg);

      var fsBtn = el("button", "meta-icon-btn", { title: "Fullscreen", type: "button" });
      fsBtn.insertAdjacentHTML("afterbegin", '<svg viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>');
      fsBtn.addEventListener("click", function () {
        if (viewer.requestFullscreen) viewer.requestFullscreen();
      });
      metaBar.appendChild(fsBtn);
    }

    var popout = el("a", "meta-popout", {
      href: "/view/" + encodeURIComponent(mockup.id),
      target: "_blank", rel: "noopener"
    });
    popout.appendChild(text("Pop out"));
    metaBar.appendChild(popout);
```

- [ ] **Step 3: Implement `setViewport` and reset on new selection**

Add the helper:

```javascript
  function setViewport(size, segEl) {
    segEl.querySelectorAll(".vp-opt").forEach(function (o) {
      o.classList.toggle("active", o.getAttribute("data-vp") === size);
    });
    viewer.classList.remove("vp-mobile", "vp-tablet");
    if (size === "mobile") viewer.classList.add("vp-mobile");
    else if (size === "tablet") viewer.classList.add("vp-tablet");
  }
```

In `renderViewer`, reset the viewport class each time a mockup is shown — add as the first line after `clearChildren(viewer);`:

```javascript
    viewer.classList.remove("vp-mobile", "vp-tablet");
```

- [ ] **Step 4: Commit**

```bash
git add app/templates/gallery.html
git commit -m "feat: viewport toggles, fullscreen, and meta-bar favorite star"
```

---

## Task 12: Auto-refresh state preservation + full manual verification

**Files:**
- Modify: `app/templates/gallery.html`

- [ ] **Step 1: Make the poll respect active sort/search/favorites**

In `pollForUpdates`, replace the URL build so it mirrors current state (so a search/filter/sort view does not get clobbered by a raw "newest" probe):

```javascript
    var url = "/api/mockups?limit=1&sort=" + encodeURIComponent(state.sort);
    if (state.activeProject === FAVORITES) url += "&favorites_only=true";
    else if (state.activeProject) url += "&project=" + encodeURIComponent(state.activeProject);
    if (state.filterText) url += "&q=" + encodeURIComponent(state.filterText);
```

Leave the rest of `pollForUpdates` (the "latest id changed → reload" logic) intact; it now reloads using the same state-aware query via `loadMockups(true)`.

- [ ] **Step 2: Start the app and verify end-to-end**

Run the app locally:

```bash
docker compose -f docker-compose.local.yml up --build
```

Open the gallery (per `docker-compose.local.yml` port mapping) and verify each path:

- [ ] Background reads as Graphite (not pure black); grid still faintly visible; Geist font in use.
- [ ] Sidebar shows `★ Favorites` at top (amber) with a count, then All, divider, then projects.
- [ ] Hovering a feed item reveals an outline ☆; clicking it fills to ★, the sidebar count increments, and the item gains the left-parked star.
- [ ] Clicking ★ again unfavorites; count decrements.
- [ ] Selecting `★ Favorites` shows only starred mockups; unfavoriting one there removes it from the list live.
- [ ] Typing in search filters across title/description/tags by hitting the server (verify a term that only appears in a description or tag matches).
- [ ] Sort toggle: Newest / Oldest reorder; ★ First floats favorites to the top.
- [ ] Open an HTML mockup: viewport toggles (375/768/Full) resize the iframe; fullscreen button works; meta-bar shows ★ when the mockup is favorited.
- [ ] Open an image mockup: viewport toggles and fullscreen-for-iframe are absent (image path unchanged).
- [ ] Leave a search/sort/favorites view active for >5s and confirm auto-refresh doesn't reset it.

- [ ] **Step 3: Run the full test suite once more**

Run: `pytest -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add app/templates/gallery.html
git commit -m "feat: auto-refresh preserves search/sort/favorites state"
```

---

## Task 13: Version bump + changelog

**Files:**
- Modify: `VERSION`, `pyproject.toml`, `server.json`, `CHANGELOG.md`

- [ ] **Step 1: Bump version strings to 1.3.0**

- `VERSION`: `1.3.0`
- `pyproject.toml`: `version = "1.3.0"`
- `server.json`: `"version": "1.3.0"` and the OCI identifier `ghcr.io/kgnatx/mockups-mpc:1.3.0`

- [ ] **Step 2: Add a CHANGELOG entry**

Add under the top of `CHANGELOG.md` (follow the existing format):

```markdown
## [1.3.0] - 2026-05-20

### Added
- Favorite (star) mockups; a Favorites filter in the sidebar.
- Server-side search across title, description, and tags.
- Sort options: newest, oldest, favorites-first.
- Viewer chrome: viewport size toggles (375 / 768 / full) and fullscreen for HTML mockups.

### Changed
- Refreshed visual direction: lifted "Graphite" background, Geist type, cyan accent retained.
- `favorite` field added to mockup API/MCP output.
```

- [ ] **Step 3: Commit**

```bash
git add VERSION pyproject.toml server.json CHANGELOG.md
git commit -m "chore: bump to 1.3.0 for favorites + UI uplift"
```

---

## Self-Review Notes

- **Spec coverage:** favorites column + migration (T1), set/count helpers (T2), search/sort/favorites in list (T3), API params + favorite + count endpoints (T4), models (T5), Graphite+Geist (T6), component CSS (T7), state/query (T8), sidebar favorites + sort (T9), star toggle (T10), viewer chrome (T11), auto-refresh + manual verify (T12), release (T13). Deferred: thumbnails (per spec).
- **Frontend testing:** vanilla JS has no harness; Task 12 enumerates explicit end-to-end checks rather than asserting "it works."
- **Type consistency:** `state.activeProject` sentinel `FAVORITES` used identically in T8/T9/T10/T12; `loadFavoritesCount`, `applyFavoriteUI`, `toggleFavorite`, `setViewport` defined once and referenced consistently; `favorite` returned as int from SQLite, coerced to bool by Pydantic (T5) and treated as truthy in JS.
- **Open spec questions resolved:** dedicated `/api/favorites/count` endpoint (chosen); 200ms search debounce; favorite field added to models.
