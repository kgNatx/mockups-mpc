import pytest
import aiosqlite
from datetime import datetime, timezone
from app import config
from app.db import init_db, insert_mockup, get_mockup, list_mockups, list_projects, update_mockup, delete_mockup, set_favorite, count_favorites

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
