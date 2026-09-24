import pytest

from app import db as dbm
from app import versioning
from app.db import get_alias, get_mockup, get_versions, init_db, list_aliases_for_version
from app.fold import FoldGroup, FoldMember, apply_fold, main, plan_folds


@pytest.fixture
async def db(tmp_data_dir):
    conn = await init_db()
    yield conn
    await conn.close()


async def _design(db, title, project="Proj", content="<p>x</p>", tags=None):
    ref = await versioning.create_design(
        db, project=project, title=title, description=None, content_type="html",
        content=content, tags=tags or [])
    return ref.mockup_id


async def _backdate(db, mockup_id, created_at):
    await versioning.set_version_created_at(db, mockup_id, 1, created_at)


# --- plan_folds: grouping ---

async def test_plan_folds_groups_by_project_and_base_title(db):
    a = await _design(db, "Screen 1", tags=["ui"])
    b = await _design(db, "Screen 2", tags=["nav"])
    c = await _design(db, "Screen 3", tags=["ui"])
    await _backdate(db, a, "2026-01-01T00:00:00+00:00")
    await _backdate(db, b, "2026-01-02T00:00:00+00:00")
    await _backdate(db, c, "2026-01-03T00:00:00+00:00")

    groups = await plan_folds(db)

    assert len(groups) == 1
    group = groups[0]
    assert group.project_slug == "proj"
    assert group.base_title == "Screen"
    assert [m.id for m in group.members] == [a, b, c]  # oldest first


async def test_designs_with_two_versions_are_never_grouped(db):
    versioned = await _design(db, "Screen 1")
    await versioning.add_version(db, versioned, title="Screen 2", description=None,
                                 content_type="html", content="<p>2</p>")
    await _design(db, "Screen 3")  # only 1 other candidate left -> group size 1

    groups = await plan_folds(db)

    assert groups == []


async def test_groups_never_cross_projects(db):
    await _design(db, "Screen 1", project="Alpha")
    await _design(db, "Screen 2", project="Beta")

    groups = await plan_folds(db)

    assert groups == []


async def test_option_b_option_c_never_group(db):
    await _design(db, "Hero — option B")
    await _design(db, "Hero — option C")

    groups = await plan_folds(db)

    assert groups == []


# --- apply_fold ---

async def test_apply_fold_merges_three_members(db, tmp_data_dir):
    a = await _design(db, "Screen 1", content="<p>1</p>", tags=["ui"])
    b = await _design(db, "Screen 2", content="<p>2</p>", tags=["nav"])
    c = await _design(db, "Screen 3", content="<p>3</p>", tags=["ui", "extra"])
    await _backdate(db, a, "2026-01-01T00:00:00+00:00")
    await _backdate(db, b, "2026-01-02T00:00:00+00:00")
    await _backdate(db, c, "2026-01-03T00:00:00+00:00")
    await dbm.set_favorite(db, b, True)

    b_v1 = (await get_versions(db, b))[0]
    b_bytes = (tmp_data_dir / b_v1["file_path"]).read_bytes()
    c_v1 = (await get_versions(db, c))[0]
    c_bytes = (tmp_data_dir / c_v1["file_path"]).read_bytes()

    [group] = await plan_folds(db)
    await apply_fold(db, group)

    survivor = await get_mockup(db, a)
    assert survivor is not None
    assert survivor["title"] == "Screen"
    assert survivor["version_count"] == 3
    assert sorted(survivor["tags"]) == ["extra", "nav", "ui"]
    assert survivor["favorite"] == 1

    versions = await get_versions(db, a)  # newest first
    assert [v["number"] for v in versions] == [3, 2, 1]

    assert await get_mockup(db, b) is None
    assert await get_mockup(db, c) is None

    alias_b = await get_alias(db, b)
    assert (alias_b["mockup_id"], alias_b["number"]) == (a, 2)
    alias_c = await get_alias(db, c)
    assert (alias_c["mockup_id"], alias_c["number"]) == (a, 3)
    assert await list_aliases_for_version(db, a, 2) == [b]
    assert await list_aliases_for_version(db, a, 3) == [c]

    # Files are never moved or copied: the same on-disk paths still hold the
    # same bytes, just owned by version rows on the survivor now.
    v2 = await dbm.get_version(db, a, 2)
    v3 = await dbm.get_version(db, a, 3)
    assert (tmp_data_dir / v2["file_path"]).read_bytes() == b_bytes
    assert (tmp_data_dir / v3["file_path"]).read_bytes() == c_bytes


