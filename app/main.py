from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.db import init_db
from app.mcp_server import mcp, register_tools
from app.seed import seed_if_empty

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    db = await init_db()
    app.state.db = db
    register_tools(lambda: app.state.db)
    await seed_if_empty(db)
    yield
    await db.close()

# Mount both transports: HTTP (streamable) for Claude Code, SSE for Claude Desktop
mcp_http = mcp.http_app(path="/", transport="http")
mcp_sse = mcp.http_app(path="/", transport="sse")

from fastmcp.utilities.lifespan import combine_lifespans
app = FastAPI(title="Mockups MPC", lifespan=combine_lifespans(app_lifespan, mcp_http.lifespan))

# SSE mount must come first (longer prefix match) — /mcp/sse/sse is the SSE endpoint, /mcp/sse/messages/ is the POST endpoint
# HTTP mount at /mcp — /mcp/mcp is the streamable HTTP endpoint
app.mount("/mcp/sse", mcp_sse)
app.mount("/mcp", mcp_http)

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
