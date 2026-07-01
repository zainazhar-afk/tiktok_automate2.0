"""Persisted video state API."""
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.services import state_store
from app.services.safety import safe_id
from app.tenant import owner_from_user

router = APIRouter()


class StateSyncItem(BaseModel):
    video_id: str
    title: str = ""
    channel: str = ""
    status: str | None = None
    download_path: str | None = None
    output_path: str | None = None

    @field_validator("video_id")
    @classmethod
    def validate_video_id(cls, value: str) -> str:
        return safe_id(value, "video id")

    @field_validator("download_path", "output_path")
    @classmethod
    def validate_path_hint(cls, value: str | None) -> str | None:
        if not value:
            return None
        if any(ch in value for ch in "\r\n\0") or ".." in value.replace("\\", "/").split("/"):
            raise ValueError("Invalid path")
        if os.path.isabs(value) or ":" in value:
            raise ValueError("Path must be a managed relative filename")
        return value


class StateSyncRequest(BaseModel):
    items: list[StateSyncItem] = Field(default_factory=list, max_length=100)


def _request_owner(request: Request) -> str:
    return owner_from_user(getattr(request.state, "user", None))


@router.get("/videos")
async def list_state(request: Request, status: str | None = None):
    videos = state_store.list_videos(status, owner_id=_request_owner(request))
    return {"videos": videos, "total": len(videos)}


@router.get("/videos/{video_id}")
async def get_state(video_id: str, request: Request):
    video_id = safe_id(video_id, "video id")
    row = state_store.get_video(video_id, owner_id=_request_owner(request))
    if not row:
        raise HTTPException(status_code=404, detail="Video state not found")
    return row


@router.post("/sync")
async def sync_state(body: StateSyncRequest, request: Request):
    """Bulk upsert from frontend (download/process tracking)."""
    owner_id = _request_owner(request)
    for item in body.items:
        state_store.upsert_video(
            item.video_id,
            owner_id=owner_id,
            title=item.title,
            channel=item.channel,
            status=item.status,
            download_path=item.download_path,
            output_path=item.output_path,
        )
    return {"synced": len(body.items)}
