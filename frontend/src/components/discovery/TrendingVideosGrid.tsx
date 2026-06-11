"use client";

import { useEffect } from "react";
import { useApp } from "@/lib/store";
import VideoCard from "./VideoCard";
import SearchBar, { SourceButtons } from "./SearchBar";

export default function TrendingVideosGrid() {
  const { state, discoverTrending, selectAll, deselectAll, downloadSelected } = useApp();

  useEffect(() => {
    discoverTrending();
  }, [discoverTrending]);

  const selectedCount = state.selectedVideoIds.size;
  const totalCount = state.discoveredVideos.length;

  return (
    <div className="space-y-4">
      <SearchBar />
      <SourceButtons />

      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>Source: {state.discoverySource}</span>
        <div className="flex gap-2">
          {state.prevPageToken && (
            <button
              onClick={() => discoverTrending(state.prevPageToken)}
              className="px-2 py-1 bg-gray-800 rounded hover:bg-gray-700"
            >
              ← Prev
            </button>
          )}
          {state.nextPageToken && (
            <button
              onClick={() => discoverTrending(state.nextPageToken)}
              className="px-2 py-1 bg-gray-800 rounded hover:bg-gray-700"
            >
              Next →
            </button>
          )}
        </div>
      </div>

      {totalCount > 0 && (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={selectedCount === totalCount ? deselectAll : selectAll}
              className="text-xs text-gray-400 hover:text-white"
            >
              {selectedCount === totalCount ? "Deselect All" : `Select All (${totalCount})`}
            </button>
            {selectedCount > 0 && (
              <span className="text-xs text-purple-400">{selectedCount} selected</span>
            )}
          </div>
          {selectedCount > 0 && (
            <button
              onClick={downloadSelected}
              disabled={state.downloadingIds.size > 0}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-lg"
            >
              {state.downloadingIds.size > 0
                ? `Downloading (${state.downloadingIds.size})...`
                : `Download ${selectedCount} Selected`}
            </button>
          )}
        </div>
      )}

      {state.isLoading && (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-500" />
          <span className="ml-3 text-gray-400 text-sm">Discovering videos...</span>
        </div>
      )}

      {state.error && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 text-red-300 text-sm">
          {state.error}
        </div>
      )}

      {!state.isLoading && totalCount > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
          {state.discoveredVideos.map((video) => (
            <VideoCard key={video.id} video={video} />
          ))}
        </div>
      )}

      {!state.isLoading && totalCount === 0 && !state.error && (
        <div className="text-center py-20 text-gray-500">
          <p className="text-lg">No videos discovered yet</p>
          <p className="text-sm mt-1">Adjust filters or search for content</p>
        </div>
      )}
    </div>
  );
}
