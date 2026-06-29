import { API_URL } from "@/types";
import type {
  AntiDetectionConfig,
  AssetLibrary,
  DiscoveryFilters,
  DiscoveryResult,
  SubtitleTrack,
  TimelineCoverResponse,
  TimelineQueueJob,
  TimelineHookResponse,
  TimelineProject,
  TimelineRenderResponse,
  TimelineScoreResponse,
  TimelineSmartCropResponse,
  VariantGenerationResponse,
  VariantSourceStatus,
  VariantUploadResponse,
} from "@/types";

export type { AntiDetectionConfig, AntiDetectionLevel, VideoInfo, JobInfo, JobStatus, DiscoveryFilters, ProcessedVideoFile, AssetLibrary, SubtitleTrack, SubtitleWord, TimelineClip, TimelineCoverResponse, TimelineQueueJob, TimelineHookResponse, TimelineHookSuggestion, TimelineProject, TimelineScoreResponse, TimelineSmartCropResponse, VariantGenerationResponse } from "@/types";
export { DEFAULT_ANTI_DETECTION, DEFAULT_FILTERS } from "@/types";

function filterBody(filters?: Partial<DiscoveryFilters>, pageToken?: string | null) {
  return {
    ...filters,
    page_token: pageToken || undefined,
  };
}

/** Extract a human-readable message (FastAPI `detail`) from an error response. */
async function errorMessage(res: Response): Promise<string> {
  const raw = await res.text();
  try {
    const parsed = JSON.parse(raw);
    if (parsed?.detail) {
      if (res.status === 429) return `Quota limit: ${parsed.detail}`;
      return typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
    }
  } catch {
    // not JSON
  }
  return raw || `Request failed (${res.status})`;
}

