from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import youtube, videos, process, events, state
from app.services.state_store import init_db
from app.utils.helpers import find_ffmpeg, find_ytdlp, find_aria2c
from app.config import get_settings
import os

app = FastAPI(
    title="TikTok Automate",
    description="YouTube Shorts → TikTok bulk repurposing with anti-detection editing",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("output", exist_ok=True)
os.makedirs("temp", exist_ok=True)
init_db()

app.mount("/output", StaticFiles(directory="output"), name="output")

app.include_router(youtube.router, prefix="/api/youtube", tags=["YouTube"])
app.include_router(videos.router, prefix="/api/videos", tags=["Videos"])
app.include_router(process.router, prefix="/api/process", tags=["Processing"])
app.include_router(events.router, prefix="/api/events", tags=["Events"])
app.include_router(state.router, prefix="/api/state", tags=["State"])


@app.get("/api/health")
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "version": "2.0.0",
        "tools": {
            "ffmpeg": bool(find_ffmpeg()),
            "yt_dlp": bool(find_ytdlp()),
            "aria2c": bool(find_aria2c()),
            "youtube_api": bool(settings.youtube_api_key),
        },
        "concurrency": {
            "download": settings.max_download_concurrent,
            "process": settings.max_process_concurrent,
        },
    }
