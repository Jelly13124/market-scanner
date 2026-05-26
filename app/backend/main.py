from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import asyncio

from dotenv import load_dotenv

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

app = FastAPI(title="AI Hedge Fund API", description="Backend API for AI Hedge Fund", version="0.1.0")

# Initialize database tables (this is safe to run multiple times)
Base.metadata.create_all(bind=engine)


def _seed_pipeline_schedule_if_missing() -> None:
    """Ensure the singleton pipeline_schedule row exists.

    Alembic migration ``b3d8f1a2c9e4`` does this in environments that run
    migrations. The dev/anaconda runtime relies on ``create_all`` (above)
    for schema and this idempotent seed for the singleton row. Daily cron
    stays OFF on first install so we don't surprise users with LLM cost
    (implementation plan §Top risks).
    """
    from app.backend.database import SessionLocal
    from app.backend.database.models import PipelineSchedule

    db = SessionLocal()
    try:
        existing = db.query(PipelineSchedule).filter(PipelineSchedule.id == 1).first()
        if existing is None:
            db.add(PipelineSchedule(
                id=1, enabled=False, top_n=5, template="balanced",
                universe="nasdaq100", model_name="gpt-4.1", model_provider="OpenAI",
            ))
            db.commit()
            logger.info("Seeded pipeline_schedule singleton row (cron disabled by default).")
    finally:
        db.close()


_seed_pipeline_schedule_if_missing()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Frontend URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routes
app.include_router(api_router)

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
