"use client";

import TrendingVideosGrid from "@/components/discovery/TrendingVideosGrid";

export default function HomePage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Discover Trending Shorts</h1>
        <p className="text-gray-400 text-sm mt-1">
          Find trending YouTube Shorts by keyword, hashtag, or competitor channels.
          Select videos to download them for anti-detection processing.
        </p>
      </div>
      <TrendingVideosGrid />
    </div>
  );
}
