"""Scanner-only FastAPI entry for isolated scanner work.

The deployed application uses app.backend.main:app. This optional entry
mounts only health/scanner routes and does not exercise Analyze or the
LangGraph investment workflow. It is not proof that the full backend fails.
"""

from __future__ import annotations

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# Lazy / sidestep imports — avoid touching routes/__init__.py
from app.backend.database.connection import SessionLocal, engine
from app.backend.database.models import Base
from app.backend.repositories.scanner_repository import ScanRunRepository
from app.backend.routes.health import router as health_router
from app.backend.routes.scanner import router as scanner_router
from app.backend.services.scan_broadcaster import get_broadcaster
from app.backend.services.scanner_service import ScannerService
from app.backend.services.scheduler_service import init_scheduler_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Hedge Fund — Scanner only",
    description="Slim entrypoint that mounts only /scanner/* and /ping (no v1 LLM routes)",
    version="0.1.0",
)

Base.metadata.create_all(bind=engine)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, tags=["health"])
app.include_router(scanner_router, tags=["scanner"])

_scanner_service = ScannerService(SessionLocal, broadcaster=get_broadcaster())
_scheduler_service = init_scheduler_service(SessionLocal, _scanner_service)


@app.on_event("startup")
async def startup_event() -> None:
    try:
        with SessionLocal() as session:
            runs = ScanRunRepository(session)
            stale = runs.list_running()
            for run in stale:
                runs.mark_error(run.id, "interrupted at startup")
            if stale:
                logger.info("Marked %d stale RUNNING scan(s) as ERROR", len(stale))
    except Exception as e:
        logger.warning("Stale-run cleanup failed: %s", e)
    try:
        _scheduler_service.start()
    except Exception as e:
        logger.exception("Failed to start scheduler: %s", e)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    try:
        _scheduler_service.shutdown(wait=False)
    except Exception as e:
        logger.warning("Scheduler shutdown raised: %s", e)
