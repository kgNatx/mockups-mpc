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
