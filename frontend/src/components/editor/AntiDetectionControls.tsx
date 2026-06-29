"use client";

import { useEffect, useState } from "react";
import { listAssets } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { AntiDetectionConfig, AntiDetectionLevel, AssetLibrary, TextRemovalRegion } from "@/types";

const LEVELS: { value: AntiDetectionLevel; label: string; desc: string }[] = [
  { value: "mild", label: "Mild", desc: "Basic watermark removal + crop jitter" },
  { value: "moderate", label: "Moderate", desc: "Full video+audio randomization" },
  { value: "aggressive", label: "Aggressive", desc: "Maximum evasion, all transforms" },
];

type ControlKey = keyof Pick<
  AntiDetectionConfig,
  | "mirror_padding"
  | "scene_reversal"
  | "frame_insertion"
  | "crop_jitter"
  | "color_lut"
  | "audio_pitch_shift"
  | "audio_eq"
  | "audio_segment_reversal"
  | "remove_watermark"
  | "speed_variation"
  | "horizontal_flip"
  | "rotation_jitter"
  | "smart_crop"
  | "auto_subtitles"
>;

const CONTROLS: { key: ControlKey; label: string }[] = [
  { key: "mirror_padding", label: "Mirror Padding" },
  { key: "scene_reversal", label: "Scene Reversal" },
  { key: "frame_insertion", label: "Black Frame Insertion" },
  { key: "crop_jitter", label: "Crop Jitter" },
  { key: "color_lut", label: "Color LUT Variation" },
  { key: "audio_pitch_shift", label: "Audio Pitch Shift" },
  { key: "audio_eq", label: "Audio EQ Randomization" },
  { key: "audio_segment_reversal", label: "Audio Segment Reversal" },
  { key: "remove_watermark", label: "Watermark Removal" },
  { key: "speed_variation", label: "Speed Variation" },
  { key: "horizontal_flip", label: "Horizontal Flip" },
  { key: "rotation_jitter", label: "Rotation Jitter" },
  { key: "smart_crop", label: "Smart Crop (content-aware)" },
  { key: "auto_subtitles", label: "Auto Subtitles (burn-in)" },
];

interface Props {
  compact?: boolean;
}

