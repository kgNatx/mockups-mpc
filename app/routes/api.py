import base64
from pathlib import PurePosixPath

from fastapi import APIRouter, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app import versioning
from app.db import get_mockup, list_mockups, list_projects, set_favorite, count_favorites
from app.storage import TEXT_TYPES, MAX_CONTENT_SIZE, slugify_project
from app.mcp_server import _send_mockup, _get_mockup, _delete_mockup, _split_version

router = APIRouter(prefix="/api")

_FALSY_FOLD = {"false", "0", "no"}


def _parse_fold(value: str | None) -> bool:
    return value is None or value.strip().lower() not in _FALSY_FOLD


def _versioning_error_status(exc: ValueError) -> int:
    # versioning.py's "not found" messages (unknown design/version) are 404;
    # its "Cannot ... the only version" messages are 409.
    return 404 if "not found" in str(exc).lower() else 409

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
async def api_get_mockup(request: Request, mockup_id: str, v: int | None = None):
    try:
        return await _get_mockup(db=request.app.state.db, id=mockup_id, version=v)
    except ValueError:
        return JSONResponse({"error": "Not found"}, status_code=404)


@router.post("/mockups/{mockup_id}/versions/{number}/split")
async def api_split_version(request: Request, mockup_id: str, number: int):
    try:
        return await _split_version(db=request.app.state.db, id=mockup_id, version=number)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=_versioning_error_status(e))


@router.delete("/mockups/{mockup_id}/versions/{number}")
async def api_delete_version(request: Request, mockup_id: str, number: int):
    try:
        await _delete_mockup(db=request.app.state.db, id=mockup_id, version=number)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=_versioning_error_status(e))
    return Response(status_code=204)

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
    parent: str | None = Form(None),
    fold: str | None = Form(None),
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
            parent=parent,
            fold=_parse_fold(fold),
        )
    except versioning.UnknownParent as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return result
