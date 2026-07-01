"use client";

import React, {
  createContext,
  useContext,
  useReducer,
  useCallback,
  useEffect,
  useRef,
} from "react";
import { useAuth } from "@/lib/auth";
import {
  VideoInfo,
  AntiDetectionConfig,
  DEFAULT_ANTI_DETECTION,
  DEFAULT_FILTERS,
  DiscoveryFilters,
  JobInfo,
} from "@/types";

const STORAGE_KEY = "tiktok_automate_state";

export interface AppState {
  discoveredVideos: VideoInfo[];
  selectedVideoIds: Set<string>;
  isLoading: boolean;
  error: string | null;
  filters: DiscoveryFilters;
  nextPageToken: string | null;
  prevPageToken: string | null;
  discoverySource: string;
  downloadedPaths: Map<string, string>;
  downloadingIds: Set<string>;
  processedPaths: Map<string, string>;
  processingIds: Set<string>;
  antiDetection: AntiDetectionConfig;
  jobs: JobInfo[];
}

const initialState: AppState = {
  discoveredVideos: [],
  selectedVideoIds: new Set(),
  isLoading: false,
  error: null,
  filters: DEFAULT_FILTERS,
  nextPageToken: null,
  prevPageToken: null,
  discoverySource: "youtube_api",
  downloadedPaths: new Map(),
  downloadingIds: new Set(),
  processedPaths: new Map(),
  processingIds: new Set(),
  antiDetection: DEFAULT_ANTI_DETECTION,
  jobs: [],
};

