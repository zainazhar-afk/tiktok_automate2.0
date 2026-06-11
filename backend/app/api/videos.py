from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os
import glob as glob_module
import mimetypes

from app.services import state_store

router = APIRouter()

OUTPUT_DIR = os.path.abspath("output")
DOWNLOAD_DIR = os.path.abspath("temp/downloads")


@router.get("/list")
async def list_videos(type: str = "processed"):
    if type == "processed":
        directory = OUTPUT_DIR
        pattern = "*_processed.mp4"
    else:
        directory = DOWNLOAD_DIR
        pattern = "*.mp4"

    if not os.path.exists(directory):
        return {"videos": [], "total": 0}

    persisted = {v["video_id"]: v for v in state_store.list_videos()}
    videos = []
    for f in sorted(glob_module.glob(os.path.join(directory, pattern)), key=os.path.getmtime, reverse=True):
        stat = os.stat(f)
        vid = os.path.basename(f).replace("_processed.mp4", "").replace(".mp4", "")
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


@router.get("/file/{filename}")
async def get_video_file(filename: str):
    for directory in [OUTPUT_DIR, DOWNLOAD_DIR]:
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            mime, _ = mimetypes.guess_type(filename)
            return FileResponse(path, media_type=mime or "application/octet-stream", filename=filename)
    raise HTTPException(status_code=404, detail="File not found")


@router.delete("/{filename}")
async def delete_video(filename: str):
    for directory in [OUTPUT_DIR, DOWNLOAD_DIR]:
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            os.remove(path)
            return {"status": "deleted", "filename": filename}
    raise HTTPException(status_code=404, detail="File not found")
