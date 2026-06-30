"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ProcessedVideoFile, SubtitleTrack, SubtitleWord } from "@/types";
import { useAuth } from "@/lib/auth";
import {
  applySubtitleTranscript,
  exportSubtitleTrack,
  getSubtitleTrack,
  importSubtitleTrack,
  listVideos,
  renderSubtitleVideo,
  saveSubtitleTrack,
  transcribeSubtitleTrack,
  translateSubtitleTrack,
  type TranscriptionProvider,
  videoFileUrl,
} from "@/lib/api";

const EMOJIS = ["🔥", "✨", "👇", "💡", "✅", "⚡"];
const LANGUAGES = [
  { value: "ur", label: "Urdu" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "pt", label: "Portuguese" },
  { value: "hi", label: "Hindi" },
  { value: "ja", label: "Japanese" },
];
const TRANSCRIPT_LANGUAGES = [
  { value: "auto", label: "Auto detect" },
  { value: "ur", label: "Urdu" },
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
  { value: "ar", label: "Arabic" },
  { value: "fa", label: "Persian" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "pt", label: "Portuguese" },
  { value: "ja", label: "Japanese" },
  { value: "multi", label: "Multilingual" },
];
const TRANSCRIPTION_PROVIDERS: { value: TranscriptionProvider; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "deepgram", label: "Deepgram" },
  { value: "groq", label: "Groq Whisper" },
  { value: "whisper", label: "Local Whisper" },
];

function formatTime(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const cs = Math.round((seconds - Math.floor(seconds)) * 100);
  return `${m}:${s.toString().padStart(2, "0")}.${cs.toString().padStart(2, "0")}`;
}

function clampTime(value: number) {
  return Math.max(0, Number.isFinite(value) ? value : 0);
}

