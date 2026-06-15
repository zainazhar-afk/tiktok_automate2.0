"use client";

import { useApp } from "@/lib/store";
import { NICHE_OPTIONS, REGION_OPTIONS } from "@/types";
import type { DiscoveryFilters as Filters } from "@/types";

export default function DiscoveryFiltersPanel() {
  const { state, setFilters, applyFilters } = useApp();
  const f = state.filters;

  const update = (patch: Partial<Filters>) => setFilters(patch);

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 p-3 bg-gray-900/60 border border-gray-700 rounded-lg text-xs">
        <label className="flex flex-col gap-1 text-gray-400">
          Niche / Topic
          <select
            value={f.niche || ""}
            onChange={(e) => update({ niche: e.target.value || undefined })}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
          >
            {NICHE_OPTIONS.map((n) => (
              <option key={n.value} value={n.value}>
                {n.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-gray-400">
          Sort by
          <select
            value={f.order}
            onChange={(e) => update({ order: e.target.value as Filters["order"] })}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
          >
            <option value="viewCount">Most viewed</option>
            <option value="date">Newest</option>
            <option value="relevance">Relevance</option>
            <option value="rating">Top rated</option>
          </select>
        </label>

        <label className="flex flex-col gap-1 text-gray-400">
          Region
          <select
            value={f.region_code || "US"}
            onChange={(e) => update({ region_code: e.target.value })}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
          >
            {REGION_OPTIONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-gray-400">
          Min views
          <input
            type="number"
            placeholder="e.g. 10000"
            value={f.min_views ?? ""}
            onChange={(e) => update({ min_views: e.target.value ? Number(e.target.value) : undefined })}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
          />
        </label>

        <label className="flex flex-col gap-1 text-gray-400">
          Max views
          <input
            type="number"
            placeholder="optional"
            value={f.max_views ?? ""}
            onChange={(e) => update({ max_views: e.target.value ? Number(e.target.value) : undefined })}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
          />
        </label>

        <label className="flex flex-col gap-1 text-gray-400">
          Published within (days)
          <input
            type="number"
            placeholder="e.g. 7"
            value={f.published_within_days ?? ""}
            onChange={(e) =>
              update({ published_within_days: e.target.value ? Number(e.target.value) : undefined })
            }
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
          />
        </label>

        <label className="flex flex-col gap-1 text-gray-400 lg:col-span-2">
          Duration (sec)
          <div className="flex gap-1">
            <input
              type="number"
              value={f.min_duration}
              onChange={(e) => update({ min_duration: Number(e.target.value) })}
              className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
            />
            <span className="self-center text-gray-500">-</span>
            <input
              type="number"
              value={f.max_duration}
              onChange={(e) => update({ max_duration: Number(e.target.value) })}
              className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
            />
          </div>
        </label>

        <label className="flex flex-col gap-1 text-gray-400">
          Results
          <input
            type="number"
            min={1}
            max={50}
            value={f.max_results}
            onChange={(e) => update({ max_results: Math.min(50, Math.max(1, Number(e.target.value) || 20)) })}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
          />
        </label>
      </div>

      <div className="flex justify-end">
        <button
          onClick={() => applyFilters()}
          disabled={state.isLoading}
          className="px-4 py-1.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white text-xs font-medium rounded-lg"
        >
          {state.isLoading ? "Applying..." : "Apply filters"}
        </button>
      </div>
    </div>
  );
}
