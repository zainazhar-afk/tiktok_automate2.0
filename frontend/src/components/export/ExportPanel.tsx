"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { API_URL } from "@/types";
import type { ProcessedVideoFile } from "@/types";
import { listVideos, deleteVideo } from "@/lib/api";

export default function ExportPanel() {
  const [videos, setVideos] = useState<ProcessedVideoFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const fetchVideos = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const data = await listVideos("processed");
      setVideos(data.videos || []);
    } catch {
      // backend offline
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
    try {
      await deleteVideo(filename);
      setVideos((prev) => prev.filter((v) => v.filename !== filename));
    } finally {
      setDeleting(null);
    }
  };

  const filteredVideos = videos.filter((video) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return [
      video.title,
      video.filename,
      video.caption,
      ...(video.hashtags || []),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(q);
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-medium text-gray-200">Processed Videos</h2>
          <p className="text-xs text-gray-500 mt-1">
            Includes auto-generated captions, hashtags, and TikTok cover thumbnails.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter exports..."
            className="w-48 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500"
          />
          <button
            onClick={() => fetchVideos()}
            disabled={loading}
            className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs rounded-lg disabled:opacity-50"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {!loading && videos.length === 0 && (
        <div className="text-center py-20 text-gray-500">
          <p className="text-lg">No processed videos yet</p>
        </div>
      )}

      {!loading && videos.length > 0 && filteredVideos.length === 0 && (
        <div className="text-center py-20 text-gray-500">
          <p className="text-lg">No exports match the filter</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredVideos.map((video) => {
          const hashtagText = (video.hashtags || []).join(" ");
          const captionBlock = [video.caption, hashtagText].filter(Boolean).join("\n\n");
          const videoUrl = `${API_URL}/api/videos/file/${encodeURIComponent(video.filename)}`;
          const coverUrl = video.cover_filename
            ? `${API_URL}/api/videos/file/${encodeURIComponent(video.cover_filename)}`
            : null;
          return (
            <div key={video.filename} className="bg-gray-900 border border-gray-700 rounded-lg overflow-hidden">
              <div className="grid grid-cols-2 gap-0">
                <div className="aspect-[9/16] bg-gray-800">
                  <video
                    src={videoUrl}
                    controls
                    className="w-full h-full object-contain"
                    preload="metadata"
                  />
                </div>
                {video.cover_filename && (
                  <div className="aspect-[9/16] bg-gray-800 border-l border-gray-700">
                    <img
                      src={coverUrl || ""}
                      alt="TikTok cover"
                      className="w-full h-full object-cover"
                    />
                  </div>
                )}
              </div>

              <div className="p-3 space-y-2">
                <p className="text-sm text-gray-200 truncate">{video.title || video.filename}</p>
                {video.size_mb > 0 && (
                  <p className="text-xs text-gray-500">{video.size_mb} MB</p>
                )}

                {video.caption && (
                  <div className="text-xs text-gray-400 bg-gray-800/50 rounded p-2 max-h-24 overflow-y-auto whitespace-pre-wrap">
                    {video.caption}
                  </div>
                )}

                {video.hashtags && video.hashtags.length > 0 && (
                  <p className="text-xs text-purple-400 line-clamp-2">{hashtagText}</p>
                )}

                <div className="flex flex-wrap gap-2">
                  <a
                    href={videoUrl}
                    download={video.filename}
                    className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded"
                  >
                    Video
                  </a>
                  {video.cover_filename && (
                    <a
                      href={coverUrl || ""}
                      download={video.cover_filename}
                      className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 text-white text-xs rounded"
                    >
                      Cover
                    </a>
                  )}
                  {captionBlock && (
                    <button
                      onClick={() => copyText(video.id, captionBlock)}
                      className="px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white text-xs rounded"
                    >
                      {copied === video.id ? "Copied!" : "Copy caption"}
                    </button>
                  )}
                  <Link
                    href={`/editor?video=${encodeURIComponent(video.id)}`}
                    className="px-3 py-1.5 bg-purple-700 hover:bg-purple-600 text-white text-xs rounded"
                  >
                    Edit
                  </Link>
                  <button
                    onClick={() => handleDelete(video.filename)}
                    disabled={deleting === video.filename}
                    className="px-3 py-1.5 bg-red-800/50 text-red-300 text-xs rounded disabled:opacity-50"
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
