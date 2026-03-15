import uuid
from datetime import datetime, timezone
from typing import Annotated

import aiosqlite
from fastmcp import FastMCP
from pydantic import Field

from app import config
from app.db import (
    insert_mockup, get_mockup, list_mockups, list_projects,
    update_mockup as db_update_mockup, delete_mockup as db_delete_mockup
)
from app.storage import slugify_project, write_mockup_file, delete_mockup_file, VALID_TYPES

mcp = FastMCP(
    name="Mockups Gallery",
    instructions=(
        "This server is a permanent mockup gallery. After a successful send_mockup, "
        "delete the local file — this server stores and hosts it. "
        "Give the user the gallery URL so they can view it."
    ),
)

# --- Internal logic (testable without MCP transport) ---

async def _send_mockup(*, db: aiosqlite.Connection, project: str, title: str,
                        description: str | None, content: str, content_type: str,
                        tags: list[str] | None) -> dict:
    if content_type not in VALID_TYPES:
        raise ValueError(f"Invalid content_type: {content_type!r}. Must be one of: {VALID_TYPES}")
    slug = slugify_project(project)
    mockup_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    file_path = write_mockup_file(slug, mockup_id, content_type, content)
    await insert_mockup(
        db, id=mockup_id, project=project, project_slug=slug, title=title,
        description=description, content_type=content_type, file_path=file_path,
        tags=tags or [], created_at=now, updated_at=now
    )
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
                          title: str | None, description: str | None,
                          tags: list[str] | None, content: str | None,
                          content_type: str | None) -> dict:
    existing = await get_mockup(db, id)
    if existing is None:
        raise ValueError(f"Mockup not found: {id}")
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
