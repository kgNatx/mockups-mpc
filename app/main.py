from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.db import init_db
from app.mcp_server import mcp, register_tools

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    db = await init_db()
    app.state.db = db
    register_tools(lambda: app.state.db)
    yield
    await db.close()

mcp_app = mcp.http_app(path="/")

from fastmcp.utilities.lifespan import combine_lifespans
app = FastAPI(title="Mockups MPC", lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan))

app.mount("/mcp", mcp_app)

from app.routes.api import router as api_router
app.include_router(api_router)

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from app.routes.gallery import router as gallery_router

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(gallery_router)

@app.get("/health")
async def health():
    return {"status": "ok"}
