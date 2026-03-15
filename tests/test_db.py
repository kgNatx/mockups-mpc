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
