"use client";

import ExportPanel from "@/components/export/ExportPanel";

export default function ExportPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Export Videos</h1>
        <p className="text-gray-400 text-sm mt-1">
          Download processed videos to your PC. Upload them manually to TikTok.
          All videos have anti-detection edits applied.
        </p>
      </div>
      <ExportPanel />
    </div>
  );
}
