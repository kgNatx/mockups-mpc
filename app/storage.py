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


def version_rel_path(project_slug: str, mockup_id: str, number: int, content_type: str) -> str:
    return f"{project_slug}/{mockup_id}/v{number}.{content_type}"


def write_mockup_file(project_slug: str, mockup_id: str, content_type: str, content: str,
                      *, rel_path: str | None = None, exclusive: bool = False) -> str:
    """Write content to rel_path, or to the v1 layout `{slug}/{id}.{ext}` when omitted.

    With exclusive=True an existing file is never overwritten: FileExistsError instead.
    """
    if content_type not in VALID_TYPES:
        raise ValueError(f"Invalid content_type: {content_type!r}")

    data_dir = get_data_dir()
    if rel_path is None:
        rel_path = f"{project_slug}/{mockup_id}.{content_type}"
    full_path = data_dir / rel_path

    if content_type in TEXT_TYPES:
        data = content.encode("utf-8")
    else:
        data = base64.b64decode(content)
    if len(data) > MAX_CONTENT_SIZE:
        raise ValueError(f"Content too large: {len(data)} bytes (max {MAX_CONTENT_SIZE})")
    full_path.parent.mkdir(parents=True, exist_ok=True)
    with open(full_path, "xb" if exclusive else "wb") as f:
        try:
            f.write(data)
        except BaseException:
            # Never leave a truncated file behind. Only after open() succeeded:
            # an exclusive open that raised FileExistsError names someone else's file.
            f.close()
            full_path.unlink(missing_ok=True)
            raise

    return rel_path


def delete_mockup_file(rel_path: str) -> None:
    full_path = get_data_dir() / rel_path
    if full_path.exists():
        full_path.unlink()
    # A `{slug}/{id}/` version directory goes once its last file does.
    if len(Path(rel_path).parts) == 3 and full_path.parent.is_dir() \
            and not any(full_path.parent.iterdir()):
        full_path.parent.rmdir()
