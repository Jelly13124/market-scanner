from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio
import json

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "Welcome to Quant Lab API"}


@router.get("/tier")
async def get_tier():
    """Phase 9: report active data-source tier.

    Returns ``{"tier": "paid" | "free", "eodhd_key_set": bool}`` —
    consumed by the frontend Scanner panel to show a tier badge so
    users see whether they're on the $20 EODHD path or the free
    Finnhub-only fallback.
    """
    from v2.data.composite_client import get_active_tier, _has_eodhd_key
    return {
        "tier": get_active_tier(),
        "eodhd_key_set": _has_eodhd_key(),
    }


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
