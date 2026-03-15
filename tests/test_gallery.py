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
    await insert_mockup(
        db, id="v1", project="Test", project_slug="test",
        title="View", description=None, content_type="html",
        file_path="test/v1.html", tags=[], created_at=now, updated_at=now,
    )
    resp = await client.get("/view/v1")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "<h1>View Test</h1>" in resp.text


@pytest.mark.asyncio
async def test_view_image_mockup(client):
    import base64
    from app.db import init_db, insert_mockup
    from app.storage import write_mockup_file

    db = await init_db()
    now = datetime.now(timezone.utc)
    raw = b"\x89PNG\r\n\x1a\nfakedata"
    write_mockup_file("test", "img1", "png", base64.b64encode(raw).decode())
    await insert_mockup(
        db, id="img1", project="Test", project_slug="test",
        title="Image", description=None, content_type="png",
        file_path="test/img1.png", tags=[], created_at=now, updated_at=now,
    )
    resp = await client.get("/view/img1")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")


@pytest.mark.asyncio
async def test_view_not_found(client):
    resp = await client.get("/view/nonexistent")
    assert resp.status_code == 404
