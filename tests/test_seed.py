import pytest

from app import versioning
from app.db import get_mockup, get_versions, init_db, list_design_titles
from app.seed import GUIDE_PATH, refresh_guide, seed_if_empty


@pytest.fixture
async def db(tmp_data_dir, monkeypatch):
    monkeypatch.delenv("SKIP_SEED", raising=False)
    conn = await init_db()
    yield conn
    await conn.close()


async def _guide_id(db):
    rows = [d for d in await list_design_titles(db, "mockups-mpc") if d["title"] == "Setup Guide"]
    return rows[0]["id"] if rows else None


async def test_fresh_seed_then_refresh_is_a_no_op(db):
    await seed_if_empty(db)
    await refresh_guide(db)
    gid = await _guide_id(db)
    assert [v["number"] for v in await get_versions(db, gid)] == [1]


async def test_refresh_adds_shipped_guide_as_new_version(db, tmp_data_dir):
    await seed_if_empty(db)
    gid = await _guide_id(db)
    v1 = (await get_versions(db, gid))[0]
    (tmp_data_dir / v1["file_path"]).write_text("<p>old guide from first boot</p>")

    await refresh_guide(db)
    versions = await get_versions(db, gid)
    assert [v["number"] for v in versions] == [2, 1]
    assert (tmp_data_dir / versions[0]["file_path"]).read_text() == \
        GUIDE_PATH.read_text(encoding="utf-8")
    design = await get_mockup(db, gid)
    assert design["title"] == "Setup Guide"  # the gallery's guide button finds it by title
    assert design["description"] == v1["description"]

    await refresh_guide(db)  # now identical: nothing more
    assert len(await get_versions(db, gid)) == 2


async def test_refresh_never_recreates_a_deleted_guide(db):
    await seed_if_empty(db)
    await versioning.delete_design(db, await _guide_id(db))
    await refresh_guide(db)
    assert await _guide_id(db) is None


async def test_refresh_skips_when_two_guides_exist(db, tmp_data_dir):
    await seed_if_empty(db)
    gid = await _guide_id(db)
    await versioning.create_design(
        db, project="Mockups MPC", title="Setup Guide", description=None,
        content_type="html", content="<p>copy</p>", tags=[])
    await refresh_guide(db)
    assert len(await get_versions(db, gid)) == 1


async def test_refresh_respects_skip_seed(db, tmp_data_dir, monkeypatch):
    await seed_if_empty(db)
    gid = await _guide_id(db)
    v1 = (await get_versions(db, gid))[0]
    (tmp_data_dir / v1["file_path"]).write_text("<p>old</p>")
    monkeypatch.setenv("SKIP_SEED", "1")
    await refresh_guide(db)
    assert len(await get_versions(db, gid)) == 1


async def test_refresh_failure_never_blocks_startup(db, tmp_data_dir, monkeypatch):
    await seed_if_empty(db)
    gid = await _guide_id(db)
    v1 = (await get_versions(db, gid))[0]
    (tmp_data_dir / v1["file_path"]).write_text("<p>old</p>")

    async def disk_full(*args, **kwargs):
        raise OSError("No space left on device")
    monkeypatch.setattr(versioning, "add_version", disk_full)
    await refresh_guide(db)  # logs, does not raise
    assert len(await get_versions(db, gid)) == 1


async def test_refresh_keeps_a_user_version_on_top(db, tmp_data_dir):
    await seed_if_empty(db)
    gid = await _guide_id(db)
    await versioning.add_version(db, gid, title="Setup Guide", description=None,
                                 content_type="png", content="iVBORw0KGgo=")  # binary, no marker
    await refresh_guide(db)
    assert [v["number"] for v in await get_versions(db, gid)] == [2, 1]


async def test_refresh_replaces_an_older_shipped_guide(db, tmp_data_dir):
    await seed_if_empty(db)
    gid = await _guide_id(db)
    await versioning.add_version(
        db, gid, title="Setup Guide", description=None, content_type="html",
        content='<html><head><meta name="mockups-mpc-guide" content="shipped"></head>old</html>')
    await refresh_guide(db)
    versions = await get_versions(db, gid)
    assert [v["number"] for v in versions] == [3, 2, 1]
    assert (tmp_data_dir / versions[0]["file_path"]).read_bytes() == GUIDE_PATH.read_bytes()
