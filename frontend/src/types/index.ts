export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type AntiDetectionLevel = "mild" | "moderate" | "aggressive";
export type TextRemovalMode = "blur" | "cover" | "crop";

export interface TextRemovalRegion {
  x_pct: number;
  y_pct: number;
  w_pct: number;
  h_pct: number;
  mode?: TextRemovalMode | null;
}

export interface AntiDetectionConfig {
  level: AntiDetectionLevel;
  mirror_padding: boolean;
  scene_reversal: boolean;
  frame_insertion: boolean;
  crop_jitter: boolean;
  color_lut: boolean;
  audio_pitch_shift: boolean;
  audio_eq: boolean;
  audio_segment_reversal: boolean;
  remove_watermark: boolean;
  remove_text_overlays: boolean;
  remove_top_text_banner: boolean;
  text_removal_mode: TextRemovalMode;
  top_text_height_pct: number;
  bottom_text_height_pct: number;
  text_removal_regions: TextRemovalRegion[];
  speed_variation: boolean;
  horizontal_flip: boolean;
  rotation_jitter: boolean;
  auto_crop_916: boolean;
  strong_audio_randomization: boolean;
  random_seed?: number | null;
  smart_crop: boolean;
  background_music?: string | null;
  music_volume: number;
  music_ducking: boolean;
  voiceover_path?: string | null;
  auto_subtitles: boolean;
  subtitle_style: "default" | "bold" | "minimal";
}

export const DEFAULT_ANTI_DETECTION: AntiDetectionConfig = {
  level: "moderate",
  mirror_padding: true,
  scene_reversal: true,
  frame_insertion: true,
  crop_jitter: true,
  color_lut: true,
  audio_pitch_shift: true,
  audio_eq: true,
  audio_segment_reversal: false,
  remove_watermark: true,
  remove_text_overlays: true,
  remove_top_text_banner: false,
  text_removal_mode: "blur",
  top_text_height_pct: 0.14,
  bottom_text_height_pct: 0.15,
  text_removal_regions: [],
  speed_variation: false,
  horizontal_flip: false,
  rotation_jitter: false,
  auto_crop_916: true,
  strong_audio_randomization: true,
  random_seed: null,
  smart_crop: false,
  background_music: null,
  music_volume: 0.15,
  music_ducking: true,
  voiceover_path: null,
  auto_subtitles: false,
  subtitle_style: "default",
};

export interface DiscoveryFilters {
  order: "relevance" | "date" | "viewCount" | "rating";
  min_duration: number;
  max_duration: number;
  min_views?: number;
  max_views?: number;
  published_within_days?: number;
  region_code?: string;
  niche?: string;
  video_category_id?: string;
  max_results: number;
}

export const DEFAULT_FILTERS: DiscoveryFilters = {
  order: "viewCount",
  min_duration: 15,
  max_duration: 90,
  min_views: undefined,
  published_within_days: undefined,
  region_code: "US",
  niche: undefined,
  video_category_id: undefined,
  max_results: 20,
};

// Content niches shown in the discovery UI (must match backend NICHE_PRESETS keys)
export const NICHE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All niches" },
  { value: "motivational", label: "Motivational" },
  { value: "comedy", label: "Comedy" },
  { value: "gaming", label: "Gaming" },
  { value: "fitness", label: "Fitness" },
  { value: "sports", label: "Sports" },
  { value: "food", label: "Food / Cooking" },
  { value: "education", label: "Education / Facts" },
  { value: "tech", label: "Tech" },
  { value: "beauty", label: "Beauty" },
  { value: "pets", label: "Pets / Animals" },
  { value: "travel", label: "Travel" },
  { value: "music", label: "Music / Dance" },
];

// ISO 3166-1 alpha-2 regions for YouTube trending
export const REGION_OPTIONS: { value: string; label: string }[] = [
  { value: "US", label: "United States" },
  { value: "GB", label: "United Kingdom" },
  { value: "CA", label: "Canada" },
  { value: "AU", label: "Australia" },
  { value: "IN", label: "India" },
  { value: "DE", label: "Germany" },
  { value: "FR", label: "France" },
  { value: "ES", label: "Spain" },
  { value: "BR", label: "Brazil" },
  { value: "JP", label: "Japan" },
  { value: "KR", label: "South Korea" },
];

export interface VideoInfo {
  id: string;
  title: string;
  channel: string;
  duration: number;
  views?: number;
  thumbnail?: string;
  url: string;
  is_short: boolean;
  published_at?: string;
  tags?: string[];
  description?: string;
}

export interface DiscoveryResult {
  videos: VideoInfo[];
  total: number;
  next_page_token?: string | null;
  prev_page_token?: string | null;
  source?: string;
}

export type JobStatus = "queued" | "downloading" | "processing" | "completed" | "failed";

export interface JobInfo {
  job_id: string;
  owner_id?: string;
  video_id: string;
  status: JobStatus;
  progress: number;
  output_path?: string;
  thumbnail_path?: string;
  caption?: string;
  hashtags?: string[];
  error?: string;
  title?: string;
  channel?: string;
}

