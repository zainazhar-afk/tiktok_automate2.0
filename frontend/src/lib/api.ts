import { API_URL } from "@/types";
import type { AntiDetectionConfig, DiscoveryFilters, DiscoveryResult } from "@/types";

export type { AntiDetectionConfig, AntiDetectionLevel, VideoInfo, JobInfo, JobStatus, DiscoveryFilters, ProcessedVideoFile } from "@/types";
export { DEFAULT_ANTI_DETECTION, DEFAULT_FILTERS } from "@/types";

type FilterPayload = Partial<DiscoveryFilters> & { page_token?: string };

function filterBody(filters?: Partial<DiscoveryFilters>, pageToken?: string | null) {
  return {
    ...filters,
    page_token: pageToken || undefined,
  };
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
  if (!res.ok) throw new Error(await res.text());
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
  if (!res.ok) throw new Error(await res.text());
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

export async function deleteVideo(filename: string) {
  const res = await fetch(`${API_URL}/api/videos/${filename}`, { method: "DELETE" });
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
