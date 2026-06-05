import pytest
from app.db import init_db
from app.mcp_server import (
    _send_mockup, _list_mockups, _get_mockup,
    _update_mockup, _delete_mockup, _tag_mockup, _set_created_at
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
async def test_update_mockup_content_type_change_deletes_old_file(db, tmp_data_dir):
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
    assert not old_path.exists()  # old .html removed


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
    import app.mcp_server as m

    async def boom(*args, **kwargs):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(m, "insert_mockup", boom)
    with pytest.raises(RuntimeError):
        await _send_mockup(db=db, project="P", title="T", description=None,
                           content="<p>x</p>", content_type="html", tags=[])
    # The written file must not be orphaned on disk.
    proj_dir = tmp_data_dir / "p"
    leftover = list(proj_dir.glob("*")) if proj_dir.exists() else []
    assert leftover == []
