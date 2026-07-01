from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
import os
import glob as glob_module
import mimetypes
from pathlib import Path
from datetime import datetime

from app.config import get_settings
from app.services import entitlements, state_store
from app.tenant import can_see_legacy, owner_from_user, storage_video_id

router = APIRouter()

OUTPUT_DIR = os.path.abspath("output")
DOWNLOAD_DIR = os.path.abspath("temp/downloads")
ASSET_EXTENSIONS = {".aac", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}


def _safe_filename(filename: str) -> str:
    name = filename.strip()
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if "/" in name or "\\" in name or Path(name).name != name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return name


def _resolve_media_file(filename: str) -> str | None:
    safe_name = _safe_filename(filename)
    for directory in [OUTPUT_DIR, DOWNLOAD_DIR]:
        root = Path(directory).resolve()
        path = (root / safe_name).resolve()
        if path.parent == root and path.is_file():
            return str(path)
    return None


def _request_owner(request: Request) -> str:
    return owner_from_user(getattr(request.state, "user", None))


def _row_filenames(row: dict) -> set[str]:
    names: set[str] = set()
    video_id = str(row.get("video_id") or "")
    if video_id:
        file_id = storage_video_id(video_id, row.get("owner_id"))
        names.update({
            f"{file_id}.mp4",
            f"{file_id}_processed.mp4",
            f"{file_id}_edited.mp4",
            f"{file_id}_timeline.mp4",
            f"{file_id}_cover.jpg",
            f"{file_id}_tiktok_cover.jpg",
            f"{file_id}_reels_cover.jpg",
            f"{file_id}_shorts_cover.jpg",
            f"{file_id}_edited.srt",
            f"{file_id}_edited.vtt",
        })
    for key in ["download_path", "output_path", "thumbnail_path"]:
        value = row.get(key)
        if value:
            names.add(os.path.basename(value))
    return names


def _owned_media_rows(owner_id: str) -> list[dict]:
    return state_store.list_videos(owner_id=owner_id)


def _filename_owned(filename: str, owner_id: str) -> bool:
    safe_name = _safe_filename(filename)
    if can_see_legacy(owner_id):
        return bool(_resolve_media_file(safe_name))
    rows = _owned_media_rows(owner_id)
    if any(safe_name in _row_filenames(row) for row in rows):
        return True
    return False


def _row_modified(row: dict) -> float:
    updated = row.get("updated_at")
    if not updated:
        return 0.0
    try:
        return datetime.fromisoformat(str(updated)).timestamp()
    except ValueError:
        return 0.0


def _video_payload(
    *,
    filename: str,
    path: str | None,
    vid: str,
    meta: dict,
    visibility_status: str = "available",
    unavailable_reason: str = "",
) -> dict:
    size_mb = 0.0
    modified = _row_modified(meta)
    if path:
        try:
            stat = os.stat(path)
            size_mb = round(stat.st_size / (1024 * 1024), 2)
            modified = stat.st_mtime
        except OSError:
            pass
    cover = meta.get("thumbnail_path")
    cover_filename = os.path.basename(cover) if cover else f"{vid}_cover.jpg"
    return {
        "id": meta.get("video_id") or vid,
        "filename": filename,
        "path": filename,
        "size_mb": size_mb,
        "modified": modified,
        "title": meta.get("title") or meta.get("video_id") or vid,
        "caption": meta.get("caption"),
        "hashtags": meta.get("hashtags", []),
        "visibility_status": visibility_status,
        "unavailable_reason": unavailable_reason,
        "cover_filename": cover_filename if os.path.exists(os.path.join(OUTPUT_DIR, cover_filename)) else None,
    }


def _list_audio_assets(directory: str) -> list[str]:
    root = Path(directory).resolve()
    if not root.is_dir():
        return []
    files = []
    for path in root.iterdir():
        if path.is_file() and path.suffix.lower() in ASSET_EXTENSIONS:
            files.append(path.name)
    return sorted(files, key=str.lower)


@router.get("/list")
async def list_videos(request: Request, type: str = "processed"):
    owner_id = _request_owner(request)
    if type == "processed":
        directory = OUTPUT_DIR
        patterns = ["*_processed.mp4", "*_edited.mp4", "*_timeline.mp4", "*_variant_*.mp4"]
    else:
        directory = DOWNLOAD_DIR
        patterns = ["*.mp4"]

    persisted_rows = _owned_media_rows(owner_id)
    persisted = {v["video_id"]: v for v in persisted_rows}
    filename_meta = {
        filename: row
        for row in persisted_rows
        for filename in _row_filenames(row)
    }
    videos = []
    files = []
    if os.path.exists(directory):
        for pattern in patterns:
            files.extend(glob_module.glob(os.path.join(directory, pattern)))
    seen_filenames: set[str] = set()
    for f in sorted(set(files), key=os.path.getmtime, reverse=True):
        vid = (
            os.path.basename(f)
            .replace("_processed.mp4", "")
            .replace("_edited.mp4", "")
            .replace("_timeline.mp4", "")
            .replace(".mp4", "")
        )
        filename = os.path.basename(f)
        meta = filename_meta.get(filename) or persisted.get(vid) or {}
        if not meta and not can_see_legacy(owner_id):
            continue
        seen_filenames.add(filename)
        videos.append(_video_payload(filename=filename, path=f, vid=vid, meta=meta))

    path_key = "output_path" if type == "processed" else "download_path"
    for row in persisted_rows:
        media_path = row.get(path_key)
        if not media_path:
            continue
        filename = os.path.basename(media_path)
        if filename in seen_filenames:
            continue
        videos.append(_video_payload(
            filename=filename,
            path=None,
            vid=str(row.get("video_id") or filename),
            meta=row,
            visibility_status="unavailable",
            unavailable_reason="The generated file is missing from storage. Re-render or refresh after storage sync.",
        ))

    return {"videos": videos, "total": len(videos)}


@router.get("/assets")
async def list_assets():
    settings = get_settings()
    return {
        "music": _list_audio_assets(settings.music_dir),
        "voiceover": _list_audio_assets(settings.voiceover_dir),
    }


@router.get("/file/{filename}")
async def get_video_file(filename: str, request: Request):
    owner_id = _request_owner(request)
    entitlements.require_feature(
        request,
        "export",
        rights_required=True,
        metadata={"filename": filename},
    )
    if not _filename_owned(filename, owner_id):
        raise HTTPException(status_code=404, detail="File not found")
    path = _resolve_media_file(filename)
    if path:
        safe_name = os.path.basename(path)
        mime, _ = mimetypes.guess_type(safe_name)
        return FileResponse(path, media_type=mime or "application/octet-stream", filename=safe_name)
    raise HTTPException(status_code=404, detail="File not found")


@router.delete("/{filename}")
async def delete_video(filename: str, request: Request):
    owner_id = _request_owner(request)
    if not _filename_owned(filename, owner_id):
        raise HTTPException(status_code=404, detail="File not found")
    path = _resolve_media_file(filename)
    if path:
        os.remove(path)
        return {"status": "deleted", "filename": os.path.basename(path)}
    raise HTTPException(status_code=404, detail="File not found")
