import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "mockups.db"
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


def _read_version() -> str:
    # Resolves to the repo-root VERSION in dev/tests and /app/VERSION in the
    # container (the Dockerfile copies it). Used to cache-bust static assets.
    try:
        return (Path(__file__).parent.parent / "VERSION").read_text().strip() or "dev"
    except OSError:
        return "dev"


APP_VERSION = _read_version()

def get_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR

def get_db_path() -> Path:
    get_data_dir()
    return DB_PATH
