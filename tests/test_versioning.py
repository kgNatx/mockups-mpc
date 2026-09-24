import base64
import re

import pytest

from app import db as dbm
from app import versioning
from app.db import get_mockup, get_version, get_versions, init_db, insert_alias, list_mockups, \
    list_projects, update_mockup
from app.versioning import VersionRef, base_title, comparison_key

PNG_B64 = base64.b64encode(b"\x89PNG-fake").decode()


@pytest.mark.parametrize("title,base", [
    ("Privacy page — draft 3b (rail fixed)", "Privacy page"),
    ("Privacy page — draft 8", "Privacy page"),
    ("Entangram hero v7", "Entangram hero"),
    ("Strata landing — r5", "Strata landing"),
    ("Hero — option B", "Hero — option B"),
    ("Hero — option C", "Hero — option C"),
    ("Layout A", "Layout A"),
    ("Scan signature chart (v2)", "Scan signature chart"),
])
def test_base_title_table(title, base):
    assert base_title(title) == base


_IDEMPOTENCE_TITLES = [
    "Privacy page — draft 3b (rail fixed)", "Privacy page — draft 8", "Entangram hero v7",
    "Strata landing — r5", "Hero — option B", "Hero — option C", "Layout A",
    "Scan signature chart (v2)", "Foo (a) (b)", "Foo (a) v2 (b)", "Hero (mobile) (v2)",
]


@pytest.mark.parametrize("title", _IDEMPOTENCE_TITLES)
def test_base_title_is_idempotent(title):
    # Regression (M3): a design titled base_title(v1) must share v1's comparison key.
    assert base_title(base_title(title)) == base_title(title)


def test_base_title_strips_every_trailing_parenthetical():
    assert base_title("Foo (a) (b)") == "Foo"
    assert base_title("Foo (a) v2 (b)") == "Foo"
    assert base_title("Hero (mobile) (v2)") == "Hero"
    assert base_title("(a) (b)") == "(a)"
    assert base_title("(a)") == "(a)"  # never strip to empty


def test_base_title_edge_cases():
    assert comparison_key("Hero — option B") != comparison_key("Hero — option C")
    assert comparison_key("Privacy page — draft 1") == comparison_key("privacy  page – Draft 8")
    assert base_title("Layout 2") == "Layout"
    assert base_title("Layout alt 2") == "Layout alt 2"
    assert base_title("v2") == "v2"  # never strip to empty


# --- versioning core ---

@pytest.fixture
async def db(tmp_data_dir):
    conn = await init_db()
    yield conn
    await conn.close()


async def _design(db, title="Privacy page — draft 1", project="Proj", content="<p>v1</p>"):
    ref = await versioning.create_design(
        db, project=project, title=title, description="first", content_type="html",
        content=content, tags=["ui"])
    return ref.mockup_id


async def _add(db, mid, title, content="<p>x</p>", content_type="html"):
    return await versioning.add_version(
        db, mid, title=title, description=f"desc {title}", content_type=content_type,
        content=content)


async def test_create_design_makes_v1(db, tmp_data_dir):
    ref = await versioning.create_design(
        db, project="Proj", title="Hero v1", description=None, content_type="html",
        content="<p>1</p>", tags=["a"])
    assert ref == VersionRef(mockup_id=ref.mockup_id, number=1, folded=False)
    design = await get_mockup(db, ref.mockup_id)
    assert design["title"] == "Hero v1"  # single version keeps its full title
    assert design["file_path"] == f"proj/{ref.mockup_id}.html"  # v1 keeps today's layout
    assert design["version_count"] == 1 and design["latest_at"] == design["created_at"]
    assert [v["number"] for v in await get_versions(db, ref.mockup_id)] == [1]


async def test_add_version_mirrors_and_renames(db, tmp_data_dir):
    mid = await _design(db)
    v1 = await get_version(db, mid, 1)
    v1_bytes = (tmp_data_dir / v1["file_path"]).read_bytes()

    ref = await _add(db, mid, "Privacy page — draft 2", content="<p>v2</p>")
    assert ref == VersionRef(mockup_id=mid, number=2, folded=False)
    design = await get_mockup(db, mid)
    v2 = await get_version(db, mid, 2)
    assert v2["file_path"] == f"proj/{mid}/v2.html"
    assert (tmp_data_dir / v2["file_path"]).read_text() == "<p>v2</p>"
    assert design["version_count"] == 2
    assert design["latest_at"] == v2["created_at"]
    assert (design["file_path"], design["description"], design["content_type"]) == \
        (v2["file_path"], v2["description"], "html")
    assert design["title"] == "Privacy page"  # base_title(v1.title) on the 2nd version
    assert (tmp_data_dir / v1["file_path"]).read_bytes() == v1_bytes


