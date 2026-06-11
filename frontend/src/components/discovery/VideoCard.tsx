"use client";

import { VideoInfo } from "@/types";
import { useApp } from "@/lib/store";

interface VideoCardProps {
  video: VideoInfo;
}

export default function VideoCard({ video }: VideoCardProps) {
  const { toggleSelect, state } = useApp();
  const isSelected = state.selectedVideoIds.has(video.id);
  const isDownloaded = state.downloadedPaths.has(video.id);
  const isDownloading = state.downloadingIds.has(video.id);
  const isProcessed = state.processedPaths.has(video.id);

  const durationStr = `${Math.floor(video.duration / 60)}:${(video.duration % 60).toString().padStart(2, "0")}`;
  const viewsStr = video.views
    ? video.views >= 1_000_000
      ? `${(video.views / 1_000_000).toFixed(1)}M`
      : video.views >= 1000
        ? `${(video.views / 1000).toFixed(1)}K`
        : String(video.views)
    : null;

  const thumbnailUrl =
    video.thumbnail || `https://i.ytimg.com/vi/${video.id}/hqdefault.jpg`;

  return (
    <div
      className={`relative rounded-lg overflow-hidden border cursor-pointer transition-all group ${
        isSelected
          ? "border-purple-500 ring-1 ring-purple-500/50"
          : "border-gray-700 hover:border-gray-500"
      } ${isProcessed ? "ring-1 ring-green-500/30" : ""}`}
      onClick={() => toggleSelect(video.id)}
    >
      {/* Thumbnail */}
      <div className="aspect-[9/16] bg-gray-800 relative overflow-hidden">
        <img
          src={thumbnailUrl}
          alt={video.title}
          className="w-full h-full object-cover"
          loading="lazy"
        />

        {/* Duration badge */}
        <span className="absolute bottom-2 right-2 bg-black/80 text-white text-xs px-1.5 py-0.5 rounded">
          {durationStr}
        </span>

        {/* Status badges */}
        <div className="absolute top-2 right-2 flex flex-col gap-1">
          {isDownloaded && (
            <span className="bg-blue-600/80 text-white text-[10px] px-1.5 py-0.5 rounded">
              DL
            </span>
          )}
          {isDownloading && (
            <span className="bg-yellow-600/80 text-white text-[10px] px-1.5 py-0.5 rounded animate-pulse">
              ...
            </span>
          )}
          {isProcessed && (
            <span className="bg-green-600/80 text-white text-[10px] px-1.5 py-0.5 rounded">
              DONE
            </span>
          )}
        </div>

        {/* Select overlay */}
        {isSelected && (
          <div className="absolute inset-0 bg-purple-600/20 flex items-center justify-center">
            <svg className="w-10 h-10 text-purple-400" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
            </svg>
          </div>
        )}
      </div>

      {/* Info */}
      <div className="p-2 bg-gray-900/80">
        <h3 className="text-xs font-medium text-gray-200 line-clamp-2 leading-tight">
          {video.title}
        </h3>
        <div className="flex items-center justify-between mt-1">
          <p className="text-[11px] text-gray-400 truncate max-w-[70%]">{video.channel}</p>
          {viewsStr && <p className="text-[10px] text-gray-500">{viewsStr} views</p>}
        </div>
      </div>
    </div>
  );
}
