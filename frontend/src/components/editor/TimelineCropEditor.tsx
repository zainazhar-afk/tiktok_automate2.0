"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { API_URL } from "@/types";
import type { ProcessedVideoFile, TimelineClip, TimelineClipScore, TimelineHookSuggestion, TimelineProject, TimelineQueueJob } from "@/types";
import {
  applyTimelineSilenceCuts,
  applyTimelineSmartCrop,
  enqueueTimelineRender,
  generateTimelineCover,
  generateTimelineHooks,
  getTimelineProject,
  listTimelineQueue,
  listVideos,
  pauseTimelineQueueJob,
  renderTimelineProject,
  retryTimelineQueueJob,
  resumeTimelineQueueJob,
  saveTimelineProject,
  scoreTimelineProject,
} from "@/lib/api";

function cloneProject(project: TimelineProject): TimelineProject {
  return JSON.parse(JSON.stringify(project)) as TimelineProject;
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, value));
}

const BRAND_TEMPLATES: { value: TimelineProject["brand_template"]; label: string; primary: string; accent: string }[] = [
  { value: "none", label: "No brand overlay", primary: "#06b6d4", accent: "#facc15" },
  { value: "creator", label: "Creator lower-third", primary: "#22c55e", accent: "#facc15" },
  { value: "product", label: "Product launch", primary: "#38bdf8", accent: "#fb7185" },
  { value: "podcast", label: "Podcast clean", primary: "#a78bfa", accent: "#f8fafc" },
];

function normalizeClip(clip: TimelineClip): TimelineClip {
  return {
    ...clip,
    broll_source: clip.broll_source || null,
    broll_mode: clip.broll_mode || "none",
    broll_start: clip.broll_start ?? 0,
    auto_zoom: clip.auto_zoom ?? false,
    zoom_strength: clip.zoom_strength ?? 0.06,
    keyframes: clip.keyframes || [],
  };
}

function normalizeProject(project: TimelineProject): TimelineProject {
  return {
    ...project,
    clips: (project.clips || []).map(normalizeClip),
    jump_cut_cleanup: project.jump_cut_cleanup ?? false,
    auto_captions: project.auto_captions ?? false,
    hook_title: project.hook_title || "",
    hook_subtitle: project.hook_subtitle || "",
    brand_template: project.brand_template || "none",
    brand_name: project.brand_name || "",
    brand_primary_color: project.brand_primary_color || "#06b6d4",
    brand_accent_color: project.brand_accent_color || "#facc15",
  };
}

function makeClip(from: TimelineClip, patch: Partial<TimelineClip> = {}): TimelineClip {
  return {
    ...normalizeClip(from),
    ...patch,
    id: patch.id || crypto.randomUUID().slice(0, 10),
    keyframes: patch.keyframes || [...(from.keyframes || [])],
    broll_mode: patch.broll_mode || from.broll_mode || "none",
    broll_start: patch.broll_start ?? from.broll_start ?? 0,
    auto_zoom: patch.auto_zoom ?? from.auto_zoom ?? false,
    zoom_strength: patch.zoom_strength ?? from.zoom_strength ?? 0.06,
  };
}

function formatRange(clip: TimelineClip) {
  return `${clip.source_start.toFixed(1)}s - ${clip.source_end.toFixed(1)}s`;
}

function scoreClass(value: number) {
  if (value >= 80) return "bg-emerald-500";
  if (value >= 60) return "bg-yellow-500";
  return "bg-red-500";
}

function statusClass(status: TimelineQueueJob["status"]) {
  if (status === "completed") return "border-emerald-800 bg-emerald-950/30 text-emerald-200";
  if (status === "failed") return "border-red-800 bg-red-950/40 text-red-200";
  if (status === "running") return "border-cyan-800 bg-cyan-950/30 text-cyan-200";
  if (status === "paused") return "border-yellow-800 bg-yellow-950/30 text-yellow-200";
  return "border-gray-700 bg-gray-950 text-gray-300";
}

