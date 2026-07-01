"""Server-Sent Events for live job and state updates."""
import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.job_queue import EVENTS_CHANNEL, _get_redis, list_jobs
from app.tenant import can_see_legacy, owner_from_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _event_visible(payload: dict, owner_id: str) -> bool:
    data = payload.get("data") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return True
    job_owner = data.get("owner_id")
    if can_see_legacy(owner_id):
        return job_owner in {None, "", owner_id, "local-dev"}
    return job_owner == owner_id


async def _event_stream(owner_id: str):
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
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        payload = {}
                    if _event_visible(payload, owner_id):
                        yield f"data: {data}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.5)
        finally:
            pubsub.unsubscribe(EVENTS_CHANNEL)
            pubsub.close()
    else:
        while True:
            jobs = [j.model_dump() for j in list_jobs(owner_id=owner_id)]
            payload = json.dumps({"type": "jobs_snapshot", "data": {"jobs": jobs}})
            yield f"data: {payload}\n\n"
            await asyncio.sleep(2)


@router.get("/stream")
async def stream_events(request: Request):
    owner_id = owner_from_user(getattr(request.state, "user", None))
    return StreamingResponse(
        _event_stream(owner_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
