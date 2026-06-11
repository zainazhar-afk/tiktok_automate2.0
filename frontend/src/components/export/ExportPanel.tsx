"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/types";
import type { ProcessedVideoFile } from "@/types";
import { listVideos, deleteVideo } from "@/lib/api";

export default function ExportPanel() {
  const [videos, setVideos] = useState<ProcessedVideoFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const fetchVideos = async () => {
    setLoading(true);
    try {
      const data = await listVideos("processed");
      setVideos(data.videos || []);
    } catch {
      // backend offline
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchVideos();
    const interval = setInterval(fetchVideos, 15000);
    return () => clearInterval(interval);
  }, []);

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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-medium text-gray-200">Processed Videos</h2>
          <p className="text-xs text-gray-500 mt-1">
            Includes auto-generated captions, hashtags, and TikTok cover thumbnails.
          </p>
        </div>
        <button
          onClick={fetchVideos}
          disabled={loading}
          className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs rounded-lg disabled:opacity-50"
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {!loading && videos.length === 0 && (
        <div className="text-center py-20 text-gray-500">
          <p className="text-lg">No processed videos yet</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {videos.map((video) => {
          const hashtagText = (video.hashtags || []).join(" ");
          const captionBlock = [video.caption, hashtagText].filter(Boolean).join("\n\n");
          return (
            <div key={video.id} className="bg-gray-900 border border-gray-700 rounded-lg overflow-hidden">
              <div className="grid grid-cols-2 gap-0">
                <div className="aspect-[9/16] bg-gray-800">
                  <video
                    src={`${API_URL}/api/videos/file/${video.filename}`}
                    controls
                    className="w-full h-full object-contain"
                    preload="metadata"
                  />
                </div>
                {video.cover_filename && (
                  <div className="aspect-[9/16] bg-gray-800 border-l border-gray-700">
                    <img
                      src={`${API_URL}/api/videos/file/${video.cover_filename}`}
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
                    href={`${API_URL}/api/videos/file/${video.filename}`}
                    download={video.filename}
                    className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded"
                  >
                    Video
                  </a>
                  {video.cover_filename && (
                    <a
                      href={`${API_URL}/api/videos/file/${video.cover_filename}`}
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
