from typing import Annotated

import aiosqlite
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from app import config, versioning
from app.db import (
    get_alias, get_mockup, get_versions, list_mockups, list_projects,
    update_mockup as db_update_mockup, UNSET,
)
from app.storage import slugify_project

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
        "To read a mockup's content later, curl the view_url returned by get_mockup. "
        "To revise an existing mockup, upload with -F parent=<id> instead of creating "
        "a new one. Use -F fold=false only for deliberate variants."
    ),
)

# --- Internal logic (testable without MCP transport) ---

async def _resolve_or_raise(db: aiosqlite.Connection, id: str,
                             version: int | None) -> tuple[str, int]:
    """`versioning.resolve`, but with the 404 messages routes/tools rely on."""
    resolved = await versioning.resolve(db, id, version)
    if resolved is not None:
        return resolved
    # The id is known (design or alias) but that version isn't: say which.
    if version is not None and (await get_mockup(db, id) is not None
                                or await get_alias(db, id) is not None):
        raise versioning.NotFound(f"Version not found: {id} v{version}")
    raise versioning.NotFound(f"Mockup not found: {id}")


def _build_send_response(design: dict, ref: versioning.VersionRef) -> dict:
    result = {
        "id": design["id"],
        "project": design["project"],
        "project_slug": design["project_slug"],
        "title": design["title"],
        "description": design["description"],
        "content_type": design["content_type"],
        "file_path": design["file_path"],
        "tags": design["tags"],
        "gallery_url": f"{config.BASE_URL}/?mockup={design['id']}",
        "created_at": design["created_at"],
        "updated_at": design["updated_at"],
        "view_url": f"{config.BASE_URL}/view/{design['id']}",
        "version": ref.number,
        "version_url": f"{config.BASE_URL}/view/{design['id']}/v/{ref.number}",
        "folded": ref.folded,
    }
    if ref.folded:
        result["note"] = (
            f"Added as version {ref.number} of '{design['title']}'. "
            "If this was meant to be a separate mockup, split it out with "
            f"split_version({design['id']}, {ref.number}) or "
            f"POST /api/mockups/{design['id']}/versions/{ref.number}/split."
        )
    return result


async def _send_mockup(*, db: aiosqlite.Connection, project: str, title: str,
                        description: str | None, content: str, content_type: str,
                        tags: list[str] | None, parent: str | None = None,
                        fold: bool = True) -> dict:
    slug = slugify_project(project)
    tags = tags or []

    if parent is not None:
        resolved = await versioning.resolve(db, parent)
        if resolved is None:
            raise versioning.UnknownParent(f"Unknown parent: {parent}")
        mockup_id, _ = resolved
        parent_design = await get_mockup(db, mockup_id)
        # None when the parent is deleted between resolve and here.
        if parent_design is None:
            raise versioning.UnknownParent(f"Unknown parent: {parent}")
        if parent_design["project_slug"] != slug:
            raise ValueError(f"Parent {parent!r} belongs to a different project")
        try:
            ref = await versioning.add_version(
                db, mockup_id, title=title, description=description,
                content_type=content_type, content=content, folded=False, add_tags=tags)
        except versioning.NotFound:
            # Deleted after the check above, before add_version took the lock.
            raise versioning.UnknownParent(f"Unknown parent: {parent}") from None
    elif fold:
        target = await versioning.find_fold_target(db, project_slug=slug, title=title)
        ref = None
        if target is not None:
            try:
                ref = await versioning.add_version(
                    db, target, title=title, description=description,
                    content_type=content_type, content=content, folded=True,
                    add_tags=tags)
            except versioning.NotFound:
                pass  # The fold target was deleted meanwhile: nothing to fold into.
        if ref is None:
            ref = await versioning.create_design(
                db, project=project, title=title, description=description,
                content_type=content_type, content=content, tags=tags)
    else:
        ref = await versioning.create_design(
            db, project=project, title=title, description=description,
            content_type=content_type, content=content, tags=tags)

    design = await get_mockup(db, ref.mockup_id)
    return _build_send_response(design, ref)


async def _list_mockups(*, db: aiosqlite.Connection, project: str | None,
                         limit: int, offset: int) -> list[dict]:
    slug = slugify_project(project) if project else None
    return await list_mockups(db, project_slug=slug, limit=limit, offset=offset)


async def _get_mockup(*, db: aiosqlite.Connection, id: str,
                       version: int | None = None) -> dict:
    design_row = await get_mockup(db, id)
    is_alias = design_row is None
    mockup_id, num = await _resolve_or_raise(db, id, version)
    if is_alias:
        design_row = await get_mockup(db, mockup_id)

    versions = await get_versions(db, mockup_id)  # newest (highest number) first
    result = dict(design_row)
    result["id"] = mockup_id
    result["versions"] = [
        {
            "number": v["number"],
            "title": v["title"],
            "created_at": v["created_at"],
            "content_type": v["content_type"],
            "view_url": f"{config.BASE_URL}/view/{mockup_id}/v/{v['number']}",
        }
        for v in versions
    ]
    result["version"] = num
    if version is None and not is_alias:
        result["view_url"] = f"{config.BASE_URL}/view/{mockup_id}"
        result["gallery_url"] = f"{config.BASE_URL}/?mockup={mockup_id}"
    else:
        result["view_url"] = f"{config.BASE_URL}/view/{mockup_id}/v/{num}"
        result["gallery_url"] = f"{config.BASE_URL}/?mockup={mockup_id}&v={num}"
    return result


