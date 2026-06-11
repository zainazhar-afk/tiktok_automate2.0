import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class Settings:
    youtube_api_key: str = os.getenv("YOUTUBE_API_KEY", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    max_download_concurrent: int = int(os.getenv("MAX_DOWNLOAD_CONCURRENT", "8"))
    max_process_concurrent: int = int(os.getenv("MAX_PROCESS_CONCURRENT", "4"))
    data_dir: str = os.path.abspath("data")


@lru_cache
def get_settings() -> Settings:
    os.makedirs(Settings().data_dir, exist_ok=True)
    return Settings()
