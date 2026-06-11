"""RQ worker entry point. Run: python -m app.worker"""
import logging

from rq import Worker

from app.services.job_queue import _get_redis, rq_available, _redis_major_version
from app.services.state_store import init_db

logging.basicConfig(level=logging.INFO)


def main():
    init_db()
    conn = _get_redis()
    if not conn:
        raise SystemExit(
            "Redis is not reachable. Start dedicated Redis:\n"
            "  cd E:\\tiktok_automate && docker compose up -d\n"
            "Then set REDIS_URL=redis://localhost:6380/0 in backend/.env"
        )
    if not rq_available():
        major = _redis_major_version()
        raise SystemExit(
            f"Redis {major}.x is too old for the RQ worker (needs Redis 4+).\n"
            "Your other project's Redis on :6379 cannot run RQ workers.\n"
            "Fix: run this project's Redis on port 6380:\n"
            "  docker compose up -d\n"
            "  REDIS_URL=redis://localhost:6380/0\n"
            "Or skip the worker — pipeline still runs in-process on the backend."
        )
    worker = Worker(["tiktok"], connection=conn)
    worker.work()


if __name__ == "__main__":
    main()
