"""Version orchestration: the base-title rule and every multi-step version write.

Routes and MCP tools never write mockup_versions directly; they call this module,
which pairs the file operations with the db.py calls (db.py stays the only SQL).
"""
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite

from app import db as queries
from app.storage import delete_mockup_file, slugify_project, version_rel_path, write_mockup_file

# Iteration markers stripped from the end of a title. Variant markers (option B,
# variant C, alt 2, a standalone letter) are deliberately absent: they name
# siblings, not revisions, and must never fold together.
_ITERATION = r"(?:v\d+(?:\.\d+)*|(?:draft|rev|iteration|iter|round|take)\s*\d+[a-z]?|r\d+|\d+[a-z]?)"
_TRAILING_TOKEN = re.compile(
    rf"^(?P<rest>.*?)(?:\s*[—–:,-]\s*|\s+)(?P<tok>{_ITERATION})\s*$", re.IGNORECASE
)
_TRAILING_PAREN = re.compile(r"^(?P<rest>.*?)\s*\([^()]*\)\s*$")
_VARIANT_WORD = re.compile(r"\b(?:option|variant|alt)$", re.IGNORECASE)


def base_title(title: str) -> str:
    """Strip trailing iteration markers ("draft 3b (rail fixed)") from a title.

    Repeats until nothing strips. Never returns an empty string: if stripping
    would consume everything, the original title is returned.
    """
    current = title.strip()
    paren_stripped = False
    while True:
        m = _TRAILING_TOKEN.match(current)
        if m and m.group("rest").strip() and not (
            m.group("tok")[0].isdigit() and _VARIANT_WORD.search(m.group("rest"))
        ):
            current = m.group("rest").rstrip()
            continue
        if not paren_stripped:
            m = _TRAILING_PAREN.match(current)
            if m and m.group("rest").strip():
                current = m.group("rest").rstrip()
                paren_stripped = True
                continue
        break
    return current or title


def comparison_key(title: str) -> str:
    """Case- and whitespace-insensitive key for "same design" matching."""
    return " ".join(base_title(title).casefold().split())


@dataclass
class VersionRef:
    mockup_id: str
    number: int
    folded: bool


class UnknownParent(ValueError):
    """Raised when `parent` (an upload's target design) doesn't resolve."""


async def create_design(db: aiosqlite.Connection, *, project: str, title: str,
                        description: str | None, content_type: str, content: str,
                        tags: list[str]) -> VersionRef:
    """New design with its v1 at the pre-versions path `{slug}/{id}.{ext}`."""
    slug = slugify_project(project)
    mockup_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    file_path = write_mockup_file(slug, mockup_id, content_type, content)
    try:
        await queries.insert_mockup(
            db, id=mockup_id, project=project, project_slug=slug, title=title,
            description=description, content_type=content_type, file_path=file_path,
            tags=tags, created_at=now, updated_at=now)
    except Exception:
        delete_mockup_file(file_path)
        raise
    return VersionRef(mockup_id=mockup_id, number=1, folded=False)


async def add_version(db: aiosqlite.Connection, mockup_id: str, *, title: str,
                      description: str | None, content_type: str, content: str,
                      folded: bool = False) -> VersionRef:
    """Append a version. The file is written first and removed if the db write fails."""
    async with queries.transaction(db):
        # Read inside the transaction: the lock makes number + count race-free.
        design = await queries.get_mockup(db, mockup_id)
        if design is None:
            raise ValueError(f"Mockup not found: {mockup_id}")
        number = await queries.next_version_number(db, mockup_id)
        while True:
            # Exclusive create: a path can already be taken by a version that
            # moved here with a reused alias id (split). Skip to the next number.
            try:
                file_path = write_mockup_file(
                    design["project_slug"], mockup_id, content_type, content,
                    rel_path=version_rel_path(design["project_slug"], mockup_id, number,
                                              content_type),
                    exclusive=True)
                break
            except FileExistsError:
                number += 1
        try:
            existing = await queries.get_versions(db, mockup_id)
            await queries.insert_version(
                db, mockup_id=mockup_id, number=number, title=title, description=description,
                content_type=content_type, file_path=file_path,
                created_at=datetime.now(timezone.utc))
            if design["last_version_number"] == 1:
                # First time past v1: the design is now named for the series. A
                # design that ever had more versions keeps its (maybe manual) title.
                await queries.update_design_title(db, mockup_id, base_title(existing[-1]["title"]))
            await queries.refresh_design_mirror(db, mockup_id)
        except BaseException:
            delete_mockup_file(file_path)
            raise
    return VersionRef(mockup_id=mockup_id, number=number, folded=folded)