async def test_apply_fold_source_version_need_not_be_number_one(db, tmp_data_dir):
    # A version_count==1 design whose surviving version isn't v1 (v1 was
    # deleted earlier) must still fold correctly: the regression this guards
    # against is silently dropping the design's only remaining content.
    a = await _design(db, "Screen 1", content="<p>1</p>")
    b = await _design(db, "Screen 2", content="<p>2-v1</p>")
    await versioning.add_version(db, b, title="Screen 2", description=None,
                                 content_type="html", content="<p>2-v2</p>")
    await versioning.delete_version(db, b, 1)  # b now has only v2, version_count == 1
    await _backdate(db, a, "2026-01-01T00:00:00+00:00")
    await versioning.set_version_created_at(db, b, 2, "2026-01-02T00:00:00+00:00")

    [group] = await plan_folds(db)
    await apply_fold(db, group)

    survivor_versions = await get_versions(db, a)
    assert [v["number"] for v in survivor_versions] == [2, 1]
    moved = await dbm.get_version(db, a, 2)
    assert (tmp_data_dir / moved["file_path"]).read_bytes() == b"<p>2-v2</p>"


async def test_apply_fold_failure_rolls_back_whole_group(db, tmp_data_dir, monkeypatch):
    # A failure partway through a 3-member group (after the first member's
    # move_version + insert_alias + delete_design_row already ran, and after
    # the second member's move_version ran too) must undo everything: fold is
    # one transaction per group, not one per member.
    a = await _design(db, "Screen 1", content="<p>1</p>", tags=["ui"])
    b = await _design(db, "Screen 2", content="<p>2</p>", tags=["nav"])
    c = await _design(db, "Screen 3", content="<p>3</p>", tags=["extra"])
    await _backdate(db, a, "2026-01-01T00:00:00+00:00")
    await _backdate(db, b, "2026-01-02T00:00:00+00:00")
    await _backdate(db, c, "2026-01-03T00:00:00+00:00")

    bytes_by_id = {}
    for mid in (a, b, c):
        v1 = (await get_versions(db, mid))[0]
        bytes_by_id[mid] = (tmp_data_dir / v1["file_path"]).read_bytes()

    real_insert_alias = dbm.insert_alias
    calls = {"n": 0}

    async def _flaky_insert_alias(conn, *, alias_id, mockup_id, number, source_number=None):
        calls["n"] += 1
        if calls["n"] == 2:  # b's alias already inserted; fail on c's, after c's move_version ran
            raise RuntimeError("simulated failure mid-group")
        await real_insert_alias(conn, alias_id=alias_id, mockup_id=mockup_id, number=number,
                                source_number=source_number)

    monkeypatch.setattr(dbm, "insert_alias", _flaky_insert_alias)

    [group] = await plan_folds(db)
    with pytest.raises(RuntimeError, match="simulated failure mid-group"):
        await apply_fold(db, group)

    for mid, title in ((a, "Screen 1"), (b, "Screen 2"), (c, "Screen 3")):
        design = await get_mockup(db, mid)
        assert design is not None, f"{mid} should not have been deleted"
        assert design["title"] == title  # survivor's own title untouched
        assert design["version_count"] == 1
        versions = await get_versions(db, mid)
        assert [v["number"] for v in versions] == [1]
        assert (tmp_data_dir / versions[0]["file_path"]).read_bytes() == bytes_by_id[mid]

    assert await get_alias(db, b) is None
    assert await get_alias(db, c) is None
    survivor = await get_mockup(db, a)
    assert survivor["tags"] == ["ui"]
    assert survivor["favorite"] == 0


