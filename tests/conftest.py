import os
import pytest
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from app import config

os.environ["SKIP_SEED"] = "1"

@pytest.fixture
def tmp_data_dir(tmp_path):
    config.DATA_DIR = tmp_path
    config.DB_PATH = tmp_path / "mockups.db"
    return tmp_path

@pytest.fixture
async def client(tmp_data_dir):
    from app.main import app, app_lifespan
    # Use only app_lifespan (db init + tool registration) without the MCP
    # transport lifespan, which spins up anyio task groups incompatible
    # with pytest-asyncio fixture teardown.
    async with app_lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
