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
async def test_upload_oversize_returns_413(client, monkeypatch):
    monkeypatch.setattr("app.routes.api.MAX_CONTENT_SIZE", 10)
    resp = await client.post(
        "/api/upload",
        files={"file": ("big.html", b"<p>" + b"x" * 50 + b"</p>", "text/html")},
        data={"project": "P", "title": "Big"},
    )
    assert resp.status_code == 413
    assert "too large" in resp.json()["error"].lower()


@pytest.mark.asyncio
async def test_upload_invalid_utf8_returns_400(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("bad.html", b"\xff\xfe\xfa", "text/html")},
        data={"project": "P", "title": "Bad UTF8"},
    )
    assert resp.status_code == 400
    assert "UTF-8" in resp.json()["error"]


@pytest.mark.asyncio
async def test_upload_bad_project_returns_400(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("ok.html", b"<p>hi</p>", "text/html")},
        data={"project": "../etc", "title": "Traversal"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_bad_project_returns_400(client):
    resp = await client.get("/api/mockups?project=../etc")
    assert resp.status_code == 400

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


# --- upload: parent / fold (chunk 2) ---

@pytest.mark.asyncio
async def test_upload_with_parent_adds_version(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>v1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    parent_id = resp.json()["id"]

    resp = await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>v2</p>", "text/html")},
        data={"project": "P", "title": "Hero v2", "parent": parent_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == parent_id
    assert body["version"] == 2
    assert body["folded"] is False

    resp = await client.get(f"/view/{parent_id}")
    assert resp.text == "<p>v2</p>"


@pytest.mark.asyncio
async def test_upload_with_alias_parent(client):
    from app.db import init_db, insert_alias, transaction

    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>v1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    parent_id = resp.json()["id"]

    db = await init_db()
    async with transaction(db):
        await insert_alias(db, alias_id="old-link", mockup_id=parent_id, number=1)
    await db.close()

    resp = await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>v2</p>", "text/html")},
        data={"project": "P", "title": "Hero v2", "parent": "old-link"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == parent_id
    assert resp.json()["version"] == 2


@pytest.mark.asyncio
async def test_upload_unknown_parent_returns_404(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>x</p>", "text/html")},
        data={"project": "P", "title": "T", "parent": "nope"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Unknown parent: nope"


@pytest.mark.asyncio
async def test_upload_parent_other_project_returns_400(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "ProjA", "title": "Hero"},
    )
    parent_id = resp.json()["id"]
    resp = await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>2</p>", "text/html")},
        data={"project": "ProjB", "title": "Hero v2", "parent": parent_id},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_auto_folds_on_single_match(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Privacy page — draft 1"},
    )
    parent_id = resp.json()["id"]
    resp = await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>2</p>", "text/html")},
        data={"project": "P", "title": "Privacy page — draft 2"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == parent_id
    assert body["folded"] is True
    assert body["note"] == (
        "Added as version 2 of 'Privacy page'. "
        "If this was meant to be a separate mockup, split it out with split_version("
        f"{parent_id}, 2) or POST /api/mockups/{parent_id}/versions/2/split."
    )


@pytest.mark.asyncio
async def test_upload_no_fold_on_two_matches(client):
    await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Privacy page — draft 1"},
    )
    await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>2</p>", "text/html")},
        data={"project": "P", "title": "Privacy page — draft 2", "fold": "false"},
    )
    resp = await client.post(
        "/api/upload",
        files={"file": ("c.html", b"<p>3</p>", "text/html")},
        data={"project": "P", "title": "Privacy page — draft 3"},
    )
    assert resp.status_code == 200
    assert resp.json()["folded"] is False
    assert resp.json()["version"] == 1


@pytest.mark.asyncio
async def test_upload_fold_false_never_folds(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Privacy page — draft 1"},
    )
    parent_id = resp.json()["id"]
    resp = await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>2</p>", "text/html")},
        data={"project": "P", "title": "Privacy page — draft 2", "fold": "false"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] != parent_id
    assert resp.json()["folded"] is False


@pytest.mark.asyncio
async def test_upload_option_b_does_not_fold_into_option_a(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>a</p>", "text/html")},
        data={"project": "P", "title": "Hero — option A"},
    )
    a_id = resp.json()["id"]
    resp = await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>b</p>", "text/html")},
        data={"project": "P", "title": "Hero — option B"},
    )
    assert resp.json()["id"] != a_id
    assert resp.json()["version"] == 1


# --- /api/mockups/{id}: version param, split, delete-version (chunk 2) ---

@pytest.mark.asyncio
async def test_api_get_mockup_with_version_param(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>2</p>", "text/html")},
        data={"project": "P", "title": "Hero v2", "parent": mid},
    )
    resp = await client.get(f"/api/mockups/{mid}?v=1")
    assert resp.status_code == 200
    assert resp.json()["version"] == 1
    assert resp.json()["view_url"].endswith("/v/1")


@pytest.mark.asyncio
async def test_api_split_version(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>2</p>", "text/html")},
        data={"project": "P", "title": "Hero v2", "parent": mid},
    )
    resp = await client.post(f"/api/mockups/{mid}/versions/2/split")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] != mid
    assert body["version"] == 1


@pytest.mark.asyncio
async def test_api_split_unknown_version_returns_404(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    resp = await client.post(f"/api/mockups/{mid}/versions/99/split")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_split_only_version_returns_409(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    resp = await client.post(f"/api/mockups/{mid}/versions/1/split")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_api_delete_version_returns_204(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>2</p>", "text/html")},
        data={"project": "P", "title": "Hero v2", "parent": mid},
    )
    resp = await client.delete(f"/api/mockups/{mid}/versions/2")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_api_delete_last_version_returns_409(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    resp = await client.delete(f"/api/mockups/{mid}/versions/1")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_api_delete_unknown_version_returns_404(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    resp = await client.delete(f"/api/mockups/{mid}/versions/99")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_delete_version_via_alias_with_mismatched_number_returns_404(client):
    # fix round 1, Entry 3 item 1: an alias pinned to v1 must not let a caller
    # delete v2 (or any other version) by tacking a different number onto it.
    from app.db import init_db, insert_alias, transaction

    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    await client.post(
        "/api/upload",
        files={"file": ("b.html", b"<p>2</p>", "text/html")},
        data={"project": "P", "title": "Hero v2", "parent": mid},
    )
    db = await init_db()
    async with transaction(db):
        await insert_alias(db, alias_id="old-link", mockup_id=mid, number=1)
    await db.close()

    resp = await client.delete("/api/mockups/old-link/versions/2")
    assert resp.status_code == 404


# --- s007 deferred minors ---

async def _alias_for_new_design(client, alias_id="old-link"):
    from app.db import init_db, insert_alias, transaction
    resp = await client.post(
        "/api/upload",
        files={"file": ("a.html", b"<p>1</p>", "text/html")},
        data={"project": "P", "title": "Hero"},
    )
    mid = resp.json()["id"]
    db = await init_db()
    async with transaction(db):
        await insert_alias(db, alias_id=alias_id, mockup_id=mid, number=1)
    await db.close()
    return mid


@pytest.mark.asyncio
async def test_api_set_favorite_by_alias_stars_the_design(client):
    mid = await _alias_for_new_design(client)
    resp = await client.put("/api/mockups/old-link/favorite", json={"favorite": True})
    assert resp.status_code == 200
    assert resp.json()["id"] == mid and resp.json()["favorite"] == 1


def test_versioning_error_status_uses_exception_types():
    from app import versioning
    from app.routes.api import _versioning_error_status
    assert _versioning_error_status(versioning.NotFound("anything")) == 404
    assert _versioning_error_status(versioning.Conflict("says not found")) == 409
    assert _versioning_error_status(ValueError("not found")) == 400
