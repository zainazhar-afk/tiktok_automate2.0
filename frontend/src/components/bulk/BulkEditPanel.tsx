"use client";

import { useApp } from "@/lib/store";
import AntiDetectionControls from "@/components/editor/AntiDetectionControls";

export default function BulkEditPanel() {
  const { state, processSelected, runPipeline } = useApp();

  const downloadedCount = state.downloadedPaths.size;
  const processedCount = state.processedPaths.size;
  const isProcessing = state.processingIds.size > 0;
  const hasPipelineJobs = state.jobs.some(j => j.status === "downloading" || j.status === "processing");

  return (
    <div className="space-y-6">
      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "Discovered", value: state.discoveredVideos.length, color: "text-gray-400" },
          { label: "Selected", value: state.selectedVideoIds.size, color: "text-blue-400" },
          { label: "Downloaded", value: downloadedCount, color: "text-yellow-400" },
          { label: "Processed", value: processedCount, color: "text-green-400" },
        ].map((stat) => (
          <div
            key={stat.label}
            className="bg-gray-900 border border-gray-700 rounded-lg p-3 text-center"
          >
            <div className={`text-2xl font-bold ${stat.color}`}>{stat.value}</div>
            <div className="text-xs text-gray-500 mt-1">{stat.label}</div>
          </div>
        ))}
      </div>

      <AntiDetectionControls compact />

      {/* Processing Actions */}
      <div className="flex gap-3">
        <button
          onClick={processSelected}
          disabled={downloadedCount === 0 || isProcessing}
          className="flex-1 px-4 py-3 bg-purple-600 hover:bg-purple-700 disabled:opacity-40
            text-white font-medium rounded-lg transition-colors text-sm"
        >
          {isProcessing
            ? `Processing ${state.processingIds.size} videos...`
            : `Process ${downloadedCount} Downloaded Videos`}
        </button>

        <button
          onClick={runPipeline}
          disabled={state.selectedVideoIds.size === 0 || hasPipelineJobs}
          className="flex-1 px-4 py-3 bg-green-600 hover:bg-green-700 disabled:opacity-40
            text-white font-medium rounded-lg transition-colors text-sm"
        >
          {hasPipelineJobs ? "Pipeline Running..." : "Run Full Pipeline (Download + Process)"}
        </button>
      </div>

      {/* Downloaded List */}
      {downloadedCount > 0 && (
        <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-200 mb-3">
            Downloaded Videos ({downloadedCount})
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
            {Array.from(state.downloadedPaths.entries()).map(([id, path]) => {
              const video = state.discoveredVideos.find((v) => v.id === id);
              const isDone = state.processedPaths.has(id);
              const isProc = state.processingIds.has(id);
              return (
                <div
                  key={id}
                  className={`text-xs p-2 rounded border ${
                    isDone
                      ? "border-green-700 bg-green-900/20"
                      : isProc
                        ? "border-yellow-700 bg-yellow-900/20"
                        : "border-gray-700 bg-gray-800/50"
                  }`}
                >
                  <p className="text-gray-300 truncate">{video?.title || id}</p>
                  <p className="text-gray-500 mt-1">
                    {isDone ? "Processed" : isProc ? "Processing..." : "Ready"}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Jobs Status */}
      {state.jobs.length > 0 && (
        <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-200 mb-3">
            Pipeline Jobs ({state.jobs.length})
          </h3>
          <div className="space-y-2">
            {state.jobs.map((job) => {
              const statusColors: Record<string, string> = {
                queued: "bg-gray-600",
                downloading: "bg-blue-600",
                processing: "bg-yellow-600",
                completed: "bg-green-600",
                failed: "bg-red-600",
              };
              const barColor = statusColors[job.status] || "bg-gray-600";
              return (
                <div key={job.job_id} className="flex items-center gap-3 text-xs">
                  <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${barColor} transition-all duration-500 rounded-full`}
                      style={{ width: `${(job.progress || 0) * 100}%` }}
                    />
                  </div>
                  <span
                    className={`w-20 text-right ${
                      job.status === "failed" ? "text-red-400" : "text-gray-400"
                    }`}
                  >
                    {job.status}
                    {job.error ? `: ${job.error.substring(0, 30)}` : ""}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
