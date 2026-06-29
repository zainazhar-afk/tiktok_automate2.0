from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os
import glob as glob_module
import mimetypes
from pathlib import Path

from app.config import get_settings
from app.services import state_store

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
async def list_videos(type: str = "processed"):
    if type == "processed":
        directory = OUTPUT_DIR
        patterns = ["*_processed.mp4", "*_edited.mp4", "*_timeline.mp4", "*_variant_*.mp4"]
    else:
        directory = DOWNLOAD_DIR
        patterns = ["*.mp4"]

    if not os.path.exists(directory):
        return {"videos": [], "total": 0}

    persisted = {v["video_id"]: v for v in state_store.list_videos()}
    videos = []
    files = []
    for pattern in patterns:
        files.extend(glob_module.glob(os.path.join(directory, pattern)))
    for f in sorted(set(files), key=os.path.getmtime, reverse=True):
        stat = os.stat(f)
        vid = (
            os.path.basename(f)
            .replace("_processed.mp4", "")
            .replace("_edited.mp4", "")
            .replace(".mp4", "")
        )
        meta = persisted.get(vid, {})
        cover = meta.get("thumbnail_path")
        cover_filename = os.path.basename(cover) if cover else f"{vid}_cover.jpg"
        videos.append({
            "id": vid,
            "filename": os.path.basename(f),
            "path": f,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "modified": stat.st_mtime,
            "title": meta.get("title", vid),
            "caption": meta.get("caption"),
            "hashtags": meta.get("hashtags", []),
            "cover_filename": cover_filename if os.path.exists(os.path.join(OUTPUT_DIR, cover_filename)) else None,
        })

    return {"videos": videos, "total": len(videos)}


@router.get("/assets")
async def list_assets():
    settings = get_settings()
    return {
        "music": _list_audio_assets(settings.music_dir),
        "voiceover": _list_audio_assets(settings.voiceover_dir),
    }


@router.get("/file/{filename}")
async def get_video_file(filename: str):
    path = _resolve_media_file(filename)
    if path:
        safe_name = os.path.basename(path)
        mime, _ = mimetypes.guess_type(safe_name)
        return FileResponse(path, media_type=mime or "application/octet-stream", filename=safe_name)
    raise HTTPException(status_code=404, detail="File not found")


@router.delete("/{filename}")
async def delete_video(filename: str):
    path = _resolve_media_file(filename)
    if path:
        os.remove(path)
        return {"status": "deleted", "filename": os.path.basename(path)}
    raise HTTPException(status_code=404, detail="File not found")
