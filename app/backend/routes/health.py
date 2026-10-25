from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio
import json

router = APIRouter()


@router.get("/health")
async def health():
    """Lightweight liveness probe (used by the Fly health check). Fast + JSON.

    The bare ``/`` is intentionally NOT a route here: in a single-origin deploy
    the SPA owns ``/`` (see ``mount_spa`` in main.py). ``/ping`` is a 5s SSE
    stream — not suitable for a health check.
    """
    return {"status": "ok"}


@router.get("/data-status")
async def data_status():
    from src.storage.mongo import get_store
    return {"storage": get_store().status, "history_source": "yahoo", "quote_source": "finnhub", "online_fallback": True}


@router.get("/ping")
async def ping():
    async def event_generator():
        for i in range(5):
            # Create a JSON object for each ping
            data = {"ping": f"ping {i+1}/5", "timestamp": i + 1}

            # Format as SSE
            yield f"data: {json.dumps(data)}\n\n"

            # Wait 1 second
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