export interface ProcessedVideoFile {
  id: string;
  owner_id?: string;
  visibility_status?: "available" | "unavailable";
  unavailable_reason?: string;
  filename: string;
  path: string;
  size_mb: number;
  modified: number;
  title?: string;
  caption?: string;
  hashtags?: string[];
  cover_filename?: string | null;
}

export interface AssetLibrary {
  music: string[];
  voiceover: string[];
}

export interface SubtitleWord {
  id: string;
  text: string;
  start: number;
  end: number;
  highlighted: boolean;
}

export interface SubtitleTrack {
  video_id: string;
  language: string;
  style: "default" | "bold" | "minimal" | "neon";
  position: "top" | "middle" | "bottom";
  animation: "none" | "pop" | "slide" | "karaoke";
  transcript: string;
  words: SubtitleWord[];
  updated_at?: string | null;
}

export interface TimelineCropKeyframe {
  time: number;
  x_pct: number;
  y_pct: number;
  w_pct: number;
  h_pct: number;
}

export interface TimelineClip {
  id: string;
  title: string;
  source_start: number;
  source_end: number;
  muted: boolean;
  crop_mode: "center" | "face" | "object" | "manual" | "split";
  layout: "single" | "split";
  x_pct: number;
  y_pct: number;
  w_pct: number;
  h_pct: number;
  keyframes: TimelineCropKeyframe[];
  broll_source?: string | null;
  broll_mode: "none" | "cover" | "pip" | "split";
  broll_start: number;
  auto_zoom: boolean;
  zoom_strength: number;
}

export interface TimelineProject {
  video_id: string;
  clips: TimelineClip[];
  crop_mode: "center" | "face" | "object" | "manual" | "split";
  keep_face_centered: boolean;
  split_layout: "speaker_gameplay";
  jump_cut_cleanup: boolean;
  auto_captions: boolean;
  hook_title: string;
  hook_subtitle: string;
  brand_template: "none" | "creator" | "product" | "podcast";
  brand_name: string;
  brand_primary_color: string;
  brand_accent_color: string;
  updated_at?: string | null;
}

export interface TimelineRenderResponse {
  video_id: string;
  output_path: string;
  filename: string;
}

export interface TimelineHookSuggestion {
  title: string;
  subtitle: string;
  angle: string;
  confidence: number;
}

export interface TimelineHookResponse {
  suggestions: TimelineHookSuggestion[];
  provider: string;
}

export interface TimelineSmartCropResponse {
  project: TimelineProject;
  clip_id: string;
  mode: "face" | "object";
  keyframes: number;
  detections: number;
  frames_analyzed: number;
  confidence: number;
  tracker: string;
  message: string;
}

export interface TimelineQueueJob {
  job_id: string;
  owner_id?: string;
  video_id: string;
  title: string;
  status: "queued" | "running" | "paused" | "completed" | "failed";
  progress: number;
  message: string;
  error: string;
  source_filename?: string | null;
  output_filename?: string | null;
  pause_requested: boolean;
  created_at: string;
  updated_at: string;
}

export interface TimelineCoverResponse {
  video_id: string;
  cover_filename: string;
  output_path: string;
  selected_time: number;
  platform: "tiktok" | "reels" | "shorts";
}

export interface ClipScoreMetric {
  label: string;
  value: number;
  detail: string;
}

export interface TimelineClipScore {
  clip_id: string;
  title: string;
  overall: number;
  metrics: ClipScoreMetric[];
  reasons: string[];
}

export interface TimelineScoreResponse {
  video_id: string;
  scores: TimelineClipScore[];
  analysis: {
    silence_segments?: number;
    scene_changes?: number;
    transcript_words?: number;
  };
}

export interface VariantUploadResponse {
  upload_id: string;
  filename: string;
}

export interface VariantSourceStatus {
  upload_id: string;
  url: string;
  filename: string;
  status: "queued" | "downloading" | "completed" | "failed";
  progress: number;
  message: string;
  error: string;
  created_at?: string;
  updated_at?: string;
}

export interface VariantSpec {
  id: string;
  title: string;
  hook: string;
  start: number;
  end: number;
  angle: string;
  compliance_note: string;
  score: number;
  reasons: string[];
  transcript_excerpt: string;
  source_signals: string[];
}

export interface VariantFile extends VariantSpec {
  filename: string;
  output_path: string;
}

export interface VariantGenerationResponse {
  upload_id: string;
  ai_planned: boolean;
  variants: VariantSpec[];
  files: VariantFile[];
  analysis: {
    duration?: number;
    transcript_available?: boolean;
    transcript_cues?: number;
    silence_segments?: number;
    scene_changes?: number;
    candidate_count?: number;
    planner?: string;
    signals?: string[];
  };
}

export interface AccountUsageItem {
  label: string;
  used: number;
  limit: number;
  remaining?: number | null;
}

export interface AccountStatus {
  user_id: string;
  email: string;
  plan: string;
  subscription_status: string;
  subscription_active: boolean;
  billing_required: boolean;
  rights_required: boolean;
  rights_accepted: boolean;
  period_start: string;
  usage: Record<string, AccountUsageItem>;
  stripe_configured: boolean;
  stripe_customer_id: string;
}
