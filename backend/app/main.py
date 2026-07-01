from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import account, youtube, videos, process, events, state, editor, timeline, variants
from app.auth import authenticate_request
from app.tenant import owner_from_user, reset_current_owner, set_current_owner
from app.services import state_store
from app.services.state_store import init_db
from app.utils.helpers import find_ffmpeg, find_ytdlp, find_aria2c
from app.config import get_settings, validate_runtime_settings
import os

settings = validate_runtime_settings()

app = FastAPI(
    title="TikTok Automate",
    description="Short-form repurposing workflow with editing presets, captions, variants, and exports",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request, call_next):
    try:
        request.state.user = await authenticate_request(request)
    except Exception as exc:
        status_code = getattr(exc, "status_code", 500)
        detail = getattr(exc, "detail", "Authentication failed")
        return JSONResponse({"detail": detail}, status_code=status_code)
    token = set_current_owner(owner_from_user(request.state.user))
    try:
        return await call_next(request)
    finally:
        reset_current_owner(token)

os.makedirs("temp", exist_ok=True)
init_db()

app.include_router(youtube.router, prefix="/api/youtube", tags=["YouTube"])
app.include_router(videos.router, prefix="/api/videos", tags=["Videos"])
app.include_router(process.router, prefix="/api/process", tags=["Processing"])
app.include_router(events.router, prefix="/api/events", tags=["Events"])
app.include_router(state.router, prefix="/api/state", tags=["State"])
app.include_router(editor.router, prefix="/api/editor", tags=["Editor"])
app.include_router(timeline.router, prefix="/api/timeline", tags=["Timeline"])
app.include_router(variants.router, prefix="/api/variants", tags=["Variants"])
app.include_router(account.router, prefix="/api/account", tags=["Account"])


@app.get("/api/health")
async def health():
    settings = get_settings()
    detailed = not settings.require_auth
    tools = {
        "ffmpeg": bool(find_ffmpeg()),
        "yt_dlp": bool(find_ytdlp()),
        "aria2c": bool(find_aria2c()),
        "youtube_api": bool(settings.youtube_api_key),
        "transcription_provider": settings.transcription_provider,
        "supabase": bool(settings.supabase_url and settings.supabase_secret_key),
        "state_store": state_store.backend_status(),
    }
    if detailed:
        tools.update({
            "google_ai_keys": len(settings.google_ai_api_keys),
            "groq_keys": len(settings.groq_api_keys),
            "groq_chat_model": settings.groq_chat_model,
            "groq_transcription_model": settings.groq_transcription_model,
            "deepgram_keys": len(settings.deepgram_api_keys),
        })
    return {
        "status": "ok",
        "version": "2.0.0",
        "environment": settings.app_environment,
        "auth_required": settings.require_auth,
        "tools": tools,
        "concurrency": {
            "download": settings.max_download_concurrent,
            "process": settings.max_process_concurrent,
        },
    }
