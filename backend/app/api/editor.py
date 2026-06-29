"""Subtitle editor API."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.models.schemas import (
    SubtitleImportRequest,
    SubtitleRenderResponse,
    SubtitleTrack,
    SubtitleTranslateRequest,
)
from app.services import subtitle_editor

router = APIRouter()


@router.get("/subtitles/{video_id}")
async def get_subtitle_track(video_id: str):
    try:
        return subtitle_editor.get_or_create_track(video_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/subtitles/{video_id}")
async def save_subtitle_track(video_id: str, track: SubtitleTrack):
    if video_id != track.video_id:
        raise HTTPException(status_code=400, detail="video id mismatch")
    try:
        saved = subtitle_editor.save_track(track)
        subtitle_editor.write_sidecars(saved)
        return saved
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/subtitles/{video_id}/import")
async def import_subtitle_track(video_id: str, req: SubtitleImportRequest):
    fmt = req.format.lower()
    if fmt not in {"srt", "vtt"}:
        raise HTTPException(status_code=400, detail="format must be srt or vtt")
    try:
        return subtitle_editor.import_track(video_id, req.content, fmt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/subtitles/{video_id}/transcribe")
async def transcribe_subtitle_track(video_id: str):
    try:
        return await subtitle_editor.transcribe_track(video_id, force=True)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/subtitles/{video_id}/export")
async def export_subtitle_track(video_id: str, format: str = "srt"):
    fmt = format.lower()
    if fmt not in {"srt", "vtt"}:
        raise HTTPException(status_code=400, detail="format must be srt or vtt")
    try:
        track = subtitle_editor.get_or_create_track(video_id)
        text = subtitle_editor.export_vtt(track) if fmt == "vtt" else subtitle_editor.export_srt(track)
        media_type = "text/vtt" if fmt == "vtt" else "application/x-subrip"
        return PlainTextResponse(
            text,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{video_id}_edited.{fmt}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/subtitles/{video_id}/translate")
async def translate_subtitle_track(video_id: str, req: SubtitleTranslateRequest):
    try:
        return await subtitle_editor.translate_track(
            video_id,
            req.source_language,
            req.target_language,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Translation failed: {str(e)}")


@router.post("/subtitles/{video_id}/render", response_model=SubtitleRenderResponse)
async def render_subtitle_track(video_id: str):
    try:
        return await subtitle_editor.render_video(video_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