async def _update_mockup(*, db: aiosqlite.Connection, id: str,
                          title: str | None = None, description=UNSET,
                          tags: list[str] | None = None, content: str | None = None,
                          content_type: str | None = None) -> dict:
    resolved = await versioning.resolve(db, id)
    if resolved is None:
        raise versioning.NotFound(f"Mockup not found: {id}")
    mockup_id, _ = resolved  # id may be an alias; every write below targets the design
    existing = await get_mockup(db, mockup_id)
    if content_type is not None and content is None:
        raise ValueError(
            "content_type can only be changed by also supplying new content, "
            "since it determines the on-disk file extension"
        )
    if content is not None:
        # Adds a version; earlier versions (and their files) are kept. The
        # design's own title/rename rule lives in versioning.add_version.
        new_title = existing["title"] if title is None else title
        new_description = existing["description"] if description is UNSET else description
        ct = content_type or existing["content_type"]
        await versioning.add_version(
            db, mockup_id, title=new_title, description=new_description,
            content_type=ct, content=content)
        if tags is not None:
            await db_update_mockup(db, mockup_id, tags=tags)
    else:
        # Metadata-only: still renames the design.
        await versioning.update_design(
            db, mockup_id, title=title, description=description, tags=tags)
    return await _get_mockup(db=db, id=mockup_id)


async def _delete_mockup(*, db: aiosqlite.Connection, id: str,
                          version: int | None = None) -> dict:
    if version is None:
        await versioning.delete_design(db, id)
        return {"deleted": True, "id": id}
    mockup_id, num = await _resolve_or_raise(db, id, version)
    await versioning.delete_version(db, mockup_id, num)
    return {"deleted": True, "id": mockup_id, "version": num}


async def _split_version(*, db: aiosqlite.Connection, id: str, version: int) -> dict:
    mockup_id, num = await _resolve_or_raise(db, id, version)
    new_id = await versioning.split_version(db, mockup_id, num)
    return await _get_mockup(db=db, id=new_id)


async def _tag_mockup(*, db: aiosqlite.Connection, id: str,
                       add: list[str] | None, remove: list[str] | None) -> dict:
    resolved = await versioning.resolve(db, id)
    if resolved is None:
        raise versioning.NotFound(f"Mockup not found: {id}")
    mockup_id, _ = resolved  # id may be an alias; tags live on the design
    existing = await get_mockup(db, mockup_id)
    current = set(existing["tags"])
    if add:
        current.update(add)
    if remove:
        current -= set(remove)
    await db_update_mockup(db, mockup_id, tags=sorted(current))
    return await _get_mockup(db=db, id=mockup_id)


async def _set_created_at(*, db: aiosqlite.Connection, id: str,
                           created_at: str, version: int | None = None) -> dict:
    # Validate ISO format
    from datetime import datetime as dt
    try:
        dt.fromisoformat(created_at)
    except ValueError:
        raise ValueError(f"Invalid ISO 8601 datetime: {created_at!r}")
    mockup_id, num = await _resolve_or_raise(db, id, version)
    await versioning.set_version_created_at(db, mockup_id, num, created_at)
    # The design, not the (maybe alias) id the caller passed: an alias would
    # return its pinned version's view instead of the design's.
    return await _get_mockup(db=db, id=mockup_id)


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
        parent: Annotated[str | None, Field(
            description="Design or alias id to add this as a new version of, "
                        "instead of creating a new mockup")] = None,
        fold: Annotated[bool, Field(
            description="Automatically add as a version when exactly one design in the "
                        "project shares this title's base (ignored when parent is given)"
        )] = True,
    ) -> dict:
        try:
            return await _send_mockup(
                db=get_db(), project=project, title=title,
                description=description, content=content,
                content_type=content_type, tags=tags,
                parent=parent, fold=fold,
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
        version: Annotated[int | None, Field(description="Version number; omit for the latest")] = None,
    ) -> dict:
        try:
            return await _get_mockup(db=get_db(), id=id, version=version)
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="update_mockup", description="Update mockup metadata, or add a new version by supplying content (earlier versions are kept).")
    async def update_mockup_tool(
        id: Annotated[str, Field(description="Mockup UUID")],
        title: Annotated[str | None, Field(description="New title")] = None,
        description: Annotated[str | None, Field(description="New description")] = None,
        tags: Annotated[list[str] | None, Field(description="Replace all tags")] = None,
        content: Annotated[str | None, Field(description="New content (adds a version)")] = None,
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
        version: Annotated[int | None, Field(
            description="Delete only this version; omit to delete the whole design")] = None,
    ) -> dict:
        try:
            return await _delete_mockup(db=get_db(), id=id, version=version)
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(name="split_version", description="Split a version out of its design into its own standalone mockup. Reverses an automatic or manual fold.")
    async def split_version_tool(
        id: Annotated[str, Field(description="Design or alias id")],
        version: Annotated[int, Field(description="Version number to split into its own design")],
    ) -> dict:
        try:
            return await _split_version(db=get_db(), id=id, version=version)
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
        version: Annotated[int | None, Field(
            description="Which version's date to change; omit for the latest")] = None,
    ) -> dict:
        try:
            return await _set_created_at(db=get_db(), id=id, created_at=created_at, version=version)
        except ValueError as e:
            raise ToolError(str(e))
