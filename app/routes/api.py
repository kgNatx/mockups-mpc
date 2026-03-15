from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.db import get_mockup, list_mockups, list_projects

router = APIRouter(prefix="/api")

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

@router.get("/projects")
async def api_list_projects(request: Request):
    return await list_projects(request.app.state.db)
