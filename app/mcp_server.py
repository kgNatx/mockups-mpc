import uuid
from datetime import datetime, timezone
from typing import Annotated

import aiosqlite
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from app import config
from app.db import (
    insert_mockup, get_mockup, list_mockups, list_projects,
    update_mockup as db_update_mockup, delete_mockup as db_delete_mockup,
    UNSET,
)
from app.storage import slugify_project, write_mockup_file, delete_mockup_file

mcp = FastMCP(
    name="Mockups Gallery",
    instructions=(
        "This server is a permanent mockup gallery. "
        "To send mockups efficiently, write the file locally then upload via curl: "
        f"curl -X POST {config.BASE_URL}/api/upload -F file=@path -F project=name -F title=name "
        '[-F description=text] [-F "tags=a,b,c"]. '
        "This avoids passing large file content through the model context. "
        "Give the user the gallery_url from the response so they can view it. "
        "The server stores all content permanently — local files are safe to "
        "clean up when no longer needed for reference. "
        "To read a mockup's content later, curl the view_url returned by get_mockup."
    ),
)

# --- Internal logic (testable without MCP transport) ---

async def _send_mockup(*, db: aiosqlite.Connection, project: str, title: str,
                        description: str | None, content: str, content_type: str,
                        tags: list[str] | None) -> dict:
    slug = slugify_project(project)
    mockup_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    # write_mockup_file is the authoritative content_type gate (it maps the type
    # to the on-disk extension), so we don't pre-validate here.
    file_path = write_mockup_file(slug, mockup_id, content_type, content)
    try:
        await insert_mockup(
            db, id=mockup_id, project=project, project_slug=slug, title=title,
            description=description, content_type=content_type, file_path=file_path,
            tags=tags or [], created_at=now, updated_at=now
        )
    except Exception:
        # Roll back the file write so a failed insert doesn't orphan it on disk.
        delete_mockup_file(file_path)
        raise
    return {
        "id": mockup_id, "project": project, "project_slug": slug,
        "title": title, "description": description, "content_type": content_type,
        "file_path": file_path, "tags": tags or [],
        "gallery_url": f"{config.BASE_URL}/?mockup={mockup_id}",
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
    }


async def _list_mockups(*, db: aiosqlite.Connection, project: str | None,
                         limit: int, offset: int) -> list[dict]:
    slug = slugify_project(project) if project else None
    return await list_mockups(db, project_slug=slug, limit=limit, offset=offset)


async def _get_mockup(*, db: aiosqlite.Connection, id: str) -> dict:
    row = await get_mockup(db, id)
    if row is None:
        raise ValueError(f"Mockup not found: {id}")
    row["view_url"] = f"{config.BASE_URL}/view/{id}"
    row["gallery_url"] = f"{config.BASE_URL}/?mockup={id}"
    return row


async def _update_mockup(*, db: aiosqlite.Connection, id: str,
                          title: str | None = None, description=UNSET,
                          tags: list[str] | None = None, content: str | None = None,
                          content_type: str | None = None) -> dict:
    existing = await get_mockup(db, id)
    if existing is None:
        raise ValueError(f"Mockup not found: {id}")
    if content_type is not None and content is None:
        raise ValueError(
            "content_type can only be changed by also supplying new content, "
            "since it determines the on-disk file extension"
        )
    new_file_path = None
    if content is not None:
        ct = content_type or existing["content_type"]
        new_file_path = write_mockup_file(existing["project_slug"], id, ct, content)
        old_path = existing["file_path"]
        if old_path != new_file_path:
            delete_mockup_file(old_path)
    new_ct = content_type if content is not None else None
    await db_update_mockup(db, id, title=title, description=description,
                           tags=tags, file_path=new_file_path, content_type=new_ct)
    return await _get_mockup(db=db, id=id)


async def _delete_mockup(*, db: aiosqlite.Connection, id: str) -> dict:
    existing = await get_mockup(db, id)
    if existing is None:
        raise ValueError(f"Mockup not found: {id}")
    delete_mockup_file(existing["file_path"])
    await db_delete_mockup(db, id)
    return {"deleted": True, "id": id}


