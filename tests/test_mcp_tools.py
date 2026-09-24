import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app import versioning
from app.db import init_db
from app.mcp_server import (
    _send_mockup, _list_mockups, _get_mockup,
    _update_mockup, _delete_mockup, _tag_mockup, _set_created_at,
    _split_version, mcp,
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
    # fold=False: "Mock 0"/"Mock 1"/"Mock 2" share a base title (a trailing bare
    # number strips), so auto-fold would otherwise merge them into one design.
    for i in range(3):
        await _send_mockup(
            db=db, project="P", title=f"Mock {i}",
            description=None, content=f"<p>{i}</p>",
            content_type="html", tags=[], fold=False
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
    v1_path = tmp_data_dir / sent["file_path"]
    result = await _update_mockup(
        db=db, id=sent["id"], title=None,
        description=None, tags=None,
        content="<p>v2</p>", content_type="html"
    )
    # Behaviour change (spec §6.2): content update creates v2; v1 is kept, not overwritten.
    assert result["version"] == 2
    file_content = (tmp_data_dir / result["file_path"]).read_text()
    assert file_content == "<p>v2</p>"
    assert v1_path.exists()

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

@pytest.mark.asyncio
async def test_set_created_at(db):
    sent = await _send_mockup(
        db=db, project="P", title="T",
        description=None, content="<p>x</p>",
        content_type="html", tags=[]
    )
    new_date = "2025-01-15T12:00:00+00:00"
    result = await _set_created_at(db=db, id=sent["id"], created_at=new_date)
    assert result["created_at"] == new_date

@pytest.mark.asyncio
async def test_set_created_at_invalid(db):
    sent = await _send_mockup(
        db=db, project="P", title="T",
        description=None, content="<p>x</p>",
        content_type="html", tags=[]
    )
    with pytest.raises(ValueError, match="Invalid ISO"):
        await _set_created_at(db=db, id=sent["id"], created_at="not-a-date")


@pytest.mark.asyncio
async def test_update_mockup_metadata_preserves_description(db):
    # Regression: a metadata-only update that omits description must NOT null it.
    sent = await _send_mockup(
        db=db, project="P", title="Old",
        description="keep me", content="<p>v1</p>",
        content_type="html", tags=[]
    )
    result = await _update_mockup(db=db, id=sent["id"], title="New", tags=["v2"])
    assert result["title"] == "New"
    assert result["description"] == "keep me"


@pytest.mark.asyncio
async def test_update_mockup_content_type_change_keeps_old_version_file(db, tmp_data_dir):
    import base64
    sent = await _send_mockup(
        db=db, project="P", title="T",
        description=None, content="<p>v1</p>",
        content_type="html", tags=[]
    )
    old_path = tmp_data_dir / sent["file_path"]
    assert old_path.exists() and old_path.suffix == ".html"

    png = base64.b64encode(b"\x89PNG fake").decode()
    result = await _update_mockup(
        db=db, id=sent["id"], content=png, content_type="png"
    )
    assert result["content_type"] == "png"
    assert result["file_path"].endswith(".png")
    assert (tmp_data_dir / result["file_path"]).exists()
    # Behaviour change (spec §6.2): a content update adds a version, so v1's
    # file (the old content type) is kept, not deleted.
    assert old_path.exists()


@pytest.mark.asyncio
async def test_update_mockup_content_type_without_content_raises(db):
    sent = await _send_mockup(
        db=db, project="P", title="T",
        description=None, content="<p>x</p>",
        content_type="html", tags=[]
    )
    with pytest.raises(ValueError, match="content_type can only be changed"):
        await _update_mockup(db=db, id=sent["id"], content_type="png")


@pytest.mark.asyncio
async def test_set_created_at_reorders_listing(db):
    a = await _send_mockup(db=db, project="P", title="A", description=None,
                           content="<p>a</p>", content_type="html", tags=[])
    await _send_mockup(db=db, project="P", title="B", description=None,
                       content="<p>b</p>", content_type="html", tags=[])
    # Backdate A to the distant past; newest-sorted listing must place it last.
    await _set_created_at(db=db, id=a["id"], created_at="2020-01-01T00:00:00+00:00")
    rows = await _list_mockups(db=db, project=None, limit=50, offset=0)
    assert rows[-1]["id"] == a["id"]


@pytest.mark.asyncio
async def test_send_mockup_rolls_back_file_on_insert_failure(db, tmp_data_dir, monkeypatch):
    import app.db as dbm

    async def boom(*args, **kwargs):
        raise RuntimeError("insert failed")

    # _send_mockup now writes through versioning.create_design, which calls
    # db.insert_mockup — the write-then-insert step this test targets moved there.
    monkeypatch.setattr(dbm, "insert_mockup", boom)
    with pytest.raises(RuntimeError):
        await _send_mockup(db=db, project="P", title="T", description=None,
                           content="<p>x</p>", content_type="html", tags=[])
    # The written file must not be orphaned on disk.
    proj_dir = tmp_data_dir / "p"
    leftover = list(proj_dir.glob("*")) if proj_dir.exists() else []
    assert leftover == []


# --- send_mockup: parent / fold (chunk 2) ---

@pytest.mark.asyncio
async def test_send_mockup_with_parent_adds_version(db):
    a = await _send_mockup(db=db, project="P", title="Hero", description=None,
                           content="<p>1</p>", content_type="html", tags=[])
    result = await _send_mockup(db=db, project="P", title="Hero v2", description=None,
                                content="<p>2</p>", content_type="html", tags=[],
                                parent=a["id"])
    assert result["id"] == a["id"]
    assert result["version"] == 2
    assert result["folded"] is False
    assert "note" not in result
    assert result["version_url"].endswith(f"/view/{a['id']}/v/2")


@pytest.mark.asyncio
async def test_send_mockup_with_alias_parent_adds_version(db):
    from app import db as dbm

    a = await _send_mockup(db=db, project="P", title="Hero", description=None,
                           content="<p>1</p>", content_type="html", tags=[])
    async with dbm.transaction(db):
        await dbm.insert_alias(db, alias_id="old-link", mockup_id=a["id"], number=1)
    result = await _send_mockup(db=db, project="P", title="Hero v2", description=None,
                                content="<p>2</p>", content_type="html", tags=[],
                                parent="old-link")
    assert result["id"] == a["id"]
    assert result["version"] == 2


@pytest.mark.asyncio
async def test_send_mockup_unknown_parent_raises(db):
    with pytest.raises(versioning.UnknownParent, match="Unknown parent: nope"):
        await _send_mockup(db=db, project="P", title="T", description=None,
                           content="<p>x</p>", content_type="html", tags=[],
                           parent="nope")


@pytest.mark.asyncio
async def test_send_mockup_parent_other_project_raises(db):
    a = await _send_mockup(db=db, project="ProjA", title="Hero", description=None,
                           content="<p>1</p>", content_type="html", tags=[])
    with pytest.raises(ValueError):
        await _send_mockup(db=db, project="ProjB", title="Hero v2", description=None,
                           content="<p>2</p>", content_type="html", tags=[],
                           parent=a["id"])


@pytest.mark.asyncio
async def test_send_mockup_auto_folds_on_single_match(db):
    a = await _send_mockup(db=db, project="P", title="Privacy page — draft 1",
                           description=None, content="<p>1</p>", content_type="html", tags=[])
    result = await _send_mockup(db=db, project="P", title="Privacy page — draft 2",
                                description=None, content="<p>2</p>", content_type="html",
                                tags=[])
    assert result["id"] == a["id"]
    assert result["version"] == 2
    assert result["folded"] is True
    assert result["note"] == (
        "Added as version 2 of 'Privacy page'. "
        "Resend with fold=false if this was meant to be a separate mockup."
    )


@pytest.mark.asyncio
async def test_send_mockup_no_fold_on_two_matches(db):
    await _send_mockup(db=db, project="P", title="Privacy page — draft 1", description=None,
                       content="<p>a</p>", content_type="html", tags=[])
    # A second design with the same comparison key, created deliberately (fold=False).
    await _send_mockup(db=db, project="P", title="Privacy page — draft 2", description=None,
                       content="<p>b</p>", content_type="html", tags=[], fold=False)
    result = await _send_mockup(db=db, project="P", title="Privacy page — draft 3",
                                description=None, content="<p>c</p>", content_type="html",
                                tags=[])
    assert result["version"] == 1
    assert result["folded"] is False


@pytest.mark.asyncio
async def test_send_mockup_fold_false_never_folds(db):
    a = await _send_mockup(db=db, project="P", title="Privacy page — draft 1", description=None,
                           content="<p>1</p>", content_type="html", tags=[])
    result = await _send_mockup(db=db, project="P", title="Privacy page — draft 2",
                                description=None, content="<p>2</p>", content_type="html",
                                tags=[], fold=False)
    assert result["id"] != a["id"]
    assert result["version"] == 1
    assert result["folded"] is False


@pytest.mark.asyncio
async def test_send_mockup_option_b_does_not_fold_into_option_a(db):
    a = await _send_mockup(db=db, project="P", title="Hero — option A", description=None,
                           content="<p>a</p>", content_type="html", tags=[])
    result = await _send_mockup(db=db, project="P", title="Hero — option B", description=None,
                                content="<p>b</p>", content_type="html", tags=[])
    assert result["id"] != a["id"]
    assert result["version"] == 1


@pytest.mark.asyncio
async def test_send_mockup_tags_union_into_design(db):
    a = await _send_mockup(db=db, project="P", title="Hero", description=None,
                           content="<p>1</p>", content_type="html", tags=["ui"])
    result = await _send_mockup(db=db, project="P", title="Hero v2", description=None,
                                content="<p>2</p>", content_type="html", tags=["landing"],
                                parent=a["id"])
    assert sorted(result["tags"]) == ["landing", "ui"]


# --- get_mockup: versions list, version param (chunk 2) ---

@pytest.mark.asyncio
async def test_get_mockup_lists_versions_newest_first(db):
    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    await _update_mockup(db=db, id=sent["id"], content="<p>2</p>", content_type="html")
    result = await _get_mockup(db=db, id=sent["id"])
    assert [v["number"] for v in result["versions"]] == [2, 1]
    assert result["view_url"].endswith(f"/view/{sent['id']}")
    assert result["version"] == 2


@pytest.mark.asyncio
async def test_get_mockup_specific_version_view_url(db):
    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    await _update_mockup(db=db, id=sent["id"], content="<p>2</p>", content_type="html")
    result = await _get_mockup(db=db, id=sent["id"], version=1)
    assert result["view_url"].endswith("/v/1")
    assert result["version"] == 1


@pytest.mark.asyncio
async def test_get_mockup_alias_shows_pinned_version(db):
    from app import db as dbm

    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    await _update_mockup(db=db, id=sent["id"], content="<p>2</p>", content_type="html")
    async with dbm.transaction(db):
        await dbm.insert_alias(db, alias_id="old-link", mockup_id=sent["id"], number=1)
    result = await _get_mockup(db=db, id="old-link")
    assert result["id"] == sent["id"]
    assert result["version"] == 1
    assert result["view_url"].endswith("/v/1")


@pytest.mark.asyncio
async def test_get_mockup_alias_with_mismatched_version_raises(db):
    # fix round 1, Entry 3 item 1: an alias pinned to v1 must not resolve for
    # a different explicit version.
    from app import db as dbm

    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    await _update_mockup(db=db, id=sent["id"], content="<p>2</p>", content_type="html")
    async with dbm.transaction(db):
        await dbm.insert_alias(db, alias_id="old-link", mockup_id=sent["id"], number=1)
    with pytest.raises(ValueError, match="not found"):
        await _get_mockup(db=db, id="old-link", version=2)


@pytest.mark.asyncio
async def test_update_mockup_content_via_alias(db):
    # fix round 1, Entry 3 item 2: _update_mockup accepts an alias id.
    from app import db as dbm

    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    async with dbm.transaction(db):
        await dbm.insert_alias(db, alias_id="old-link", mockup_id=sent["id"], number=1)
    result = await _update_mockup(db=db, id="old-link", content="<p>2</p>", content_type="html")
    assert result["id"] == sent["id"]
    assert result["version"] == 2
    assert [v["number"] for v in result["versions"]] == [2, 1]


@pytest.mark.asyncio
async def test_tag_mockup_via_alias(db):
    # fix round 1, Entry 3 item 2: _tag_mockup accepts an alias id.
    from app import db as dbm

    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=["ui"])
    async with dbm.transaction(db):
        await dbm.insert_alias(db, alias_id="old-link", mockup_id=sent["id"], number=1)
    result = await _tag_mockup(db=db, id="old-link", add=["landing"], remove=["ui"])
    assert result["id"] == sent["id"]
    assert result["tags"] == ["landing"]


# --- split_version (chunk 2, new tool) ---

@pytest.mark.asyncio
async def test_split_version_returns_new_design(db):
    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    await _update_mockup(db=db, id=sent["id"], content="<p>2</p>", content_type="html")
    result = await _split_version(db=db, id=sent["id"], version=2)
    assert result["id"] != sent["id"]
    assert result["version"] == 1


@pytest.mark.asyncio
async def test_split_only_version_raises(db):
    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    with pytest.raises(ValueError, match="Cannot split the only version"):
        await _split_version(db=db, id=sent["id"], version=1)


# --- delete_mockup: version param (chunk 2) ---

@pytest.mark.asyncio
async def test_delete_mockup_specific_version(db):
    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    await _update_mockup(db=db, id=sent["id"], content="<p>2</p>", content_type="html")
    result = await _delete_mockup(db=db, id=sent["id"], version=2)
    assert result["deleted"] is True
    after = await _get_mockup(db=db, id=sent["id"])
    assert [v["number"] for v in after["versions"]] == [1]


@pytest.mark.asyncio
async def test_delete_last_version_raises(db):
    sent = await _send_mockup(db=db, project="P", title="T", description=None,
                              content="<p>x</p>", content_type="html", tags=[])
    with pytest.raises(ValueError, match="Cannot delete the only version"):
        await _delete_mockup(db=db, id=sent["id"], version=1)


@pytest.mark.asyncio
async def test_delete_last_version_via_mcp_tool_raises_tool_error(client):
    # `client` (the httpx/ASGI fixture) already runs app_lifespan, which calls
    # register_tools once against ITS OWN db and keeps it open for the test's
    # duration. Registering again here (on the shared module-level `mcp`) would
    # leave stale closures pointing at a since-closed db for whichever test
    # runs next — see task-2-review.md Minor 7. Reuse the existing registration
    # instead of mutating the global server ourselves.
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>x</p>", "text/html")},
        data={"project": "P", "title": "T"},
    )
    mockup_id = resp.json()["id"]
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError):
            await mcp_client.call_tool("delete_mockup", {"id": mockup_id, "version": 1})


