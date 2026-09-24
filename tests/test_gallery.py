import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_gallery_loads(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Mockups" in resp.text


@pytest.mark.asyncio
async def test_gallery_has_compact_sidebar_markup(client):
    # The compact sidebar (brand bar + scope picker) replaces the old
    # brand block + full project list. The old project list markup must
    # be gone; the new brand bar, scope picker, and collapsed-bar eyebrow
    # must be present.
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'class="brand-bar"' in resp.text
    assert 'id="scope-btn"' in resp.text
    assert 'class="bar-eyebrow"' in resp.text
    assert 'id="project-list"' not in resp.text


@pytest.mark.asyncio
async def test_gallery_stylesheet_is_cache_busted(client):
    # The stylesheet href must carry a ?v=<version> query so each release busts
    # the browser cache; no unversioned reference should remain.
    from pathlib import Path

    version = (Path(__file__).parent.parent / "VERSION").read_text().strip()
    resp = await client.get("/")
    assert resp.status_code == 200
    assert f"/static/style.css?v={version}" in resp.text
    assert '/static/style.css"' not in resp.text


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


@pytest.mark.asyncio
async def test_view_html_is_sandboxed(client):
    # Stored html served top-level must carry the sandbox CSP + nosniff so a
    # popped-out mockup's scripts can't reach our same-origin API.
    resp = await client.post(
        "/api/upload",
        files={"file": ("xss.html", b"<script>alert(1)</script>", "text/html")},
        data={"project": "Sec", "title": "XSS"},
    )
    vid = resp.json()["id"]
    resp = await client.get(f"/view/{vid}")
    assert resp.status_code == 200
    assert "sandbox" in resp.headers["content-security-policy"]
    assert resp.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_view_image_has_no_sandbox_csp(client):
    # Images carry no executable content; they should not get the sandbox CSP.
    resp = await client.post(
        "/api/upload",
        files={"file": ("i.png", b"\x89PNG\r\n\x1a\nx", "image/png")},
        data={"project": "P", "title": "Img"},
    )
    vid = resp.json()["id"]
    resp = await client.get(f"/view/{vid}")
    assert resp.status_code == 200
    assert "content-security-policy" not in resp.headers


# --- versioned /view routes (chunk 2) ---

@pytest.mark.asyncio
async def test_view_id_serves_latest_and_v_n_serves_that_version(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>v1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>v2</p>", "text/html")},
        data={"project": "P", "title": "Hero v2", "parent": mid},
    )
    resp = await client.get(f"/view/{mid}")
    assert resp.text == "<p>v2</p>"
    resp = await client.get(f"/view/{mid}/v/1")
    assert resp.text == "<p>v1</p>"


@pytest.mark.asyncio
async def test_view_unknown_version_returns_404(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>v1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    resp = await client.get(f"/view/{mid}/v/99")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_view_alias_serves_pinned_version(client):
    from app.db import init_db, insert_alias, transaction

    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>v1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]

    db = await init_db()
    async with transaction(db):
        await insert_alias(db, alias_id="old-link", mockup_id=mid, number=1)
    await db.close()

    resp = await client.get("/view/old-link")
    assert resp.status_code == 200
    assert resp.text == "<p>v1</p>"


@pytest.mark.asyncio
async def test_view_serves_each_version_headers_independently_rf2(client):
    # RF-2: v1 is html (sandboxed), v2 is png (no CSP). Each URL must reflect
    # its OWN version's content type and headers, not the design's mirror.
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<h1>v1</h1>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    await client.post(
        "/api/upload",
        files={"file": ("b.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
        data={"project": "P", "title": "Hero v2", "parent": mid},
    )

    resp = await client.get(f"/view/{mid}")
    assert resp.headers["content-type"].startswith("image/png")
    assert "content-security-policy" not in resp.headers

    resp = await client.get(f"/view/{mid}/v/1")
    assert resp.headers["content-type"].startswith("text/html")
    assert "sandbox" in resp.headers["content-security-policy"]
    assert resp.headers["x-content-type-options"] == "nosniff"


# --- alias id + mismatched explicit version (fix round 1, Entry 3 item 1) ---

@pytest.mark.asyncio
async def test_view_alias_with_mismatched_version_returns_404(client):
    # An alias is pinned to one version (spec §7): asking for a DIFFERENT
    # version through it must 404, not silently serve the pinned file.
    from app.db import init_db, insert_alias, transaction

    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>v1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>v2</p>", "text/html")},
        data={"project": "P", "title": "Hero v2", "parent": mid},
    )
    db = await init_db()
    async with transaction(db):
        await insert_alias(db, alias_id="old-link", mockup_id=mid, number=1)
    await db.close()

    resp = await client.get("/view/old-link/v/2")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_view_alias_with_matching_version_returns_200(client):
    from app.db import init_db, insert_alias, transaction

    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>v1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    db = await init_db()
    async with transaction(db):
        await insert_alias(db, alias_id="old-link", mockup_id=mid, number=1)
    await db.close()

    resp = await client.get("/view/old-link/v/1")
    assert resp.status_code == 200
    assert resp.text == "<p>v1</p>"
