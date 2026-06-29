from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class AntiDetectionLevel(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class TextRemovalMode(str, Enum):
    BLUR = "blur"
    COVER = "cover"
    CROP = "crop"


class TextRemovalRegion(BaseModel):
    x_pct: float = Field(0.0, ge=0.0, le=1.0)
    y_pct: float = Field(0.0, ge=0.0, le=1.0)
    w_pct: float = Field(1.0, ge=0.01, le=1.0)
    h_pct: float = Field(0.15, ge=0.01, le=1.0)
    mode: Optional[TextRemovalMode] = None


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
    remove_top_text_banner: bool = False
    text_removal_mode: TextRemovalMode = TextRemovalMode.BLUR
    top_text_height_pct: float = Field(0.14, ge=0.02, le=0.45)
    bottom_text_height_pct: float = Field(0.15, ge=0.02, le=0.45)
    text_removal_regions: list[TextRemovalRegion] = Field(default_factory=list)
    speed_variation: bool = False
    horizontal_flip: bool = False
    rotation_jitter: bool = False
    auto_crop_916: bool = True
    strong_audio_randomization: bool = True

    # Per-video fingerprint seed (auto-generated per render when None)
    random_seed: Optional[int] = None

    # Smart, content-aware crop using ffmpeg cropdetect (removes letter/pillarbox)
    smart_crop: bool = False

    # Background music / voiceover layering with auto-ducking
    background_music: Optional[str] = None   # filename inside the assets/music dir
    music_volume: float = 0.15               # 0..1, music level under speech
    music_ducking: bool = True               # duck music under speech via sidechain
    voiceover_path: Optional[str] = None     # filename inside assets/voiceover dir

    # Auto subtitles (burned in via whisper transcription)
    auto_subtitles: bool = False
    subtitle_style: str = "default"          # default | bold | minimal


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
    niche: Optional[str] = None  # motivational, comedy, gaming, etc.


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
    niche: Optional[str] = None  # motivational, comedy, gaming, etc.


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


class SubtitleWord(BaseModel):
    id: str
    text: str
    start: float
    end: float
    highlighted: bool = False


class SubtitleTrack(BaseModel):
    video_id: str
    language: str = "en"
    style: str = "default"
    position: str = "bottom"
    animation: str = "none"
    transcript: str = ""
    words: list[SubtitleWord] = Field(default_factory=list)
    updated_at: Optional[str] = None


class SubtitleImportRequest(BaseModel):
    format: str = "srt"
    content: str


class SubtitleTranscribeRequest(BaseModel):
    language: str = "auto"
    provider: str = "auto"  # auto | groq | deepgram | whisper
    force: bool = True


class SubtitleTranslateRequest(BaseModel):
    target_language: str
    source_language: str = "en"


class SubtitleRenderResponse(BaseModel):
    video_id: str
    output_path: str
    filename: str


class TimelineCropKeyframe(BaseModel):
    time: float = Field(0.0, ge=0.0)
    x_pct: float = Field(0.0, ge=0.0, le=1.0)
    y_pct: float = Field(0.0, ge=0.0, le=1.0)
    w_pct: float = Field(1.0, ge=0.05, le=1.0)
    h_pct: float = Field(1.0, ge=0.05, le=1.0)


class TimelineClip(BaseModel):
    id: str
    title: str = ""
    source_start: float = Field(0.0, ge=0.0)
    source_end: float = Field(30.0, gt=0.0)
    muted: bool = False
    crop_mode: str = "center"  # center | face | object | manual | split
    layout: str = "single"     # single | split
    x_pct: float = Field(0.0, ge=0.0, le=1.0)
    y_pct: float = Field(0.0, ge=0.0, le=1.0)
    w_pct: float = Field(1.0, ge=0.05, le=1.0)
    h_pct: float = Field(1.0, ge=0.05, le=1.0)
    keyframes: list[TimelineCropKeyframe] = Field(default_factory=list)
    broll_source: Optional[str] = None
    broll_mode: str = "none"  # none | cover | pip | split
    broll_start: float = Field(0.0, ge=0.0)
    auto_zoom: bool = False
    zoom_strength: float = Field(0.06, ge=0.0, le=0.2)


class TimelineProject(BaseModel):
    video_id: str
    clips: list[TimelineClip] = Field(default_factory=list)
    crop_mode: str = "center"
    keep_face_centered: bool = False
    split_layout: str = "speaker_gameplay"
    jump_cut_cleanup: bool = False
    auto_captions: bool = False
    hook_title: str = ""
    hook_subtitle: str = ""
    brand_template: str = "none"  # none | creator | product | podcast
    brand_name: str = ""
    brand_primary_color: str = "#06b6d4"
    brand_accent_color: str = "#facc15"
    updated_at: Optional[str] = None


class TimelineRenderResponse(BaseModel):
    video_id: str
    output_path: str
    filename: str


class TimelineSilenceCutRequest(BaseModel):
    project: TimelineProject
    noise_db: float = Field(-35.0, ge=-80.0, le=-10.0)
    min_silence: float = Field(0.45, ge=0.1, le=3.0)
    padding: float = Field(0.08, ge=0.0, le=1.0)
    min_clip: float = Field(0.75, ge=0.2, le=5.0)


class TimelineHookSuggestion(BaseModel):
    title: str
    subtitle: str = ""
    angle: str = "hook"
    confidence: float = Field(0.0, ge=0.0, le=100.0)


class TimelineHookRequest(BaseModel):
    project: TimelineProject


class TimelineHookResponse(BaseModel):
    suggestions: list[TimelineHookSuggestion]
    provider: str = "local"


class TimelineSmartCropRequest(BaseModel):
    project: TimelineProject
    clip_id: Optional[str] = None
    mode: str = "face"  # face | object
    sample_interval: float = Field(0.5, ge=0.25, le=2.0)


class TimelineSmartCropResponse(BaseModel):
    project: TimelineProject
    clip_id: str
    mode: str
    keyframes: int
    detections: int
    frames_analyzed: int
    confidence: float = Field(0.0, ge=0.0, le=100.0)
    tracker: str = "opencv"
    message: str = ""


class TimelineQueueRequest(BaseModel):
    project: TimelineProject


class TimelineQueueJob(BaseModel):
    job_id: str
    video_id: str
    title: str = ""
    status: str = "queued"  # queued | running | paused | completed | failed
    progress: float = Field(0.0, ge=0.0, le=1.0)
    message: str = ""
    error: str = ""
    source_filename: Optional[str] = None
    output_filename: Optional[str] = None
    pause_requested: bool = False
    created_at: str = ""
    updated_at: str = ""


class TimelineCoverRequest(BaseModel):
    project: TimelineProject
    headline: str = ""
    brand_name: str = ""
    brand_color: str = "#06b6d4"
    accent_color: str = "#facc15"
    platform: str = "tiktok"  # tiktok | reels | shorts


class TimelineCoverResponse(BaseModel):
    video_id: str
    cover_filename: str
    output_path: str
    selected_time: float = 0.0
    platform: str = "tiktok"


class ClipScoreMetric(BaseModel):
    label: str
    value: float = Field(0.0, ge=0.0, le=100.0)
    detail: str = ""


class TimelineClipScore(BaseModel):
    clip_id: str
    title: str = ""
    overall: float = Field(0.0, ge=0.0, le=100.0)
    metrics: list[ClipScoreMetric] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class TimelineScoreRequest(BaseModel):
    project: TimelineProject


class TimelineScoreResponse(BaseModel):
    video_id: str
    scores: list[TimelineClipScore]
    analysis: dict = Field(default_factory=dict)


class VariantUploadResponse(BaseModel):
    upload_id: str
    filename: str


class VariantUrlRequest(BaseModel):
    url: str


class VariantSpec(BaseModel):
    id: str
    title: str
    hook: str
    start: float = Field(0.0, ge=0.0)
    end: float = Field(30.0, gt=0.0)
    angle: str = "short-form"
    compliance_note: str = "Cropped to 9:16 with original audio retained."
    score: float = Field(0.0, ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)
    transcript_excerpt: str = ""
    source_signals: list[str] = Field(default_factory=list)


class VariantGenerationResponse(BaseModel):
    upload_id: str
    ai_planned: bool = False
    variants: list[VariantSpec]
    files: list[dict] = Field(default_factory=list)
    analysis: dict = Field(default_factory=dict)
