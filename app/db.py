import asyncio
import json
import weakref
from contextlib import asynccontextmanager
import aiosqlite
from datetime import datetime, timezone
from app.config import get_db_path

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS mockups (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    project_slug TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    content_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    favorite INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    latest_at TEXT NOT NULL DEFAULT '',
    version_count INTEGER NOT NULL DEFAULT 1,
    last_version_number INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_mockups_project_slug ON mockups(project_slug);
CREATE INDEX IF NOT EXISTS idx_mockups_created_at ON mockups(created_at);
"""

CREATE_VERSION_TABLES = """
CREATE TABLE IF NOT EXISTS mockup_versions (
    mockup_id TEXT NOT NULL REFERENCES mockups(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    content_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (mockup_id, number)
);
CREATE TABLE IF NOT EXISTS mockup_aliases (
    alias_id TEXT PRIMARY KEY,
    mockup_id TEXT NOT NULL REFERENCES mockups(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    source_number INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mockup_aliases_target ON mockup_aliases(mockup_id, number);
"""

# The app shares one connection across coroutines, so BEGIN IMMEDIATE alone does
# not isolate them: another coroutine's statements would join the open
# transaction. Every write therefore holds this per-connection lock.
#
# The lock is NOT re-entrant: calling transaction(), or a helper that opens one
# (insert_mockup, update_mockup, set_favorite), from inside
# transaction() deadlocks. Inside a transaction use only the non-committing
# helpers below.
#
# Reads do not take the lock. A read on the shared connection while another
# coroutine's transaction is open sees that transaction's uncommitted rows, which
# vanish if it rolls back. Any read that decides a write must therefore run
# inside the same transaction() as the write.
_locks: "weakref.WeakKeyDictionary[aiosqlite.Connection, asyncio.Lock]" = weakref.WeakKeyDictionary()


@asynccontextmanager
async def transaction(db: aiosqlite.Connection):
    """Serialise a write: lock, BEGIN IMMEDIATE, COMMIT (ROLLBACK on exception)."""
    lock = _locks.setdefault(db, asyncio.Lock())
    async with lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            # Inside the try: a failed COMMIT must roll back too, or the
            # connection stays in an open transaction after the lock is released.
            await db.commit()
        except BaseException:
            await db.rollback()
            raise


async def _migrate_favorite_column(db: aiosqlite.Connection) -> None:
    """Add the favorite column to databases created before it existed."""
    cursor = await db.execute("PRAGMA table_info(mockups)")
    cols = {row["name"] for row in await cursor.fetchall()}
    if "favorite" not in cols:
        await db.execute("ALTER TABLE mockups ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mockups_favorite ON mockups(favorite)")
    await db.commit()


async def _migrate_versions(db: aiosqlite.Connection) -> None:
    """Give every pre-1.5 mockup a v1 row and the design columns. Idempotent."""
    await db.executescript(CREATE_VERSION_TABLES)
    cursor = await db.execute("PRAGMA table_info(mockups)")
    cols = {row["name"] for row in await cursor.fetchall()}
    cursor = await db.execute("PRAGMA table_info(mockup_aliases)")
    alias_cols = {row["name"] for row in await cursor.fetchall()}
    async with transaction(db):
        if "source_number" not in alias_cols:
            await db.execute("ALTER TABLE mockup_aliases ADD COLUMN source_number INTEGER")
        # SQLite needs a DEFAULT to add a NOT NULL column; the backfill below
        # replaces the '' placeholder.
        if "latest_at" not in cols:
            await db.execute("ALTER TABLE mockups ADD COLUMN latest_at TEXT NOT NULL DEFAULT ''")
        if "version_count" not in cols:
            await db.execute("ALTER TABLE mockups ADD COLUMN version_count INTEGER NOT NULL DEFAULT 1")
        if "last_version_number" not in cols:
            await db.execute(
                "ALTER TABLE mockups ADD COLUMN last_version_number INTEGER NOT NULL DEFAULT 1")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_mockups_latest_at ON mockups(latest_at)")
        # Titles are copied, not rewritten: base-title normalisation is fold-only.
        await db.execute(
            """INSERT INTO mockup_versions (mockup_id, number, title, description,
               content_type, file_path, created_at)
               SELECT id, 1, title, description, content_type, file_path, created_at
               FROM mockups m
               WHERE NOT EXISTS (SELECT 1 FROM mockup_versions v WHERE v.mockup_id = m.id)""")
        await db.execute("UPDATE mockups SET latest_at = created_at WHERE latest_at = ''")
        await db.execute(
            """UPDATE mockups SET last_version_number = (
                   SELECT MAX(number) FROM mockup_versions v WHERE v.mockup_id = mockups.id)
               WHERE last_version_number < (
                   SELECT MAX(number) FROM mockup_versions v WHERE v.mockup_id = mockups.id)""")


async def init_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(get_db_path()))
    db.row_factory = aiosqlite.Row
    # Off by default in SQLite; ON DELETE CASCADE on versions/aliases needs it.
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA journal_mode=WAL")
    # Wait up to 5s for a lock rather than failing immediately, so the single-
    # connection assumption stays robust if a second connection ever appears.
    await db.execute("PRAGMA busy_timeout=5000")
    await db.executescript(CREATE_TABLE)
    await db.commit()
    await _migrate_favorite_column(db)
    await _migrate_versions(db)
    return db


def _ts(value: datetime | str) -> str:
    return value.isoformat() if isinstance(value, datetime) else value


async def insert_mockup(db: aiosqlite.Connection, *, id: str, project: str,
                         project_slug: str, title: str, description: str | None,
                         content_type: str, file_path: str, tags: list[str],
                         created_at: datetime, updated_at: datetime) -> None:
    """Insert a design and its v1 in one transaction."""
    async with transaction(db):
        await insert_design_row(
            db, id=id, project=project, project_slug=project_slug, title=title,
            description=description, content_type=content_type, file_path=file_path,
            tags=tags, created_at=created_at, updated_at=updated_at,
            latest_at=created_at, version_count=1)
        await insert_version(
            db, mockup_id=id, number=1, title=title, description=description,
            content_type=content_type, file_path=file_path, created_at=created_at)


# --- Helpers below do not commit: call them inside `async with transaction(db)`. ---

async def insert_design_row(db: aiosqlite.Connection, *, id: str, project: str,
                            project_slug: str, title: str, description: str | None,
                            content_type: str, file_path: str, tags: list[str],
                            created_at: datetime | str, updated_at: datetime | str,
                            latest_at: datetime | str, version_count: int) -> None:
    await db.execute(
        """INSERT INTO mockups (id, project, project_slug, title, description,
           content_type, file_path, tags, created_at, updated_at, latest_at, version_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, project, project_slug, title, description, content_type, file_path,
         json.dumps(tags), _ts(created_at), _ts(updated_at), _ts(latest_at), version_count)
    )


async def insert_version(db: aiosqlite.Connection, *, mockup_id: str, number: int,
                         title: str, description: str | None, content_type: str,
                         file_path: str, created_at: datetime | str) -> None:
    await db.execute(
        """INSERT INTO mockup_versions (mockup_id, number, title, description,
           content_type, file_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (mockup_id, number, title, description, content_type, file_path, _ts(created_at))
    )
    # High-water mark: numbers are never reused, even after the top one is
    # deleted or split away.
    await db.execute(
        "UPDATE mockups SET last_version_number = MAX(last_version_number, ?) WHERE id = ?",
        (number, mockup_id)
    )


async def next_version_number(db: aiosqlite.Connection, mockup_id: str) -> int:
    cursor = await db.execute(
        """SELECT MAX(m.last_version_number,
                      COALESCE((SELECT MAX(number) FROM mockup_versions v
                                WHERE v.mockup_id = m.id), 0)) + 1 AS n
           FROM mockups m WHERE m.id = ?""",
        (mockup_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        raise ValueError(f"Mockup not found: {mockup_id}")
    return int(row["n"])


async def update_design_title(db: aiosqlite.Connection, mockup_id: str, title: str) -> None:
    await db.execute("UPDATE mockups SET title = ? WHERE id = ?", (title, mockup_id))


async def update_design_fields(db: aiosqlite.Connection, mockup_id: str, *,
                               title: str | None = None, tags: list[str] | None = None,
                               favorite: bool | None = None) -> None:
    """Non-committing metadata update for a caller already inside transaction()

    (e.g. fold, which sets a survivor's title/tags/favorite alongside its own
    version writes). update_mockup() commits on its own and cannot be reused there.
    """
    sets = []
    params = []
    if title is not None:
        sets.append("title = ?")
        params.append(title)
    if tags is not None:
        sets.append("tags = ?")
        params.append(json.dumps(tags))
    if favorite is not None:
        sets.append("favorite = ?")
        params.append(1 if favorite else 0)
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    params.append(mockup_id)
    await db.execute(f"UPDATE mockups SET {', '.join(sets)} WHERE id = ?", params)


async def update_version_created_at(db: aiosqlite.Connection, mockup_id: str, number: int,
                                    created_at: datetime | str) -> None:
    await db.execute(
        "UPDATE mockup_versions SET created_at = ? WHERE mockup_id = ? AND number = ?",
        (_ts(created_at), mockup_id, number))


async def update_version_description(db: aiosqlite.Connection, mockup_id: str, number: int,
                                     description: str | None) -> None:
    await db.execute(
        "UPDATE mockup_versions SET description = ? WHERE mockup_id = ? AND number = ?",
        (description, mockup_id, number))


async def refresh_design_mirror(db: aiosqlite.Connection, mockup_id: str) -> None:
    """Copy the highest-numbered version onto the design row; recount versions.

    created_at comes from the lowest-numbered version: it means "the design's
    first version's time", which moves when v1 is split out or deleted.
    """
    latest = """(SELECT {col} FROM mockup_versions v WHERE v.mockup_id = mockups.id
                 ORDER BY number DESC LIMIT 1)"""
    first_created_at = """(SELECT created_at FROM mockup_versions v WHERE v.mockup_id = mockups.id
                           ORDER BY number ASC LIMIT 1)"""
    await db.execute(
        f"""UPDATE mockups SET
               created_at = {first_created_at},
               description = {latest.format(col="description")},
               content_type = {latest.format(col="content_type")},
               file_path = {latest.format(col="file_path")},
               latest_at = {latest.format(col="created_at")},
               version_count = (SELECT COUNT(*) FROM mockup_versions v
                                WHERE v.mockup_id = mockups.id),
               updated_at = ?
           WHERE id = ?""",
        (datetime.now(timezone.utc).isoformat(), mockup_id)
    )


async def delete_version_row(db: aiosqlite.Connection, mockup_id: str, number: int) -> None:
    """Delete one version and any alias pinned to it (it would point at nothing)."""
    await db.execute("DELETE FROM mockup_aliases WHERE mockup_id = ? AND number = ?",
                     (mockup_id, number))
    await db.execute("DELETE FROM mockup_versions WHERE mockup_id = ? AND number = ?",
                     (mockup_id, number))


async def move_version(db: aiosqlite.Connection, mockup_id: str, number: int, *,
                       to_mockup_id: str, to_number: int) -> None:
    """Re-parent a version row, and re-point aliases pinned to it.

    An alias keeps its source_number, so a link minted before the move still resolves.
    """
    await db.execute(
        "UPDATE mockup_versions SET mockup_id = ?, number = ? WHERE mockup_id = ? AND number = ?",
        (to_mockup_id, to_number, mockup_id, number))
    await db.execute(
        "UPDATE mockup_aliases SET mockup_id = ?, number = ? WHERE mockup_id = ? AND number = ?",
        (to_mockup_id, to_number, mockup_id, number))
    await db.execute(
        "UPDATE mockups SET last_version_number = MAX(last_version_number, ?) WHERE id = ?",
        (to_number, to_mockup_id))


async def insert_alias(db: aiosqlite.Connection, *, alias_id: str, mockup_id: str,
                       number: int, source_number: int | None = None) -> None:
    """`source_number` is the version number the alias id had as a design (fold)."""
    await db.execute(
        "INSERT INTO mockup_aliases (alias_id, mockup_id, number, source_number) "
        "VALUES (?, ?, ?, ?)",
        (alias_id, mockup_id, number, source_number))


async def delete_alias(db: aiosqlite.Connection, alias_id: str) -> None:
    await db.execute("DELETE FROM mockup_aliases WHERE alias_id = ?", (alias_id,))


async def delete_design_row(db: aiosqlite.Connection, mockup_id: str) -> None:
    """Non-committing design-row delete for a caller already inside transaction()

    (fold, after re-parenting the design's version elsewhere; versioning's
    delete_design). Cascade
    removes any of its own versions/aliases still pointing at it; a version or
    alias already re-parented onto another design is untouched (its mockup_id
    no longer matches).
    """
    await db.execute("DELETE FROM mockups WHERE id = ?", (mockup_id,))


# --- Reads ---

async def get_versions(db: aiosqlite.Connection, mockup_id: str) -> list[dict]:
    """All versions of a design, newest (highest number) first."""
    cursor = await db.execute(
        "SELECT * FROM mockup_versions WHERE mockup_id = ? ORDER BY number DESC", (mockup_id,))
    return [dict(row) for row in await cursor.fetchall()]


async def get_version(db: aiosqlite.Connection, mockup_id: str, number: int) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM mockup_versions WHERE mockup_id = ? AND number = ?", (mockup_id, number))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_alias(db: aiosqlite.Connection, alias_id: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM mockup_aliases WHERE alias_id = ?", (alias_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_aliases_for_version(db: aiosqlite.Connection, mockup_id: str,
                                   number: int) -> list[str]:
    cursor = await db.execute(
        "SELECT alias_id FROM mockup_aliases WHERE mockup_id = ? AND number = ? ORDER BY alias_id",
        (mockup_id, number))
    return [row["alias_id"] for row in await cursor.fetchall()]


async def list_single_version_designs(db: aiosqlite.Connection) -> list[dict]:
    """Designs with exactly one version, oldest first (the fold command's candidates)."""
    cursor = await db.execute(
        "SELECT id, project_slug, title, created_at FROM mockups "
        "WHERE version_count = 1 ORDER BY created_at ASC")
    return [dict(row) for row in await cursor.fetchall()]


async def list_design_titles(db: aiosqlite.Connection, project_slug: str) -> list[dict]:
    cursor = await db.execute(
        "SELECT id, title FROM mockups WHERE project_slug = ?", (project_slug,))
    return [dict(row) for row in await cursor.fetchall()]


async def get_mockup(db: aiosqlite.Connection, mockup_id: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM mockups WHERE id = ?", (mockup_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


# `id` breaks ties, so equal timestamps order the same under every
# LIMIT/OFFSET: scroll pages neither repeat nor skip rows, and the gallery's
# poll probe (one query over all loaded rows) matches the pages it compares to.
_SORT_ORDERS = {
    "newest": "latest_at DESC, id",
    "oldest": "created_at ASC, id",
    "favorites": "favorite DESC, latest_at DESC, id",
}


async def list_mockups(db: aiosqlite.Connection, *, project_slug: str | None = None,
                        q: str | None = None, sort: str = "newest",
                        favorites_only: bool = False,
                        limit: int = 50, offset: int = 0) -> list[dict]:
    conditions = []
    params: list = []
    if project_slug:
        conditions.append("project_slug = ?")
        params.append(project_slug)
    if favorites_only:
        conditions.append("favorite = 1")
    if q:
        like = f"%{q}%"
        # Version titles too: a folded design is findable by any draft's title.
        conditions.append(
            "(title LIKE ? OR description LIKE ? OR tags LIKE ? OR EXISTS ("
            "SELECT 1 FROM mockup_versions v WHERE v.mockup_id = mockups.id AND v.title LIKE ?))")
        params.extend([like, like, like, like])

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order = _SORT_ORDERS.get(sort, _SORT_ORDERS["newest"])
    params.extend([limit, offset])

    cursor = await db.execute(
        f"SELECT * FROM mockups {where} ORDER BY {order} LIMIT ? OFFSET ?", params
    )
    return [_row_to_dict(row) for row in await cursor.fetchall()]


async def list_projects(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        """SELECT project, project_slug, COUNT(*) as count
           FROM mockups GROUP BY project_slug ORDER BY MAX(latest_at) DESC, project"""
    )
    return [dict(row) for row in await cursor.fetchall()]


# Shared sentinel distinguishing "leave description unchanged" (UNSET) from
# "set description to NULL" (None). Public because callers across module
# boundaries must pass the same object to preserve the distinction.
UNSET = object()


async def update_mockup(db: aiosqlite.Connection, mockup_id: str, *,
                         title: str | None = None, description=UNSET,
                         tags: list[str] | None = None, file_path: str | None = None,
                         content_type: str | None = None,
                         created_at: str | None = None) -> bool:
    """Direct design-row write, no version logic. The app writes through
    versioning; tests use this to set up rows (e.g. a backdated created_at)."""
    sets = []
    params = []
    if title is not None:
        sets.append("title = ?")
        params.append(title)
    if description is not UNSET:
        sets.append("description = ?")
        params.append(description)
    if tags is not None:
        sets.append("tags = ?")
        params.append(json.dumps(tags))
    if file_path is not None:
        sets.append("file_path = ?")
        params.append(file_path)
    if content_type is not None:
        sets.append("content_type = ?")
        params.append(content_type)
    if created_at is not None:
        sets.append("created_at = ?")
        params.append(created_at)
    if not sets:
        return False
    sets.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    params.append(mockup_id)
    async with transaction(db):
        cursor = await db.execute(
            f"UPDATE mockups SET {', '.join(sets)} WHERE id = ?", params
        )
    return cursor.rowcount > 0


async def set_favorite(db: aiosqlite.Connection, mockup_id: str, value: bool) -> bool:
    async with transaction(db):
        cursor = await db.execute(
            "UPDATE mockups SET favorite = ?, updated_at = ? WHERE id = ?",
            (1 if value else 0, datetime.now(timezone.utc).isoformat(), mockup_id)
        )
    return cursor.rowcount > 0


async def count_favorites(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COUNT(*) AS n FROM mockups WHERE favorite = 1")
    row = await cursor.fetchone()
    return int(row["n"])


def _row_to_dict(row: aiosqlite.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"]) if d["tags"] else []
    return d