async def test_third_version_keeps_manual_title(db):
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2")
    await update_mockup(db, mid, title="Privacy (renamed)")
    await _add(db, mid, "Privacy page — draft 3")
    assert (await get_mockup(db, mid))["title"] == "Privacy (renamed)"


async def test_add_version_db_failure_leaves_no_file(db, tmp_data_dir, monkeypatch):
    mid = await _design(db)

    async def boom(*args, **kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(dbm, "insert_version", boom)
    with pytest.raises(RuntimeError):
        await _add(db, mid, "Privacy page — draft 2")
    assert not (tmp_data_dir / "proj" / mid / "v2.html").exists()
    design = await get_mockup(db, mid)
    assert design["version_count"] == 1 and design["title"] == "Privacy page — draft 1"


async def test_add_version_unknown_design(db):
    with pytest.raises(ValueError):
        await _add(db, "nope", "x")


async def test_find_fold_target(db):
    a = await _design(db, title="Privacy page — draft 1")
    assert await versioning.find_fold_target(
        db, project_slug="proj", title="privacy  page – Draft 8") == a
    assert await versioning.find_fold_target(
        db, project_slug="other", title="Privacy page — draft 8") is None
    await _design(db, title="Privacy page (old)")
    assert await versioning.find_fold_target(
        db, project_slug="proj", title="Privacy page — draft 8") is None
    await _design(db, title="Hero — option B")
    assert await versioning.find_fold_target(
        db, project_slug="proj", title="Hero — option C") is None


async def test_resolve(db):
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2")
    async with dbm.transaction(db):
        await insert_alias(db, alias_id="old", mockup_id=mid, number=1)
    assert await versioning.resolve(db, mid) == (mid, 2)
    assert await versioning.resolve(db, mid, 1) == (mid, 1)
    assert await versioning.resolve(db, mid, 9) is None
    assert await versioning.resolve(db, "old") == (mid, 1)
    assert await versioning.resolve(db, "old", 1) == (mid, 1)  # matches the pinned version
    assert await versioning.resolve(db, "old", 2) is None  # mismatched number: not found
    assert await versioning.resolve(db, "nope") is None


async def test_delete_top_version_rf1(db, tmp_data_dir):
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2")
    await _add(db, mid, "Privacy page — draft 3")
    v2 = await get_version(db, mid, 2)
    v3 = await get_version(db, mid, 3)
    title = (await get_mockup(db, mid))["title"]

    await versioning.delete_version(db, mid, 3)
    design = await get_mockup(db, mid)
    assert (design["file_path"], design["description"], design["latest_at"]) == \
        (v2["file_path"], v2["description"], v2["created_at"])
    assert design["version_count"] == 2 and design["title"] == title
    assert not (tmp_data_dir / v3["file_path"]).exists()
    # Numbers are never reused, even for the deleted top version.
    assert (await _add(db, mid, "Privacy page — draft 4")).number == 4


async def test_delete_only_version_refuses(db):
    mid = await _design(db)
    with pytest.raises(ValueError, match=re.escape(
            "Cannot delete the only version; use delete_mockup without version "
            "to delete the mockup.")):
        await versioning.delete_version(db, mid, 1)


async def test_delete_version_drops_its_aliases(db):
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2")
    async with dbm.transaction(db):
        await insert_alias(db, alias_id="old", mockup_id=mid, number=1)
    await versioning.delete_version(db, mid, 1)
    assert await dbm.get_alias(db, "old") is None
    assert await versioning.resolve(db, "old") is None


async def test_mixed_content_types_rf2(db, tmp_data_dir):
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2", content=PNG_B64, content_type="png")
    v1 = await get_version(db, mid, 1)
    v2 = await get_version(db, mid, 2)
    assert v1["content_type"] == "html" and v1["file_path"].endswith(".html")
    assert v2["file_path"] == f"proj/{mid}/v2.png"
    assert (tmp_data_dir / v1["file_path"]).exists() and (tmp_data_dir / v2["file_path"]).exists()
    assert (await get_mockup(db, mid))["content_type"] == "png"


async def test_split_aliased_version_rf3(db, tmp_data_dir):
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2")
    await _add(db, mid, "Privacy page — draft 3")
    async with dbm.transaction(db):
        await insert_alias(db, alias_id="old", mockup_id=mid, number=2)
    v2 = await get_version(db, mid, 2)

    new_id = await versioning.split_version(db, mid, 2)
    assert new_id == "old"
    assert await dbm.get_alias(db, "old") is None
    assert await versioning.resolve(db, "old") == ("old", 1)
    split = await get_mockup(db, "old")
    moved = await get_version(db, "old", 1)
    assert (moved["file_path"], moved["created_at"], moved["title"], moved["description"]) == \
        (v2["file_path"], v2["created_at"], v2["title"], v2["description"])
    assert split["title"] == "Privacy page — draft 2"
    assert split["project_slug"] == "proj" and split["tags"] == ["ui"] and split["favorite"] == 0
    assert split["version_count"] == 1 and split["latest_at"] == v2["created_at"]
    assert split["created_at"] == v2["created_at"]

    assert [v["number"] for v in await get_versions(db, mid)] == [3, 1]  # no renumbering
    source = await get_mockup(db, mid)
    assert source["version_count"] == 2
    assert source["file_path"] == (await get_version(db, mid, 3))["file_path"]


async def test_split_top_version_does_not_reuse_number_or_path(db, tmp_data_dir):
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2")
    await _add(db, mid, "Privacy page — draft 3", content="<p>three</p>")
    new_id = await versioning.split_version(db, mid, 3)
    assert new_id not in (mid, "old")
    moved = await get_version(db, new_id, 1)

    ref = await _add(db, mid, "Privacy page — draft 4", content="<p>four</p>")
    assert ref.number == 4
    assert (tmp_data_dir / moved["file_path"]).read_text() == "<p>three</p>"
    # The split design's own numbering starts after its v1.
    assert (await _add(db, new_id, "Privacy page — draft 3 again")).number == 2


async def test_split_reuses_lowest_alias_and_repoints_rest(db):
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2")
    async with dbm.transaction(db):
        await insert_alias(db, alias_id="b-old", mockup_id=mid, number=2)
        await insert_alias(db, alias_id="a-old", mockup_id=mid, number=2)
    new_id = await versioning.split_version(db, mid, 2)
    assert new_id == "a-old"
    assert await versioning.resolve(db, "b-old") == ("a-old", 1)


async def test_split_only_version_refuses(db):
    mid = await _design(db)
    with pytest.raises(ValueError):
        await versioning.split_version(db, mid, 1)


async def test_delete_design_removes_files_and_rows(db, tmp_data_dir):
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2")
    await _add(db, mid, "Privacy page — draft 3", content=PNG_B64, content_type="png")
    async with dbm.transaction(db):
        await insert_alias(db, alias_id="old", mockup_id=mid, number=2)
    paths = [v["file_path"] for v in await get_versions(db, mid)]

    await versioning.delete_design(db, mid)
    assert await get_mockup(db, mid) is None
    for p in paths:
        assert not (tmp_data_dir / p).exists()
    assert not (tmp_data_dir / "proj" / mid).exists()
    # Cascade (proves foreign_keys=ON).
    cursor = await db.execute("SELECT COUNT(*) AS n FROM mockup_versions WHERE mockup_id = ?", (mid,))
    assert (await cursor.fetchone())["n"] == 0
    assert await dbm.get_alias(db, "old") is None


async def test_list_sorts_by_latest_activity_and_searches_versions(db):
    old = await _design(db, title="Old design — draft 1")
    await update_mockup(db, old, created_at="2020-01-01T00:00:00+00:00")
    async with dbm.transaction(db):
        await db.execute("UPDATE mockups SET latest_at = created_at WHERE id = ?", (old,))
        await db.execute("UPDATE mockup_versions SET created_at = '2020-01-01T00:00:00+00:00' "
                         "WHERE mockup_id = ?", (old,))
    mid = await _design(db, title="Middle", project="Other")
    assert [r["id"] for r in await list_mockups(db)] == [mid, old]
    assert (await list_projects(db))[0]["project_slug"] == "other"

    await _add(db, old, "Old design — draft 3b (rail fixed)")
    rows = await list_mockups(db, sort="newest")
    assert [r["id"] for r in rows] == [old, mid]
    assert rows[0]["version_count"] == 2 and rows[0]["latest_at"]
    assert (await list_projects(db))[0]["project_slug"] == "proj"

    await _add(db, old, "Something else")
    assert [r["id"] for r in await list_mockups(db, q="draft 3b")] == [old]


async def test_split_restored_alias_never_overwrites_files(db, tmp_data_dir):
    # X keeps only v2 (p/X/v2.html), is folded into Y, then split back out as X
    # with that file as its v1. X's next version must not land on p/X/v2.html.
    x = await _design(db, title="X", content="<p>x1</p>")
    await _add(db, x, "X 2", content="<p>x2-original</p>")
    await versioning.delete_version(db, x, 1)
    y = await _design(db, title="Y", content="<p>y1</p>")
    async with dbm.transaction(db):  # simulate a chunk-3 fold of X into Y
        n = await dbm.next_version_number(db, y)
        await dbm.move_version(db, x, 2, to_mockup_id=y, to_number=n)
        await db.execute("DELETE FROM mockups WHERE id = ?", (x,))
        await dbm.insert_alias(db, alias_id=x, mockup_id=y, number=n)
        await dbm.refresh_design_mirror(db, y)
    assert await versioning.split_version(db, y, n) == x
    v1 = await get_version(db, x, 1)
    assert v1["file_path"] == f"proj/{x}/v2.html"

    ref = await _add(db, x, "X again", content="<p>NEW</p>")
    new = await get_version(db, x, ref.number)
    assert new["file_path"] != v1["file_path"]
    assert (tmp_data_dir / new["file_path"]).read_text() == "<p>NEW</p>"
    assert (tmp_data_dir / v1["file_path"]).read_text() == "<p>x2-original</p>"

    await versioning.delete_version(db, x, ref.number)
    assert (tmp_data_dir / v1["file_path"]).read_text() == "<p>x2-original</p>"


async def test_manual_title_survives_drop_back_to_one_version(db):
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2")
    await update_mockup(db, mid, title="My manual name")
    await versioning.delete_version(db, mid, 1)
    await _add(db, mid, "Privacy page — draft 3")
    assert (await get_mockup(db, mid))["title"] == "My manual name"


async def test_split_design_rederives_title_on_first_v2(db):
    mid = await _design(db)
    await _add(db, mid, "Hero — draft 2")
    new_id = await versioning.split_version(db, mid, 2)
    assert (await get_mockup(db, new_id))["title"] == "Hero — draft 2"
    await _add(db, new_id, "Hero — draft 5")
    assert (await get_mockup(db, new_id))["title"] == "Hero"


async def test_split_v1_moves_design_created_at_to_new_first_version(db):
    # Regression (M1): created_at is the first remaining version's time.
    mid = await _design(db)
    await versioning.set_version_created_at(db, mid, 1, "2026-01-01T00:00:00+00:00")
    await _add(db, mid, "Privacy page — draft 2")
    await _add(db, mid, "Privacy page — draft 3")
    v2 = await get_version(db, mid, 2)

    new_id = await versioning.split_version(db, mid, 1)
    assert (await get_mockup(db, mid))["created_at"] == v2["created_at"]
    assert (await get_mockup(db, new_id))["created_at"] == "2026-01-01T00:00:00+00:00"


async def test_delete_v1_moves_design_created_at_to_new_first_version(db):
    mid = await _design(db)
    await versioning.set_version_created_at(db, mid, 1, "2026-01-01T00:00:00+00:00")
    await _add(db, mid, "Privacy page — draft 2")
    v2 = await get_version(db, mid, 2)

    await versioning.delete_version(db, mid, 1)
    assert (await get_mockup(db, mid))["created_at"] == v2["created_at"]


# --- write-path hardening (s007 deferred minors) ---

async def test_transaction_commit_failure_rolls_back(db, monkeypatch):
    real_commit = db.commit

    async def boom():
        raise RuntimeError("commit failed")
    monkeypatch.setattr(db, "commit", boom)
    with pytest.raises(RuntimeError):
        async with dbm.transaction(db):
            await db.execute("UPDATE mockups SET title = 'x'")
    assert not db.in_transaction  # rolled back, not left open
    monkeypatch.setattr(db, "commit", real_commit)
    async with dbm.transaction(db):  # the lock was released
        pass


async def test_add_version_commit_failure_leaves_no_file(db, tmp_data_dir, monkeypatch):
    mid = await _design(db)

    async def boom():
        raise RuntimeError("commit failed")
    monkeypatch.setattr(db, "commit", boom)
    with pytest.raises(RuntimeError):
        await _add(db, mid, "Privacy page — draft 2")
    assert not (tmp_data_dir / "proj" / mid / "v2.html").exists()


async def test_add_version_unknown_design_is_not_found(db):
    with pytest.raises(versioning.NotFound):
        await _add(db, "nope", "x")


async def test_next_version_number_unknown_design_raises(db):
    with pytest.raises(ValueError, match="Mockup not found"):
        async with dbm.transaction(db):
            await dbm.next_version_number(db, "nope")


async def test_only_version_refusals_are_conflicts(db):
    mid = await _design(db)
    with pytest.raises(versioning.Conflict):
        await versioning.split_version(db, mid, 1)
    with pytest.raises(versioning.Conflict):
        await versioning.delete_version(db, mid, 1)


async def test_delete_design_racing_add_version_leaves_no_files(db, tmp_data_dir):
    import asyncio
    mid = await _design(db)
    await _add(db, mid, "Privacy page — draft 2")
    results = await asyncio.gather(
        versioning.delete_design(db, mid),
        _add(db, mid, "Privacy page — draft 3"),
        return_exceptions=True)
    assert await get_mockup(db, mid) is None
    assert not (tmp_data_dir / "proj" / mid).exists()
    assert not (tmp_data_dir / "proj" / f"{mid}.html").exists()
    assert results[0] is None
    assert results[1] is None or isinstance(results[1], versioning.NotFound)
