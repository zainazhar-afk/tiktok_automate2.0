"use client";

import Link from "next/link";
import { useApp } from "@/lib/store";
import AntiDetectionControls from "@/components/editor/AntiDetectionControls";

export default function BulkEditPanel() {
  const {
    state,
    processSelected,
    processAllDownloaded,
    runPipeline,
    retryFailedJobs,
    clearError,
  } = useApp();

  const downloadedCount = state.downloadedPaths.size;
  const processedCount = state.processedPaths.size;
  const isProcessing = state.processingIds.size > 0;
  const hasPipelineJobs = state.jobs.some((j) =>
    j.status === "queued" || j.status === "downloading" || j.status === "processing"
  );
  const selectedDownloadedCount = Array.from(state.downloadedPaths.keys()).filter((id) =>
    state.selectedVideoIds.has(id)
  ).length;
  const failedJobs = state.jobs.filter((job) => job.status === "failed");
  const firstProcessedId = Array.from(state.processedPaths.keys())[0];

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


      {state.error && (
        <div className="flex items-start justify-between gap-3 bg-red-950/40 border border-red-800 rounded-lg p-3">
          <p className="text-sm text-red-200">{state.error}</p>
          <button
            onClick={clearError}
            className="px-2 py-1 text-xs bg-red-900/50 hover:bg-red-900 text-red-100 rounded"
          >
            Dismiss
          </button>
        </div>
      )}

      <AntiDetectionControls />

      {/* Processing Actions */}
      <div className="grid gap-3 md:grid-cols-3">
        <button
          onClick={processSelected}
          disabled={selectedDownloadedCount === 0 || isProcessing}
          className="px-4 py-3 bg-purple-600 hover:bg-purple-700 disabled:opacity-40
            text-white font-medium rounded-lg transition-colors text-sm"
        >
          {isProcessing
            ? `Processing ${state.processingIds.size} videos...`
            : `Process ${selectedDownloadedCount} Selected Downloaded`}
        </button>

        <button
          onClick={processAllDownloaded}
          disabled={downloadedCount === 0 || isProcessing}
          className="px-4 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40
            text-white font-medium rounded-lg transition-colors text-sm"
        >
          Process All Downloaded ({downloadedCount})
        </button>

        <button
          onClick={runPipeline}
          disabled={state.selectedVideoIds.size === 0 || hasPipelineJobs}
          className="px-4 py-3 bg-green-600 hover:bg-green-700 disabled:opacity-40
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
            {Array.from(state.downloadedPaths.keys()).map((id) => {
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

      {processedCount > 0 && (
        <div className="rounded-lg border border-green-700/60 bg-green-950/20 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h3 className="text-sm font-medium text-green-100">Processed videos are ready</h3>
              <p className="mt-1 text-xs text-green-200/70">
                Continue with subtitle editing or go straight to export.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link
                href={firstProcessedId ? `/editor?video=${encodeURIComponent(firstProcessedId)}` : "/editor"}
                className="rounded bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
              >
                Additional Editing
              </Link>
              <Link
                href="/export"
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                Export
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* Jobs Status */}
      {state.jobs.length > 0 && (
        <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-200 mb-3">
            Pipeline Jobs ({state.jobs.length})
          </h3>
          {failedJobs.length > 0 && (
            <div className="mb-3 flex justify-end">
              <button
                onClick={retryFailedJobs}
                disabled={hasPipelineJobs}
                className="px-3 py-1.5 bg-red-700 hover:bg-red-600 disabled:opacity-40 text-white text-xs rounded"
              >
                Retry failed ({failedJobs.length})
              </button>
            </div>
          )}
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
                <div key={job.job_id} className="space-y-1 rounded border border-gray-800 bg-gray-950/40 p-2 text-xs">
                  <div className="flex items-center gap-3">
                    <span className="w-36 truncate text-gray-300" title={job.title || job.video_id}>
                      {job.title || job.video_id}
                    </span>
                    <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full ${barColor} transition-all duration-500 rounded-full`}
                        style={{ width: `${Math.round((job.progress || 0) * 100)}%` }}
                      />
                    </div>
                    <span
                      className={`w-28 text-right ${
                        job.status === "failed" ? "text-red-400" : "text-gray-400"
                      }`}
                    >
                      {job.status} {Math.round((job.progress || 0) * 100)}%
                    </span>
                  </div>
                  {job.error && <p className="text-red-300 break-words">{job.error}</p>}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