async def test_apply_fold_moves_a_pre_existing_alias_with_its_member(db, tmp_data_dir):
    # x is restored-by-split shaped: version_count == 1, but its one surviving
    # version already has an alias pinned to it (e.g. from an earlier fold).
    # Folding x into another design must carry that alias along, not strand
    # or drop it.
    y = await _design(db, "Screen 1", content="<p>y1</p>")
    x = await _design(db, "Screen 2", content="<p>x1</p>")
    await versioning.add_version(db, x, title="Screen 2", description=None,
                                 content_type="html", content="<p>x2</p>")
    async with dbm.transaction(db):
        await dbm.insert_alias(db, alias_id="old-x", mockup_id=x, number=2)
    await versioning.delete_version(db, x, 1)  # x now has only v2, version_count == 1
    await _backdate(db, y, "2026-01-01T00:00:00+00:00")
    await versioning.set_version_created_at(db, x, 2, "2026-01-02T00:00:00+00:00")

    [group] = await plan_folds(db)
    await apply_fold(db, group)

    assert await versioning.resolve(db, "old-x") == (y, 2)


@pytest.mark.asyncio
async def test_apply_fold_moves_a_pre_existing_alias_view_via_http(client):
    resp_y = await client.post(
        "/api/upload",
        files={"file": ("y.html", b"<p>y1</p>", "text/html")},
        data={"project": "Proj", "title": "Screen 1", "fold": "false"},
    )
    y = resp_y.json()["id"]

    db = await init_db()
    x = await _design(db, "Screen 2", content="<p>x1</p>")
    await versioning.add_version(db, x, title="Screen 2", description=None,
                                 content_type="html", content="<p>x2</p>")
    async with dbm.transaction(db):
        await dbm.insert_alias(db, alias_id="old-x", mockup_id=x, number=2)
    await versioning.delete_version(db, x, 1)
    await _backdate(db, y, "2026-01-01T00:00:00+00:00")
    await versioning.set_version_created_at(db, x, 2, "2026-01-02T00:00:00+00:00")

    [group] = await plan_folds(db)
    await apply_fold(db, group)
    await db.close()

    resp = await client.get("/view/old-x")
    assert resp.status_code == 200
    assert resp.text == "<p>x2</p>"


# --- fold via HTTP: old ids read the byte-identical file afterward ---

@pytest.mark.asyncio
async def test_folded_member_view_serves_original_bytes(client):
    resp_a = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>first</p>", "text/html")},
        data={"project": "Proj", "title": "Screen 1", "fold": "false"},
    )
    a = resp_a.json()["id"]
    resp_b = await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>second</p>", "text/html")},
        data={"project": "Proj", "title": "Screen 2", "fold": "false"},
    )
    b = resp_b.json()["id"]

    db = await init_db()
    await _backdate(db, a, "2026-01-01T00:00:00+00:00")
    await _backdate(db, b, "2026-01-02T00:00:00+00:00")
    [group] = await plan_folds(db)
    await apply_fold(db, group)
    await db.close()

    resp = await client.get(f"/view/{b}")
    assert resp.status_code == 200
    assert resp.text == "<p>second</p>"


# --- CLI ---

def test_cli_requires_exactly_one_mode(tmp_data_dir):
    with pytest.raises(SystemExit):
        main([])
    with pytest.raises(SystemExit):
        main(["--dry-run", "--apply"])


