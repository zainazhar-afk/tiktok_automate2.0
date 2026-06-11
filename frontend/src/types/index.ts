export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type AntiDetectionLevel = "mild" | "moderate" | "aggressive";

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
  speed_variation: boolean;
  horizontal_flip: boolean;
  rotation_jitter: boolean;
  auto_crop_916: boolean;
  strong_audio_randomization: boolean;
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
  speed_variation: false,
  horizontal_flip: false,
  rotation_jitter: false,
  auto_crop_916: true,
  strong_audio_randomization: true,
};

export interface DiscoveryFilters {
  order: "relevance" | "date" | "viewCount" | "rating";
  min_duration: number;
  max_duration: number;
  min_views?: number;
  max_views?: number;
  published_within_days?: number;
  region_code?: string;
  max_results: number;
}

export const DEFAULT_FILTERS: DiscoveryFilters = {
  order: "viewCount",
  min_duration: 15,
  max_duration: 90,
  min_views: undefined,
  published_within_days: undefined,
  region_code: "US",
  max_results: 20,
};

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
  filename: string;
  path: string;
  size_mb: number;
  modified: number;
  title?: string;
  caption?: string;
  hashtags?: string[];
  cover_filename?: string | null;
}
