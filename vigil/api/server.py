import asyncio
import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from vigil import __version__
from vigil.config import VigilConfig

log = logging.getLogger(__name__)

USE_DATABASE = os.getenv("VIGIL_USE_DATABASE", "false").lower() == "true"


def create_app(config: VigilConfig, orchestrator, provider=None) -> FastAPI:
    app = FastAPI(title="Vigil", version=__version__)

    # CORS: required for OPTIONS preflight on non-simple requests (e.g. JSON POST) when the
    # UI is served from another origin (Vite dev proxy is same-origin; direct :7420 + tools may not be).
    _cors = os.getenv("VIGIL_CORS_ORIGINS", "*")
    _origins = [o.strip() for o in _cors.split(",") if o.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if USE_DATABASE:
        from vigil.api.routes_v2 import router, set_context
        set_context(orchestrator, config)
        log.info("Using database-backed API routes")
    else:
        from vigil.api.routes import router, set_context
        set_context(orchestrator, config)
        log.info("Using file-backed API routes")

    app.include_router(router)

    from vigil.api.websocket import start_queue_consumer, websocket_endpoint
    app.add_api_websocket_route("/api/ws/live", websocket_endpoint)

    static_dir = Path(__file__).parent.parent.parent / "web" / "dist"
    if static_dir.exists():
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/favicon.svg")
        async def favicon():
            favicon_path = static_dir / "favicon.svg"
            if favicon_path.exists():
                return FileResponse(str(favicon_path))
            return FileResponse(str(static_dir / "index.html"))

        @app.get("/{full_path:path}")
        async def serve_spa(request: Request, full_path: str):
            if full_path.startswith("api/"):
                return {"detail": "Not Found"}
            return FileResponse(str(static_dir / "index.html"))
    else:
        log.info("No frontend build found at %s — API-only mode", static_dir)

    @app.on_event("startup")
    async def on_startup():
        if USE_DATABASE:
            from vigil.db.session import init_db
            await init_db()
            log.info("Database initialized")

            from vigil.api.routes_v2 import reconcile_startup_project
            await reconcile_startup_project()

        loop = asyncio.get_event_loop()
        start_queue_consumer(loop)

    @app.on_event("shutdown")
    async def on_shutdown():
        if USE_DATABASE:
            from vigil.db.session import get_db_manager
            db_manager = get_db_manager()
            if db_manager:
                await db_manager.close()

    return app


def start_server(config: VigilConfig, orchestrator, provider=None) -> None:
    app = create_app(config, orchestrator, provider)
    log.info("Starting API server on %s:%d", config.api.host, config.api.port)
    uvicorn.run(
        app,
        host=config.api.host,
        port=config.api.port,
        log_level="warning",
    )
