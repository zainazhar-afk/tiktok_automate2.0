"""
RQ worker tasks — download, process, metadata generation.
Run: python -m app.worker
"""
import asyncio
import logging

from app.models.schemas import AntiDetectionConfig, JobStatus
from app.services import downloader, processor, metadata, job_queue, state_store
from app.tenant import reset_current_owner, set_current_owner

logger = logging.getLogger(__name__)


def _run_async(coro):
    return asyncio.run(coro)


def run_pipeline_job(
    job_id: str,
    video_id: str,
    url: str,
    config_dict: dict,
    video_meta: dict,
    owner_id: str = "local-dev",
):
    """Full pipeline executed by RQ worker."""
    token = set_current_owner(owner_id)
    title = video_meta.get("title", "")
    channel = video_meta.get("channel", "")
    description = video_meta.get("description", "")
    tags = video_meta.get("tags", [])

    try:
        state_store.upsert_video(
            video_id, title=title, channel=channel, status="queued"
        )
        job_queue.update_job(job_id, status=JobStatus.DOWNLOADING, progress=0.2)
        state_store.upsert_video(video_id, status="downloading")

        path = _run_async(downloader.download_video(url, video_id))
        if not path:
            raise RuntimeError("Download failed")

        job_queue.update_job(job_id, status=JobStatus.DOWNLOADING, progress=0.4)
        state_store.upsert_video(
            video_id, status="downloaded", download_path=path
        )

        job_queue.update_job(job_id, status=JobStatus.PROCESSING, progress=0.6)
        state_store.upsert_video(video_id, status="processing")

        def processing_progress(value: float):
            progress = 0.6 + max(0.0, min(1.0, value)) * 0.25
            job_queue.update_job(job_id, status=JobStatus.PROCESSING, progress=progress)

        config = AntiDetectionConfig(**config_dict)
        output = _run_async(
            processor.process_video(
                path,
                video_id,
                config,
                progress_callback=processing_progress,
            )
        )
        if not output:
            raise RuntimeError("Processing failed")

        job_queue.update_job(job_id, status=JobStatus.PROCESSING, progress=0.85)
        probe = _run_async(processor.probe_video(output))
        meta = _run_async(metadata.generate_all_metadata(
            video_id, output, title, channel, description, tags,
            duration=probe.get("duration", 30),
        ))

        state_store.upsert_video(
            video_id,
            status="completed",
            output_path=output,
            thumbnail_path=meta.get("thumbnail_path"),
            caption=meta.get("caption"),
            hashtags=meta.get("hashtags"),
        )
        job_queue.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=1.0,
            output_path=output,
            caption=meta.get("caption"),
            hashtags=meta.get("hashtags"),
            thumbnail_path=meta.get("thumbnail_path"),
        )
        return {"status": "completed", "output_path": output}

    except Exception as e:
        logger.exception(f"Pipeline failed for {video_id}")
        state_store.upsert_video(video_id, status="failed", error=str(e))
        job_queue.update_job(job_id, status=JobStatus.FAILED, error=str(e))
        raise
    finally:
        reset_current_owner(token)
