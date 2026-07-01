"""Timeline and crop editor API."""
from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import (
    TimelineCoverRequest,
    TimelineCoverResponse,
    TimelineHookRequest,
    TimelineHookResponse,
    TimelineProject,
    TimelineQueueRequest,
    TimelineScoreRequest,
    TimelineScoreResponse,
    TimelineRenderResponse,
    TimelineSilenceCutRequest,
    TimelineSmartCropRequest,
    TimelineSmartCropResponse,
)
from app.services import clip_scoring, cover_generator, entitlements, render_queue, timeline_editor
from app.tenant import owner_from_user

router = APIRouter()


@router.get("/{video_id}")
async def get_timeline_project(video_id: str):
    try:
        return await timeline_editor.get_or_create_project(video_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{video_id}")
async def save_timeline_project(video_id: str, project: TimelineProject):
    if video_id != project.video_id:
        raise HTTPException(status_code=400, detail="video id mismatch")
    try:
        return timeline_editor.save_project(project)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{video_id}/render", response_model=TimelineRenderResponse)
async def render_timeline_project(video_id: str, project: TimelineProject, request: Request):
    if video_id != project.video_id:
        raise HTTPException(status_code=400, detail="video id mismatch")
    entitlements.require_feature(
        request,
        "timeline_render",
        rights_required=True,
        metadata={"video_id": video_id, "clips": len(project.clips)},
    )
    try:
        return await timeline_editor.render_project(project)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{video_id}/queue")
async def enqueue_timeline_render(video_id: str, req: TimelineQueueRequest, request: Request):
    if video_id != req.project.video_id:
        raise HTTPException(status_code=400, detail="video id mismatch")
    entitlements.require_feature(
        request,
        "timeline_render",
        rights_required=True,
        metadata={"video_id": video_id, "queued": True, "clips": len(req.project.clips)},
    )
    try:
        return await render_queue.enqueue(req.project)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue/jobs")
async def list_timeline_queue(request: Request):
    return {"jobs": await render_queue.list_jobs(owner_from_user(getattr(request.state, "user", None)))}


@router.post("/queue/{job_id}/pause")
async def pause_timeline_queue_job(job_id: str, request: Request):
    job = await render_queue.pause_job(job_id, owner_from_user(getattr(request.state, "user", None)))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/queue/{job_id}/resume")
async def resume_timeline_queue_job(job_id: str, request: Request):
    job = await render_queue.resume_job(job_id, owner_from_user(getattr(request.state, "user", None)))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/queue/{job_id}/retry")
async def retry_timeline_queue_job(job_id: str, request: Request):
    job = await render_queue.retry_job(job_id, owner_from_user(getattr(request.state, "user", None)))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{video_id}/silence-cuts")
async def apply_silence_cuts(video_id: str, req: TimelineSilenceCutRequest):
    if video_id != req.project.video_id:
        raise HTTPException(status_code=400, detail="video id mismatch")
    try:
        return await timeline_editor.apply_silence_cuts(
            req.project,
            noise_db=req.noise_db,
            min_silence=req.min_silence,
            padding=req.padding,
            min_clip=req.min_clip,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{video_id}/hooks", response_model=TimelineHookResponse)
async def generate_timeline_hooks(video_id: str, req: TimelineHookRequest, request: Request):
    if video_id != req.project.video_id:
        raise HTTPException(status_code=400, detail="video id mismatch")
    entitlements.require_feature(
        request,
        "variant",
        rights_required=True,
        metadata={"video_id": video_id, "kind": "hook_generation"},
    )
    try:
        return await timeline_editor.generate_hook_suggestions(req.project)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{video_id}/smart-crop", response_model=TimelineSmartCropResponse)
async def apply_smart_crop(video_id: str, req: TimelineSmartCropRequest, request: Request):
    if video_id != req.project.video_id:
        raise HTTPException(status_code=400, detail="video id mismatch")
    entitlements.require_feature(
        request,
        "process",
        rights_required=True,
        metadata={"video_id": video_id, "kind": "smart_crop"},
    )
    try:
        return await timeline_editor.apply_smart_crop(
            req.project,
            clip_id=req.clip_id,
            mode=req.mode,
            sample_interval=req.sample_interval,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{video_id}/cover", response_model=TimelineCoverResponse)
async def generate_timeline_cover(video_id: str, req: TimelineCoverRequest, request: Request):
    if video_id != req.project.video_id:
        raise HTTPException(status_code=400, detail="video id mismatch")
    entitlements.require_feature(
        request,
        "timeline_render",
        rights_required=True,
        metadata={"video_id": video_id, "kind": "cover", "platform": req.platform},
    )
    try:
        headline = req.headline or req.project.hook_title or req.project.clips[0].title if req.project.clips else ""
        brand_name = req.brand_name or req.project.brand_name
        brand_color = req.brand_color or req.project.brand_primary_color
        accent_color = req.accent_color or req.project.brand_accent_color
        return await cover_generator.generate_cover(
            video_id,
            headline=headline,
            brand_name=brand_name,
            brand_color=brand_color,
            accent_color=accent_color,
            platform=req.platform,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{video_id}/score", response_model=TimelineScoreResponse)
async def score_timeline_project(video_id: str, req: TimelineScoreRequest):
    if video_id != req.project.video_id:
        raise HTTPException(status_code=400, detail="video id mismatch")
    try:
        return await clip_scoring.score_project(req.project)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
