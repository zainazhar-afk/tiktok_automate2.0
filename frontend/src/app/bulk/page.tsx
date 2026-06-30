"use client";

import BulkEditPanel from "@/components/bulk/BulkEditPanel";

export default function BulkPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Bulk Edit & Process</h1>
        <p className="text-gray-400 text-sm mt-1">
          Configure editing presets and process approved videos in bulk.
          Processed videos appear in the Export tab for final review.
        </p>
      </div>
      <BulkEditPanel />
    </div>
  );
}