async def find_fold_target(db: aiosqlite.Connection, *, project_slug: str,
                           title: str) -> str | None:
    """The one design in the project with the same comparison key, else None."""
    key = comparison_key(title)
    matches = [d["id"] for d in await queries.list_design_titles(db, project_slug)
               if comparison_key(d["title"]) == key]
    return matches[0] if len(matches) == 1 else None


async def split_version(db: aiosqlite.Connection, mockup_id: str, number: int) -> str:
    """Make one version its own design (as v1). Returns the new design id.

    Reuses the id of an alias pinned to that version, so a folded-away id comes
    back as a normal design. The file is not moved.
    """
    async with queries.transaction(db):
        design = await queries.get_mockup(db, mockup_id)
        if design is None:
            raise ValueError(f"Mockup not found: {mockup_id}")
        version = await queries.get_version(db, mockup_id, number)
        if version is None:
            raise ValueError(f"Version not found: {mockup_id} v{number}")
        if design["version_count"] <= 1:
            raise ValueError("Cannot split the only version")
        aliases = await queries.list_aliases_for_version(db, mockup_id, number)
        new_id = aliases[0] if aliases else str(uuid.uuid4())
        if aliases:
            await queries.delete_alias(db, new_id)
        await queries.insert_design_row(
            db, id=new_id, project=design["project"], project_slug=design["project_slug"],
            title=version["title"], description=version["description"],
            content_type=version["content_type"], file_path=version["file_path"],
            tags=design["tags"], created_at=version["created_at"],
            updated_at=datetime.now(timezone.utc), latest_at=version["created_at"],
            version_count=1)
        # Remaining aliases on this version follow it to (new_id, 1).
        await queries.move_version(db, mockup_id, number, to_mockup_id=new_id, to_number=1)
        await queries.refresh_design_mirror(db, mockup_id)
    return new_id


async def delete_version(db: aiosqlite.Connection, mockup_id: str, number: int) -> None:
    """Delete one version (row, then file). The design keeps its other numbers."""
    async with queries.transaction(db):
        design = await queries.get_mockup(db, mockup_id)
        if design is None:
            raise ValueError(f"Mockup not found: {mockup_id}")
        version = await queries.get_version(db, mockup_id, number)
        if version is None:
            raise ValueError(f"Version not found: {mockup_id} v{number}")
        if design["version_count"] <= 1:
            raise ValueError("Cannot delete the only version; delete the mockup instead")
        await queries.delete_version_row(db, mockup_id, number)
        await queries.refresh_design_mirror(db, mockup_id)
    # After commit: a failed unlink leaves an orphan file, never a row without a file.
    delete_mockup_file(version["file_path"])


async def delete_design(db: aiosqlite.Connection, mockup_id: str) -> None:
    """Delete every version's file, then the design (cascade removes versions + aliases)."""
    if await queries.get_mockup(db, mockup_id) is None:
        raise ValueError(f"Mockup not found: {mockup_id}")
    for version in await queries.get_versions(db, mockup_id):
        delete_mockup_file(version["file_path"])
    await queries.delete_mockup(db, mockup_id)


async def set_version_created_at(db: aiosqlite.Connection, mockup_id: str, number: int,
                                 created_at: str) -> None:
    """Backdate/forward-date one version.

    `mockups.created_at` means "the design's first version's time", so touching
    the design's lowest-numbered version moves it too; touching any other
    version leaves it alone.
    """
    async with queries.transaction(db):
        design = await queries.get_mockup(db, mockup_id)
        if design is None:
            raise ValueError(f"Mockup not found: {mockup_id}")
        versions = await queries.get_versions(db, mockup_id)
        numbers = [v["number"] for v in versions]
        if number not in numbers:
            raise ValueError(f"Version not found: {mockup_id} v{number}")
        await queries.update_version_created_at(db, mockup_id, number, created_at)
        if number == min(numbers):
            await queries.update_design_created_at(db, mockup_id, created_at)
        await queries.refresh_design_mirror(db, mockup_id)


async def resolve(db: aiosqlite.Connection, id: str,
                  number: int | None = None) -> tuple[str, int] | None:
    """Map a design or alias id (plus optional version) to (design id, version number).

    An alias is pinned to one version, so an explicit number is ignored for it.
    """
    if await queries.get_mockup(db, id) is not None:
        if number is None:
            versions = await queries.get_versions(db, id)
            return (id, versions[0]["number"]) if versions else None
        return (id, number) if await queries.get_version(db, id, number) else None
    alias = await queries.get_alias(db, id)
    if alias is None:
        return None
    if await queries.get_version(db, alias["mockup_id"], alias["number"]) is None:
        return None
    return (alias["mockup_id"], alias["number"])