function downloadText(filename: string, text: string, type: string) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function SubtitleEditor() {
  const params = useSearchParams();
  const { accessToken } = useAuth();
  const requestedVideo = params.get("video");
  const [videos, setVideos] = useState<ProcessedVideoFile[]>([]);
  const [activeId, setActiveId] = useState<string>(requestedVideo || "");
  const [track, setTrack] = useState<SubtitleTrack | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [applyingTranscript, setApplyingTranscript] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [keywordInput, setKeywordInput] = useState("");
  const [importFormat, setImportFormat] = useState<"srt" | "vtt">("srt");
  const [importText, setImportText] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("es");
  const [transcriptLanguage, setTranscriptLanguage] = useState("auto");
  const [transcriptionProvider, setTranscriptionProvider] = useState<TranscriptionProvider>("auto");

  const activeVideo = videos.find((video) => video.id === activeId) || null;
  const previewWords = useMemo(() => track?.words.slice(0, 8) || [], [track]);

  const loadVideos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listVideos("processed");
      const nextVideos = data.videos || [];
      setVideos(nextVideos);
      if (!activeId && nextVideos.length) {
        setActiveId(requestedVideo || nextVideos[0].id);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeId, requestedVideo]);

  const loadTrack = useCallback(async (videoId: string) => {
    if (!videoId) return;
    setError(null);
    try {
      const data = await getSubtitleTrack(videoId);
      setTrack({
        ...data,
        transcript: data.transcript || (data.words || []).map((word) => word.text).join(" "),
      });
      if (data.language && !["auto", "en"].includes(data.language)) {
        setTranscriptLanguage(data.language);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void loadVideos(), 0);
    return () => clearTimeout(timer);
  }, [loadVideos]);

  useEffect(() => {
    if (!activeId) return;
    const timer = setTimeout(() => void loadTrack(activeId), 0);
    return () => clearTimeout(timer);
  }, [activeId, loadTrack]);

  const setTrackPatch = (patch: Partial<SubtitleTrack>) => {
    setTrack((current) => (current ? { ...current, ...patch } : current));
  };

  const setWordPatch = (id: string, patch: Partial<SubtitleWord>) => {
    setTrack((current) => {
      if (!current) return current;
      const words = current.words.map((word) => (
        word.id === id ? { ...word, ...patch } : word
      ));
      return {
        ...current,
        words,
        transcript: words.map((word) => word.text).join(" "),
      };
    });
  };

  const addWordAfter = (word: SubtitleWord) => {
    setTrack((current) => {
      if (!current) return current;
      const idx = current.words.findIndex((item) => item.id === word.id);
      const nextWord: SubtitleWord = {
        id: crypto.randomUUID().slice(0, 10),
        text: "word",
        start: Number(word.end.toFixed(2)),
        end: Number((word.end + 0.4).toFixed(2)),
        highlighted: false,
      };
      const words = [...current.words];
      words.splice(idx + 1, 0, nextWord);
      return { ...current, words, transcript: words.map((item) => item.text).join(" ") };
    });
  };

  const deleteWord = (id: string) => {
    setTrack((current) => {
      if (!current) return current;
      const words = current.words.filter((word) => word.id !== id);
      return { ...current, words, transcript: words.map((word) => word.text).join(" ") };
    });
  };

  const highlightKeywords = () => {
    if (!track) return;
    const terms = keywordInput
      .split(/[, ]+/)
      .map((term) => term.trim().toLowerCase())
      .filter(Boolean);
    if (!terms.length) return;
    const words = track.words.map((word) => ({
      ...word,
      highlighted: terms.some((term) => word.text.toLowerCase().replace(/[^\w]/g, "").includes(term)),
    }));
    setTrackPatch({ words });
  };

  const handleApplyTranscript = async () => {
    if (!track || !track.transcript.trim()) return;
    setApplyingTranscript(true);
    setError(null);
    try {
      const applied = await applySubtitleTranscript(track);
      setTrack({
        ...applied,
        transcript: applied.transcript || applied.words.map((word) => word.text).join(" "),
      });
      setMessage(`Applied transcript to ${applied.words.length} timed words`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplyingTranscript(false);
    }
  };

  const handleSave = async () => {
    if (!track) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await saveSubtitleTrack(track);
      setTrack(saved);
      setMessage("Saved subtitle edits");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleImport = async () => {
    if (!activeId || !importText.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const imported = await importSubtitleTrack(activeId, importFormat, importText);
      setTrack(imported);
      setImportText("");
      setMessage("Imported subtitle file");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleTranscribe = async () => {
    if (!activeId) return;
    setTranscribing(true);
    setError(null);
    try {
      const transcribed = await transcribeSubtitleTrack(activeId, {
        language: transcriptLanguage,
        provider: transcriptionProvider,
        force: true,
      });
      setTrack({
        ...transcribed,
        transcript: transcribed.transcript || transcribed.words.map((word) => word.text).join(" "),
      });
      const languageLabel = TRANSCRIPT_LANGUAGES.find((item) => item.value === transcriptLanguage)?.label || transcriptLanguage;
      const providerLabel = TRANSCRIPTION_PROVIDERS.find((item) => item.value === transcriptionProvider)?.label || transcriptionProvider;
      setMessage(`Generated ${languageLabel} transcript with ${transcribed.words.length} words via ${providerLabel}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTranscribing(false);
    }
  };

  const handleExport = async (format: "srt" | "vtt") => {
    if (!track) return;
    const saved = await saveSubtitleTrack(track);
    setTrack(saved);
    const text = await exportSubtitleTrack(saved.video_id, format);
    downloadText(`${saved.video_id}_edited.${format}`, text, format === "vtt" ? "text/vtt" : "text/plain");
  };

  const handleTranslate = async () => {
    if (!track) return;
    setSaving(true);
    setError(null);
    try {
      const translated = await translateSubtitleTrack(track.video_id, targetLanguage, track.language || "en");
      setTrack(translated);
      setMessage("Translated subtitle draft");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleRender = async () => {
    if (!track) return;
    setRendering(true);
    setError(null);
    try {
      const saved = await saveSubtitleTrack(track);
      setTrack(saved);
      await renderSubtitleVideo(saved.video_id);
      await loadVideos();
      setMessage("Rendered edited-caption video");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRendering(false);
    }
  };

  const positionClass = {
    top: "items-start pt-20",
    middle: "items-center",
    bottom: "items-end pb-24",
  }[track?.position || "bottom"];

  const captionClass = {
    default: "bg-black/55 text-white border-white/10",
    bold: "bg-black/70 text-yellow-300 border-yellow-300/30 font-black uppercase",
    minimal: "bg-transparent text-white border-transparent shadow-none",
    neon: "bg-fuchsia-950/70 text-emerald-300 border-emerald-300/40 shadow-[0_0_20px_rgba(16,185,129,.35)]",
  }[track?.style || "default"];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Subtitle Editor</h1>
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            {["Choose video", "Edit words", "Save or render"].map((step, idx) => (
              <span key={step} className="rounded-full border border-gray-700 bg-gray-900 px-3 py-1 text-gray-300">
                {idx + 1}. {step}
              </span>
            ))}
          </div>
        </div>
        <div className="flex gap-2">
          <Link href="/bulk" className="rounded bg-gray-800 px-3 py-2 text-xs text-gray-200 hover:bg-gray-700">
            Bulk
          </Link>
          <Link href="/export" className="rounded bg-blue-600 px-3 py-2 text-xs text-white hover:bg-blue-700">
            Export
          </Link>
        </div>
      </div>

      {(error || message) && (
        <div className={`rounded-lg border p-3 text-sm ${error ? "border-red-800 bg-red-950/40 text-red-200" : "border-green-800 bg-green-950/30 text-green-200"}`}>
          {error || message}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[280px_1fr_360px]">
        <aside className="rounded-lg border border-gray-700 bg-gray-900 p-3">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-gray-200">Videos</h2>
            <button onClick={loadVideos} className="rounded bg-gray-800 px-2 py-1 text-xs text-gray-300 hover:bg-gray-700">
              Refresh
            </button>
          </div>
          <div className="max-h-[560px] space-y-2 overflow-y-auto">
            {loading && <p className="text-xs text-gray-500">Loading...</p>}
            {!loading && videos.length === 0 && <p className="text-xs text-gray-500">No processed videos yet.</p>}
            {videos.map((video) => (
              <button
                key={video.filename}
                onClick={() => setActiveId(video.id)}
                className={`w-full rounded border p-2 text-left text-xs transition ${
                  activeId === video.id
                    ? "border-purple-500 bg-purple-950/40 text-white"
                    : "border-gray-800 bg-gray-950/50 text-gray-300 hover:border-gray-600"
                }`}
              >
                <span className="block truncate font-medium">{video.title || video.filename}</span>
                <span className="mt-1 block text-gray-500">{video.filename}</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[260px_1fr]">
            <div className="mx-auto aspect-[9/16] w-full max-w-[260px] overflow-hidden rounded-lg border border-gray-700 bg-black">
              {activeVideo ? (
                <div className="relative h-full w-full">
                  <video
                    src={videoFileUrl(activeVideo.filename, accessToken)}
                    controls
                    className="h-full w-full object-contain"
                    preload="metadata"
                  />
                  {track && (
                    <div className={`pointer-events-none absolute inset-0 flex justify-center px-5 ${positionClass}`}>
                      <div className={`max-w-full rounded border px-3 py-2 text-center text-lg leading-tight ${captionClass}`}>
                        {previewWords.map((word) => (
                          <span
                            key={word.id}
                            className={`${word.highlighted ? "text-yellow-300" : ""} ${track.animation === "pop" ? "inline-block scale-105" : ""}`}
                          >
                            {word.text}{" "}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-gray-500">Select a video</div>
              )}
            </div>

            <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
              <h2 className="mb-3 text-sm font-medium text-gray-200">Transcript</h2>
              <textarea
                value={track?.transcript || ""}
                onChange={(e) => setTrackPatch({ transcript: e.target.value })}
                disabled={!track}
                className="h-40 w-full resize-none rounded border border-gray-700 bg-gray-950 p-3 text-sm text-gray-200 focus:border-purple-500 focus:outline-none disabled:opacity-50"
              />
              <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                <label className="grid gap-1 text-xs text-gray-400">
                  Audio language
                  <select
                    value={transcriptLanguage}
                    onChange={(e) => setTranscriptLanguage(e.target.value)}
                    disabled={!activeId || transcribing}
                    className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200 disabled:opacity-50"
                  >
                    {TRANSCRIPT_LANGUAGES.map((language) => (
                      <option key={language.value} value={language.value}>{language.label}</option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-1 text-xs text-gray-400">
                  Provider
                  <select
                    value={transcriptionProvider}
                    onChange={(e) => setTranscriptionProvider(e.target.value as TranscriptionProvider)}
                    disabled={!activeId || transcribing}
                    className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200 disabled:opacity-50"
                  >
                    {TRANSCRIPTION_PROVIDERS.map((provider) => (
                      <option key={provider.value} value={provider.value}>{provider.label}</option>
                    ))}
                  </select>
                </label>
                <button
                  onClick={handleTranscribe}
                  disabled={!activeId || transcribing}
                  className="self-end rounded bg-purple-700 px-3 py-2 text-xs text-white hover:bg-purple-600 disabled:opacity-40"
                >
                  {transcribing ? "Transcribing..." : "Generate transcript"}
                </button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={handleApplyTranscript}
                  disabled={!track || applyingTranscript}
                  className="rounded bg-gray-700 px-3 py-2 text-xs text-white hover:bg-gray-600 disabled:opacity-40"
                >
                  {applyingTranscript ? "Applying..." : "Apply transcript"}
                </button>
                <button
                  onClick={() => handleExport("srt")}
                  disabled={!track}
                  className="rounded bg-gray-800 px-3 py-2 text-xs text-gray-200 hover:bg-gray-700 disabled:opacity-40"
                >
                  Export SRT
                </button>
                <button
                  onClick={() => handleExport("vtt")}
                  disabled={!track}
                  className="rounded bg-gray-800 px-3 py-2 text-xs text-gray-200 hover:bg-gray-700 disabled:opacity-40"
                >
                  Export VTT
                </button>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-gray-200">Words</h2>
              <div className="flex gap-2">
                <input
                  value={keywordInput}
                  onChange={(e) => setKeywordInput(e.target.value)}
                  placeholder="keyword, phrase"
                  className="w-44 rounded border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs text-gray-200"
                />
                <button
                  onClick={highlightKeywords}
                  disabled={!track}
                  className="rounded bg-yellow-700 px-3 py-1.5 text-xs text-white hover:bg-yellow-600 disabled:opacity-40"
                >
                  Highlight
                </button>
              </div>
            </div>
            <div className="max-h-[420px] overflow-y-auto rounded border border-gray-800">
              <div className="grid grid-cols-[88px_88px_1fr_92px_128px] gap-2 border-b border-gray-800 bg-gray-950 px-3 py-2 text-[11px] uppercase text-gray-500">
                <span>Start</span>
                <span>End</span>
                <span>Text</span>
                <span>Accent</span>
                <span>Actions</span>
              </div>
              {track?.words.map((word) => (
                <div key={word.id} className="grid grid-cols-[88px_88px_1fr_92px_128px] items-center gap-2 border-b border-gray-800 px-3 py-2 text-xs last:border-b-0">
                  <input
                    type="number"
                    min={0}
                    step={0.05}
                    value={word.start}
                    onChange={(e) => setWordPatch(word.id, { start: clampTime(Number(e.target.value)) })}
                    className="rounded border border-gray-700 bg-gray-950 px-2 py-1 text-gray-200"
                    title={formatTime(word.start)}
                  />
                  <input
                    type="number"
                    min={0}
                    step={0.05}
                    value={word.end}
                    onChange={(e) => setWordPatch(word.id, { end: clampTime(Number(e.target.value)) })}
                    className="rounded border border-gray-700 bg-gray-950 px-2 py-1 text-gray-200"
                    title={formatTime(word.end)}
                  />
                  <input
                    value={word.text}
                    onChange={(e) => setWordPatch(word.id, { text: e.target.value })}
                    className="rounded border border-gray-700 bg-gray-950 px-2 py-1 text-gray-200"
                  />
                  <label className="flex items-center gap-2 text-gray-300">
                    <input
                      type="checkbox"
                      checked={word.highlighted}
                      onChange={(e) => setWordPatch(word.id, { highlighted: e.target.checked })}
                      className="accent-yellow-500"
                    />
                    Mark
                  </label>
                  <div className="flex flex-wrap gap-1">
                    {EMOJIS.slice(0, 3).map((emoji) => (
                      <button
                        key={emoji}
                        onClick={() => setWordPatch(word.id, { text: `${word.text}${emoji}` })}
                        className="rounded bg-gray-800 px-1.5 py-1 hover:bg-gray-700"
                      >
                        {emoji}
                      </button>
                    ))}
                    <button onClick={() => addWordAfter(word)} className="rounded bg-gray-800 px-2 py-1 text-gray-200 hover:bg-gray-700">
                      +
                    </button>
                    <button onClick={() => deleteWord(word.id)} className="rounded bg-red-950 px-2 py-1 text-red-200 hover:bg-red-900">
                      Del
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <aside className="space-y-4">
          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <h2 className="mb-3 text-sm font-medium text-gray-200">Style</h2>
            <div className="grid gap-3 text-xs">
              <label className="grid gap-1 text-gray-400">
                Caption style
                <select
                  value={track?.style || "default"}
                  onChange={(e) => setTrackPatch({ style: e.target.value as SubtitleTrack["style"] })}
                  disabled={!track}
                  className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200"
                >
                  <option value="default">Default</option>
                  <option value="bold">Bold yellow</option>
                  <option value="minimal">Minimal</option>
                  <option value="neon">Neon</option>
                </select>
              </label>
              <label className="grid gap-1 text-gray-400">
                Position
                <select
                  value={track?.position || "bottom"}
                  onChange={(e) => setTrackPatch({ position: e.target.value as SubtitleTrack["position"] })}
                  disabled={!track}
                  className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200"
                >
                  <option value="top">Top</option>
                  <option value="middle">Middle</option>
                  <option value="bottom">Bottom</option>
                </select>
              </label>
              <label className="grid gap-1 text-gray-400">
                Animation
                <select
                  value={track?.animation || "none"}
                  onChange={(e) => setTrackPatch({ animation: e.target.value as SubtitleTrack["animation"] })}
                  disabled={!track}
                  className="rounded border border-gray-700 bg-gray-950 px-2 py-2 text-gray-200"
                >
                  <option value="none">None</option>
                  <option value="pop">Pop</option>
                  <option value="slide">Slide</option>
                  <option value="karaoke">Karaoke fade</option>
                </select>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <h2 className="mb-3 text-sm font-medium text-gray-200">Translate</h2>
            <div className="flex gap-2">
              <select
                value={targetLanguage}
                onChange={(e) => setTargetLanguage(e.target.value)}
                className="flex-1 rounded border border-gray-700 bg-gray-950 px-2 py-2 text-xs text-gray-200"
              >
                {LANGUAGES.map((language) => (
                  <option key={language.value} value={language.value}>{language.label}</option>
                ))}
              </select>
              <button
                onClick={handleTranslate}
                disabled={!track || saving}
                className="rounded bg-teal-700 px-3 py-2 text-xs text-white hover:bg-teal-600 disabled:opacity-40"
              >
                Translate
              </button>
            </div>
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <h2 className="mb-3 text-sm font-medium text-gray-200">Import</h2>
            <select
              value={importFormat}
              onChange={(e) => setImportFormat(e.target.value as "srt" | "vtt")}
              className="mb-2 w-full rounded border border-gray-700 bg-gray-950 px-2 py-2 text-xs text-gray-200"
            >
              <option value="srt">SRT</option>
              <option value="vtt">VTT</option>
            </select>
            <textarea
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              className="h-28 w-full resize-none rounded border border-gray-700 bg-gray-950 p-2 text-xs text-gray-200"
              placeholder="Paste subtitle file content"
            />
            <button
              onClick={handleImport}
              disabled={!activeId || !importText.trim() || saving}
              className="mt-2 w-full rounded bg-gray-700 px-3 py-2 text-xs text-white hover:bg-gray-600 disabled:opacity-40"
            >
              Import subtitles
            </button>
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
            <div className="grid gap-2">
              <button
                onClick={handleSave}
                disabled={!track || saving}
                className="rounded bg-purple-600 px-4 py-3 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-40"
              >
                {saving ? "Saving..." : "Save edits"}
              </button>
              <button
                onClick={handleRender}
                disabled={!track || rendering}
                className="rounded bg-green-600 px-4 py-3 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-40"
              >
                {rendering ? "Rendering..." : "Render edited video"}
              </button>
              <Link href="/export" className="rounded bg-blue-600 px-4 py-3 text-center text-sm font-medium text-white hover:bg-blue-700">
                Export videos
              </Link>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
