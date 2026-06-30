"use client";

import ExportPanel from "@/components/export/ExportPanel";

export default function ExportPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Export Videos</h1>
        <p className="text-gray-400 text-sm mt-1">
          Download processed videos, captions, covers, and posting assets.
          Review rights and platform requirements before publishing.
        </p>
      </div>
      <ExportPanel />
    </div>
  );
}
