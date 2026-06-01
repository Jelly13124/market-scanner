from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import logging
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.backend.rate_limit import limiter
from app.backend.routes import api_router
from app.backend.database.connection import SessionLocal, engine
from app.backend.database.models import Base
from app.backend.repositories.scanner_repository import ScanRunRepository
from app.backend.services.ollama_service import ollama_service
from app.backend.services.scan_broadcaster import get_broadcaster
from app.backend.services.scanner_service import ScannerService
from app.backend.services.scheduler_service import init_scheduler_service

# Load .env for API keys (scanner providers, etc.) before any service init.
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def mount_spa(app, dist_dir: Path) -> None:
    """Serve a built Vite SPA from FastAPI (single-origin deploy).

    Mounts ``dist_dir/assets`` under ``/assets`` and registers a catch-all that
    returns ``index.html`` for any path not already claimed by an API router.
    Because FastAPI matches routes in registration order, this MUST be called
    AFTER ``app.include_router(api_router)`` so API routes win and are never
    shadowed by the SPA fallback.

    No-op when no build is present (dev / tests): if ``dist_dir`` is missing or
    has no ``index.html``, nothing is mounted and the app stays API-only.
    """
    if not dist_dir.is_dir() or not (dist_dir / "index.html").exists():
        return  # no build present (dev/tests) -> skip, API-only

    assets = dist_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    index = dist_dir / "index.html"

    # "/" -> index.html
    @app.get("/")
    def _spa_root():
        return FileResponse(str(index))

    # client-side route -> index.html. API routes (registered earlier) already won.
    @app.get("/{full_path:path}")
    def _spa(full_path: str):
        return FileResponse(str(index))

# JWT secret guard. The signing default lives in auth/security.py; here we just
# warn (dev) or hard-fail (prod) when the operator hasn't overridden it via
# JWT_SECRET, so an insecure default never silently ships to production.
if not os.getenv("JWT_SECRET"):
    logger.warning("JWT_SECRET not set — using an insecure dev default; set it before deploying.")
    if os.getenv("ENVIRONMENT", "").lower() == "production":
        raise RuntimeError("JWT_SECRET must be set in production")

app = FastAPI(title="AI Hedge Fund API", description="Backend API for AI Hedge Fund", version="0.1.0")

# Initialize database tables (this is safe to run multiple times)
Base.metadata.create_all(bind=engine)


# Wave 4 tenancy: ``pipeline_schedule`` is no longer a global id=1 singleton
# — it is per-user. Each user's row is created lazily with defaults (cron
# OFF) on first ``GET /pipeline/schedule`` via
# ``PipelineScheduleRepository.get_or_create_for_user``; the daily cron does
# the same for the seed owner. So there is nothing to seed at startup anymore.

# Configure CORS. Origins come from the comma-separated FRONTEND_ORIGINS env
# var (so prod can point at its real domain) and default to the two localhost
# dev URLs when unset. allow_credentials stays True (cookie/Bearer auth).
_DEFAULT_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
_origins_env = os.getenv("FRONTEND_ORIGINS", "")
allow_origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or _DEFAULT_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# IP-keyed rate limiting (slowapi) for the public deploy surface. The shared
# ``limiter`` (app/backend/rate_limit.py) is OFF unless RATE_LIMIT_ENABLED=true,
# so dev/tests are unaffected; prod turns it on. Per-route limits are applied
# via @limiter.limit decorators in the auth/research/scanner routes. This wiring
# (state + handler + middleware) lives ONLY here, so the conftest test apps —
# which build their own FastAPI and never run main.py — don't activate limiting.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Include all routes
app.include_router(api_router)

# Serve the built SPA (single-origin deploy): index at "/", hashed assets under
# "/assets", catch-all for client-side routes. Registered LAST so API routes
# above always win. No-op when no build is present (dev/tests).
mount_spa(app, Path(os.getenv("FRONTEND_DIST", "app/frontend/dist")))

# Wire the scanner pipeline: broadcaster -> service -> scheduler. Module-level so
# routes can grab the scheduler via Depends(get_scheduler_service).
_scanner_service = ScannerService(SessionLocal, broadcaster=get_broadcaster())
_scheduler_service = init_scheduler_service(SessionLocal, _scanner_service)


@app.on_event("startup")
async def startup_event():
    """Startup: clean up interrupted scans, start scheduler, check Ollama."""
    # 1. Recover from an unclean previous shutdown: mark any lingering RUNNING
    #    scan rows as ERROR so the user knows they were interrupted.
    try:
        with SessionLocal() as session:
            runs = ScanRunRepository(session)
            stale = runs.list_running()
            for run in stale:
                runs.mark_error(run.id, "interrupted at startup")
            if stale:
                logger.info(
                    "Marked %d stale RUNNING scan(s) as ERROR (interrupted at startup)",
                    len(stale),
                )
    except Exception as e:
        logger.warning("Stale-run cleanup failed: %s", e)

    # 2. Start the scheduler — registers cron jobs for all enabled configs.
    try:
        _scheduler_service.start()
    except Exception as e:
        logger.exception("Failed to start scheduler: %s", e)

    # 3. Ollama health check (existing).
    try:
        logger.info("Checking Ollama availability...")
        status = await ollama_service.check_ollama_status()

        if status["installed"]:
            if status["running"]:
                logger.info(f"✓ Ollama is installed and running at {status['server_url']}")
                if status["available_models"]:
                    logger.info(f"✓ Available models: {', '.join(status['available_models'])}")
                else:
                    logger.info("ℹ No models are currently downloaded")
            else:
                logger.info("ℹ Ollama is installed but not running")
                logger.info("ℹ You can start it from the Settings page or manually with 'ollama serve'")
        else:
            logger.info("ℹ Ollama is not installed. Install it to use local models.")
            logger.info("ℹ Visit https://ollama.com to download and install Ollama")

    except Exception as e:
        logger.warning(f"Could not check Ollama status: {e}")
        logger.info("ℹ Ollama integration is available if you install it later")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown: stop scheduler without waiting on long-running scans."""
    try:
        _scheduler_service.shutdown(wait=False)
    except Exception as e:
        logger.warning("Scheduler shutdown raised: %s", e)
