"""DeepField — Fleet-scale OpenShift signal intelligence and inference benchmarking."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.runs import router as runs_router
from app.api.session import router as session_router
from app.api.ws import router as ws_router
from app.api.sse import router as sse_router
from app.api.demo import router as demo_router
from app.api.observatory import router as observatory_router
from app.api.remediation import router as remediation_router
from app.api.integration import router as integration_router
from app.api.metrics import router as metrics_router

app = FastAPI(
    title="DeepField",
    description="Fleet-scale OpenShift signal intelligence and inference benchmarking platform",
    version="0.1.0",
)

cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3100").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)

app.include_router(runs_router)
app.include_router(session_router)
app.include_router(ws_router)
app.include_router(sse_router)
app.include_router(demo_router)
app.include_router(observatory_router)
app.include_router(remediation_router)
app.include_router(integration_router)
app.include_router(metrics_router)


@app.on_event("startup")
async def startup():
    from app.db import init_db
    try:
        await init_db()
    except Exception:
        pass

    from app.api.session import start_live_monitoring
    try:
        start_live_monitoring()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Live monitoring startup failed: %s", e)


@app.on_event("shutdown")
async def shutdown():
    from app.db import close_db
    await close_db()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "deepfield"}


STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")
    app.mount("/logos", StaticFiles(directory=str(STATIC_DIR / "logos")), name="logos")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        file_path = STATIC_DIR / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
