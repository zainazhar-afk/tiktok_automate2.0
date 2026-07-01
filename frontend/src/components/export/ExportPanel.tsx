"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { AccountStatus, ProcessedVideoFile } from "@/types";
import { useAuth } from "@/lib/auth";
import { deleteVideo, getAccountStatus, listVideos, videoFileUrl } from "@/lib/api";

type ReadinessState = "ready" | "review" | "blocked";

interface Readiness {
  state: ReadinessState;
  label: string;
  reason: string;
  action: "account" | "editor" | "refresh" | null;
}

function readinessFor(
  video: ProcessedVideoFile,
  account: AccountStatus | null,
  videoFailed: boolean,
  coverFailed: boolean
): Readiness {
  if (video.visibility_status === "unavailable" || videoFailed) {
    return {
      state: "blocked",
      label: "Unavailable",
      reason: video.unavailable_reason || "The generated video could not be loaded.",
      action: "refresh",
    };
  }
  if (account?.billing_required && !account.subscription_active) {
    return {
      state: "blocked",
      label: "Billing required",
      reason: "Activate a subscription before exporting this asset.",
      action: "account",
    };
  }
  if (account?.rights_required && !account.rights_accepted) {
    return {
      state: "blocked",
      label: "Rights required",
      reason: "Confirm source-media rights before exporting this asset.",
      action: "account",
    };
  }
  if (!video.cover_filename || coverFailed) {
    return {
      state: "review",
      label: "Missing cover",
      reason: "Generate or refresh the cover before publishing.",
      action: "editor",
    };
  }
  if (!video.caption?.trim()) {
    return {
      state: "review",
      label: "Missing caption",
      reason: "Add a caption and hashtags before publishing.",
      action: "editor",
    };
  }
  return {
    state: "ready",
    label: "Ready to publish",
    reason: "Video, cover, and caption are available.",
    action: null,
  };
}

function badgeClass(state: ReadinessState) {
  if (state === "ready") return "border-green-700 bg-green-950/50 text-green-200";
  if (state === "review") return "border-yellow-700 bg-yellow-950/40 text-yellow-200";
  return "border-red-800 bg-red-950/50 text-red-200";
}

function ActionCta({
  action,
  videoId,
  onRefresh,
}: {
  action: Readiness["action"];
  videoId: string;
  onRefresh: () => void;
}) {
  if (action === "account") {
    return (
      <Link href="/account" className="rounded bg-yellow-700 px-3 py-1.5 text-xs text-white hover:bg-yellow-600">
        Open Account
      </Link>
    );
  }
  if (action === "editor") {
    return (
      <Link
        href={`/editor?video=${encodeURIComponent(videoId)}`}
        className="rounded bg-purple-700 px-3 py-1.5 text-xs text-white hover:bg-purple-600"
      >
        Regenerate in Editor
      </Link>
    );
  }
  if (action === "refresh") {
    return (
      <button onClick={onRefresh} className="rounded bg-gray-700 px-3 py-1.5 text-xs text-white hover:bg-gray-600">
        Refresh
      </button>
    );
  }
  return null;
}

