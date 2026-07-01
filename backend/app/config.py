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
    uploads_dir: str = os.path.abspath(os.getenv("UPLOADS_DIR", "uploads"))
    app_environment: str = os.getenv("APP_ENVIRONMENT", "development")
    require_auth: bool = os.getenv("REQUIRE_AUTH", "false").lower() in {"1", "true", "yes"}
    cors_origins_raw: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001")
    service_api_key: str = os.getenv("SERVICE_API_KEY", "")
    allowed_video_hosts_raw: str = os.getenv(
        "ALLOWED_VIDEO_HOSTS",
        "youtube.com,youtu.be,tiktok.com,vimeo.com,instagram.com,facebook.com,fb.watch,loom.com",
    )
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "1024"))
    max_download_mb: int = int(os.getenv("MAX_DOWNLOAD_MB", "1024"))
    max_source_duration_seconds: int = int(os.getenv("MAX_SOURCE_DURATION_SECONDS", "14400"))
    billing_required: bool = os.getenv("BILLING_REQUIRED", "false").lower() in {"1", "true", "yes"}
    require_rights_attestation: bool = os.getenv("REQUIRE_RIGHTS_ATTESTATION", "false").lower() in {"1", "true", "yes"}
    default_plan: str = os.getenv("DEFAULT_PLAN", "pro")
    allowed_subscription_statuses_raw: str = os.getenv("ALLOWED_SUBSCRIPTION_STATUSES", "active,trialing")
    monthly_download_limit: int = int(os.getenv("MONTHLY_DOWNLOAD_LIMIT", "500"))
    monthly_process_limit: int = int(os.getenv("MONTHLY_PROCESS_LIMIT", "500"))
    monthly_transcription_limit: int = int(os.getenv("MONTHLY_TRANSCRIPTION_LIMIT", "500"))
    monthly_variant_limit: int = int(os.getenv("MONTHLY_VARIANT_LIMIT", "100"))
    monthly_timeline_render_limit: int = int(os.getenv("MONTHLY_TIMELINE_RENDER_LIMIT", "500"))
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    stripe_price_id: str = os.getenv("STRIPE_PRICE_ID", "")
    stripe_portal_return_url: str = os.getenv("STRIPE_PORTAL_RETURN_URL", "")
    app_url: str = os.getenv("APP_URL", "http://localhost:3001")

    # Whisper model size for auto subtitles: tiny|base|small|medium|large-v3
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")
    transcription_provider: str = os.getenv("TRANSCRIPTION_PROVIDER", "auto")
    # Asset directories for background music / voiceover tracks
    assets_dir: str = os.path.abspath(os.getenv("ASSETS_DIR", "assets"))
    google_ai_model: str = os.getenv("GOOGLE_AI_MODEL", "gemini-2.0-flash")
    google_ai_api_keys_raw: str = os.getenv("GOOGLE_AI_API_KEYS", "")
    groq_api_keys_raw: str = os.getenv("GROQ_API_KEYS", "")
    groq_chat_model: str = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-120b")
    groq_transcription_model: str = os.getenv("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo")
    groq_language: str = os.getenv("GROQ_LANGUAGE", "auto")
    deepgram_api_keys_raw: str = os.getenv("DEEPGRAM_API_KEYS", "")
    deepgram_model: str = os.getenv("DEEPGRAM_MODEL", "nova-3")
    deepgram_language: str = os.getenv("DEEPGRAM_LANGUAGE", "auto")
    state_store_backend: str = os.getenv("STATE_STORE_BACKEND", "sqlite")
    database_url: str = os.getenv("DATABASE_URL", "")
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_publishable_key: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    supabase_secret_key: str = os.getenv("SUPABASE_SECRET_KEY", "")
    supabase_jwks_url: str = os.getenv("SUPABASE_JWKS_URL", "")
    supabase_db_url: str = os.getenv("SUPABASE_DB_URL", "")
    state_store_fallback_to_sqlite: bool = os.getenv("STATE_STORE_FALLBACK_TO_SQLITE", "true").lower() not in {"0", "false", "no"}

    @property
    def google_ai_api_keys(self) -> list[str]:
        raw = self.google_ai_api_keys_raw.replace("\n", ",").replace(";", ",")
        return [key.strip() for key in raw.split(",") if key.strip()]

    @property
    def groq_api_keys(self) -> list[str]:
        raw = self.groq_api_keys_raw.replace("\n", ",").replace(";", ",")
        return [key.strip() for key in raw.split(",") if key.strip()]

    @property
    def deepgram_api_keys(self) -> list[str]:
        raw = self.deepgram_api_keys_raw.replace("\n", ",").replace(";", ",")
        return [key.strip() for key in raw.split(",") if key.strip()]

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_origins_raw.replace("\n", ",").replace(";", ",")
        return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]

    @property
    def allowed_video_hosts(self) -> list[str]:
        raw = self.allowed_video_hosts_raw.replace("\n", ",").replace(";", ",")
        return [host.strip().lower() for host in raw.split(",") if host.strip()]

    @property
    def allowed_subscription_statuses(self) -> set[str]:
        raw = self.allowed_subscription_statuses_raw.replace("\n", ",").replace(";", ",")
        return {status.strip().lower() for status in raw.split(",") if status.strip()}

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
    os.makedirs(s.uploads_dir, exist_ok=True)
    os.makedirs(s.music_dir, exist_ok=True)
    os.makedirs(s.voiceover_dir, exist_ok=True)
    return s


def validate_runtime_settings(settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    if settings.app_environment.lower() == "production":
        if not settings.require_auth:
            raise RuntimeError("REQUIRE_AUTH=true is required when APP_ENVIRONMENT=production")
        if not settings.supabase_url or not settings.supabase_jwks_url:
            raise RuntimeError("SUPABASE_URL and SUPABASE_JWKS_URL are required in production")
    return settings
