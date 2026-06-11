"""Persisted video state API."""
from fastapi import APIRouter, HTTPException

from app.services import state_store

router = APIRouter()


@router.get("/videos")
async def list_state(status: str | None = None):
    return {"videos": state_store.list_videos(status), "total": len(state_store.list_videos(status))}


@router.get("/videos/{video_id}")
async def get_state(video_id: str):
    row = state_store.get_video(video_id)
    if not row:
        raise HTTPException(status_code=404, detail="Video state not found")
    return row


@router.post("/sync")
async def sync_state(body: dict):
    """Bulk upsert from frontend (download/process tracking)."""
    items = body.get("items", [])
    for item in items:
        state_store.upsert_video(
            item["video_id"],
            title=item.get("title", ""),
            channel=item.get("channel", ""),
            status=item.get("status"),
            download_path=item.get("download_path"),
            output_path=item.get("output_path"),
        )
    return {"synced": len(items)}