export async function searchVideos(
  query: string,
  filters?: Partial<DiscoveryFilters>,
  pageToken?: string | null
): Promise<DiscoveryResult> {
  const res = await fetch(`${API_URL}/api/youtube/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, ...filterBody(filters, pageToken) }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function discoverContent(
  source: string,
  query?: string,
  filters?: Partial<DiscoveryFilters>,
  pageToken?: string | null
): Promise<DiscoveryResult> {
  const res = await fetch(`${API_URL}/api/youtube/discover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, query, ...filterBody(filters, pageToken) }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function downloadVideo(url: string, videoId: string, force = false) {
  const res = await fetch(`${API_URL}/api/youtube/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, video_id: videoId, force }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function batchDownload(
  videos: { url: string; video_id: string }[],
  maxConcurrent = 8
) {
  const res = await fetch(`${API_URL}/api/youtube/batch-download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ videos, max_concurrent: maxConcurrent }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function processVideo(
  videoId: string,
  config: AntiDetectionConfig,
  meta?: { title?: string; channel?: string; description?: string; tags?: string[] }
) {
  const res = await fetch(`${API_URL}/api/process/single`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      video_id: videoId,
      config,
      title: meta?.title || "",
      channel: meta?.channel || "",
      description: meta?.description || "",
      tags: meta?.tags || [],
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function pipelineProcess(
  videoIds: string[],
  config: AntiDetectionConfig,
  videoMeta?: Record<string, { url?: string; title?: string; channel?: string; description?: string; tags?: string[] }>,
  maxConcurrent = 4
) {
  const res = await fetch(`${API_URL}/api/process/pipeline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      video_ids: videoIds,
      config,
      max_concurrent: maxConcurrent,
      video_meta: videoMeta || {},
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listJobs() {
  const res = await fetch(`${API_URL}/api/process/jobs`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listStateVideos(status?: string) {
  const q = status ? `?status=${status}` : "";
  const res = await fetch(`${API_URL}/api/state/videos${q}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function syncState(items: { video_id: string; status?: string; download_path?: string; output_path?: string; title?: string; channel?: string }[]) {
  const res = await fetch(`${API_URL}/api/state/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listVideos(type: "processed" | "downloaded" = "processed") {
  const res = await fetch(`${API_URL}/api/videos/list?type=${type}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listAssets(): Promise<AssetLibrary> {
  const res = await fetch(`${API_URL}/api/videos/assets`);
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function getSubtitleTrack(videoId: string): Promise<SubtitleTrack> {
  const res = await fetch(`${API_URL}/api/editor/subtitles/${encodeURIComponent(videoId)}`);
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function saveSubtitleTrack(track: SubtitleTrack): Promise<SubtitleTrack> {
  const res = await fetch(`${API_URL}/api/editor/subtitles/${encodeURIComponent(track.video_id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(track),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export type TranscriptionProvider = "auto" | "groq" | "deepgram" | "whisper";

export interface TranscriptionOptions {
  language?: string;
  provider?: TranscriptionProvider;
  force?: boolean;
}

export async function transcribeSubtitleTrack(
  videoId: string,
  options: TranscriptionOptions = {}
): Promise<SubtitleTrack> {
  const res = await fetch(`${API_URL}/api/editor/subtitles/${encodeURIComponent(videoId)}/transcribe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      language: options.language || "auto",
      provider: options.provider || "auto",
      force: options.force ?? true,
    }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function importSubtitleTrack(
  videoId: string,
  format: "srt" | "vtt",
  content: string
): Promise<SubtitleTrack> {
  const res = await fetch(`${API_URL}/api/editor/subtitles/${encodeURIComponent(videoId)}/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format, content }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function exportSubtitleTrack(videoId: string, format: "srt" | "vtt"): Promise<string> {
  const res = await fetch(`${API_URL}/api/editor/subtitles/${encodeURIComponent(videoId)}/export?format=${format}`);
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.text();
}

export async function translateSubtitleTrack(
  videoId: string,
  targetLanguage: string,
  sourceLanguage = "en"
): Promise<SubtitleTrack> {
  const res = await fetch(`${API_URL}/api/editor/subtitles/${encodeURIComponent(videoId)}/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_language: targetLanguage, source_language: sourceLanguage }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function renderSubtitleVideo(videoId: string) {
  const res = await fetch(`${API_URL}/api/editor/subtitles/${encodeURIComponent(videoId)}/render`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function getTimelineProject(videoId: string): Promise<TimelineProject> {
  const res = await fetch(`${API_URL}/api/timeline/${encodeURIComponent(videoId)}`);
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function saveTimelineProject(project: TimelineProject): Promise<TimelineProject> {
  const res = await fetch(`${API_URL}/api/timeline/${encodeURIComponent(project.video_id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(project),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function renderTimelineProject(project: TimelineProject): Promise<TimelineRenderResponse> {
  const res = await fetch(`${API_URL}/api/timeline/${encodeURIComponent(project.video_id)}/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(project),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function enqueueTimelineRender(project: TimelineProject): Promise<TimelineQueueJob> {
  const res = await fetch(`${API_URL}/api/timeline/${encodeURIComponent(project.video_id)}/queue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function listTimelineQueue(): Promise<{ jobs: TimelineQueueJob[] }> {
  const res = await fetch(`${API_URL}/api/timeline/queue/jobs`);
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function pauseTimelineQueueJob(jobId: string): Promise<TimelineQueueJob> {
  const res = await fetch(`${API_URL}/api/timeline/queue/${encodeURIComponent(jobId)}/pause`, { method: "POST" });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function resumeTimelineQueueJob(jobId: string): Promise<TimelineQueueJob> {
  const res = await fetch(`${API_URL}/api/timeline/queue/${encodeURIComponent(jobId)}/resume`, { method: "POST" });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function retryTimelineQueueJob(jobId: string): Promise<TimelineQueueJob> {
  const res = await fetch(`${API_URL}/api/timeline/queue/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function applyTimelineSilenceCuts(project: TimelineProject): Promise<TimelineProject> {
  const res = await fetch(`${API_URL}/api/timeline/${encodeURIComponent(project.video_id)}/silence-cuts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function generateTimelineHooks(project: TimelineProject): Promise<TimelineHookResponse> {
  const res = await fetch(`${API_URL}/api/timeline/${encodeURIComponent(project.video_id)}/hooks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function generateTimelineCover(
  project: TimelineProject,
  headline: string,
  platform: "tiktok" | "reels" | "shorts" = "tiktok"
): Promise<TimelineCoverResponse> {
  const res = await fetch(`${API_URL}/api/timeline/${encodeURIComponent(project.video_id)}/cover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project,
      headline,
      brand_name: project.brand_name,
      brand_color: project.brand_primary_color,
      accent_color: project.brand_accent_color,
      platform,
    }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function scoreTimelineProject(project: TimelineProject): Promise<TimelineScoreResponse> {
  const res = await fetch(`${API_URL}/api/timeline/${encodeURIComponent(project.video_id)}/score`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function applyTimelineSmartCrop(
  project: TimelineProject,
  clipId: string,
  mode: "face" | "object"
): Promise<TimelineSmartCropResponse> {
  const res = await fetch(`${API_URL}/api/timeline/${encodeURIComponent(project.video_id)}/smart-crop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project, clip_id: clipId, mode, sample_interval: 0.5 }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function uploadVariantSource(file: File): Promise<VariantUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_URL}/api/variants/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function createVariantSourceFromUrl(url: string): Promise<VariantUploadResponse> {
  const res = await fetch(`${API_URL}/api/variants/from-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function startVariantSourceFromUrl(url: string): Promise<VariantSourceStatus> {
  const res = await fetch(`${API_URL}/api/variants/from-url/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function getVariantSourceStatus(uploadId: string): Promise<VariantSourceStatus> {
  const res = await fetch(`${API_URL}/api/variants/${encodeURIComponent(uploadId)}/source-status`);
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function generateVariants(uploadId: string): Promise<VariantGenerationResponse> {
  const res = await fetch(`${API_URL}/api/variants/${encodeURIComponent(uploadId)}/generate`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function deleteVideo(filename: string) {
  const res = await fetch(`${API_URL}/api/videos/${encodeURIComponent(filename)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function checkHealth() {
  const res = await fetch(`${API_URL}/api/health`);
  return res.json();
}

export function subscribeEvents(onEvent: (data: unknown) => void): () => void {
  const es = new EventSource(`${API_URL}/api/events/stream`);
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      // ignore keepalive
    }
  };
  return () => es.close();
}
