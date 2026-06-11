from fastapi import APIRouter, HTTPException, BackgroundTasks

from app.config import get_settings
from app.models.schemas import (
    ProcessRequest, BatchProcessRequest, AntiDetectionConfig,
    JobStatus, JobInfo,
)
from app.services import processor, downloader, job_queue, metadata, state_store

router = APIRouter()


def _resolve_input(video_id: str) -> str:
    path = downloader.find_merged_file(video_id)
    if not path:
        raise HTTPException(status_code=404, detail="Downloaded video not found")
    return path


@router.post("/single")
async def process_single(req: ProcessRequest):
    input_path = _resolve_input(req.video_id)
    state_store.upsert_video(
        req.video_id, title=req.title, channel=req.channel, status="processing"
    )

    output_path = await processor.process_video(input_path, req.video_id, req.config)
    if not output_path:
        state_store.upsert_video(req.video_id, status="failed", error="Processing failed")
        raise HTTPException(status_code=500, detail="Processing failed")

    probe = await processor.probe_video(output_path)
    meta = await metadata.generate_all_metadata(
        req.video_id, output_path, req.title, req.channel,
        req.description, req.tags, probe.get("duration", 30),
    )
    state_store.upsert_video(
        req.video_id,
        status="completed",
        output_path=output_path,
        thumbnail_path=meta.get("thumbnail_path"),
        caption=meta.get("caption"),
        hashtags=meta.get("hashtags"),
    )

    return {
        "video_id": req.video_id,
        "output_path": output_path,
        "status": "processed",
        "caption": meta.get("caption"),
        "hashtags": meta.get("hashtags"),
        "thumbnail_path": meta.get("thumbnail_path"),
    }


@router.post("/batch")
async def process_batch(req: BatchProcessRequest):
    settings = get_settings()
    inputs = []
    missing = []

    for vid in req.video_ids:
        path = downloader.find_merged_file(vid)
        if path:
            inputs.append((path, vid, req.config))
        else:
            missing.append(vid)

    results = await processor.batch_process(
        inputs, req.max_concurrent or settings.max_process_concurrent
    )
    successful = {k: v for k, v in results.items() if v is not None}
    failed = [k for k, v in results.items() if v is None]

    return {
        "processed": len(successful),
        "failed": len(failed) + len(missing),
        "missing": missing,
        "results": successful,
        "failed_ids": failed,
    }


@router.post("/pipeline")
async def pipeline_process(req: BatchProcessRequest, background_tasks: BackgroundTasks):
    """Enqueue download+process+metadata via Redis worker, or run in-process."""
    settings = get_settings()
    video_meta = req.video_meta or {}
    urls = {
        vid: video_meta.get(vid, {}).get("url", f"https://youtube.com/shorts/{vid}")
        for vid in req.video_ids
    }

    jobs = job_queue.enqueue_pipeline(
        req.video_ids,
        req.config.model_dump(),
        urls=urls,
        video_meta=video_meta,
    )

    use_rq = job_queue.rq_available()
    if not use_rq:
        background_tasks.add_task(
            _run_pipeline_inprocess, req, jobs, urls, video_meta
        )

    return {
        "jobs": [j.model_dump() for j in jobs],
        "pipeline": "queued" if use_rq else "started_inprocess",
        "redis": job_queue.redis_available(),
        "rq_worker": use_rq,
    }


async def _run_pipeline_inprocess(req, jobs, urls, video_meta):
    import asyncio
    from app.services.worker_tasks import run_pipeline_job

    sem = asyncio.Semaphore(req.max_concurrent or get_settings().max_process_concurrent)

    async def process_one(vid: str):
        job = next((j for j in jobs if j.video_id == vid), None)
        meta = video_meta.get(vid, {})
        async with sem:
            await asyncio.to_thread(
                run_pipeline_job,
                job.job_id if job else "local",
                vid,
                urls.get(vid, f"https://youtube.com/shorts/{vid}"),
                req.config.model_dump(),
                meta,
            )

    await asyncio.gather(*[process_one(vid) for vid in req.video_ids], return_exceptions=True)


@router.get("/jobs")
async def list_jobs():
    jobs = job_queue.list_jobs()
    return {"jobs": [j.model_dump() for j in jobs], "total": len(jobs)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.model_dump()


@router.post("/preset/{level}")
async def get_preset(level: str):
    from app.models.schemas import AntiDetectionLevel
    try:
        level_enum = AntiDetectionLevel(level)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid level: {level}")
    config = AntiDetectionConfig(level=level_enum)
    config = processor.resolve_preset(config)
    return config.model_dump()