type Action =
  | { type: "SET_VIDEOS"; payload: { videos: VideoInfo[]; next?: string | null; prev?: string | null; source?: string } }
  | { type: "APPEND_VIDEOS"; payload: VideoInfo[] }
  | { type: "SET_LOADING"; payload: boolean }
  | { type: "SET_ERROR"; payload: string | null }
  | { type: "SET_FILTERS"; payload: Partial<DiscoveryFilters> }
  | { type: "TOGGLE_SELECT"; payload: string }
  | { type: "SELECT_ALL"; payload: string[] }
  | { type: "DESELECT_ALL" }
  | { type: "SET_DOWNLOADING"; payload: string[] }
  | { type: "DOWNLOAD_SETTLED"; payload: string }
  | { type: "DOWNLOAD_COMPLETE"; payload: { videoId: string; path: string } }
  | { type: "DOWNLOAD_FAILED"; payload: string }
  | { type: "SET_PROCESSING"; payload: string[] }
  | { type: "PROCESS_COMPLETE"; payload: { videoId: string; path: string } }
  | { type: "PROCESS_FAILED"; payload: string }
  | { type: "SET_ANTI_DETECTION"; payload: Partial<AntiDetectionConfig> }
  | { type: "SET_JOBS"; payload: JobInfo[] }
  | { type: "UPDATE_JOB"; payload: JobInfo }
  | { type: "HYDRATE"; payload: Partial<AppState> }
  | { type: "RESET_ACCOUNT_STATE" }
  | { type: "CLEAR_ERROR" };

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "SET_VIDEOS":
      return {
        ...state,
        discoveredVideos: action.payload.videos,
        nextPageToken: action.payload.next ?? null,
        prevPageToken: action.payload.prev ?? null,
        discoverySource: action.payload.source || state.discoverySource,
        error: null,
        isLoading: false,
      };
    case "APPEND_VIDEOS": {
      const existingIds = new Set(state.discoveredVideos.map((v) => v.id));
      const newVideos = action.payload.filter((v) => !existingIds.has(v.id));
      return {
        ...state,
        discoveredVideos: [...state.discoveredVideos, ...newVideos],
        isLoading: false,
      };
    }
    case "SET_LOADING":
      return { ...state, isLoading: action.payload };
    case "SET_ERROR":
      return { ...state, error: action.payload, isLoading: false };
    case "SET_FILTERS":
      return { ...state, filters: { ...state.filters, ...action.payload } };
    case "TOGGLE_SELECT": {
      const next = new Set(state.selectedVideoIds);
      if (next.has(action.payload)) next.delete(action.payload);
      else next.add(action.payload);
      return { ...state, selectedVideoIds: next };
    }
    case "SELECT_ALL":
      return { ...state, selectedVideoIds: new Set(action.payload) };
    case "DESELECT_ALL":
      return { ...state, selectedVideoIds: new Set() };
    case "SET_DOWNLOADING": {
      const next = new Set(state.downloadingIds);
      action.payload.forEach((id) => next.add(id));
      return { ...state, downloadingIds: next };
    }
    case "DOWNLOAD_SETTLED": {
      const downloading = new Set(state.downloadingIds);
      downloading.delete(action.payload);
      return { ...state, downloadingIds: downloading };
    }
    case "DOWNLOAD_COMPLETE": {
      const downloading = new Set(state.downloadingIds);
      downloading.delete(action.payload.videoId);
      const paths = new Map(state.downloadedPaths);
      paths.set(action.payload.videoId, action.payload.path);
      return { ...state, downloadedPaths: paths, downloadingIds: downloading };
    }
    case "DOWNLOAD_FAILED": {
      const downloading = new Set(state.downloadingIds);
      downloading.delete(action.payload);
      return { ...state, downloadingIds: downloading };
    }
    case "SET_PROCESSING": {
      const next = new Set(state.processingIds);
      action.payload.forEach((id) => next.add(id));
      return { ...state, processingIds: next };
    }
    case "PROCESS_COMPLETE": {
      const processing = new Set(state.processingIds);
      processing.delete(action.payload.videoId);
      const paths = new Map(state.processedPaths);
      paths.set(action.payload.videoId, action.payload.path);
      return { ...state, processedPaths: paths, processingIds: processing };
    }
    case "PROCESS_FAILED": {
      const processing = new Set(state.processingIds);
      processing.delete(action.payload);
      return { ...state, processingIds: processing };
    }
    case "SET_ANTI_DETECTION":
      return { ...state, antiDetection: { ...state.antiDetection, ...action.payload } };
    case "SET_JOBS":
      return { ...state, jobs: action.payload };
    case "UPDATE_JOB": {
      const idx = state.jobs.findIndex((j) => j.job_id === action.payload.job_id);
      if (idx === -1) return { ...state, jobs: [...state.jobs, action.payload] };
      const next = [...state.jobs];
      next[idx] = action.payload;
      return { ...state, jobs: next };
    }
    case "HYDRATE":
      return { ...state, ...action.payload };
    case "RESET_ACCOUNT_STATE":
      return {
        ...state,
        selectedVideoIds: new Set(),
        downloadedPaths: new Map(),
        downloadingIds: new Set(),
        processedPaths: new Map(),
        processingIds: new Set(),
        jobs: [],
        error: null,
      };
    case "CLEAR_ERROR":
      return { ...state, error: null };
    default:
      return state;
  }
}

function persistState(storageKey: string, state: AppState) {
  try {
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        downloadedPaths: Array.from(state.downloadedPaths.entries()),
        processedPaths: Array.from(state.processedPaths.entries()),
        filters: state.filters,
        antiDetection: state.antiDetection,
      })
    );
  } catch {
    // ignore quota errors
  }
}

interface AppContextValue {
  state: AppState;
  discoverTrending: (pageToken?: string | null) => Promise<void>;
  discoverByHashtag: (hashtag: string, pageToken?: string | null) => Promise<void>;
  discoverCompetitor: (handle: string) => Promise<void>;
  searchVideos: (query: string, pageToken?: string | null) => Promise<void>;
  setFilters: (filters: Partial<DiscoveryFilters>) => void;
  applyFilters: () => Promise<void>;
  downloadSelected: () => Promise<void>;
  processSelected: () => Promise<void>;
  processAllDownloaded: () => Promise<void>;
  runPipeline: () => Promise<void>;
  retryFailedJobs: () => Promise<void>;
  toggleSelect: (id: string) => void;
  selectAll: () => void;
  deselectAll: () => void;
  setAntiDetection: (config: Partial<AntiDetectionConfig>) => void;
  clearError: () => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const [state, dispatch] = useReducer(reducer, initialState);
  const stateRef = useRef(state);
  const storageKey = `${STORAGE_KEY}:${auth.user?.id || "local-dev"}`;

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  // Remember the last discovery action so filter changes can re-run it.
  const lastDiscoveryRef = useRef<{ type: "trending" | "search" | "hashtag" | "competitor"; query?: string }>({
    type: "trending",
  });

