from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class AntiDetectionLevel(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class AntiDetectionConfig(BaseModel):
    level: AntiDetectionLevel = AntiDetectionLevel.MODERATE
    mirror_padding: bool = True
    scene_reversal: bool = True
    frame_insertion: bool = True
    crop_jitter: bool = True
    color_lut: bool = True
    audio_pitch_shift: bool = True
    audio_eq: bool = True
    audio_segment_reversal: bool = False
    remove_watermark: bool = True
    remove_text_overlays: bool = True
    speed_variation: bool = False
    horizontal_flip: bool = False
    rotation_jitter: bool = False
    auto_crop_916: bool = True
    strong_audio_randomization: bool = True


class VideoInfo(BaseModel):
    id: str
    title: str
    channel: str
    duration: int
    views: Optional[int] = None
    thumbnail: Optional[str] = None
    url: str
    is_short: bool = True
    published_at: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    description: str = ""


class DownloadRequest(BaseModel):
    url: str
    video_id: str


class BatchDownloadRequest(BaseModel):
    videos: list[DownloadRequest]
    max_concurrent: int = 8


class ProcessRequest(BaseModel):
    video_id: str
    config: AntiDetectionConfig
    output_format: str = "mp4"
    title: str = ""
    channel: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class BatchProcessRequest(BaseModel):
    video_ids: list[str]
    config: AntiDetectionConfig
    output_format: str = "mp4"
    max_concurrent: int = 4
    video_meta: dict[str, dict] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str
    max_results: int = 20
    page_token: Optional[str] = None
    order: str = "relevance"  # relevance, date, viewCount, rating
    min_duration: int = 15
    max_duration: int = 90
    min_views: Optional[int] = None
    max_views: Optional[int] = None
    published_within_days: Optional[int] = None
    region_code: Optional[str] = None
    video_category_id: Optional[str] = None


class DiscoverRequest(BaseModel):
    source: str = "trending"
    query: Optional[str] = None
    max_results: int = 20
    page_token: Optional[str] = None
    order: str = "viewCount"
    min_duration: int = 15
    max_duration: int = 90
    min_views: Optional[int] = None
    max_views: Optional[int] = None
    published_within_days: Optional[int] = None
    region_code: Optional[str] = None
    video_category_id: Optional[str] = None


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobInfo(BaseModel):
    job_id: str
    video_id: str
    status: JobStatus
    progress: float = 0.0
    output_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    caption: Optional[str] = None
    hashtags: Optional[list[str]] = None
    error: Optional[str] = None
    title: str = ""
    channel: str = ""