def test_cli_dry_run_prints_groups_and_changes_nothing(tmp_data_dir, capsys):
    import asyncio

    async def _setup():
        conn = await init_db()
        a = await _design(conn, "Screen 1")
        b = await _design(conn, "Screen 2")
        await _backdate(conn, a, "2026-01-01T00:00:00+00:00")
        await _backdate(conn, b, "2026-01-02T00:00:00+00:00")
        await conn.close()
        return a, b

    a, b = asyncio.run(_setup())
    before = (tmp_data_dir / "proj").exists() and sorted(
        p.relative_to(tmp_data_dir) for p in (tmp_data_dir / "proj").rglob("*") if p.is_file())

    code = main(["--dry-run"])

    out = capsys.readouterr().out
    assert code == 0
    assert 'proj · "Screen" · 2 mockups' in out
    assert f"  2026-01-01T00:00  Screen 1  ({a})" in out
    assert f"  2026-01-02T00:00  Screen 2  ({b})" in out
    assert "1 groups, 2 mockups would become 1 designs" in out

    async def _check():
        conn = await init_db()
        design_a = await get_mockup(conn, a)
        design_b = await get_mockup(conn, b)
        await conn.close()
        return design_a, design_b

    design_a, design_b = asyncio.run(_check())
    assert design_a is not None and design_b is not None  # dry-run touched nothing
    after = sorted(p.relative_to(tmp_data_dir) for p in (tmp_data_dir / "proj").rglob("*")
                   if p.is_file())
    assert before == after


def test_cli_apply_folds_and_reports_total(tmp_data_dir, capsys):
    import asyncio

    async def _setup():
        conn = await init_db()
        a = await _design(conn, "Screen 1")
        b = await _design(conn, "Screen 2")
        await _backdate(conn, a, "2026-01-01T00:00:00+00:00")
        await _backdate(conn, b, "2026-01-02T00:00:00+00:00")
        await conn.close()
        return a, b

    a, b = asyncio.run(_setup())

    code = main(["--apply"])

    out = capsys.readouterr().out
    assert code == 0
    assert 'proj · "Screen" · 2 mockups' in out
    assert "folded 1 groups" in out

    async def _check():
        conn = await init_db()
        survivor = await get_mockup(conn, a)
        gone = await get_mockup(conn, b)
        await conn.close()
        return survivor, gone

    survivor, gone = asyncio.run(_check())
    assert survivor["version_count"] == 2
    assert gone is None


def test_cli_apply_reports_failed_group_and_exits_nonzero(tmp_data_dir, capsys, monkeypatch):
    import asyncio

    async def _setup():
        conn = await init_db()
        a = await _design(conn, "Screen 1")
        b = await _design(conn, "Screen 2")
        c = await _design(conn, "Other 1")
        d = await _design(conn, "Other 2")
        await _backdate(conn, a, "2026-01-01T00:00:00+00:00")
        await _backdate(conn, b, "2026-01-02T00:00:00+00:00")
        await _backdate(conn, c, "2026-01-01T00:00:00+00:00")
        await _backdate(conn, d, "2026-01-02T00:00:00+00:00")
        await conn.close()
        return a, b, c, d

    a, b, c, d = asyncio.run(_setup())

    import app.fold as fold_module
    real_apply = fold_module.apply_fold

    async def _flaky_apply(conn, group):
        if group.base_title == "Other":
            raise ValueError("boom")
        await real_apply(conn, group)

    monkeypatch.setattr(fold_module, "apply_fold", _flaky_apply)

    code = main(["--apply"])

    out = capsys.readouterr().out
    assert code == 1
    assert "FAILED Other: boom" in out
    assert "folded 1 groups" in out


