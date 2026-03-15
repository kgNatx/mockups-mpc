import base64

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from app.db import get_mockup, list_mockups, list_projects, delete_mockup as db_delete_mockup
from app.storage import BINARY_TYPES, TEXT_TYPES, VALID_TYPES, MAX_CONTENT_SIZE

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
                           limit: int = 50, offset: int = 0):
    # project param accepts either slug or display name
    from app.storage import slugify_project
    slug = slugify_project(project) if project else None
    rows = await list_mockups(request.app.state.db, project_slug=slug,
                              limit=limit, offset=offset)
    return rows

@router.get("/mockups/{mockup_id}")
async def api_get_mockup(request: Request, mockup_id: str):
    row = await get_mockup(request.app.state.db, mockup_id)
    if row is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return row

@router.delete("/mockups/{mockup_id}")
async def api_delete_mockup(request: Request, mockup_id: str):
    from app.storage import delete_mockup_file
    row = await get_mockup(request.app.state.db, mockup_id)
    if row is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    delete_mockup_file(row["file_path"])
    await db_delete_mockup(request.app.state.db, mockup_id)
    return {"deleted": True, "id": mockup_id}

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
    from pathlib import PurePosixPath
    from app.mcp_server import _send_mockup

    # Determine content type from file extension
    ext = PurePosixPath(file.filename or "").suffix.lower()
    content_type = EXT_TO_TYPE.get(ext)
    if content_type is None:
        return JSONResponse(
            {"error": f"Unsupported file extension: {ext!r}. Supported: {', '.join(sorted(EXT_TO_TYPE))}"},
            status_code=400,
        )

    # Read file data with size check
    data = await file.read()
    if len(data) > MAX_CONTENT_SIZE:
        return JSONResponse(
            {"error": f"File too large: {len(data)} bytes (max {MAX_CONTENT_SIZE})"},
            status_code=413,
        )

    # Encode content the way _send_mockup expects it
    if content_type in TEXT_TYPES:
        content = data.decode("utf-8")
    else:
        content = base64.b64encode(data).decode("ascii")

    # Parse tags: comma-separated string → list
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    result = await _send_mockup(
        db=request.app.state.db,
        project=project,
        title=title,
        description=description,
        content=content,
        content_type=content_type,
        tags=tag_list,
    )
    return result
