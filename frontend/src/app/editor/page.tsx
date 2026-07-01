"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import SubtitleEditor from "@/components/editor/SubtitleEditor";
import TimelineCropEditor from "@/components/editor/TimelineCropEditor";

function EditorContent() {
  const params = useSearchParams();
  const requestedMode = params.get("mode");
  const [mode, setMode] = useState<"timeline" | "subtitles">(
    requestedMode === "subtitles" ? "subtitles" : "timeline"
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-800 bg-gray-950 p-2">
        <div className="flex rounded-md bg-gray-900 p-1">
          <button
            onClick={() => setMode("timeline")}
            className={`rounded px-4 py-2 text-sm font-medium transition ${
              mode === "timeline" ? "bg-cyan-700 text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            Timeline & Crop
          </button>
          <button
            onClick={() => setMode("subtitles")}
            className={`rounded px-4 py-2 text-sm font-medium transition ${
              mode === "subtitles" ? "bg-purple-700 text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            Subtitles
          </button>
        </div>
        <p className="text-xs text-gray-500">Choose extra edits or go straight to export.</p>
      </div>

      {mode === "timeline" ? <TimelineCropEditor /> : <SubtitleEditor />}
    </div>
  );
}

export default function EditorPage() {
  return (
    <Suspense fallback={<div className="text-sm text-gray-400">Loading editor...</div>}>
      <EditorContent />
    </Suspense>
  );
}
