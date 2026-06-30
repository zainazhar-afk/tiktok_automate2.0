"""Long-form upload to short-form variant generation."""
import asyncio
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.models.schemas import VariantSpec
from app.services import downloader, state_store, variant_intelligence
from app.services.processor import TARGET_H, TARGET_W, probe_video, validate_output
from app.services.safety import validate_public_video_url
from app.utils.helpers import find_ffmpeg, run_command

OUTPUT_DIR = os.path.abspath("output")
SAFE_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
_source_jobs: dict[str, dict] = {}


def _safe_upload_id(upload_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", upload_id or ""):
        raise ValueError("Invalid upload id")
    return upload_id


def _source_path(upload_id: str) -> str | None:
    upload_id = _safe_upload_id(upload_id)
    root = Path(get_settings().uploads_dir)
    for path in root.glob(f"{upload_id}.*"):
        if path.is_file():
            return str(path)
    downloaded = downloader.find_merged_file(upload_id)
    if downloaded:
        return downloaded
    return None


def upload_path(upload_id: str, original_name: str) -> str:
    suffix = Path(original_name).suffix.lower()
    if suffix not in SAFE_EXTENSIONS:
        suffix = ".mp4"
    return os.path.join(get_settings().uploads_dir, f"{_safe_upload_id(upload_id)}{suffix}")


async def create_source_from_url(url: str) -> dict:
    clean_url = validate_public_video_url(url)

    upload_id = new_upload_id()
    path = await downloader.download_video(clean_url, upload_id, force=True, timeout=1200)
    if not path:
        raise RuntimeError("Video download failed. Use a public video URL supported by yt-dlp.")
    return {
        "upload_id": upload_id,
        "filename": os.path.basename(path),
        "url": clean_url,
        "path": path,
    }


def start_source_download(url: str) -> dict:
    clean_url = validate_public_video_url(url)

    upload_id = new_upload_id()
    now = datetime.now(timezone.utc).isoformat()
    _source_jobs[upload_id] = {
        "upload_id": upload_id,
        "url": clean_url,
        "filename": "",
        "status": "queued",
        "progress": 0.0,
        "message": "Queued",
        "error": "",
        "created_at": now,
        "updated_at": now,
    }
    return _source_jobs[upload_id].copy()


def get_source_status(upload_id: str) -> dict:
    upload_id = _safe_upload_id(upload_id)
    job = _source_jobs.get(upload_id)
    if job:
        return job.copy()
    source = _source_path(upload_id)
    if source:
        return {
            "upload_id": upload_id,
            "url": "",
            "filename": os.path.basename(source),
            "status": "completed",
            "progress": 1.0,
            "message": "Source ready",
            "error": "",
            "created_at": "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    raise FileNotFoundError("Source download not found")


async def download_source_job(upload_id: str, url: str) -> None:
    upload_id = _safe_upload_id(upload_id)

    def update(status: str, progress: float, message: str = "", error: str = "", filename: str = ""):
        current = _source_jobs.get(upload_id, {"upload_id": upload_id, "url": url})
        current.update({
            "status": status,
            "progress": round(max(0.0, min(1.0, progress)), 4),
            "message": message or current.get("message", ""),
            "error": error,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        if filename:
            current["filename"] = filename
        _source_jobs[upload_id] = current

    def progress_callback(progress: float, line: str):
        update("downloading", progress, line[:180])

    try:
        update("downloading", 0.0, "Starting download")
        path = await downloader.download_video(
            url,
            upload_id,
            force=True,
            timeout=1200,
            progress_callback=progress_callback,
        )
        if not path:
            update("failed", 0.0, "Download failed", "Video download failed")
            return
        update("completed", 1.0, "Source ready", filename=os.path.basename(path))
    except Exception as e:
        update("failed", 0.0, "Download failed", str(e))


async def plan_variants(source_path: str, upload_id: str, *, count: int = 10) -> tuple[list[VariantSpec], bool, dict]:
    return await variant_intelligence.intelligent_plan(source_path, upload_id, count=count)


def _variant_filter() -> str:
    return (
        f"[0:v]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},setsar=1[v]"
    )


async def _render_variant(ffmpeg: str, source: str, upload_id: str, spec: VariantSpec, index: int) -> dict:
    output_id = f"{upload_id}_variant_{index:02d}"
    output_path = os.path.join(OUTPUT_DIR, f"{output_id}.mp4")
    duration = max(0.2, spec.end - spec.start)
    cmd = [
        ffmpeg, "-y",
        "-ss", f"{spec.start:.3f}",
        "-t", f"{duration:.3f}",
        "-i", source,
        "-filter_complex", _variant_filter(),
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]
    rc, _stdout, stderr = await asyncio.to_thread(run_command, cmd, timeout=900)
    if rc != 0 or not os.path.exists(output_path):
        raise RuntimeError(stderr[-500:] if stderr else f"Variant {index} render failed")
    ok, reason = await validate_output(output_path)
    if not ok:
        raise RuntimeError(f"Variant {index} output invalid: {reason}")
    state_store.upsert_video(
        output_id,
        title=spec.title,
        status="completed",
        output_path=output_path,
        caption=spec.hook,
        hashtags=["#shorts", "#tiktok", f"#{spec.angle.replace('-', '')}"],
        metadata={
            "source_upload_id": upload_id,
            "start": spec.start,
            "end": spec.end,
            "compliance_note": spec.compliance_note,
            "score": spec.score,
            "reasons": spec.reasons,
            "transcript_excerpt": spec.transcript_excerpt,
            "source_signals": spec.source_signals,
        },
    )
    return {
        "id": output_id,
        "filename": Path(output_path).name,
        "output_path": output_path,
        "title": spec.title,
        "hook": spec.hook,
        "start": spec.start,
        "end": spec.end,
        "angle": spec.angle,
        "compliance_note": spec.compliance_note,
        "score": spec.score,
        "reasons": spec.reasons,
        "transcript_excerpt": spec.transcript_excerpt,
        "source_signals": spec.source_signals,
    }


async def generate_variants(upload_id: str, *, count: int = 10) -> dict:
    upload_id = _safe_upload_id(upload_id)
    source = _source_path(upload_id)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    if not source:
        raise FileNotFoundError("Uploaded source video not found")

    specs, ai_planned, analysis = await plan_variants(source, upload_id, count=count)
    files: list[dict] = []
    for index, spec in enumerate(specs, start=1):
        files.append(await _render_variant(ffmpeg, source, upload_id, spec, index))
    return {
        "upload_id": upload_id,
        "ai_planned": ai_planned,
        "variants": [spec.model_dump() for spec in specs],
        "files": files,
        "analysis": analysis,
    }


def new_upload_id() -> str:
    return uuid.uuid4().hex[:12]
