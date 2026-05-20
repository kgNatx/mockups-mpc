import json
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
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mockups_project_slug ON mockups(project_slug);
CREATE INDEX IF NOT EXISTS idx_mockups_created_at ON mockups(created_at);
"""


async def _migrate_favorite_column(db: aiosqlite.Connection) -> None:
    """Add the favorite column to databases created before it existed."""
    cursor = await db.execute("PRAGMA table_info(mockups)")
    cols = {row["name"] for row in await cursor.fetchall()}
    if "favorite" not in cols:
        await db.execute("ALTER TABLE mockups ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
        await db.commit()
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mockups_favorite ON mockups(favorite)")
    await db.commit()


async def init_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(get_db_path()))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(CREATE_TABLE)
    await db.commit()
    await _migrate_favorite_column(db)
    return db


async def insert_mockup(db: aiosqlite.Connection, *, id: str, project: str,
                         project_slug: str, title: str, description: str | None,
                         content_type: str, file_path: str, tags: list[str],
                         created_at: datetime, updated_at: datetime) -> None:
    await db.execute(
        """INSERT INTO mockups (id, project, project_slug, title, description,
           content_type, file_path, tags, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, project, project_slug, title, description, content_type,
         file_path, json.dumps(tags), created_at.isoformat(), updated_at.isoformat())
    )
    await db.commit()


async def get_mockup(db: aiosqlite.Connection, mockup_id: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM mockups WHERE id = ?", (mockup_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


_SORT_ORDERS = {
    "newest": "created_at DESC",
    "oldest": "created_at ASC",
    "favorites": "favorite DESC, created_at DESC",
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
        conditions.append("(title LIKE ? OR description LIKE ? OR tags LIKE ?)")
        params.extend([like, like, like])

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
           FROM mockups GROUP BY project_slug ORDER BY count DESC, project"""
    )
    return [dict(row) for row in await cursor.fetchall()]


_UNSET = object()


async def update_mockup(db: aiosqlite.Connection, mockup_id: str, *,
                         title: str | None = None, description=_UNSET,
                         tags: list[str] | None = None, file_path: str | None = None,
                         content_type: str | None = None,
                         created_at: str | None = None) -> bool:
    sets = []
    params = []
    if title is not None:
        sets.append("title = ?")
        params.append(title)
    if description is not _UNSET:
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
    cursor = await db.execute(
        f"UPDATE mockups SET {', '.join(sets)} WHERE id = ?", params
    )
    await db.commit()
    return cursor.rowcount > 0


async def set_favorite(db: aiosqlite.Connection, mockup_id: str, value: bool) -> bool:
    cursor = await db.execute(
        "UPDATE mockups SET favorite = ?, updated_at = ? WHERE id = ?",
        (1 if value else 0, datetime.now(timezone.utc).isoformat(), mockup_id)
    )
    await db.commit()
    return cursor.rowcount > 0


async def count_favorites(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COUNT(*) AS n FROM mockups WHERE favorite = 1")
    row = await cursor.fetchone()
    return row["n"]


async def delete_mockup(db: aiosqlite.Connection, mockup_id: str) -> bool:
    cursor = await db.execute("DELETE FROM mockups WHERE id = ?", (mockup_id,))
    await db.commit()
    return cursor.rowcount > 0


def _row_to_dict(row: aiosqlite.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"]) if d["tags"] else []
    return d
