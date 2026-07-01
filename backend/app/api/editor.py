"""Subtitle editor API."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.models.schemas import (
    SubtitleApplyTranscriptRequest,
    SubtitleImportRequest,
    SubtitleRenderResponse,
    SubtitleTranscribeRequest,
    SubtitleTrack,
    SubtitleTranslateRequest,
)
from app.services import entitlements, subtitle_editor

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
async def transcribe_subtitle_track(video_id: str, request: Request, req: SubtitleTranscribeRequest | None = None):
    payload = req or SubtitleTranscribeRequest()
    entitlements.require_feature(
        request,
        "transcription",
        rights_required=True,
        metadata={"video_id": video_id, "provider": payload.provider, "language": payload.language},
    )
    try:
        return await subtitle_editor.transcribe_track(
            video_id,
            force=payload.force,
            language=payload.language,
            provider=payload.provider,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/subtitles/{video_id}/apply")
async def apply_subtitle_transcript(video_id: str, req: SubtitleApplyTranscriptRequest):
    if video_id != req.track.video_id:
        raise HTTPException(status_code=400, detail="video id mismatch")
    try:
        return subtitle_editor.apply_transcript(req.track)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
async def render_subtitle_track(video_id: str, request: Request):
    entitlements.require_feature(
        request,
        "timeline_render",
        rights_required=True,
        metadata={"video_id": video_id, "kind": "subtitle_render"},
    )
    try:
        return await subtitle_editor.render_video(video_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