def test_cli_data_dir_targets_a_different_directory(tmp_data_dir, tmp_path, capsys):
    import asyncio
    from app import config

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    real_data_dir, real_db_path = config.DATA_DIR, config.DB_PATH

    async def _setup():
        config.DATA_DIR = scratch
        config.DB_PATH = scratch / "mockups.db"
        conn = await init_db()
        a = await _design(conn, "Screen 1")
        b = await _design(conn, "Screen 2")
        await _backdate(conn, a, "2026-01-01T00:00:00+00:00")
        await _backdate(conn, b, "2026-01-02T00:00:00+00:00")
        await conn.close()

    asyncio.run(_setup())
    config.DATA_DIR, config.DB_PATH = real_data_dir, real_db_path  # tmp_data_dir's dir, empty

    code = main(["--dry-run", "--data-dir", str(scratch)])

    out = capsys.readouterr().out
    assert code == 0
    assert '"Screen" · 2 mockups' in out
    assert config.DATA_DIR == scratch
    assert config.DB_PATH == scratch / "mockups.db"


# --- a version link minted before a fold keeps working after it (I3 / R23) ---

@pytest.mark.asyncio
async def test_version_url_minted_before_fold_keeps_working(client):
    resp_a = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>a1</p>", "text/html")},
        data={"project": "Proj", "title": "Screen 1", "fold": "false"},
    )
    a = resp_a.json()["id"]
    resp_b = await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>b1</p>", "text/html")},
        data={"project": "Proj", "title": "Screen 2", "fold": "false"},
    )
    b = resp_b.json()["id"]
    resp_c = await client.post(
        "/api/upload",
        files={"file": ("c.html", b"<p>c1</p>", "text/html")},
        data={"project": "Proj", "title": "Screen 3", "fold": "false"},
    )
    c = resp_c.json()["id"]
    minted = resp_c.json()["version_url"]
    assert minted.endswith(f"/view/{c}/v/1")

    db = await init_db()
    await _backdate(db, a, "2026-01-01T00:00:00+00:00")
    await _backdate(db, b, "2026-01-02T00:00:00+00:00")
    await _backdate(db, c, "2026-01-03T00:00:00+00:00")
    [group] = await plan_folds(db)
    await apply_fold(db, group)
    alias = await get_alias(db, c)
    await db.close()
    assert (alias["mockup_id"], alias["number"], alias["source_number"]) == (a, 3, 1)

    resp = await client.get(f"/view/{c}/v/1")  # the link minted before the fold
    assert resp.status_code == 200
    assert resp.text == "<p>c1</p>"
    resp = await client.get(f"/view/{c}/v/3")  # the pinned number on the survivor
    assert resp.status_code == 200
    assert resp.text == "<p>c1</p>"
    assert (await client.get(f"/view/{c}/v/99")).status_code == 404
    assert (await client.get(f"/view/{c}/v/2")).status_code == 404


async def test_move_version_keeps_alias_source_number(db):
    a = await _design(db, "Screen 1")
    b = await _design(db, "Screen 2")
    c = await _design(db, "Screen 3")
    await _backdate(db, a, "2026-01-01T00:00:00+00:00")
    await _backdate(db, b, "2026-01-02T00:00:00+00:00")
    await _backdate(db, c, "2026-01-03T00:00:00+00:00")
    [group] = await plan_folds(db)
    await apply_fold(db, group)
    # Split v2 back out: b's alias becomes a design again; c's alias is untouched.
    await versioning.split_version(db, a, 2)
    assert await versioning.resolve(db, c, 1) == (a, 3)
    # Re-point c's version onto b: the alias follows and keeps its source number.
    async with dbm.transaction(db):
        await dbm.move_version(db, a, 3, to_mockup_id=b, to_number=2)
        await dbm.refresh_design_mirror(db, a)
        await dbm.refresh_design_mirror(db, b)
    alias = await get_alias(db, c)
    assert (alias["mockup_id"], alias["number"], alias["source_number"]) == (b, 2, 1)
    assert await versioning.resolve(db, c, 1) == (b, 2)
    assert await versioning.resolve(db, c, 2) == (b, 2)
    assert await versioning.resolve(db, c, 3) is None
