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

    # Whisper model size for auto subtitles: tiny|base|small|medium|large-v3
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")
    # Asset directories for background music / voiceover tracks
    assets_dir: str = os.path.abspath(os.getenv("ASSETS_DIR", "assets"))

    @property
    def music_dir(self) -> str:
        return os.path.join(self.assets_dir, "music")

    @property
    def voiceover_dir(self) -> str:
        return os.path.join(self.assets_dir, "voiceover")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    os.makedirs(s.data_dir, exist_ok=True)
    os.makedirs(s.music_dir, exist_ok=True)
    os.makedirs(s.voiceover_dir, exist_ok=True)
    return s
