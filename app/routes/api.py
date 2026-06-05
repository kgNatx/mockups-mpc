import base64
from pathlib import PurePosixPath

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.db import get_mockup, list_mockups, list_projects, set_favorite, count_favorites
from app.storage import TEXT_TYPES, MAX_CONTENT_SIZE, slugify_project
from app.mcp_server import _send_mockup, _delete_mockup

router = APIRouter(prefix="/api")

EXT_TO_TYPE = {
    ".html": "html",
    ".htm": "html",
    ".svg": "svg",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
}

@router.get("/mockups")
async def api_list_mockups(request: Request, project: str | None = None,
                           q: str | None = None, sort: str = "newest",
                           favorites_only: bool = False,
                           limit: int = 50, offset: int = 0):
    # project param accepts either slug or display name
    try:
        slug = slugify_project(project) if project else None
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    rows = await list_mockups(request.app.state.db, project_slug=slug, q=q,
                              sort=sort, favorites_only=favorites_only,
                              limit=limit, offset=offset)
    return rows

@router.get("/mockups/{mockup_id}")
async def api_get_mockup(request: Request, mockup_id: str):
    row = await get_mockup(request.app.state.db, mockup_id)
    if row is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return row

class FavoriteBody(BaseModel):
    favorite: bool


@router.put("/mockups/{mockup_id}/favorite")
async def api_set_favorite(request: Request, mockup_id: str, body: FavoriteBody):
    ok = await set_favorite(request.app.state.db, mockup_id, body.favorite)
    if not ok:
        return JSONResponse({"error": "Not found"}, status_code=404)
    row = await get_mockup(request.app.state.db, mockup_id)
    return row


@router.get("/favorites/count")
async def api_favorites_count(request: Request):
    return {"count": await count_favorites(request.app.state.db)}


@router.delete("/mockups/{mockup_id}")
async def api_delete_mockup(request: Request, mockup_id: str):
    try:
        return await _delete_mockup(db=request.app.state.db, id=mockup_id)
    except ValueError:
        return JSONResponse({"error": "Not found"}, status_code=404)

@router.get("/projects")
async def api_list_projects(request: Request):
    return await list_projects(request.app.state.db)

@router.post("/upload")
async def api_upload(
    request: Request,
    file: UploadFile,
    project: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    tags: str | None = Form(None),
):
    """Upload a mockup file directly. More token-efficient than send_mockup
    since file content doesn't flow through the model context."""
    # Determine content type from file extension
    ext = PurePosixPath(file.filename or "").suffix.lower()
    content_type = EXT_TO_TYPE.get(ext)
    if content_type is None:
        return JSONResponse(
            {"error": f"Unsupported file extension: {ext!r}. Supported: {', '.join(sorted(EXT_TO_TYPE))}"},
            status_code=400,
        )

    # Read in bounded chunks so an oversize upload can't exhaust memory before
    # the size check (file.read() with no arg would buffer the whole body).
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_CONTENT_SIZE:
            return JSONResponse(
                {"error": f"File too large (max {MAX_CONTENT_SIZE} bytes)"},
                status_code=413,
            )
    data = bytes(data)

    # Encode content the way _send_mockup expects it
    if content_type in TEXT_TYPES:
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            return JSONResponse({"error": "File is not valid UTF-8"}, status_code=400)
    else:
        content = base64.b64encode(data).decode("ascii")

    # Parse tags: comma-separated string → list
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    try:
        result = await _send_mockup(
            db=request.app.state.db,
            project=project,
            title=title,
            description=description,
            content=content,
            content_type=content_type,
            tags=tag_list,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return result
