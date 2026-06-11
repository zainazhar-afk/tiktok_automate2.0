"""Server-Sent Events for live job and state updates."""
import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.services.job_queue import EVENTS_CHANNEL, _get_redis, list_jobs

logger = logging.getLogger(__name__)
router = APIRouter()


async def _event_stream():
    """SSE stream — Redis pub/sub when available, else periodic job poll."""
    r = _get_redis()
    if r:
        pubsub = r.pubsub()
        pubsub.subscribe(EVENTS_CHANNEL)
        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    yield f"data: {data}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.5)
        finally:
            pubsub.unsubscribe(EVENTS_CHANNEL)
            pubsub.close()
    else:
        while True:
            jobs = [j.model_dump() for j in list_jobs()]
            payload = json.dumps({"type": "jobs_snapshot", "data": {"jobs": jobs}})
            yield f"data: {payload}\n\n"
            await asyncio.sleep(2)


@router.get("/stream")
async def stream_events():
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
