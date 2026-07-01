"""In-process batch timeline render queue with retry/pause/resume controls."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

from app.models.schemas import TimelineProject, TimelineQueueJob
from app.services import timeline_editor
from app.services.subtitle_editor import source_video_path
from app.tenant import can_see_legacy, current_owner_id, reset_current_owner, set_current_owner

_jobs: dict[str, dict] = {}
_worker_task: asyncio.Task | None = None
_lock = asyncio.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_public(job: dict) -> dict:
    return TimelineQueueJob(
        job_id=job["job_id"],
        owner_id=job.get("owner_id", ""),
        video_id=job["video_id"],
        title=job.get("title", ""),
        status=job.get("status", "queued"),
        progress=float(job.get("progress", 0.0)),
        message=job.get("message", ""),
        error=job.get("error", ""),
        source_filename=job.get("source_filename"),
        output_filename=job.get("output_filename"),
        pause_requested=bool(job.get("pause_requested", False)),
        created_at=job.get("created_at", ""),
        updated_at=job.get("updated_at", ""),
    ).model_dump()


def _visible_to_owner(job: dict, owner_id: str) -> bool:
    job_owner = job.get("owner_id", "")
    if can_see_legacy(owner_id):
        return job_owner in {"", owner_id, "local-dev"}
    return job_owner == owner_id


async def enqueue(project: TimelineProject) -> dict:
    global _worker_task
    source = source_video_path(project.video_id)
    job_id = uuid.uuid4().hex[:10]
    now = _now()
    owner_id = current_owner_id()
    async with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "owner_id": owner_id,
            "video_id": project.video_id,
            "title": f"{project.video_id} timeline",
            "status": "queued",
            "progress": 0.0,
            "message": "Waiting to render",
            "error": "",
            "project": project.model_dump(),
            "source_filename": os.path.basename(source) if source else None,
            "output_filename": None,
            "pause_requested": False,
            "created_at": now,
            "updated_at": now,
        }
        if _worker_task is None or _worker_task.done():
            _worker_task = asyncio.create_task(_worker_loop())
        return _job_public(_jobs[job_id])


async def list_jobs(owner_id: str | None = None) -> list[dict]:
    owner = owner_id or current_owner_id()
    async with _lock:
        jobs = [_job_public(job) for job in _jobs.values() if _visible_to_owner(job, owner)]
    return sorted(jobs, key=lambda job: job["created_at"], reverse=True)


async def get_job(job_id: str, owner_id: str | None = None) -> dict | None:
    owner = owner_id or current_owner_id()
    async with _lock:
        job = _jobs.get(job_id)
        return _job_public(job) if job and _visible_to_owner(job, owner) else None


async def pause_job(job_id: str, owner_id: str | None = None) -> dict | None:
    owner = owner_id or current_owner_id()
    async with _lock:
        job = _jobs.get(job_id)
        if not job or not _visible_to_owner(job, owner):
            return None
        if job["status"] == "queued":
            job["status"] = "paused"
            job["message"] = "Paused before render"
        elif job["status"] == "running":
            job["pause_requested"] = True
            job["message"] = "Pause requested after current render"
        job["updated_at"] = _now()
        return _job_public(job)


async def resume_job(job_id: str, owner_id: str | None = None) -> dict | None:
    global _worker_task
    owner = owner_id or current_owner_id()
    async with _lock:
        job = _jobs.get(job_id)
        if not job or not _visible_to_owner(job, owner):
            return None
        if job["status"] == "paused":
            job["status"] = "queued"
            job["message"] = "Queued"
            job["pause_requested"] = False
        job["updated_at"] = _now()
        if _worker_task is None or _worker_task.done():
            _worker_task = asyncio.create_task(_worker_loop())
        return _job_public(job)


async def retry_job(job_id: str, owner_id: str | None = None) -> dict | None:
    global _worker_task
    owner = owner_id or current_owner_id()
    async with _lock:
        job = _jobs.get(job_id)
        if not job or not _visible_to_owner(job, owner):
            return None
        if job["status"] in {"failed", "completed"}:
            job["status"] = "queued"
            job["progress"] = 0.0
            job["message"] = "Queued for retry"
            job["error"] = ""
            job["output_filename"] = None
            job["pause_requested"] = False
            job["updated_at"] = _now()
        if _worker_task is None or _worker_task.done():
            _worker_task = asyncio.create_task(_worker_loop())
        return _job_public(job)


async def _update(job_id: str, **patch):
    async with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        if job.get("status") in {"completed", "failed"} and "status" not in patch:
            return
        job.update(patch)
        job["updated_at"] = _now()


async def _next_job() -> dict | None:
    async with _lock:
        for job in sorted(_jobs.values(), key=lambda item: item["created_at"]):
            if job["status"] == "queued":
                return dict(job)
    return None


async def _worker_loop():
    while True:
        job = await _next_job()
        if not job:
            return
        job_id = job["job_id"]
        await _update(job_id, status="running", progress=0.03, message="Starting render", error="")
        token = set_current_owner(job.get("owner_id") or "local-dev")
        try:
            project = TimelineProject(**job["project"])

            def progress(value: float, message: str = ""):
                asyncio.create_task(_update(
                    job_id,
                    progress=max(0.03, min(0.98, value)),
                    message=message or "Rendering",
                ))

            result = await timeline_editor.render_project(project, progress_callback=progress)
            await _update(
                job_id,
                status="completed",
                progress=1.0,
                message="Render complete",
                output_filename=result.get("filename"),
                error="",
            )
        except Exception as exc:
            await _update(job_id, status="failed", progress=1.0, message="Render failed", error=str(exc))
        finally:
            reset_current_owner(token)