async def _tag_mockup(*, db: aiosqlite.Connection, id: str,
                       add: list[str] | None, remove: list[str] | None) -> dict:
    existing = await get_mockup(db, id)
    if existing is None:
        raise ValueError(f"Mockup not found: {id}")
    current = set(existing["tags"])
    if add:
        current.update(add)
    if remove:
        current -= set(remove)
    await db_update_mockup(db, id, tags=sorted(current))
    return await _get_mockup(db=db, id=id)


async def _set_created_at(*, db: aiosqlite.Connection, id: str,
                            created_at: str) -> dict:
    existing = await get_mockup(db, id)
    if existing is None:
        raise ValueError(f"Mockup not found: {id}")
    # Validate ISO format
    from datetime import datetime as dt
    try:
        dt.fromisoformat(created_at)
    except ValueError:
        raise ValueError(f"Invalid ISO 8601 datetime: {created_at!r}")
    await db_update_mockup(db, id, created_at=created_at)
    return await _get_mockup(db=db, id=id)


# --- FastMCP tool wrappers ---

def register_tools(get_db):
    """Register MCP tools. `get_db` is a callable that returns the db connection."""

    @mcp.tool(
        description="Sends a mockup to the gallery for permanent storage."
    )
    async def send_mockup(
        project: Annotated[str, Field(description="Project name")],
        title: Annotated[str, Field(description="Mockup title")],
        content: Annotated[str, Field(description="HTML/SVG as raw string, PNG/JPG as base64")],
        content_type: Annotated[str, Field(description="File type: html, png, jpg, or svg")],
        description: Annotated[str | None, Field(description="Optional description")] = None,
        tags: Annotated[list[str] | None, Field(description="Optional tags")] = None,
    ) -> dict:
        try:
            return await _send_mockup(
                db=get_db(), project=project, title=title,
                description=description, content=content,
                content_type=content_type, tags=tags
            )
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="list_mockups", description="List mockups, optionally filtered by project. Returns reverse-chronological order.")
    async def list_mockups_tool(
        project: Annotated[str | None, Field(description="Filter by project name")] = None,
        limit: Annotated[int, Field(description="Max results", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Offset for pagination", ge=0)] = 0,
    ) -> list[dict]:
        return await _list_mockups(db=get_db(), project=project, limit=limit, offset=offset)

    @mcp.tool(name="get_mockup", description="Get a specific mockup by ID, including view and gallery URLs. To read the file content, curl the view_url.")
    async def get_mockup_tool(
        id: Annotated[str, Field(description="Mockup UUID")],
    ) -> dict:
        try:
            return await _get_mockup(db=get_db(), id=id)
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="update_mockup", description="Update mockup metadata or replace its content.")
    async def update_mockup_tool(
        id: Annotated[str, Field(description="Mockup UUID")],
        title: Annotated[str | None, Field(description="New title")] = None,
        description: Annotated[str | None, Field(description="New description")] = None,
        tags: Annotated[list[str] | None, Field(description="Replace all tags")] = None,
        content: Annotated[str | None, Field(description="New content (replaces file)")] = None,
        content_type: Annotated[str | None, Field(description="Required if content provided")] = None,
    ) -> dict:
        try:
            return await _update_mockup(
                db=get_db(), id=id, title=title,
                description=UNSET if description is None else description,
                tags=tags, content=content, content_type=content_type
            )
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="delete_mockup", description="Delete a mockup by ID. Removes both the database record and file.")
    async def delete_mockup_tool(
        id: Annotated[str, Field(description="Mockup UUID")],
    ) -> dict:
        try:
            return await _delete_mockup(db=get_db(), id=id)
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="tag_mockup", description="Add or remove tags on a mockup.")
    async def tag_mockup_tool(
        id: Annotated[str, Field(description="Mockup UUID")],
        add: Annotated[list[str] | None, Field(description="Tags to add")] = None,
        remove: Annotated[list[str] | None, Field(description="Tags to remove")] = None,
    ) -> dict:
        try:
            return await _tag_mockup(db=get_db(), id=id, add=add, remove=remove)
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="set_created_at", description="Change the created date of a mockup. Useful for backdating uploads or reordering the timeline.")
    async def set_created_at_tool(
        id: Annotated[str, Field(description="Mockup UUID")],
        created_at: Annotated[str, Field(description="ISO 8601 datetime, e.g. 2026-03-10T14:30:00+00:00")],
    ) -> dict:
        try:
            return await _set_created_at(db=get_db(), id=id, created_at=created_at)
        except ValueError as e:
            raise ToolError(str(e))