  useEffect(() => {
    dispatch({ type: "RESET_ACCOUNT_STATE" });
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const saved = JSON.parse(raw);
        dispatch({
          type: "HYDRATE",
          payload: {
            downloadedPaths: new Map(saved.downloadedPaths || []),
            processedPaths: new Map(saved.processedPaths || []),
            filters: { ...DEFAULT_FILTERS, ...saved.filters },
            antiDetection: { ...DEFAULT_ANTI_DETECTION, ...saved.antiDetection },
          },
        });
      }
    } catch {
      // ignore
    }

    import("@/lib/api").then(({ listStateVideos }) => {
      listStateVideos()
        .then((data) => {
          const dl = new Map<string, string>();
          const proc = new Map<string, string>();
          for (const v of data.videos || []) {
            if (v.download_path) dl.set(v.video_id, v.download_path);
            if (v.output_path) proc.set(v.video_id, v.output_path);
          }
          if (dl.size || proc.size) {
            dispatch({ type: "HYDRATE", payload: { downloadedPaths: dl, processedPaths: proc } });
          }
        })
        .catch(() => {});
    });
  }, [storageKey]);

  useEffect(() => {
    persistState(storageKey, state);
  }, [state, storageKey]);

  useEffect(() => {
    let unsub: (() => void) | undefined;
    import("@/lib/api").then(({ subscribeEvents }) => {
      unsub = subscribeEvents((event: unknown) => {
        const ev = event as { type?: string; data?: JobInfo & { jobs?: JobInfo[] } };
        if (ev?.type === "job_update" && ev.data?.job_id) {
          dispatch({ type: "UPDATE_JOB", payload: ev.data });
          const job = ev.data;
          if (job.status === "completed" && job.output_path) {
            dispatch({ type: "DOWNLOAD_SETTLED", payload: job.video_id });
            dispatch({
              type: "PROCESS_COMPLETE",
              payload: { videoId: job.video_id, path: job.output_path },
            });
          }
          if (job.status === "downloading") {
            dispatch({ type: "SET_DOWNLOADING", payload: [job.video_id] });
          }
          if (job.status === "processing") {
            dispatch({ type: "DOWNLOAD_SETTLED", payload: job.video_id });
            dispatch({ type: "SET_PROCESSING", payload: [job.video_id] });
          }
          if (job.status === "failed") {
            dispatch({ type: "DOWNLOAD_SETTLED", payload: job.video_id });
            dispatch({ type: "PROCESS_FAILED", payload: job.video_id });
          }
        }
        if (ev?.type === "jobs_snapshot" && ev.data?.jobs) {
          dispatch({ type: "SET_JOBS", payload: ev.data.jobs });
        }
      });
    });
    return () => unsub?.();
  }, [storageKey]);

  const setFilters = useCallback((filters: Partial<DiscoveryFilters>) => {
    dispatch({ type: "SET_FILTERS", payload: filters });
  }, []);

  const applyDiscovery = useCallback((data: { videos?: VideoInfo[]; next_page_token?: string | null; prev_page_token?: string | null; source?: string }) => {
    dispatch({
      type: "SET_VIDEOS",
      payload: {
        videos: data.videos || [],
        next: data.next_page_token,
        prev: data.prev_page_token,
        source: data.source,
      },
    });
  }, []);

  const discoverTrending = useCallback(async (pageToken?: string | null) => {
    lastDiscoveryRef.current = { type: "trending" };
    dispatch({ type: "SET_LOADING", payload: true });
    try {
      const { discoverContent } = await import("@/lib/api");
      const data = await discoverContent("trending", undefined, stateRef.current.filters, pageToken);
      if (!data.videos?.length && !pageToken) {
        const { searchVideos } = await import("@/lib/api");
        const backup = await searchVideos("trending viral shorts", stateRef.current.filters);
        applyDiscovery(backup);
      } else {
        applyDiscovery(data);
      }
    } catch (e: unknown) {
      dispatch({ type: "SET_ERROR", payload: e instanceof Error ? e.message : String(e) });
    }
  }, [applyDiscovery]);

  const discoverByHashtag = useCallback(async (hashtag: string, pageToken?: string | null) => {
    lastDiscoveryRef.current = { type: "hashtag", query: hashtag };
    dispatch({ type: "SET_LOADING", payload: true });
    try {
      const { discoverContent } = await import("@/lib/api");
      const data = await discoverContent("hashtag", hashtag, stateRef.current.filters, pageToken);
      applyDiscovery(data);
    } catch (e: unknown) {
      dispatch({ type: "SET_ERROR", payload: e instanceof Error ? e.message : String(e) });
    }
  }, [applyDiscovery]);

  const discoverCompetitor = useCallback(async (handle: string) => {
    lastDiscoveryRef.current = { type: "competitor", query: handle };
    dispatch({ type: "SET_LOADING", payload: true });
    try {
      const { discoverContent } = await import("@/lib/api");
      const data = await discoverContent("competitor", handle, stateRef.current.filters);
      dispatch({ type: "APPEND_VIDEOS", payload: data.videos || [] });
    } catch (e: unknown) {
      dispatch({ type: "SET_ERROR", payload: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  const searchVideosFn = useCallback(async (query: string, pageToken?: string | null) => {
    lastDiscoveryRef.current = { type: "search", query };
    dispatch({ type: "SET_LOADING", payload: true });
    try {
      const { searchVideos } = await import("@/lib/api");
      const data = await searchVideos(query, stateRef.current.filters, pageToken);
      applyDiscovery(data);
    } catch (e: unknown) {
      dispatch({ type: "SET_ERROR", payload: e instanceof Error ? e.message : String(e) });
    }
  }, [applyDiscovery]);

  // Re-run the most recent discovery with the current filters applied.
  const applyFilters = useCallback(async () => {
    const last = lastDiscoveryRef.current;
    if (last.type === "search" && last.query) return searchVideosFn(last.query);
    if (last.type === "hashtag" && last.query) return discoverByHashtag(last.query);
    if (last.type === "competitor" && last.query) return discoverCompetitor(last.query);
    return discoverTrending();
  }, [searchVideosFn, discoverByHashtag, discoverCompetitor, discoverTrending]);

  const downloadSelected = useCallback(async () => {
    const selected = stateRef.current.discoveredVideos.filter((v) =>
      stateRef.current.selectedVideoIds.has(v.id)
    );
    if (!selected.length) return;

    dispatch({ type: "SET_DOWNLOADING", payload: selected.map((v) => v.id) });
    try {
      const { batchDownload, syncState } = await import("@/lib/api");
      const result = await batchDownload(
        selected.map((v) => ({ url: v.url, video_id: v.id })),
        8
      );
      for (const [id, path] of Object.entries(result.results || {})) {
        dispatch({ type: "DOWNLOAD_COMPLETE", payload: { videoId: id, path: path as string } });
      }
      for (const id of result.failed_ids || []) {
        dispatch({ type: "DOWNLOAD_FAILED", payload: id });
      }
      await syncState(
        selected.map((v) => ({
          video_id: v.id,
          title: v.title,
          channel: v.channel,
          status: "downloaded",
          download_path: result.results?.[v.id],
        }))
      );
    } catch {
      selected.forEach((v) => dispatch({ type: "DOWNLOAD_FAILED", payload: v.id }));
    }
  }, []);

  const processDownloadedIds = useCallback(async (ids: string[]) => {
    if (!ids.length) return;

    dispatch({ type: "SET_PROCESSING", payload: ids });
    const { processVideo, syncState } = await import("@/lib/api");
    const completed: {
      video_id: string;
      status: string;
      output_path: string;
      title?: string;
      channel?: string;
    }[] = [];
    const batchSize = 4;
    for (let i = 0; i < ids.length; i += batchSize) {
      const batch = ids.slice(i, i + batchSize);
      await Promise.all(
        batch.map(async (id) => {
          const video = stateRef.current.discoveredVideos.find((v) => v.id === id);
          try {
            const result = await processVideo(id, stateRef.current.antiDetection, {
              title: video?.title,
              channel: video?.channel,
              description: video?.description,
              tags: video?.tags,
            });
            dispatch({
              type: "PROCESS_COMPLETE",
              payload: { videoId: id, path: result.output_path },
            });
            completed.push({
              video_id: id,
              status: "completed",
              output_path: result.output_path,
              title: video?.title,
              channel: video?.channel,
            });
          } catch {
            dispatch({ type: "PROCESS_FAILED", payload: id });
          }
        })
      );
    }
    if (completed.length) await syncState(completed);
  }, []);

  const processSelected = useCallback(async () => {
    const ids = Array.from(stateRef.current.downloadedPaths.keys()).filter((id) =>
      stateRef.current.selectedVideoIds.has(id)
    );
    await processDownloadedIds(ids);
  }, [processDownloadedIds]);

  const processAllDownloaded = useCallback(async () => {
    await processDownloadedIds(Array.from(stateRef.current.downloadedPaths.keys()));
  }, [processDownloadedIds]);

  const enqueuePipelineForIds = useCallback(async (ids: string[]) => {
    if (!ids.length) return;

    const videoMeta = Object.fromEntries(
      ids.map((id) => {
        const video = stateRef.current.discoveredVideos.find((v) => v.id === id);
        const job = stateRef.current.jobs.find((j) => j.video_id === id);
        return [
          id,
          {
            url: video?.url,
            title: video?.title || job?.title,
            channel: video?.channel || job?.channel,
            description: video?.description,
            tags: video?.tags,
          },
        ];
      })
    );

    const { pipelineProcess } = await import("@/lib/api");
    const result = await pipelineProcess(
      ids,
      stateRef.current.antiDetection,
      videoMeta,
      4
    );
    dispatch({ type: "SET_JOBS", payload: result.jobs || [] });
  }, []);

  const runPipeline = useCallback(async () => {
    try {
      await enqueuePipelineForIds(
        stateRef.current.discoveredVideos
          .filter((v) => stateRef.current.selectedVideoIds.has(v.id))
          .map((v) => v.id)
      );
    } catch (e: unknown) {
      dispatch({ type: "SET_ERROR", payload: e instanceof Error ? e.message : String(e) });
    }
  }, [enqueuePipelineForIds]);

  const retryFailedJobs = useCallback(async () => {
    const ids = Array.from(
      new Set(
        stateRef.current.jobs
          .filter((job) => job.status === "failed")
          .map((job) => job.video_id)
      )
    );
    try {
      await enqueuePipelineForIds(ids);
    } catch (e: unknown) {
      dispatch({ type: "SET_ERROR", payload: e instanceof Error ? e.message : String(e) });
    }
  }, [enqueuePipelineForIds]);

  const toggleSelect = useCallback((id: string) => dispatch({ type: "TOGGLE_SELECT", payload: id }), []);
  const selectAll = useCallback(() => {
    dispatch({ type: "SELECT_ALL", payload: stateRef.current.discoveredVideos.map((v) => v.id) });
  }, []);
  const deselectAll = useCallback(() => dispatch({ type: "DESELECT_ALL" }), []);
  const setAntiDetection = useCallback(
    (config: Partial<AntiDetectionConfig>) => dispatch({ type: "SET_ANTI_DETECTION", payload: config }),
    []
  );
  const clearError = useCallback(() => dispatch({ type: "CLEAR_ERROR" }), []);

  return (
    <AppContext.Provider
      value={{
        state,
        discoverTrending,
        discoverByHashtag,
        discoverCompetitor,
        searchVideos: searchVideosFn,
        setFilters,
        applyFilters,
        downloadSelected,
        processSelected,
        processAllDownloaded,
        runPipeline,
        retryFailedJobs,
        toggleSelect,
        selectAll,
        deselectAll,
        setAntiDetection,
        clearError,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}
