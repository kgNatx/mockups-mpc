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
    """Add the shipped setup guide as a new version when the stored one differs.

    seed_if_empty writes the guide only into an empty gallery, so without this
    an existing install keeps the guide from its first boot forever. Only the
    one design titled "Setup Guide" in the "Mockups MPC" project is touched: a
    deleted guide stays deleted, and a renamed or duplicated one is left alone.
    """
    if os.environ.get("SKIP_SEED"):
        return
    matches = [d["id"] for d in await list_design_titles(db, slugify_project(GUIDE_PROJECT))
               if d["title"] == GUIDE_TITLE]
    if len(matches) != 1:
        return
    guide_id = matches[0]
    shipped = GUIDE_PATH.read_text(encoding="utf-8")
    latest = (await get_versions(db, guide_id))[0]
    stored_path = get_data_dir() / latest["file_path"]
    if stored_path.exists() and stored_path.read_text(encoding="utf-8") == shipped:
        return
    await versioning.add_version(
        db, guide_id, title=GUIDE_TITLE, description=latest["description"],
        content_type="html", content=shipped)