export default function AntiDetectionControls({ compact = false }: Props) {
  const { state, setAntiDetection } = useApp();
  const [assets, setAssets] = useState<AssetLibrary>({ music: [], voiceover: [] });
  const [assetError, setAssetError] = useState<string | null>(null);
  const customRegion = state.antiDetection.text_removal_regions[0];

  useEffect(() => {
    if (compact) return;
    let mounted = true;
    listAssets()
      .then((data) => {
        if (mounted) {
          setAssets(data);
          setAssetError(null);
        }
      })
      .catch((e: unknown) => {
        if (mounted) {
          setAssetError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      mounted = false;
    };
  }, [compact]);

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
        remove_top_text_banner: false,
        text_removal_mode: "blur",
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
        remove_top_text_banner: false,
        text_removal_mode: "blur",
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
        remove_top_text_banner: true,
        text_removal_mode: "blur",
        speed_variation: true,
        horizontal_flip: true,
        rotation_jitter: true,
      });
    }
  };

  const setCustomRegionEnabled = (enabled: boolean) => {
    if (!enabled) {
      setAntiDetection({ text_removal_regions: [] });
      return;
    }
    const next: TextRemovalRegion = customRegion || {
      x_pct: 0.0,
      y_pct: 0.0,
      w_pct: 1.0,
      h_pct: 0.14,
      mode: null,
    };
    setAntiDetection({ text_removal_regions: [next] });
  };

  const setCustomRegionPatch = (patch: Partial<TextRemovalRegion>) => {
    const next: TextRemovalRegion = {
      x_pct: customRegion?.x_pct ?? 0,
      y_pct: customRegion?.y_pct ?? 0,
      w_pct: customRegion?.w_pct ?? 1,
      h_pct: customRegion?.h_pct ?? 0.14,
      mode: customRegion?.mode ?? null,
      ...patch,
    };
    setAntiDetection({ text_removal_regions: [next] });
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

      {!compact && (
        <div className="mt-4 pt-3 border-t border-gray-800 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs font-medium text-gray-400">Text/Banner Removal</div>
              <p className="text-[10px] text-gray-600 mt-0.5">
                Crop top/bottom banners or mask known text areas.
              </p>
            </div>
            <select
              value={state.antiDetection.text_removal_mode}
              onChange={(e) =>
                setAntiDetection({
                  text_removal_mode: e.target.value as AntiDetectionConfig["text_removal_mode"],
                })
              }
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200"
            >
              <option value="blur">Blur/inpaint</option>
              <option value="crop">Crop away</option>
              <option value="cover">Cover black</option>
            </select>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-xs text-gray-300">
              <span className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={state.antiDetection.remove_top_text_banner}
                  onChange={(e) => setAntiDetection({ remove_top_text_banner: e.target.checked })}
                  className="rounded bg-gray-700 border-gray-600 text-purple-600 focus:ring-purple-500/50"
                />
                Remove top banner/text
              </span>
              <input
                type="range"
                min={0.04}
                max={0.35}
                step={0.01}
                value={state.antiDetection.top_text_height_pct}
                onChange={(e) => setAntiDetection({ top_text_height_pct: Number(e.target.value) })}
                className="w-full accent-purple-600 disabled:opacity-40"
                disabled={!state.antiDetection.remove_top_text_banner}
              />
              <span className="block text-[10px] text-gray-500">
                Top height {Math.round(state.antiDetection.top_text_height_pct * 100)}%
              </span>
            </label>

            <label className="space-y-1 text-xs text-gray-300">
              <span className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={state.antiDetection.remove_text_overlays}
                  onChange={(e) => setAntiDetection({ remove_text_overlays: e.target.checked })}
                  className="rounded bg-gray-700 border-gray-600 text-purple-600 focus:ring-purple-500/50"
                />
                Remove bottom captions/text
              </span>
              <input
                type="range"
                min={0.04}
                max={0.35}
                step={0.01}
                value={state.antiDetection.bottom_text_height_pct}
                onChange={(e) => setAntiDetection({ bottom_text_height_pct: Number(e.target.value) })}
                className="w-full accent-purple-600 disabled:opacity-40"
                disabled={!state.antiDetection.remove_text_overlays}
              />
              <span className="block text-[10px] text-gray-500">
                Bottom height {Math.round(state.antiDetection.bottom_text_height_pct * 100)}%
              </span>
            </label>
          </div>

          <div className="rounded border border-gray-800 bg-gray-950/40 p-3 space-y-2">
            <label className="flex items-center gap-2 text-xs text-gray-300">
              <input
                type="checkbox"
                checked={Boolean(customRegion)}
                onChange={(e) => setCustomRegionEnabled(e.target.checked)}
                className="rounded bg-gray-700 border-gray-600 text-purple-600 focus:ring-purple-500/50"
              />
              Custom text box removal
            </label>
            {customRegion && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {[
                  ["x_pct", "X", customRegion.x_pct],
                  ["y_pct", "Y", customRegion.y_pct],
                  ["w_pct", "Width", customRegion.w_pct],
                  ["h_pct", "Height", customRegion.h_pct],
                ].map(([key, label, value]) => (
                  <label key={key as string} className="flex flex-col gap-1 text-[11px] text-gray-500">
                    {label} %
                    <input
                      type="number"
                      min={key === "w_pct" || key === "h_pct" ? 1 : 0}
                      max={100}
                      value={Math.round((value as number) * 100)}
                      onChange={(e) =>
                        setCustomRegionPatch({
                          [key as keyof TextRemovalRegion]: Math.max(0, Math.min(100, Number(e.target.value))) / 100,
                        })
                      }
                      className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
                    />
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Enhancements: music, voiceover, subtitles */}
      {!compact && (
        <div className="mt-4 pt-3 border-t border-gray-800 space-y-3">
          <div className="text-xs font-medium text-gray-400">Audio & Captions</div>

          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 text-[11px] text-gray-400">
              Background music
              <select
                value={state.antiDetection.background_music ?? ""}
                onChange={(e) => setAntiDetection({ background_music: e.target.value || null })}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
              >
                <option value="">No music</option>
                {assets.music.length === 0 && <option disabled>No music files found</option>}
                {assets.music.map((file) => (
                  <option key={file} value={file}>
                    {file}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-[11px] text-gray-400">
              Voiceover
              <select
                value={state.antiDetection.voiceover_path ?? ""}
                onChange={(e) => setAntiDetection({ voiceover_path: e.target.value || null })}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
              >
                <option value="">No voiceover</option>
                {assets.voiceover.length === 0 && <option disabled>No voiceover files found</option>}
                {assets.voiceover.map((file) => (
                  <option key={file} value={file}>
                    {file}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-[11px] text-gray-400">
              Music volume ({Math.round(state.antiDetection.music_volume * 100)}%)
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={state.antiDetection.music_volume}
                onChange={(e) => setAntiDetection({ music_volume: Number(e.target.value) })}
                className="accent-purple-600"
              />
            </label>

            <label className="flex flex-col gap-1 text-[11px] text-gray-400">
              Subtitle style
              <select
                value={state.antiDetection.subtitle_style}
                onChange={(e) =>
                  setAntiDetection({ subtitle_style: e.target.value as AntiDetectionConfig["subtitle_style"] })
                }
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
              >
                <option value="default">Default</option>
                <option value="bold">Bold (yellow)</option>
                <option value="minimal">Minimal</option>
              </select>
            </label>
          </div>

          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer hover:text-white">
            <input
              type="checkbox"
              checked={state.antiDetection.music_ducking}
              onChange={(e) => setAntiDetection({ music_ducking: e.target.checked })}
              className="rounded bg-gray-700 border-gray-600 text-purple-600 focus:ring-purple-500/50"
            />
            Duck music under speech (sidechain)
          </label>

          <p className="text-[10px] text-gray-600 leading-relaxed">
            Music/voiceover files go in <code>backend/assets/music</code> and{" "}
            <code>backend/assets/voiceover</code>. Auto subtitles require{" "}
            <code>pip install faster-whisper</code>.
          </p>
          {assetError && <p className="text-[10px] text-red-400">{assetError}</p>}
        </div>
      )}

      {/* Active protections summary */}
      <div className={`flex flex-wrap gap-1 ${compact ? "mt-2" : "mt-3"}`}>
        {state.antiDetection.remove_top_text_banner && (
          <span className="text-[10px] bg-purple-600/20 text-purple-300 px-1.5 py-0.5 rounded">
            Top Text Removal
          </span>
        )}
        {state.antiDetection.remove_text_overlays && (
          <span className="text-[10px] bg-purple-600/20 text-purple-300 px-1.5 py-0.5 rounded">
            Bottom Text Removal
          </span>
        )}
        {customRegion && (
          <span className="text-[10px] bg-purple-600/20 text-purple-300 px-1.5 py-0.5 rounded">
            Custom Text Box
          </span>
        )}
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
