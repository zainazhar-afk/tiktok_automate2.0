"use client";

import { useApp } from "@/lib/store";
import { AntiDetectionLevel } from "@/types";

const LEVELS: { value: AntiDetectionLevel; label: string; desc: string }[] = [
  { value: "mild", label: "Mild", desc: "Basic watermark removal + crop jitter" },
  { value: "moderate", label: "Moderate", desc: "Full video+audio randomization" },
  { value: "aggressive", label: "Aggressive", desc: "Maximum evasion, all transforms" },
];

const CONTROLS: { key: keyof NonNullable<ReturnType<typeof useApp>["state"]["antiDetection"]>; label: string }[] = [
  { key: "mirror_padding", label: "Mirror Padding" },
  { key: "scene_reversal", label: "Scene Reversal" },
  { key: "frame_insertion", label: "Black Frame Insertion" },
  { key: "crop_jitter", label: "Crop Jitter" },
  { key: "color_lut", label: "Color LUT Variation" },
  { key: "audio_pitch_shift", label: "Audio Pitch Shift" },
  { key: "audio_eq", label: "Audio EQ Randomization" },
  { key: "audio_segment_reversal", label: "Audio Segment Reversal" },
  { key: "remove_watermark", label: "Watermark Removal" },
  { key: "remove_text_overlays", label: "Text Overlay Removal" },
  { key: "speed_variation", label: "Speed Variation" },
  { key: "horizontal_flip", label: "Horizontal Flip" },
  { key: "rotation_jitter", label: "Rotation Jitter" },
];

interface Props {
  compact?: boolean;
}

export default function AntiDetectionControls({ compact = false }: Props) {
  const { state, setAntiDetection } = useApp();

  const handleLevelChange = (level: AntiDetectionLevel) => {
    setAntiDetection({ level });
    // Reset all filters based on preset level
    if (level === "mild") {
      setAntiDetection({
        level: "mild",
        mirror_padding: true,
        scene_reversal: false,
        frame_insertion: false,
        crop_jitter: true,
        color_lut: false,
        audio_pitch_shift: false,
        audio_eq: false,
        audio_segment_reversal: false,
        remove_watermark: true,
        remove_text_overlays: true,
        speed_variation: false,
        horizontal_flip: false,
        rotation_jitter: false,
      });
    } else if (level === "moderate") {
      setAntiDetection({
        level: "moderate",
        mirror_padding: true,
        scene_reversal: true,
        frame_insertion: true,
        crop_jitter: true,
        color_lut: true,
        audio_pitch_shift: true,
        audio_eq: true,
        audio_segment_reversal: false,
        remove_watermark: true,
        remove_text_overlays: true,
        speed_variation: false,
        horizontal_flip: false,
        rotation_jitter: false,
      });
    } else {
      setAntiDetection({
        level: "aggressive",
        mirror_padding: true,
        scene_reversal: true,
        frame_insertion: true,
        crop_jitter: true,
        color_lut: true,
        audio_pitch_shift: true,
        audio_eq: true,
        audio_segment_reversal: true,
        remove_watermark: true,
        remove_text_overlays: true,
        speed_variation: true,
        horizontal_flip: true,
        rotation_jitter: true,
      });
    }
  };

  return (
    <div className={`bg-gray-900 border border-gray-700 rounded-lg ${compact ? "p-3" : "p-4"}`}>
      <h3 className={`font-medium text-gray-200 ${compact ? "text-sm" : "text-base"} mb-3`}>
        Anti-Detection Settings
      </h3>

      {/* Level selector */}
      <div className="flex gap-2 mb-4">
        {LEVELS.map((lv) => (
          <button
            key={lv.value}
            onClick={() => handleLevelChange(lv.value)}
            className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-all ${
              state.antiDetection.level === lv.value
                ? "bg-purple-600 text-white ring-1 ring-purple-400"
                : "bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700"
            }`}
          >
            <div>{lv.label}</div>
            {!compact && <div className="text-[10px] opacity-70 mt-0.5">{lv.desc}</div>}
          </button>
        ))}
      </div>

      {/* Individual toggles */}
      {!compact && (
        <div className="grid grid-cols-2 gap-2">
          {CONTROLS.map((ctrl) => (
            <label
              key={ctrl.key}
              className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer
                hover:text-white transition-colors"
            >
              <input
                type="checkbox"
                checked={state.antiDetection[ctrl.key] as boolean}
                onChange={(e) => setAntiDetection({ [ctrl.key]: e.target.checked })}
                className="rounded bg-gray-700 border-gray-600 text-purple-600
                  focus:ring-purple-500/50"
              />
              {ctrl.label}
            </label>
          ))}
        </div>
      )}

      {/* Active protections summary */}
      <div className={`flex flex-wrap gap-1 ${compact ? "mt-2" : "mt-3"}`}>
        {CONTROLS.filter((c) => state.antiDetection[c.key]).map((ctrl) => (
          <span
            key={ctrl.key}
            className="text-[10px] bg-purple-600/20 text-purple-300 px-1.5 py-0.5 rounded"
          >
            {ctrl.label}
          </span>
        ))}
      </div>
    </div>
  );
}
