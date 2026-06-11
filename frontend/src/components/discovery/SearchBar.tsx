"use client";

import { useState } from "react";
import { useApp } from "@/lib/store";
import DiscoveryFiltersPanel from "./DiscoveryFilters";

export default function SearchBar() {
  const [query, setQuery] = useState("");
  const { searchVideos, discoverTrending } = useApp();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) searchVideos(query.trim());
    else discoverTrending();
  };

  return (
    <div className="space-y-2">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search Shorts... (empty = trending)"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-sm
            text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500"
        />
        <button
          type="submit"
          className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white text-sm font-medium rounded-lg"
        >
          Search
        </button>
      </form>
      <DiscoveryFiltersPanel />
    </div>
  );
}

export function SourceButtons() {
  const { discoverTrending, discoverByHashtag, discoverCompetitor } = useApp();
  const [hashtag, setHashtag] = useState("");
  const [competitor, setCompetitor] = useState("");

  return (
    <div className="flex flex-wrap gap-2 mt-2">
      <button
        onClick={() => discoverTrending()}
        className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs rounded-lg"
      >
        Trending
      </button>
      <div className="flex gap-1">
        <input
          type="text"
          value={hashtag}
          onChange={(e) => setHashtag(e.target.value)}
          placeholder="#hashtag"
          className="w-28 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-gray-200"
          onKeyDown={(e) => {
            if (e.key === "Enter" && hashtag.trim()) {
              discoverByHashtag(hashtag.trim().replace(/^#/, ""));
              setHashtag("");
            }
          }}
        />
        <button
          onClick={() => {
            if (hashtag.trim()) {
              discoverByHashtag(hashtag.trim().replace(/^#/, ""));
              setHashtag("");
            }
          }}
          className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs rounded-lg disabled:opacity-50"
          disabled={!hashtag.trim()}
        >
          Search #
        </button>
      </div>
      <div className="flex gap-1">
        <input
          type="text"
          value={competitor}
          onChange={(e) => setCompetitor(e.target.value)}
          placeholder="@channel"
          className="w-32 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-gray-200"
          onKeyDown={(e) => {
            if (e.key === "Enter" && competitor.trim()) {
              discoverCompetitor(competitor.trim().replace(/^@/, ""));
              setCompetitor("");
            }
          }}
        />
        <button
          onClick={() => {
            if (competitor.trim()) {
              discoverCompetitor(competitor.trim().replace(/^@/, ""));
              setCompetitor("");
            }
          }}
          className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs rounded-lg disabled:opacity-50"
          disabled={!competitor.trim()}
        >
          Scrape Channel
        </button>
      </div>
    </div>
  );
}
