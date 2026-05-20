import pytest

@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_list_mockups_empty(client):
    resp = await client.get("/api/mockups")
    assert resp.status_code == 200
    assert resp.json() == []

@pytest.mark.asyncio
async def test_create_and_list_via_api(client):
    from app.db import init_db, insert_mockup
    from app.storage import write_mockup_file
    from datetime import datetime, timezone
    db = await init_db()
    now = datetime.now(timezone.utc)
    write_mockup_file("test", "m1", "html", "<p>hi</p>")
    await insert_mockup(db, id="m1", project="Test", project_slug="test",
                        title="First", description=None, content_type="html",
                        file_path="test/m1.html", tags=["ui"], created_at=now, updated_at=now)
    resp = await client.get("/api/mockups")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "First"

@pytest.mark.asyncio
async def test_get_mockup_api(client):
    from app.db import init_db, insert_mockup
    from app.storage import write_mockup_file
    from datetime import datetime, timezone
    db = await init_db()
    now = datetime.now(timezone.utc)
    write_mockup_file("test", "m2", "html", "<p>hello</p>")
    await insert_mockup(db, id="m2", project="Test", project_slug="test",
                        title="Second", description="desc", content_type="html",
                        file_path="test/m2.html", tags=[], created_at=now, updated_at=now)
    resp = await client.get("/api/mockups/m2")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Second"

@pytest.mark.asyncio
async def test_get_mockup_not_found(client):
    resp = await client.get("/api/mockups/nonexistent")
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_list_projects(client):
    from app.db import init_db, insert_mockup
    from app.storage import write_mockup_file
    from datetime import datetime, timezone
    db = await init_db()
    now = datetime.now(timezone.utc)
    write_mockup_file("alpha", "a1", "html", "<p>a</p>")
    await insert_mockup(db, id="a1", project="Alpha", project_slug="alpha",
                        title="A1", description=None, content_type="html",
                        file_path="alpha/a1.html", tags=[], created_at=now, updated_at=now)
    resp = await client.get("/api/projects")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["project"] == "Alpha"
    assert data[0]["count"] == 1

@pytest.mark.asyncio
async def test_delete_mockup_api(client, tmp_data_dir):
    # Create one first
    resp = await client.post(
        "/api/upload",
        files={"file": ("m.html", b"<p>bye</p>", "text/html")},
        data={"project": "P", "title": "To Delete"},
    )
    mockup_id = resp.json()["id"]
    file_path = resp.json()["file_path"]
    assert (tmp_data_dir / file_path).exists()

    # Delete it
    resp = await client.delete(f"/api/mockups/{mockup_id}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    assert not (tmp_data_dir / file_path).exists()

    # Verify gone
    resp = await client.get(f"/api/mockups/{mockup_id}")
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_delete_mockup_api_not_found(client):
    resp = await client.delete("/api/mockups/nonexistent")
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_upload_html(client, tmp_data_dir):
    resp = await client.post(
        "/api/upload",
        files={"file": ("mockup.html", b"<h1>Uploaded</h1>", "text/html")},
        data={"project": "Upload Test", "title": "Via Upload", "tags": "ui,test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project"] == "Upload Test"
    assert body["title"] == "Via Upload"
    assert body["tags"] == ["ui", "test"]
    assert "gallery_url" in body
    assert (tmp_data_dir / body["file_path"]).exists()

@pytest.mark.asyncio
async def test_upload_png(client, tmp_data_dir):
    resp = await client.post(
        "/api/upload",
        files={"file": ("shot.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
        data={"project": "P", "title": "Screenshot"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content_type"] == "png"
    assert (tmp_data_dir / body["file_path"]).read_bytes() == b"\x89PNG\r\n\x1a\nfake"

@pytest.mark.asyncio
async def test_upload_unsupported_ext(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("anim.gif", b"GIF89a", "image/gif")},
        data={"project": "P", "title": "Bad"},
    )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["error"]

@pytest.mark.asyncio
async def test_upload_no_tags(client, tmp_data_dir):
    resp = await client.post(
        "/api/upload",
        files={"file": ("page.html", b"<p>hi</p>", "text/html")},
        data={"project": "P", "title": "No Tags"},
    )
    assert resp.status_code == 200
    assert resp.json()["tags"] == []


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
