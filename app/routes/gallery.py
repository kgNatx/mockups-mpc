from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app import versioning
from app.db import get_version
from app.config import get_data_dir, APP_VERSION

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
FAVICON_PATH = Path(__file__).parent.parent / "static" / "favicon.svg"
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


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Browsers ask for /favicon.ico on pages with no <link rel="icon">, such as
    # a popped-out mockup at /view/{id}. Modern browsers accept an SVG here.
    return FileResponse(str(FAVICON_PATH), media_type="image/svg+xml")


async def _serve_version(request: Request, mockup_id: str, number: int | None):
    """Shared by /view/{id} (latest, or an alias's pinned version) and
    /view/{id}/v/{n} (a fixed version). `mockup_id` may be a design or alias id.
    """
    resolved = await versioning.resolve(request.app.state.db, mockup_id, number)
    if resolved is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    design_id, num = resolved
    version = await get_version(request.app.state.db, design_id, num)
    if version is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    file_path = get_data_dir() / version["file_path"]
    if not file_path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    mime = MIME_MAP.get(version["content_type"], "application/octet-stream")
    headers = {"X-Content-Type-Options": "nosniff"}
    # Stored html/svg is user-supplied and is served at the top level here (the
    # "Pop out" link and the MCP view_url navigate directly to it, bypassing the
    # in-feed iframe sandbox). The CSP `sandbox` directive sandboxes even a
    # top-level document into an opaque origin, so embedded scripts still run
    # (mockups stay interactive) but cannot reach our same-origin API, cookies,
    # or storage. `allow-scripts` mirrors the in-feed iframe's sandbox.
    if version["content_type"] in ("html", "svg"):
        headers["Content-Security-Policy"] = "sandbox allow-scripts"
    return FileResponse(str(file_path), media_type=mime, headers=headers)


@router.get("/view/{mockup_id}")
async def view_mockup(request: Request, mockup_id: str):
    return await _serve_version(request, mockup_id, None)


@router.get("/view/{mockup_id}/v/{number}")
async def view_mockup_version(request: Request, mockup_id: str, number: int):
    return await _serve_version(request, mockup_id, number)
