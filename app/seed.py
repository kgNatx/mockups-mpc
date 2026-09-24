import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app import versioning
from app.config import get_data_dir
from app.db import get_versions, insert_mockup, list_design_titles, list_mockups
from app.storage import write_mockup_file, slugify_project, delete_mockup_file

GUIDE_PATH = Path(__file__).parent / "static" / "setup-guide.html"
GUIDE_PROJECT = "Mockups MPC"
GUIDE_TITLE = "Setup Guide"
# In the shipped guide's <head>: marks a stored version as one this app wrote.
GUIDE_MARKER = b'<meta name="mockups-mpc-guide"'

logger = logging.getLogger(__name__)


async def seed_if_empty(db) -> None:
    """Insert the setup guide as the first mockup if DB is empty."""
    if os.environ.get("SKIP_SEED"):
        return
    existing = await list_mockups(db, limit=1, offset=0)
    if existing:
        return

    content = GUIDE_PATH.read_text(encoding="utf-8")
    project = GUIDE_PROJECT
    slug = slugify_project(project)
    mockup_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    file_path = write_mockup_file(slug, mockup_id, "html", content)
    try:
        await insert_mockup(
            db, id=mockup_id, project=project, project_slug=slug,
            title=GUIDE_TITLE, description="How to configure the MCP server in your AI tools",
            content_type="html", file_path=file_path,
            tags=["setup", "docs"], created_at=now, updated_at=now
        )
    except Exception:
        delete_mockup_file(file_path)
        raise


async def refresh_guide(db) -> None:
    """Best-effort: never let the guide refresh stop the app from starting."""
    try:
        await _refresh_guide(db)
    except Exception:
        logger.warning("Setup Guide refresh skipped", exc_info=True)


async def _refresh_guide(db) -> None:
    """Add the shipped setup guide as a new version when the stored one is stale.

    seed_if_empty writes the guide only into an empty gallery, so without this
    an existing install keeps the guide from its first boot forever. Only the
    one design titled "Setup Guide" in the "Mockups MPC" project is touched: a
    deleted guide stays deleted, and a renamed or duplicated one is left alone.

    The stored latest is replaced only when it is a guide this app shipped:
    it carries GUIDE_MARKER, or it is the design's only version (a guide seeded
    before the marker existed). A version the user added on top is kept.

    The reads below decide the write outside a transaction (project rule:
    they belong inside one). That is safe only because this runs once, in the
    startup lifespan, before the app serves requests, in a single process;
    add_version still re-checks that the design exists under the lock.
    """
    if os.environ.get("SKIP_SEED"):
        return
    matches = [d["id"] for d in await list_design_titles(db, slugify_project(GUIDE_PROJECT))
               if d["title"] == GUIDE_TITLE]
    if len(matches) != 1:
        return
    guide_id = matches[0]
    shipped = GUIDE_PATH.read_bytes()
    versions = await get_versions(db, guide_id)
    latest = versions[0]
    stored_path = get_data_dir() / latest["file_path"]
    stored = stored_path.read_bytes() if stored_path.exists() else b""
    if stored == shipped:
        return
    if GUIDE_MARKER not in stored and len(versions) > 1:
        return  # the user's own version on top: leave it
    await versioning.add_version(
        db, guide_id, title=GUIDE_TITLE, description=latest["description"],
        content_type="html", content=shipped.decode("utf-8"))
