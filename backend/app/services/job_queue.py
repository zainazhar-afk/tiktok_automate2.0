"""
Redis-backed job queue with in-memory fallback.
Uses RQ for worker processing when Redis 4+ is available.
"""
import json
import logging
import uuid
from typing import Optional

from app.models.schemas import JobInfo, JobStatus

logger = logging.getLogger(__name__)

_redis = None
_rq_queue = None
_rq_supported: Optional[bool] = None
_memory_jobs: dict[str, JobInfo] = {}
EVENTS_CHANNEL = "tiktok_automate:events"


def _get_redis():
    global _redis
    if _redis is not None:
        return _redis if _redis is not False else None
    try:
        from redis import Redis
        from app.config import get_settings

        _redis = Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            protocol=2,
        )
        _redis.ping()
        return _redis
    except Exception as e:
        logger.warning(f"Redis unavailable, using in-memory jobs: {e}")
        _redis = False
        return None


def _redis_major_version() -> int:
    r = _get_redis()
    if not r:
        return 0
    try:
        version = r.info("server").get("redis_version", "0")
        return int(str(version).split(".")[0])
    except Exception:
        return 0


def rq_available() -> bool:
    """RQ 2.x requires Redis 4+ (variadic HSET)."""
    global _rq_supported
    if _rq_supported is not None:
        return _rq_supported
    major = _redis_major_version()
    _rq_supported = major >= 4
    if not _rq_supported and major > 0:
        logger.warning(
            f"Redis {major}.x detected — RQ worker needs Redis 4+. "
            "Use docker compose (port 6380) or run pipeline in-process."
        )
    return _rq_supported


def _get_rq_queue():
    global _rq_queue
    if _rq_queue is not None:
        return _rq_queue
    if not rq_available():
        return None
    r = _get_redis()
    if not r:
        return None
    try:
        from rq import Queue

        _rq_queue = Queue("tiktok", connection=r)
        return _rq_queue
    except Exception as e:
        logger.warning(f"RQ queue unavailable: {e}")
        return None


def _job_key(job_id: str) -> str:
    return f"job:{job_id}"


def _save_job(job: JobInfo):
    r = _get_redis()
    if r:
        r.set(_job_key(job.job_id), job.model_dump_json())
        r.sadd("jobs:all", job.job_id)
        publish_event("job_update", job.model_dump())
    else:
        _memory_jobs[job.job_id] = job


def publish_event(event_type: str, data: dict):
    r = _get_redis()
    payload = json.dumps({"type": event_type, "data": data})
    if r:
        r.publish(EVENTS_CHANNEL, payload)
    else:
        logger.debug(f"Event (no redis): {event_type}")


def create_job(video_id: str, title: str = "", channel: str = "") -> JobInfo:
    job_id = str(uuid.uuid4())[:8]
    job = JobInfo(
        job_id=job_id,
        video_id=video_id,
        status=JobStatus.QUEUED,
        title=title,
        channel=channel,
    )
    _save_job(job)
    return job


def get_job(job_id: str) -> Optional[JobInfo]:
    r = _get_redis()
    if r:
        raw = r.get(_job_key(job_id))
        if raw:
            return JobInfo.model_validate_json(raw)
        return None
    return _memory_jobs.get(job_id)


def update_job(job_id: str, **kwargs):
    job = get_job(job_id)
    if not job:
        return
    for key, value in kwargs.items():
        if hasattr(job, key):
            setattr(job, key, value)
    _save_job(job)


def list_jobs() -> list[JobInfo]:
    r = _get_redis()
    if r:
        ids = r.smembers("jobs:all")
        jobs = []
        for jid in ids:
            raw = r.get(_job_key(jid))
            if raw:
                jobs.append(JobInfo.model_validate_json(raw))
        return jobs
    return list(_memory_jobs.values())


def bulk_create_jobs(video_ids: list[str], video_meta: Optional[dict] = None) -> list[JobInfo]:
    meta = video_meta or {}
    return [
        create_job(
            vid,
            title=meta.get(vid, {}).get("title", ""),
            channel=meta.get(vid, {}).get("channel", ""),
        )
        for vid in video_ids
    ]


def enqueue_pipeline(
    video_ids: list[str],
    config_dict: dict,
    urls: Optional[dict[str, str]] = None,
    video_meta: Optional[dict] = None,
) -> list[JobInfo]:
    """Enqueue pipeline jobs to RQ worker when Redis 4+ is available."""
    jobs = bulk_create_jobs(video_ids, video_meta)
    queue = _get_rq_queue()

    if queue:
        from app.services.worker_tasks import run_pipeline_job

        for job in jobs:
            url = (urls or {}).get(job.video_id, f"https://youtube.com/shorts/{job.video_id}")
            meta = (video_meta or {}).get(job.video_id, {})
            queue.enqueue(
                run_pipeline_job,
                job.job_id,
                job.video_id,
                url,
                config_dict,
                meta,
                job_timeout=900,
            )
            update_job(job.job_id, status=JobStatus.QUEUED)
        return jobs

    return jobs


def redis_available() -> bool:
    return _get_redis() is not None
