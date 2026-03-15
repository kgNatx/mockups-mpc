import base64
import re
from pathlib import Path

from app.config import get_data_dir

MAX_CONTENT_SIZE = 25 * 1024 * 1024  # 25 MB

TEXT_TYPES = {"html", "svg"}
BINARY_TYPES = {"png", "jpg"}
VALID_TYPES = TEXT_TYPES | BINARY_TYPES


def slugify_project(name: str) -> str:
    if ".." in name or name.startswith("/"):
        raise ValueError(f"Invalid project name: {name!r}")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower())
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError(f"Project name produces empty slug: {name!r}")
    return slug


def write_mockup_file(project_slug: str, mockup_id: str, content_type: str, content: str) -> str:
    if content_type not in VALID_TYPES:
        raise ValueError(f"Invalid content_type: {content_type!r}")

    data_dir = get_data_dir()
    project_dir = data_dir / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)

    rel_path = f"{project_slug}/{mockup_id}.{content_type}"
    full_path = data_dir / rel_path

    if content_type in TEXT_TYPES:
        data = content.encode("utf-8")
        if len(data) > MAX_CONTENT_SIZE:
            raise ValueError(f"Content too large: {len(data)} bytes (max {MAX_CONTENT_SIZE})")
        full_path.write_bytes(data)
    else:
        data = base64.b64decode(content)
        if len(data) > MAX_CONTENT_SIZE:
            raise ValueError(f"Content too large: {len(data)} bytes (max {MAX_CONTENT_SIZE})")
        full_path.write_bytes(data)

    return rel_path


def delete_mockup_file(rel_path: str) -> None:
    full_path = get_data_dir() / rel_path
    if full_path.exists():
        full_path.unlink()
