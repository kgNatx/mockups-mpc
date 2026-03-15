import pytest
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from app import config

@pytest.fixture
def tmp_data_dir(tmp_path):
    config.DATA_DIR = tmp_path
    config.DB_PATH = tmp_path / "mockups.db"
    return tmp_path

@pytest.fixture
async def client(tmp_data_dir):
    from app.main import app
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