export default function TimelineCropEditor() {
  const params = useSearchParams();
  const requestedVideo = params.get("video");
  const [videos, setVideos] = useState<ProcessedVideoFile[]>([]);
  const [activeId, setActiveId] = useState(requestedVideo || "");
  const [project, setProject] = useState<TimelineProject | null>(null);
  const [selectedClipId, setSelectedClipId] = useState("");
  const [undoStack, setUndoStack] = useState<TimelineProject[]>([]);
  const [redoStack, setRedoStack] = useState<TimelineProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [toolBusy, setToolBusy] = useState<string | null>(null);
  const [hookSuggestions, setHookSuggestions] = useState<TimelineHookSuggestion[]>([]);
  const [smartCropSummary, setSmartCropSummary] = useState<string | null>(null);
  const [queueJobs, setQueueJobs] = useState<TimelineQueueJob[]>([]);
  const [queueLoading, setQueueLoading] = useState(false);
  const [coverHeadline, setCoverHeadline] = useState("");
  const [coverPlatform, setCoverPlatform] = useState<"tiktok" | "reels" | "shorts">("tiktok");
  const [coverPreview, setCoverPreview] = useState<string | null>(null);
  const [clipScores, setClipScores] = useState<TimelineClipScore[]>([]);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeVideo = videos.find((video) => video.id === activeId) || null;
  const selectedClip = project?.clips.find((clip) => clip.id === selectedClipId) || project?.clips[0] || null;
  const brollVideos = videos.filter((video) => video.filename !== activeVideo?.filename);
  const previewUrl = activeVideo ? `${API_URL}/api/videos/file/${encodeURIComponent(activeVideo.filename)}` : "";

  const totalDuration = useMemo(() => {
    return project?.clips.reduce((sum, clip) => sum + Math.max(0, clip.source_end - clip.source_start), 0) || 0;
  }, [project]);

  const activeScore = useMemo(() => {
    if (!selectedClip) return null;
    return clipScores.find((score) => score.clip_id === selectedClip.id) || null;
  }, [clipScores, selectedClip]);

  const loadVideos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listVideos("processed");
      const nextVideos = data.videos || [];
      setVideos(nextVideos);
      if (!activeId && nextVideos.length) {
        setActiveId(requestedVideo || nextVideos[0].id);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeId, requestedVideo]);

  const loadProject = useCallback(async (videoId: string) => {
    if (!videoId) return;
    setError(null);
    try {
      const data = normalizeProject(await getTimelineProject(videoId));
      setProject(data);
      setSelectedClipId(data.clips[0]?.id || "");
      setUndoStack([]);
      setRedoStack([]);
      setHookSuggestions([]);
      setSmartCropSummary(null);
      setClipScores([]);
      setCoverPreview(null);
      setCoverHeadline(data.hook_title || data.clips[0]?.title || "");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const loadQueue = useCallback(async (quiet = false) => {
    if (!quiet) setQueueLoading(true);
    try {
      const data = await listTimelineQueue();
      setQueueJobs(data.jobs || []);
    } catch (e: unknown) {
      if (!quiet) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (!quiet) setQueueLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void loadVideos(), 0);
    return () => clearTimeout(timer);
  }, [loadVideos]);

  useEffect(() => {
    if (!activeId) return;
    const timer = setTimeout(() => void loadProject(activeId), 0);
    return () => clearTimeout(timer);
  }, [activeId, loadProject]);

  useEffect(() => {
    const immediate = window.setTimeout(() => void loadQueue(true), 0);
    const timer = window.setInterval(() => void loadQueue(true), 2500);
    return () => {
      window.clearTimeout(immediate);
      window.clearInterval(timer);
    };
  }, [loadQueue]);

  const commit = (updater: (draft: TimelineProject) => TimelineProject) => {
    if (!project) return;
    const before = cloneProject(project);
    const after = normalizeProject(updater(cloneProject(project)));
    setUndoStack((prev) => [before, ...prev].slice(0, 30));
    setRedoStack([]);
    setProject(after);
    setClipScores([]);
  };

  const updateClip = (clipId: string, patch: Partial<TimelineClip>) => {
    commit((draft) => ({
      ...draft,
      clips: draft.clips.map((clip) => (
        clip.id === clipId
          ? {
              ...clip,
              ...patch,
              source_start: patch.source_start === undefined ? clip.source_start : clamp(patch.source_start, 0, 99999),
              source_end: patch.source_end === undefined ? clip.source_end : clamp(patch.source_end, 0.1, 99999),
              x_pct: patch.x_pct === undefined ? clip.x_pct : clamp(patch.x_pct, 0, 1),
              y_pct: patch.y_pct === undefined ? clip.y_pct : clamp(patch.y_pct, 0, 1),
              w_pct: patch.w_pct === undefined ? clip.w_pct : clamp(patch.w_pct, 0.05, 1),
              h_pct: patch.h_pct === undefined ? clip.h_pct : clamp(patch.h_pct, 0.05, 1),
              broll_start: patch.broll_start === undefined ? clip.broll_start : clamp(patch.broll_start, 0, 99999),
              zoom_strength: patch.zoom_strength === undefined ? clip.zoom_strength : clamp(patch.zoom_strength, 0, 0.2),
            }
          : clip
      )),
    }));
  };

  const undo = () => {
    if (!project || undoStack.length === 0) return;
    const [next, ...rest] = undoStack;
    setRedoStack((prev) => [cloneProject(project), ...prev]);
    setProject(next);
    setUndoStack(rest);
    setSelectedClipId(next.clips[0]?.id || "");
  };

  const redo = () => {
    if (!project || redoStack.length === 0) return;
    const [next, ...rest] = redoStack;
    setUndoStack((prev) => [cloneProject(project), ...prev]);
    setProject(next);
    setRedoStack(rest);
    setSelectedClipId(next.clips[0]?.id || "");
  };

  const splitClip = () => {
    if (!project || !selectedClip) return;
    const midpoint = Number(((selectedClip.source_start + selectedClip.source_end) / 2).toFixed(3));
    if (midpoint <= selectedClip.source_start || midpoint >= selectedClip.source_end) return;
    commit((draft) => {
      const idx = draft.clips.findIndex((clip) => clip.id === selectedClip.id);
      const clips = [...draft.clips];
      const left = { ...clips[idx], source_end: midpoint, title: `${clips[idx].title || "Clip"} A` };
      const right = makeClip(clips[idx], {
        source_start: midpoint,
        source_end: clips[idx].source_end,
        title: `${clips[idx].title || "Clip"} B`,
      });
      clips.splice(idx, 1, left, right);
      setSelectedClipId(right.id);
      return { ...draft, clips };
    });
  };

  const duplicateClip = () => {
    if (!project || !selectedClip) return;
    commit((draft) => {
      const idx = draft.clips.findIndex((clip) => clip.id === selectedClip.id);
      const next = makeClip(selectedClip, { title: `${selectedClip.title || "Clip"} copy` });
      const clips = [...draft.clips];
      clips.splice(idx + 1, 0, next);
      setSelectedClipId(next.id);
      return { ...draft, clips };
    });
  };

  const deleteClip = () => {
    if (!project || !selectedClip || project.clips.length <= 1) return;
    commit((draft) => {
      const clips = draft.clips.filter((clip) => clip.id !== selectedClip.id);
      setSelectedClipId(clips[0]?.id || "");
      return { ...draft, clips };
    });
  };

  const moveClip = (direction: -1 | 1) => {
    if (!project || !selectedClip) return;
    commit((draft) => {
      const idx = draft.clips.findIndex((clip) => clip.id === selectedClip.id);
      const nextIdx = idx + direction;
      if (idx < 0 || nextIdx < 0 || nextIdx >= draft.clips.length) return draft;
      const clips = [...draft.clips];
      [clips[idx], clips[nextIdx]] = [clips[nextIdx], clips[idx]];
      return { ...draft, clips };
    });
  };

  const addKeyframe = () => {
    if (!selectedClip) return;
    updateClip(selectedClip.id, {
      crop_mode: "manual",
      keyframes: [
        ...(selectedClip.keyframes || []),
        {
          time: selectedClip.source_start,
          x_pct: selectedClip.x_pct,
          y_pct: selectedClip.y_pct,
          w_pct: selectedClip.w_pct,
          h_pct: selectedClip.h_pct,
        },
      ],
    });
  };

  const handleSave = async () => {
    if (!project) return;
    setSaving(true);
    setError(null);
    try {
      const saved = normalizeProject(await saveTimelineProject(project));
      setProject(saved);
      setMessage("Timeline saved");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleRender = async () => {
    if (!project) return;
    setRendering(true);
    setError(null);
    try {
      const rendered = await renderTimelineProject(project);
      await loadVideos();
      setMessage(`Rendered ${rendered.filename}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRendering(false);
    }
  };

  const setProjectPatch = (patch: Partial<TimelineProject>) => {
    commit((draft) => ({ ...draft, ...patch }));
  };

  const applyBrandTemplate = (value: TimelineProject["brand_template"]) => {
    const template = BRAND_TEMPLATES.find((item) => item.value === value) || BRAND_TEMPLATES[0];
    setProjectPatch({
      brand_template: value,
      brand_primary_color: template.primary,
      brand_accent_color: template.accent,
    });
  };

  const enableAutoZoomCuts = () => {
    commit((draft) => ({
      ...draft,
      clips: draft.clips.map((clip) => ({
        ...clip,
        auto_zoom: true,
        zoom_strength: clip.zoom_strength || 0.06,
      })),
    }));
    setMessage("Auto zoom enabled on every clip");
  };

  const handleAnalyzeSmartCrop = async () => {
    if (!project || !selectedClip) return;
    const mode = selectedClip.crop_mode === "object" ? "object" : "face";
    const before = cloneProject(project);
    setToolBusy("smart-crop");
    setError(null);
    try {
      const result = await applyTimelineSmartCrop(project, selectedClip.id, mode);
      const tracked = normalizeProject(result.project);
      setUndoStack((prev) => [before, ...prev].slice(0, 30));
      setRedoStack([]);
      setProject(tracked);
      setSelectedClipId(result.clip_id);
      setSmartCropSummary(`${result.tracker}: ${result.detections}/${result.frames_analyzed} detections, ${Math.round(result.confidence)}% confidence`);
      setMessage(`Smart crop generated ${result.keyframes} tracking keyframes`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setToolBusy(null);
    }
  };

  const handleSilenceCleanup = async () => {
    if (!project) return;
    const before = cloneProject(project);
    setToolBusy("silence");
    setError(null);
    try {
      const cleaned = normalizeProject(await applyTimelineSilenceCuts(project));
      setUndoStack((prev) => [before, ...prev].slice(0, 30));
      setRedoStack([]);
      setProject(cleaned);
      setSelectedClipId(cleaned.clips[0]?.id || "");
      setMessage(`Removed silence into ${cleaned.clips.length} speech cuts`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setToolBusy(null);
    }
  };

  const handleGenerateHooks = async () => {
    if (!project) return;
    setToolBusy("hooks");
    setError(null);
    try {
      const result = await generateTimelineHooks(project);
      setHookSuggestions(result.suggestions || []);
      if (result.suggestions?.[0]) {
        const first = result.suggestions[0];
        setProjectPatch({ hook_title: first.title, hook_subtitle: first.subtitle });
      }
      setMessage(`Generated hook ideas with ${result.provider}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setToolBusy(null);
    }
  };

  const applyHookSuggestion = (suggestion: TimelineHookSuggestion) => {
    setProjectPatch({ hook_title: suggestion.title, hook_subtitle: suggestion.subtitle });
    setCoverHeadline(suggestion.title);
  };

  const handleQueueRender = async () => {
    if (!project) return;
    setToolBusy("queue");
    setError(null);
    try {
      const job = await enqueueTimelineRender(project);
      setQueueJobs((prev) => [job, ...prev.filter((item) => item.job_id !== job.job_id)]);
      setMessage(`Queued ${job.title}`);
      void loadQueue(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setToolBusy(null);
    }
  };

  const handleQueueAction = async (jobId: string, action: "pause" | "resume" | "retry") => {
    setQueueLoading(true);
    setError(null);
    try {
      const job =
        action === "pause"
          ? await pauseTimelineQueueJob(jobId)
          : action === "resume"
            ? await resumeTimelineQueueJob(jobId)
            : await retryTimelineQueueJob(jobId);
      setQueueJobs((prev) => prev.map((item) => (item.job_id === job.job_id ? job : item)));
      setMessage(`${action[0].toUpperCase()}${action.slice(1)} requested`);
      void loadQueue(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setQueueLoading(false);
    }
  };

  const handleGenerateCover = async () => {
    if (!project) return;
    setToolBusy("cover");
    setError(null);
    try {
      const headline = coverHeadline.trim() || project.hook_title || selectedClip?.title || "New short";
      const result = await generateTimelineCover(project, headline, coverPlatform);
      setCoverPreview(`${API_URL}/api/videos/file/${encodeURIComponent(result.cover_filename)}`);
      await loadVideos();
      setMessage(`Cover generated from ${result.selected_time.toFixed(1)}s`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setToolBusy(null);
    }
  };

  const handleScoreClips = async () => {
    if (!project) return;
    setScoreLoading(true);
    setError(null);
    try {
      const result = await scoreTimelineProject(project);
      setClipScores(result.scores || []);
      setMessage(`Scored ${result.scores.length} clips`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setScoreLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Timeline & Smart Crop</h1>
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-gray-700 bg-gray-900 px-3 py-1 text-gray-300">Trim</span>
            <span className="rounded-full border border-gray-700 bg-gray-900 px-3 py-1 text-gray-300">Split</span>
            <span className="rounded-full border border-gray-700 bg-gray-900 px-3 py-1 text-gray-300">Crop</span>
            <span className="rounded-full border border-gray-700 bg-gray-900 px-3 py-1 text-gray-300">B-roll</span>
            <span className="rounded-full border border-gray-700 bg-gray-900 px-3 py-1 text-gray-300">Captions</span>
            <span className="rounded-full border border-gray-700 bg-gray-900 px-3 py-1 text-gray-300">Brand</span>
          </div>
        </div>
        <div className="flex gap-2">
          <Link href="/bulk" className="rounded bg-gray-800 px-3 py-2 text-xs text-gray-200 hover:bg-gray-700">
            Bulk
          </Link>
          <Link href="/export" className="rounded bg-blue-600 px-3 py-2 text-xs text-white hover:bg-blue-700">
            Export
          </Link>
        </div>
      </div>

      {(error || message) && (
        <div className={`rounded-lg border p-3 text-sm ${error ? "border-red-800 bg-red-950/40 text-red-200" : "border-green-800 bg-green-950/30 text-green-200"}`}>
          {error || message}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[270px_1fr_360px]">
        <aside className="rounded-lg border border-gray-700 bg-gray-900 p-3">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-gray-200">Videos</h2>
            <button onClick={loadVideos} className="rounded bg-gray-800 px-2 py-1 text-xs text-gray-300 hover:bg-gray-700">
              Refresh
            </button>
          </div>
          <div className="max-h-[620px] space-y-2 overflow-y-auto">
            {loading && <p className="text-xs text-gray-500">Loading...</p>}
            {!loading && videos.length === 0 && <p className="text-xs text-gray-500">No processed videos yet.</p>}
            {videos.map((video) => (
              <button
                key={video.filename}
                onClick={() => setActiveId(video.id)}
                className={`w-full rounded border p-2 text-left text-xs transition ${
                  activeId === video.id
                    ? "border-cyan-500 bg-cyan-950/30 text-white"
                    : "border-gray-800 bg-gray-950/50 text-gray-300 hover:border-gray-600"
                }`}
              >
                <span className="block truncate font-medium">{video.title || video.filename}</span>
                <span className="mt-1 block text-gray-500">{video.filename}</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-gray-700 bg-gray-900 p-3">
              <div className="mb-2 flex items-center justify-between text-xs text-gray-400">
                <span>Before</span>
                {selectedClip && <span>{formatRange(selectedClip)}</span>}
              </div>
              <div className="relative mx-auto aspect-[9/16] max-h-[560px] overflow-hidden rounded border border-gray-800 bg-black">
                {previewUrl ? (
                  <>
                    <video src={previewUrl} controls className="h-full w-full object-contain" preload="metadata" />
                    {selectedClip && (selectedClip.crop_mode === "manual" || selectedClip.keyframes.length > 0) && (
                      <div
                        className="pointer-events-none absolute border-2 border-cyan-300 bg-cyan-300/10"
                        style={{
                          left: `${selectedClip.x_pct * 100}%`,
                          top: `${selectedClip.y_pct * 100}%`,
                          width: `${selectedClip.w_pct * 100}%`,
                          height: `${selectedClip.h_pct * 100}%`,
                        }}
                      />
                    )}
                  </>
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-gray-500">Select a video</div>
                )}
              </div>
            </div>

            <div className="rounded-lg border border-gray-700 bg-gray-900 p-3">
              <div className="mb-2 flex items-center justify-between text-xs text-gray-400">
                <span>After</span>
                <span>{totalDuration.toFixed(1)}s total</span>
              </div>
              <div className="relative mx-auto aspect-[9/16] max-h-[560px] overflow-hidden rounded border border-cyan-900 bg-black">
                {previewUrl && selectedClip ? (
                  <>
                    {selectedClip.broll_mode === "split" || selectedClip.layout === "split" || selectedClip.crop_mode === "split" ? (
                      <div className="grid h-full grid-rows-2">
                        <video src={previewUrl} className="h-full w-full object-cover" muted playsInline preload="metadata" />
                        <video src={previewUrl} className="h-full w-full object-cover blur-sm brightness-75" muted playsInline preload="metadata" />
                      </div>
                    ) : (
                      <video
                        src={previewUrl}
                        className={`h-full w-full object-cover ${selectedClip.auto_zoom ? "scale-105" : ""}`}
                        muted
                        playsInline
                        preload="metadata"
                      />
                    )}
                    {selectedClip.broll_mode === "pip" && (
                      <div className="absolute bottom-14 right-4 aspect-[9/16] w-24 overflow-hidden rounded border border-white/40 bg-gray-950 shadow-lg">
                        <video src={previewUrl} className="h-full w-full object-cover opacity-80" muted playsInline preload="metadata" />
                      </div>
                    )}
                    {(project?.hook_title || project?.hook_subtitle) && (
                      <div className="pointer-events-none absolute left-5 right-5 top-10 text-center">
                        {project.hook_title && <div className="text-balance text-2xl font-black uppercase leading-tight text-white drop-shadow">{project.hook_title}</div>}
                        {project.hook_subtitle && <div className="mt-2 text-balance text-xs font-medium text-gray-100 drop-shadow">{project.hook_subtitle}</div>}
                      </div>
                    )}
                    {project?.brand_template !== "none" && project?.brand_name && (
                      <div
                        className="pointer-events-none absolute bottom-7 left-5 rounded border border-white/15 bg-black/65 px-3 py-1.5 text-xs font-bold uppercase tracking-wide"
                        style={{ color: project.brand_accent_color }}
                      >
                        {project.brand_name}
                      </div>
                    )}
                    {project?.auto_captions && (
                      <div className="pointer-events-none absolute bottom-20 left-6 right-6 rounded border border-white/10 bg-black/60 px-3 py-2 text-center text-sm font-bold text-white">
                        Synced captions
                      </div>
                    )}
                  </>
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-gray-500">Preview</div>
                )}
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-gray-200">Timeline</h2>
              <div className="flex flex-wrap gap-1">
                <button onClick={undo} disabled={undoStack.length === 0} title="Undo" className="h-8 w-8 rounded bg-gray-800 text-sm text-gray-200 hover:bg-gray-700 disabled:opacity-40">U</button>
                <button onClick={redo} disabled={redoStack.length === 0} title="Redo" className="h-8 w-8 rounded bg-gray-800 text-sm text-gray-200 hover:bg-gray-700 disabled:opacity-40">R</button>
                <button onClick={splitClip} disabled={!selectedClip} className="rounded bg-cyan-700 px-3 py-1.5 text-xs text-white hover:bg-cyan-600 disabled:opacity-40">Split</button>
                <button onClick={duplicateClip} disabled={!selectedClip} className="rounded bg-gray-700 px-3 py-1.5 text-xs text-white hover:bg-gray-600 disabled:opacity-40">Duplicate</button>
                <button onClick={deleteClip} disabled={!selectedClip || (project?.clips.length || 0) <= 1} className="rounded bg-red-900 px-3 py-1.5 text-xs text-red-100 hover:bg-red-800 disabled:opacity-40">Delete</button>
              </div>
            </div>
            <div className="space-y-2">
              {project?.clips.map((clip, index) => (
                <button
                  key={clip.id}
                  onClick={() => setSelectedClipId(clip.id)}
                  className={`grid w-full grid-cols-[32px_1fr_74px_74px_74px_96px] items-center gap-2 rounded border p-2 text-left text-xs ${
                    selectedClipId === clip.id
                      ? "border-cyan-500 bg-cyan-950/30"
                      : "border-gray-800 bg-gray-950/50 hover:border-gray-600"
                  }`}
                >
                  <span className="text-center text-gray-500">{index + 1}</span>
                  <span className="truncate text-gray-200">{clip.title || `Clip ${index + 1}`}</span>
                  <span className="text-gray-400">{clip.source_start.toFixed(1)}s</span>
                  <span className="text-gray-400">{clip.source_end.toFixed(1)}s</span>
                  <span className="text-gray-500">{clip.layout}</span>
                  <span className="truncate text-gray-500">
                    {[clip.keyframes.length > 1 ? "Tracked" : "", clip.broll_mode !== "none" ? "B-roll" : "", clip.auto_zoom ? "Zoom" : ""].filter(Boolean).join(" + ") || "Clean"}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-medium text-gray-200">AI Clip Score Dashboard</h2>
                {activeScore && <p className="mt-1 text-xs text-gray-500">Selected clip score: {Math.round(activeScore.overall)}%</p>}
              </div>
              <button
                onClick={handleScoreClips}
                disabled={!project || scoreLoading}
                className="rounded bg-violet-700 px-3 py-2 text-xs font-medium text-white hover:bg-violet-600 disabled:opacity-40"
              >
                {scoreLoading ? "Analyzing..." : "Analyze clips"}
              </button>
            </div>
            {clipScores.length === 0 ? (
              <div className="grid gap-2 text-xs text-gray-400 sm:grid-cols-3">
                <div className="rounded border border-gray-800 bg-gray-950/60 p-3">Hook strength, pacing, and retention signals</div>
                <div className="rounded border border-gray-800 bg-gray-950/60 p-3">Dead-air %, scene changes, and speech density</div>
                <div className="rounded border border-gray-800 bg-gray-950/60 p-3">Face visibility and caption readability</div>
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {clipScores.map((score) => (
                  <button
                    key={score.clip_id}
                    onClick={() => setSelectedClipId(score.clip_id)}
                    className={`rounded border p-3 text-left text-xs transition ${
                      selectedClipId === score.clip_id
                        ? "border-violet-500 bg-violet-950/30"
                        : "border-gray-800 bg-gray-950/50 hover:border-gray-600"
                    }`}
                  >
                    <div className="mb-3 flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-gray-100">{score.title}</div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {score.reasons.slice(0, 3).map((reason) => (
                            <span key={reason} className="rounded bg-gray-800 px-2 py-0.5 text-[11px] text-gray-300">{reason}</span>
                          ))}
                        </div>
                      </div>
                      <span className="shrink-0 rounded bg-gray-800 px-2 py-1 font-bold text-white">{Math.round(score.overall)}%</span>
                    </div>
                    <div className="grid gap-2">
                      {score.metrics.map((metric) => (
                        <div key={metric.label}>
                          <div className="mb-1 flex justify-between gap-2 text-[11px] text-gray-400">
                            <span className="truncate">{metric.label}</span>
                            <span>{Math.round(metric.value)}%</span>
                          </div>
                          <div className="h-1.5 overflow-hidden rounded bg-gray-800">
                            <div className={`h-full ${scoreClass(metric.value)}`} style={{ width: `${clamp(metric.value, 0, 100)}%` }} />
                          </div>
                          <div className="mt-1 line-clamp-1 text-[11px] text-gray-500">{metric.detail}</div>
                        </div>
                      ))}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>

        <aside className="space-y-4">
          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <h2 className="mb-3 text-sm font-medium text-gray-200">Clip</h2>
            {selectedClip ? (
              <div className="grid gap-3 text-xs">
                <label className="grid gap-1 text-gray-400">
                  Name
                  <input
                    value={selectedClip.title}
                    onChange={(e) => updateClip(selectedClip.id, { title: e.target.value })}
                    className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200"
                  />
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <label className="grid gap-1 text-gray-400">
                    Start
                    <input
                      type="number"
                      min={0}
                      step={0.1}
                      value={selectedClip.source_start}
                      onChange={(e) => updateClip(selectedClip.id, { source_start: Number(e.target.value) })}
                      className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200"
                    />
                  </label>
                  <label className="grid gap-1 text-gray-400">
                    End
                    <input
                      type="number"
                      min={0.1}
                      step={0.1}
                      value={selectedClip.source_end}
                      onChange={(e) => updateClip(selectedClip.id, { source_end: Number(e.target.value) })}
                      className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200"
                    />
                  </label>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <button onClick={() => moveClip(-1)} className="rounded bg-gray-800 px-3 py-2 text-gray-200 hover:bg-gray-700">Move up</button>
                  <button onClick={() => moveClip(1)} className="rounded bg-gray-800 px-3 py-2 text-gray-200 hover:bg-gray-700">Move down</button>
                </div>
                <label className="flex items-center gap-2 text-gray-300">
                  <input
                    type="checkbox"
                    checked={selectedClip.muted}
                    onChange={(e) => updateClip(selectedClip.id, { muted: e.target.checked })}
                    className="accent-cyan-500"
                  />
                  Mute clip
                </label>
                <div className="grid gap-2 border-t border-gray-800 pt-3">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-gray-500">B-roll insertion</div>
                  <label className="grid gap-1 text-gray-400">
                    Source
                    <select
                      value={selectedClip.broll_source || ""}
                      onChange={(e) => updateClip(selectedClip.id, {
                        broll_source: e.target.value || null,
                        broll_mode: e.target.value ? (selectedClip.broll_mode === "none" ? "cover" : selectedClip.broll_mode) : "none",
                      })}
                      className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200"
                    >
                      <option value="">No B-roll</option>
                      {brollVideos.map((video) => (
                        <option key={video.filename} value={video.filename}>
                          {video.title || video.filename}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="grid gap-1 text-gray-400">
                      Mode
                      <select
                        value={selectedClip.broll_mode}
                        onChange={(e) => updateClip(selectedClip.id, { broll_mode: e.target.value as TimelineClip["broll_mode"] })}
                        disabled={!selectedClip.broll_source}
                        className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200 disabled:opacity-50"
                      >
                        <option value="none">Off</option>
                        <option value="cover">Full cover</option>
                        <option value="pip">Picture-in-picture</option>
                        <option value="split">Split screen</option>
                      </select>
                    </label>
                    <label className="grid gap-1 text-gray-400">
                      B-roll start
                      <input
                        type="number"
                        min={0}
                        step={0.1}
                        value={selectedClip.broll_start}
                        onChange={(e) => updateClip(selectedClip.id, { broll_start: Number(e.target.value) })}
                        disabled={!selectedClip.broll_source}
                        className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200 disabled:opacity-50"
                      />
                    </label>
                  </div>
                </div>
                <div className="grid gap-2 border-t border-gray-800 pt-3">
                  <label className="flex items-center gap-2 text-gray-300">
                    <input
                      type="checkbox"
                      checked={selectedClip.auto_zoom}
                      onChange={(e) => updateClip(selectedClip.id, { auto_zoom: e.target.checked })}
                      className="accent-cyan-500"
                    />
                    Auto zoom cuts
                  </label>
                  <label className="grid gap-1 text-gray-400">
                    <span className="flex justify-between">
                      <span>Zoom strength</span>
                      <span>{Math.round(selectedClip.zoom_strength * 100)}%</span>
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={0.2}
                      step={0.01}
                      value={selectedClip.zoom_strength}
                      onChange={(e) => updateClip(selectedClip.id, { zoom_strength: Number(e.target.value), auto_zoom: true })}
                      className="accent-cyan-500"
                    />
                  </label>
                </div>
              </div>
            ) : (
              <p className="text-xs text-gray-500">Select a clip.</p>
            )}
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <h2 className="mb-3 text-sm font-medium text-gray-200">Smart Crop</h2>
            {selectedClip && (
              <div className="grid gap-3 text-xs">
                <label className="grid gap-1 text-gray-400">
                  Mode
                  <select
                    value={selectedClip.crop_mode}
                    onChange={(e) => updateClip(selectedClip.id, {
                      crop_mode: e.target.value as TimelineClip["crop_mode"],
                      layout: e.target.value === "split" ? "split" : selectedClip.layout,
                    })}
                    className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200"
                  >
                    <option value="center">Center crop</option>
                    <option value="face">Face center</option>
                    <option value="object">Object center</option>
                    <option value="manual">Manual crop</option>
                    <option value="split">Speaker + product</option>
                  </select>
                </label>
                <label className="flex items-center gap-2 text-gray-300">
                  <input
                    type="checkbox"
                    checked={project?.keep_face_centered || false}
                    onChange={(e) => setProjectPatch({ keep_face_centered: e.target.checked, crop_mode: e.target.checked ? "face" : project?.crop_mode || "center" })}
                    className="accent-cyan-500"
                  />
                  Keep face centered
                </label>
                <div className="grid gap-2 rounded border border-cyan-900/60 bg-cyan-950/20 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <div className="text-[11px] font-medium uppercase tracking-wide text-cyan-200">OpenCV tracking</div>
                      <div className="mt-0.5 text-[11px] leading-snug text-gray-500">Generates moving crop keyframes for the selected clip.</div>
                    </div>
                    <button
                      onClick={handleAnalyzeSmartCrop}
                      disabled={!project || !selectedClip || toolBusy === "smart-crop" || !["face", "object"].includes(selectedClip.crop_mode)}
                      className="shrink-0 rounded bg-cyan-700 px-3 py-2 text-xs font-medium text-white hover:bg-cyan-600 disabled:opacity-40"
                    >
                      {toolBusy === "smart-crop" ? "Analyzing..." : "Analyze"}
                    </button>
                  </div>
                  {smartCropSummary && (
                    <div className="rounded bg-gray-950/70 px-2 py-1.5 text-[11px] text-cyan-100">
                      {smartCropSummary}
                    </div>
                  )}
                </div>
                <label className="grid gap-1 text-gray-400">
                  Layout
                  <select
                    value={selectedClip.layout}
                    onChange={(e) => updateClip(selectedClip.id, { layout: e.target.value as TimelineClip["layout"] })}
                    className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200"
                  >
                    <option value="single">Single 9:16</option>
                    <option value="split">Speaker + product</option>
                  </select>
                </label>
                <div className="grid gap-2 rounded border border-gray-800 bg-gray-950/50 p-3">
                  {[
                    ["X", "x_pct", 0, 1],
                    ["Y", "y_pct", 0, 1],
                    ["Width", "w_pct", 0.05, 1],
                    ["Height", "h_pct", 0.05, 1],
                  ].map(([label, key, min, max]) => (
                    <label key={key as string} className="grid gap-1 text-gray-400">
                      <span className="flex justify-between">
                        <span>{label}</span>
                        <span>{Math.round((selectedClip[key as keyof TimelineClip] as number) * 100)}%</span>
                      </span>
                      <input
                        type="range"
                        min={min as number}
                        max={max as number}
                        step={0.01}
                        value={selectedClip[key as keyof TimelineClip] as number}
                        onChange={(e) => updateClip(selectedClip.id, { crop_mode: "manual", [key as string]: Number(e.target.value) } as Partial<TimelineClip>)}
                        className="accent-cyan-500"
                      />
                    </label>
                  ))}
                  <button onClick={addKeyframe} className="rounded bg-cyan-700 px-3 py-2 text-white hover:bg-cyan-600">
                    Add keyframe
                  </button>
                  {selectedClip.keyframes.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {selectedClip.keyframes.map((keyframe, idx) => (
                        <span key={`${keyframe.time}-${idx}`} className="rounded bg-gray-800 px-2 py-1 text-[11px] text-gray-300">
                          {keyframe.time.toFixed(1)}s
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <h2 className="mb-3 text-sm font-medium text-gray-200">More Editing Tools</h2>
            <div className="grid gap-3 text-xs">
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={handleSilenceCleanup}
                  disabled={!project || toolBusy === "silence"}
                  className="rounded bg-emerald-700 px-3 py-2 text-white hover:bg-emerald-600 disabled:opacity-40"
                >
                  {toolBusy === "silence" ? "Detecting..." : "Remove silence"}
                </button>
                <button
                  onClick={enableAutoZoomCuts}
                  disabled={!project}
                  className="rounded bg-cyan-700 px-3 py-2 text-white hover:bg-cyan-600 disabled:opacity-40"
                >
                  Auto zoom all
                </button>
              </div>
              <label className="flex items-center gap-2 text-gray-300">
                <input
                  type="checkbox"
                  checked={project?.jump_cut_cleanup || false}
                  onChange={(e) => setProjectPatch({ jump_cut_cleanup: e.target.checked })}
                  disabled={!project}
                  className="accent-emerald-500 disabled:opacity-50"
                />
                Jump cut cleanup
              </label>
              <label className="flex items-center gap-2 text-gray-300">
                <input
                  type="checkbox"
                  checked={project?.auto_captions || false}
                  onChange={(e) => setProjectPatch({ auto_captions: e.target.checked })}
                  disabled={!project}
                  className="accent-yellow-500 disabled:opacity-50"
                />
                Auto captions synced to transcript
              </label>

              <div className="grid gap-2 border-t border-gray-800 pt-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-medium uppercase tracking-wide text-gray-500">Hook/title</span>
                  <button
                    onClick={handleGenerateHooks}
                    disabled={!project || toolBusy === "hooks"}
                    className="rounded bg-yellow-700 px-2 py-1 text-[11px] text-white hover:bg-yellow-600 disabled:opacity-40"
                  >
                    {toolBusy === "hooks" ? "Generating..." : "Generate"}
                  </button>
                </div>
                <input
                  value={project?.hook_title || ""}
                  onChange={(e) => setProjectPatch({ hook_title: e.target.value })}
                  disabled={!project}
                  placeholder="Hook title"
                  className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200 disabled:opacity-50"
                />
                <input
                  value={project?.hook_subtitle || ""}
                  onChange={(e) => setProjectPatch({ hook_subtitle: e.target.value })}
                  disabled={!project}
                  placeholder="Supporting line"
                  className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200 disabled:opacity-50"
                />
                {hookSuggestions.length > 0 && (
                  <div className="grid gap-1">
                    {hookSuggestions.slice(0, 3).map((suggestion) => (
                      <button
                        key={`${suggestion.title}-${suggestion.angle}`}
                        onClick={() => applyHookSuggestion(suggestion)}
                        className="rounded border border-gray-800 bg-gray-950/70 px-2 py-2 text-left hover:border-yellow-700"
                      >
                        <span className="block truncate text-gray-100">{suggestion.title}</span>
                        <span className="mt-0.5 block truncate text-[11px] text-gray-500">{suggestion.angle} - {Math.round(suggestion.confidence)}%</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="grid gap-2 border-t border-gray-800 pt-3">
                <div className="text-[11px] font-medium uppercase tracking-wide text-gray-500">Brand kit</div>
                <label className="grid gap-1 text-gray-400">
                  Template
                  <select
                    value={project?.brand_template || "none"}
                    onChange={(e) => applyBrandTemplate(e.target.value as TimelineProject["brand_template"])}
                    disabled={!project}
                    className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200 disabled:opacity-50"
                  >
                    {BRAND_TEMPLATES.map((template) => (
                      <option key={template.value} value={template.value}>{template.label}</option>
                    ))}
                  </select>
                </label>
                <input
                  value={project?.brand_name || ""}
                  onChange={(e) => setProjectPatch({ brand_name: e.target.value })}
                  disabled={!project || project.brand_template === "none"}
                  placeholder="Brand name"
                  className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200 disabled:opacity-50"
                />
                <div className="grid grid-cols-2 gap-2">
                  <label className="grid gap-1 text-gray-400">
                    Primary
                    <input
                      type="color"
                      value={project?.brand_primary_color || "#06b6d4"}
                      onChange={(e) => setProjectPatch({ brand_primary_color: e.target.value })}
                      disabled={!project || project.brand_template === "none"}
                      className="h-9 rounded border border-gray-700 bg-gray-950 p-1 disabled:opacity-50"
                    />
                  </label>
                  <label className="grid gap-1 text-gray-400">
                    Accent
                    <input
                      type="color"
                      value={project?.brand_accent_color || "#facc15"}
                      onChange={(e) => setProjectPatch({ brand_accent_color: e.target.value })}
                      disabled={!project || project.brand_template === "none"}
                      className="h-9 rounded border border-gray-700 bg-gray-950 p-1 disabled:opacity-50"
                    />
                  </label>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-gray-200">Auto Cover</h2>
              <span className="rounded bg-gray-800 px-2 py-1 text-[11px] text-gray-400">9:16 export</span>
            </div>
            <div className="grid gap-3 text-xs">
              <label className="grid gap-1 text-gray-400">
                Headline
                <input
                  value={coverHeadline}
                  onChange={(e) => setCoverHeadline(e.target.value)}
                  disabled={!project}
                  placeholder="Cover headline"
                  className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200 disabled:opacity-50"
                />
              </label>
              <div className="grid grid-cols-[1fr_auto] gap-2">
                <label className="grid gap-1 text-gray-400">
                  Platform
                  <select
                    value={coverPlatform}
                    onChange={(e) => setCoverPlatform(e.target.value as "tiktok" | "reels" | "shorts")}
                    disabled={!project}
                    className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200 disabled:opacity-50"
                  >
                    <option value="tiktok">TikTok</option>
                    <option value="reels">Reels</option>
                    <option value="shorts">Shorts</option>
                  </select>
                </label>
                <button
                  onClick={handleGenerateCover}
                  disabled={!project || toolBusy === "cover"}
                  className="self-end rounded bg-fuchsia-700 px-3 py-2 text-white hover:bg-fuchsia-600 disabled:opacity-40"
                >
                  {toolBusy === "cover" ? "Making..." : "Generate"}
                </button>
              </div>
              {coverPreview && (
                <div className="overflow-hidden rounded border border-gray-800 bg-gray-950">
                  <img src={coverPreview} alt="Generated cover" className="aspect-[9/16] w-full object-cover" />
                </div>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-gray-200">Batch Render Queue</h2>
              <button onClick={() => void loadQueue()} disabled={queueLoading} className="rounded bg-gray-800 px-2 py-1 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-40">
                Refresh
              </button>
            </div>
            <div className="grid gap-3 text-xs">
              <button
                onClick={handleQueueRender}
                disabled={!project || toolBusy === "queue"}
                className="rounded bg-indigo-700 px-3 py-2 font-medium text-white hover:bg-indigo-600 disabled:opacity-40"
              >
                {toolBusy === "queue" ? "Queueing..." : "Queue current timeline"}
              </button>
              {queueJobs.length === 0 ? (
                <p className="rounded border border-gray-800 bg-gray-950/60 p-3 text-gray-500">No queued renders yet.</p>
              ) : (
                <div className="grid gap-2">
                  {queueJobs.slice(0, 6).map((job) => {
                    const sourceUrl = job.source_filename ? `${API_URL}/api/videos/file/${encodeURIComponent(job.source_filename)}` : "";
                    const outputUrl = job.output_filename ? `${API_URL}/api/videos/file/${encodeURIComponent(job.output_filename)}` : "";
                    return (
                      <div key={job.job_id} className="rounded border border-gray-800 bg-gray-950/60 p-3">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="truncate font-medium text-gray-100">{job.title}</div>
                            <div className="mt-1 truncate text-[11px] text-gray-500">{job.message || job.job_id}</div>
                          </div>
                          <span className={`shrink-0 rounded border px-2 py-0.5 text-[11px] ${statusClass(job.status)}`}>{job.status}</span>
                        </div>
                        <div className="mt-3 h-1.5 overflow-hidden rounded bg-gray-800">
                          <div className="h-full bg-indigo-500" style={{ width: `${clamp(job.progress * 100, 0, 100)}%` }} />
                        </div>
                        {job.error && <div className="mt-2 line-clamp-2 text-[11px] text-red-300">{job.error}</div>}
                        <div className="mt-3 flex flex-wrap gap-2">
                          {job.status === "queued" || job.status === "running" ? (
                            <button onClick={() => void handleQueueAction(job.job_id, "pause")} className="rounded bg-gray-800 px-2 py-1 text-gray-200 hover:bg-gray-700">
                              Pause
                            </button>
                          ) : null}
                          {job.status === "paused" && (
                            <button onClick={() => void handleQueueAction(job.job_id, "resume")} className="rounded bg-cyan-700 px-2 py-1 text-white hover:bg-cyan-600">
                              Resume
                            </button>
                          )}
                          {job.status === "failed" && (
                            <button onClick={() => void handleQueueAction(job.job_id, "retry")} className="rounded bg-red-800 px-2 py-1 text-red-50 hover:bg-red-700">
                              Retry
                            </button>
                          )}
                          {sourceUrl && (
                            <a href={sourceUrl} target="_blank" rel="noreferrer" className="rounded bg-gray-800 px-2 py-1 text-gray-200 hover:bg-gray-700">
                              Original
                            </a>
                          )}
                          {outputUrl && (
                            <a href={outputUrl} target="_blank" rel="noreferrer" className="rounded bg-emerald-800 px-2 py-1 text-emerald-50 hover:bg-emerald-700">
                              Output
                            </a>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <div className="grid gap-2">
              <button
                onClick={handleSave}
                disabled={!project || saving}
                className="rounded bg-cyan-700 px-4 py-3 text-sm font-medium text-white hover:bg-cyan-600 disabled:opacity-40"
              >
                {saving ? "Saving..." : "Save timeline"}
              </button>
              <button
                onClick={handleRender}
                disabled={!project || rendering}
                className="rounded bg-green-600 px-4 py-3 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-40"
              >
                {rendering ? "Rendering..." : "Render timeline"}
              </button>
              <Link href="/export" className="rounded bg-blue-600 px-4 py-3 text-center text-sm font-medium text-white hover:bg-blue-700">
                Export videos
              </Link>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
