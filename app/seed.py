import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.db import insert_mockup, list_mockups
from app.storage import write_mockup_file, slugify_project

GUIDE_PATH = Path(__file__).parent / "static" / "setup-guide.html"


async def seed_if_empty(db) -> None:
    """Insert the setup guide as the first mockup if DB is empty."""
    if os.environ.get("SKIP_SEED"):
        return
    existing = await list_mockups(db, limit=1, offset=0)
    if existing:
        return

    content = GUIDE_PATH.read_text(encoding="utf-8")
    project = "Mockups MPC"
    slug = slugify_project(project)
    mockup_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    file_path = write_mockup_file(slug, mockup_id, "html", content)
    await insert_mockup(
        db, id=mockup_id, project=project, project_slug=slug,
        title="Setup Guide", description="How to configure the MCP server in your AI tools",
        content_type="html", file_path=file_path,
        tags=["setup", "docs"], created_at=now, updated_at=now
    )
