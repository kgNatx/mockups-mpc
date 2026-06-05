from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.db import get_mockup
from app.config import get_data_dir, APP_VERSION

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

MIME_MAP = {
    "html": "text/html",
    "png": "image/png",
    "jpg": "image/jpeg",
    "svg": "image/svg+xml",
}


@router.get("/", response_class=HTMLResponse)
async def gallery(request: Request):
    return templates.TemplateResponse(request, "gallery.html", {"version": APP_VERSION})


@router.get("/view/{mockup_id}")
async def view_mockup(request: Request, mockup_id: str):
    row = await get_mockup(request.app.state.db, mockup_id)
    if row is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    file_path = get_data_dir() / row["file_path"]
    if not file_path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    mime = MIME_MAP.get(row["content_type"], "application/octet-stream")
    headers = {"X-Content-Type-Options": "nosniff"}
    # Stored html/svg is user-supplied and is served at the top level here (the
    # "Pop out" link and the MCP view_url navigate directly to it, bypassing the
    # in-feed iframe sandbox). The CSP `sandbox` directive sandboxes even a
    # top-level document into an opaque origin, so embedded scripts still run
    # (mockups stay interactive) but cannot reach our same-origin API, cookies,
    # or storage. `allow-scripts` mirrors the in-feed iframe's sandbox.
    if row["content_type"] in ("html", "svg"):
        headers["Content-Security-Policy"] = "sandbox allow-scripts"
    return FileResponse(str(file_path), media_type=mime, headers=headers)