export default function ExportPanel() {
  const { accessToken } = useAuth();
  const [videos, setVideos] = useState<ProcessedVideoFile[]>([]);
  const [account, setAccount] = useState<AccountStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [accountError, setAccountError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [videoErrors, setVideoErrors] = useState<Set<string>>(new Set());
  const [coverErrors, setCoverErrors] = useState<Set<string>>(new Set());

  const fetchVideos = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    setLoadError(null);
    setAccountError(null);
    try {
      const data = await listVideos("processed");
      setVideos(data.videos || []);
      setVideoErrors(new Set());
      setCoverErrors(new Set());
    } catch (e: unknown) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
    try {
      setAccount(await getAccountStatus());
    } catch (e: unknown) {
      setAccount(null);
      setAccountError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initial = setTimeout(() => void fetchVideos(false), 0);
    const interval = setInterval(() => void fetchVideos(false), 15000);
    return () => {
      clearTimeout(initial);
      clearInterval(interval);
    };
  }, [fetchVideos]);

  const copyText = async (id: string, text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(null), 2000);
  };

  const handleDelete = async (filename: string) => {
    setDeleting(filename);
    setLoadError(null);
    try {
      await deleteVideo(filename);
      setVideos((prev) => prev.filter((v) => v.filename !== filename));
    } catch (e: unknown) {
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleting(null);
    }
  };

  const filteredVideos = videos.filter((video) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return [video.title, video.filename, video.caption, ...(video.hashtags || [])]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(q);
  });

  const readinessByFile = useMemo(() => {
    const map = new Map<string, Readiness>();
    for (const video of videos) {
      map.set(
        video.filename,
        readinessFor(
          video,
          account,
          videoErrors.has(video.filename),
          Boolean(video.cover_filename && coverErrors.has(video.cover_filename))
        )
      );
    }
    return map;
  }, [account, coverErrors, videoErrors, videos]);

  const summary = useMemo(() => {
    const counts = { ready: 0, review: 0, blocked: 0 };
    for (const video of videos) {
      counts[readinessByFile.get(video.filename)?.state || "blocked"] += 1;
    }
    return counts;
  }, [readinessByFile, videos]);

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-medium text-gray-200">Export Readiness</h2>
            <p className="mt-1 text-xs text-gray-500">Verify account, media, cover, and caption status before download.</p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded border border-green-800 bg-green-950/40 px-3 py-1.5 text-green-200">
              Ready {summary.ready}
            </span>
            <span className="rounded border border-yellow-800 bg-yellow-950/40 px-3 py-1.5 text-yellow-200">
              Needs review {summary.review}
            </span>
            <span className="rounded border border-red-900 bg-red-950/40 px-3 py-1.5 text-red-200">
              Blocked {summary.blocked}
            </span>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-gray-300">Processed Videos</h2>
          <p className="mt-1 text-xs text-gray-500">Download MP4s, cover images, captions, hashtags, and posting assets.</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter exports..."
            className="w-48 rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:border-purple-500 focus:outline-none"
          />
          <button
            onClick={() => fetchVideos()}
            disabled={loading}
            className="rounded-lg bg-gray-700 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-600 disabled:opacity-50"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {(loadError || accountError) && (
        <div className="rounded-lg border border-red-800 bg-red-950/40 p-4 text-sm text-red-100">
          <div className="font-medium">{loadError ? "Could not load exports" : "Could not verify account readiness"}</div>
          <p className="mt-1 text-red-200/80">{loadError || accountError}</p>
          <div className="mt-3 flex gap-2">
            <button onClick={() => fetchVideos()} className="rounded bg-red-700 px-3 py-1.5 text-xs text-white hover:bg-red-600">
              Retry
            </button>
            <Link href="/account" className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-100 hover:bg-gray-700">
              Account
            </Link>
          </div>
        </div>
      )}

      {!loading && !loadError && videos.length === 0 && (
        <div className="rounded-lg border border-gray-800 bg-gray-900 py-16 text-center text-gray-500">
          <p className="text-lg text-gray-300">No processed videos yet</p>
          <div className="mt-4 flex justify-center gap-2">
            <Link href="/bulk" className="rounded bg-purple-700 px-3 py-2 text-xs text-white hover:bg-purple-600">
              Process videos
            </Link>
            <Link href="/variants" className="rounded bg-gray-800 px-3 py-2 text-xs text-gray-200 hover:bg-gray-700">
              Generate variants
            </Link>
          </div>
        </div>
      )}

      {!loading && videos.length > 0 && filteredVideos.length === 0 && (
        <div className="rounded-lg border border-gray-800 bg-gray-900 py-16 text-center text-gray-500">
          <p className="text-lg">No exports match the filter</p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filteredVideos.map((video) => {
          const hashtagText = (video.hashtags || []).join(" ");
          const captionBlock = [video.caption, hashtagText].filter(Boolean).join("\n\n");
          const videoUrl = videoFileUrl(video.filename, accessToken);
          const coverUrl = video.cover_filename ? videoFileUrl(video.cover_filename, accessToken) : null;
          const readiness = readinessByFile.get(video.filename) || readinessFor(video, account, false, false);
          const videoFailed = videoErrors.has(video.filename);
          const coverFailed = Boolean(video.cover_filename && coverErrors.has(video.cover_filename));
          const videoDownloadEnabled = readiness.state !== "blocked" && !videoFailed;
          const coverDownloadEnabled = Boolean(video.cover_filename && coverUrl && !coverFailed && readiness.state !== "blocked");

          return (
            <div key={video.filename} className="overflow-hidden rounded-lg border border-gray-700 bg-gray-900">
              <div className="grid grid-cols-2 gap-0">
                <div className="aspect-[9/16] bg-gray-950">
                  {readiness.state === "blocked" || videoFailed ? (
                    <div className="flex h-full items-center justify-center px-4 text-center text-xs text-gray-500">
                      Preview unavailable
                    </div>
                  ) : (
                    <video
                      src={videoUrl}
                      controls
                      className="h-full w-full object-contain"
                      preload="metadata"
                      onError={() => setVideoErrors((current) => new Set(current).add(video.filename))}
                    />
                  )}
                </div>
                <div className="aspect-[9/16] border-l border-gray-700 bg-gray-950">
                  {coverUrl && !coverFailed ? (
                    // Export covers are generated media that may require tokenized URLs.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={coverUrl}
                      alt="TikTok cover"
                      className="h-full w-full object-cover"
                      onError={() => setCoverErrors((current) => new Set(current).add(video.cover_filename || ""))}
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center px-4 text-center text-xs text-gray-500">
                      Cover unavailable
                    </div>
                  )}
                </div>
              </div>

              <div className="space-y-3 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-gray-200">{video.title || video.filename}</p>
                    {video.size_mb > 0 && <p className="mt-1 text-xs text-gray-500">{video.size_mb} MB</p>}
                  </div>
                  <span className={`shrink-0 rounded border px-2 py-1 text-[11px] font-medium ${badgeClass(readiness.state)}`}>
                    {readiness.label}
                  </span>
                </div>

                <div className={`rounded border p-2 text-xs ${badgeClass(readiness.state)}`}>
                  {readiness.reason}
                </div>

                {video.caption && (
                  <div className="max-h-24 overflow-y-auto whitespace-pre-wrap rounded bg-gray-800/50 p-2 text-xs text-gray-400">
                    {video.caption}
                  </div>
                )}

                {video.hashtags && video.hashtags.length > 0 && (
                  <p className="line-clamp-2 text-xs text-purple-400">{hashtagText}</p>
                )}

                <div className="flex flex-wrap gap-2">
                  {videoDownloadEnabled ? (
                    <a href={videoUrl} download={video.filename} className="rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700">
                      Video
                    </a>
                  ) : (
                    <button disabled className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-500">
                      Video
                    </button>
                  )}
                  {coverDownloadEnabled ? (
                    <a href={coverUrl || ""} download={video.cover_filename || "cover.jpg"} className="rounded bg-purple-600 px-3 py-1.5 text-xs text-white hover:bg-purple-700">
                      Cover
                    </a>
                  ) : (
                    <button disabled className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-500">
                      Cover
                    </button>
                  )}
                  {captionBlock && (
                    <button
                      onClick={() => copyText(video.id, captionBlock)}
                      className="rounded bg-green-700 px-3 py-1.5 text-xs text-white hover:bg-green-600"
                    >
                      {copied === video.id ? "Copied!" : "Copy caption"}
                    </button>
                  )}
                  <Link href={`/editor?video=${encodeURIComponent(video.id)}`} className="rounded bg-purple-700 px-3 py-1.5 text-xs text-white hover:bg-purple-600">
                    Edit
                  </Link>
                  <ActionCta action={readiness.action} videoId={video.id} onRefresh={() => void fetchVideos()} />
                  <button
                    onClick={() => handleDelete(video.filename)}
                    disabled={deleting === video.filename}
                    className="rounded bg-red-800/50 px-3 py-1.5 text-xs text-red-300 disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
