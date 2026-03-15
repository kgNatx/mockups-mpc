import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "mockups.db"
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

def get_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR

def get_db_path() -> Path:
    get_data_dir()
    return DB_PATH