# --- set_created_at: version param (chunk 2) ---

@pytest.mark.asyncio
async def test_set_created_at_on_lowest_version_also_sets_design_created_at(db):
    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    await _update_mockup(db=db, id=sent["id"], content="<p>2</p>", content_type="html")
    await _set_created_at(db=db, id=sent["id"], created_at="1999-01-01T00:00:00+00:00",
                          version=1)
    after = await _get_mockup(db=db, id=sent["id"])
    assert after["created_at"] == "1999-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_set_created_at_on_later_version_rf4(db):
    # RF-4: backdating v1 past v2 must not disturb version order or latest_at.
    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    await _update_mockup(db=db, id=sent["id"], content="<p>2</p>", content_type="html")
    before = await _get_mockup(db=db, id=sent["id"])

    await _set_created_at(db=db, id=sent["id"], created_at="2099-01-01T00:00:00+00:00",
                          version=1)
    after = await _get_mockup(db=db, id=sent["id"])
    assert [v["number"] for v in after["versions"]] == [2, 1]
    assert after["latest_at"] == before["latest_at"]
    assert after["created_at"] == "2099-01-01T00:00:00+00:00"  # v1 is still the lowest version


@pytest.mark.asyncio
async def test_set_created_at_on_non_lowest_version_leaves_design_created_at(db):
    sent = await _send_mockup(db=db, project="P", title="Hero", description=None,
                              content="<p>1</p>", content_type="html", tags=[])
    await _update_mockup(db=db, id=sent["id"], content="<p>2</p>", content_type="html")
    before = await _get_mockup(db=db, id=sent["id"])

    await _set_created_at(db=db, id=sent["id"], created_at="2050-06-01T00:00:00+00:00",
                          version=2)
    after = await _get_mockup(db=db, id=sent["id"])
    assert after["created_at"] == before["created_at"]  # v2 is not the design's lowest version
    assert after["latest_at"] == "2050-06-01T00:00:00+00:00"
