"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { AccountStatus, VariantGenerationResponse, VariantSourceStatus, VariantUploadResponse } from "@/types";
import { useAuth } from "@/lib/auth";
import { generateVariants, getAccountStatus, getVariantSourceStatus, startVariantSourceFromUrl, videoFileUrl } from "@/lib/api";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const GENERATION_STAGES = [
  { after: 0, label: "Analyzing transcript, silence, and scenes", progress: 22 },
  { after: 15, label: "Scoring best-moment candidates", progress: 42 },
  { after: 35, label: "Reranking hooks with AI", progress: 58 },
  { after: 55, label: "Rendering 9:16 shorts", progress: 76 },
  { after: 100, label: "Registering export assets", progress: 92 },
];

function usageLabel(account: AccountStatus | null, key: string) {
  const item = account?.usage?.[key];
  if (!item) return "Quota unavailable";
  if (item.remaining === null || item.remaining === undefined) return `${item.used} used, unlimited`;
  return `${item.remaining}/${item.limit} left`;
}

function shouldShowAccountCta(message: string | null) {
  if (!message) return false;
  return /subscription|billing|quota|limit|rights/i.test(message);
}

export default function VariantGenerator() {
  const { accessToken } = useAuth();
  const [videoUrl, setVideoUrl] = useState("");
  const [upload, setUpload] = useState<VariantUploadResponse | null>(null);
  const [account, setAccount] = useState<AccountStatus | null>(null);
  const [accountError, setAccountError] = useState<string | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<VariantSourceStatus | null>(null);
  const [result, setResult] = useState<VariantGenerationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<"idle" | "downloading" | "planning" | "rendering" | "complete">("idle");
  const [generationStartedAt, setGenerationStartedAt] = useState<number | null>(null);
  const [generationElapsed, setGenerationElapsed] = useState(0);
  const [videoErrors, setVideoErrors] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const downloadRemaining = account?.usage?.download?.remaining;
  const variantRemaining = account?.usage?.variant?.remaining;
  const accountBlocked =
    Boolean(account?.billing_required && !account.subscription_active) ||
    Boolean(account?.rights_required && !account.rights_accepted);
  const quotaBlocked = downloadRemaining === 0 || variantRemaining === 0;
  const generateBlocked = accountBlocked || quotaBlocked;
  const generationStage = useMemo(() => {
    return [...GENERATION_STAGES].reverse().find((item) => generationElapsed >= item.after) || GENERATION_STAGES[0];
  }, [generationElapsed]);

  const loadAccount = useCallback(async () => {
    setAccountError(null);
    try {
      setAccount(await getAccountStatus());
    } catch (e: unknown) {
      setAccount(null);
      setAccountError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadAccount(), 0);
    return () => window.clearTimeout(timer);
  }, [loadAccount]);

  useEffect(() => {
    if (!generationStartedAt || !busy || (stage !== "planning" && stage !== "rendering")) return;
    const tick = () => setGenerationElapsed(Math.floor((Date.now() - generationStartedAt) / 1000));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [busy, generationStartedAt, stage]);

  const waitForSource = async (uploadId: string) => {
    for (let attempt = 0; attempt < 1200; attempt += 1) {
      const status = await getVariantSourceStatus(uploadId);
      setDownloadStatus(status);
      if (status.status === "completed") {
        setUpload({ upload_id: status.upload_id, filename: status.filename });
        return status;
      }
      if (status.status === "failed") {
        throw new Error(status.error || "Download failed");
      }
      await sleep(1000);
    }
    throw new Error("Download timed out");
  };

  const handleGenerate = async () => {
    const cleanUrl = videoUrl.trim();
    if ((!cleanUrl && !upload) || generateBlocked) return;
    setBusy(true);
    setStage("downloading");
    setError(null);
    setVideoErrors(new Set());
    setMessage("Downloading source video...");
    try {
      let source: VariantSourceStatus;
      if (upload) {
        source = await getVariantSourceStatus(upload.upload_id);
        setDownloadStatus(source);
      } else {
        const started = await startVariantSourceFromUrl(cleanUrl);
        setDownloadStatus(started);
        source = await waitForSource(started.upload_id);
      }
      if (source.status !== "completed") {
        source = await waitForSource(source.upload_id);
      }
      const readyUpload = { upload_id: source.upload_id, filename: source.filename };
      if (!readyUpload) return;
      setUpload(readyUpload);
      setStage("planning");
      setGenerationStartedAt(Date.now());
      setMessage("Finding the best short-form moments...");
      const generated = await generateVariants(readyUpload.upload_id);
      setResult(generated);
      setStage("complete");
      setGenerationStartedAt(null);
      setMessage(generated.ai_planned ? "Generated with AI-assisted planning" : "Generated with automatic segment planning");
      void loadAccount();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setStage("idle");
    } finally {
      setBusy(false);
      setGenerationStartedAt(null);
      setGenerationElapsed(0);
    }
  };

  const reset = () => {
    setVideoUrl("");
    setUpload(null);
    setDownloadStatus(null);
    setResult(null);
    setMessage(null);
    setError(null);
    setVideoErrors(new Set());
    setStage("idle");
    setGenerationStartedAt(null);
    setGenerationElapsed(0);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Long-Form Variant Studio</h1>
          <p className="mt-1 max-w-3xl text-sm text-gray-400">
            Paste a public video URL for long-form content, product footage, webinars, podcasts, UGC, or ads and render 10 compliant short-form variants.
          </p>
        </div>
        <Link href="/export" className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
          Export
        </Link>
      </div>

      {(error || message || accountError) && (
        <div className={`rounded-lg border p-3 text-sm ${error || accountError ? "border-red-800 bg-red-950/40 text-red-200" : "border-cyan-800 bg-cyan-950/30 text-cyan-100"}`}>
          <div className="font-medium">{error || accountError || message}</div>
          {(error || accountError) && (
            <div className="mt-3 flex flex-wrap gap-2">
              <button onClick={handleGenerate} disabled={busy || (!videoUrl.trim() && !upload) || generateBlocked} className="rounded bg-red-700 px-3 py-1.5 text-xs text-white hover:bg-red-600 disabled:opacity-40">
                Retry
              </button>
              <button onClick={() => void loadAccount()} className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-100 hover:bg-gray-700">
                Retry account
              </button>
              {shouldShowAccountCta(error || accountError) && (
                <Link href="/account" className="rounded bg-yellow-700 px-3 py-1.5 text-xs text-white hover:bg-yellow-600">
                  Open Account
                </Link>
              )}
            </div>
          )}
        </div>
      )}

      <section className="grid gap-4 lg:grid-cols-[420px_1fr]">
        <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <h2 className="mb-4 text-sm font-medium text-gray-200">Source</h2>
          <div className="rounded-lg border border-gray-800 bg-gray-950 p-4">
            <label className="grid gap-2 text-sm text-gray-300">
              Video URL
              <input
                type="url"
                value={videoUrl}
                onChange={(e) => {
                  setVideoUrl(e.target.value);
                  setUpload(null);
                  setDownloadStatus(null);
                  setResult(null);
                  setMessage(null);
                  setError(null);
                }}
                placeholder="https://www.youtube.com/watch?v=..."
                disabled={busy}
                className="rounded border border-gray-700 bg-gray-900 px-3 py-3 text-sm text-gray-100 placeholder-gray-600 outline-none focus:border-cyan-500 disabled:opacity-50"
              />
            </label>
            <p className="mt-3 text-xs leading-5 text-gray-500">
              Supports public URLs that yt-dlp can download. Private links, login-only videos, or blocked platforms may fail.
            </p>
            <div className={`mt-3 rounded border p-3 text-xs ${generateBlocked ? "border-yellow-800 bg-yellow-950/30 text-yellow-100" : "border-gray-800 bg-gray-950/70 text-gray-400"}`}>
              <div className="grid gap-2 sm:grid-cols-2">
                <span>Downloads: {usageLabel(account, "download")}</span>
                <span>Variants: {usageLabel(account, "variant")}</span>
              </div>
              {account?.rights_required && !account.rights_accepted && <p className="mt-2 text-yellow-300">Confirm source-media rights before downloading or generating variants.</p>}
              {account?.billing_required && !account.subscription_active && <p className="mt-2 text-yellow-300">An active subscription is required for this action.</p>}
              {quotaBlocked && <p className="mt-2 text-yellow-300">Monthly quota reached. Open Account to review plan status.</p>}
              {generateBlocked && (
                <Link href="/account" className="mt-3 inline-flex rounded bg-yellow-700 px-3 py-1.5 text-white hover:bg-yellow-600">
                  Open Account
                </Link>
              )}
            </div>
            {upload && (
              <div className="mt-3 rounded border border-cyan-900 bg-cyan-950/30 px-3 py-2 text-xs text-cyan-100">
                Source ready: {upload.filename}
              </div>
            )}
            {downloadStatus && downloadStatus.status !== "completed" && (
              <div className="mt-4 rounded border border-gray-800 bg-gray-900 p-3">
                <div className="mb-2 flex items-center justify-between text-xs text-gray-400">
                  <span>{downloadStatus.status === "failed" ? "Download failed" : "Downloading"}</span>
                  <span>{Math.round((downloadStatus.progress || 0) * 100)}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-gray-800">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${downloadStatus.status === "failed" ? "bg-red-600" : "bg-cyan-500"}`}
                    style={{ width: `${Math.max(2, Math.round((downloadStatus.progress || 0) * 100))}%` }}
                  />
                </div>
                <p className="mt-2 line-clamp-2 text-xs text-gray-500">{downloadStatus.error || downloadStatus.message}</p>
              </div>
            )}
            {busy && (stage === "planning" || stage === "rendering") && (
              <div className="mt-4 rounded border border-purple-900 bg-purple-950/30 p-3">
                <div className="mb-2 flex items-center justify-between text-xs text-purple-100">
                  <span>{generationStage.label}</span>
                  <span>{generationElapsed}s</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-gray-800">
                  <div className="h-full rounded-full bg-purple-500 transition-all duration-500" style={{ width: `${generationStage.progress}%` }} />
                </div>
                <p className="mt-2 text-xs leading-5 text-gray-500">The backend is selecting hooks, removing dead air, and rendering export-ready MP4s.</p>
              </div>
            )}
          </div>

          <div className="mt-4 grid gap-2">
            <button
              onClick={handleGenerate}
              disabled={busy || (!videoUrl.trim() && !upload) || generateBlocked}
              className="rounded bg-cyan-700 px-4 py-3 text-sm font-medium text-white hover:bg-cyan-600 disabled:opacity-40"
            >
              {busy ? "Generating..." : "Generate 10 variants"}
            </button>
            <button
              onClick={reset}
              disabled={busy}
              className="rounded bg-gray-800 px-4 py-2 text-sm text-gray-200 hover:bg-gray-700 disabled:opacity-40"
            >
              New source
            </button>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            {[
              ["Output", "10 variants"],
              ["Format", "9:16 MP4"],
              ["Input", "Video URL"],
              ["Planner", "Transcript + audio"],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-gray-800 bg-gray-950 p-3">
                <div className="text-gray-500">{label}</div>
                <div className="mt-1 text-gray-200">{value}</div>
              </div>
            ))}
          </div>

          {result?.analysis && (
            <div className="mt-4 rounded-lg border border-gray-800 bg-gray-950 p-3 text-xs">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-medium text-gray-200">Planning signals</span>
                <span className="text-cyan-300">{result.analysis.planner || "local_intelligence"}</span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-gray-400">
                <span>Transcript: {result.analysis.transcript_available ? "yes" : "no"}</span>
                <span>Candidates: {result.analysis.candidate_count || 0}</span>
                <span>Silences: {result.analysis.silence_segments || 0}</span>
                <span>Scenes: {result.analysis.scene_changes || 0}</span>
              </div>
              {result.analysis.signals && result.analysis.signals.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {result.analysis.signals.map((signal) => (
                    <span key={signal} className="rounded bg-cyan-950 px-2 py-1 text-cyan-200">
                      {signal}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-medium text-gray-200">Variants</h2>
            <span className="text-xs text-gray-500">{result?.files.length || 0}/10 rendered</span>
          </div>
          {!result && (
            <div className="flex min-h-72 items-center justify-center rounded-lg border border-gray-800 bg-gray-950 text-sm text-gray-500">
              Generated variants appear here.
            </div>
          )}
          {result && (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {result.files.map((item, idx) => {
                const videoUrl = videoFileUrl(item.filename, accessToken);
                const failedPreview = videoErrors.has(item.filename);
                return (
                  <div key={item.filename} className="overflow-hidden rounded-lg border border-gray-800 bg-gray-950">
                    <div className="aspect-[9/16] bg-black">
                      {failedPreview ? (
                        <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center text-xs text-gray-500">
                          <div>
                            <div className="font-medium text-gray-200">Preview unavailable</div>
                            <div className="mt-1 leading-5">The rendered file could not be loaded. Try Export or regenerate.</div>
                          </div>
                          <Link href="/export" className="rounded bg-gray-800 px-3 py-1.5 text-gray-200 hover:bg-gray-700">
                            Export
                          </Link>
                        </div>
                      ) : (
                        <video
                          src={videoUrl}
                          controls
                          className="h-full w-full object-contain"
                          preload="metadata"
                          onError={() => setVideoErrors((current) => new Set(current).add(item.filename))}
                        />
                      )}
                    </div>
                    <div className="space-y-2 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate text-sm font-medium text-gray-200">{item.title || `Variant ${idx + 1}`}</p>
                        <span className="rounded bg-cyan-950 px-2 py-1 text-[11px] text-cyan-200">
                          {Math.round(item.score || 0)}
                        </span>
                      </div>
                      <p className="line-clamp-2 text-xs text-gray-400">{item.hook}</p>
                      {item.transcript_excerpt && (
                        <p className="line-clamp-2 rounded bg-gray-900 p-2 text-[11px] leading-4 text-gray-500">
                          {item.transcript_excerpt}
                        </p>
                      )}
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                        <span>{item.start.toFixed(1)}s - {item.end.toFixed(1)}s</span>
                        <span>{item.angle}</span>
                      </div>
                      {item.reasons && item.reasons.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {item.reasons.slice(0, 3).map((reason) => (
                            <span key={reason} className="rounded bg-gray-900 px-2 py-1 text-[11px] text-gray-400">
                              {reason}
                            </span>
                          ))}
                        </div>
                      )}
                      {item.source_signals && item.source_signals.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {item.source_signals.map((signal) => (
                            <span key={signal} className="rounded bg-cyan-950/70 px-2 py-1 text-[11px] text-cyan-200">
                              {signal}
                            </span>
                          ))}
                        </div>
                      )}
                      {item.compliance_note && (
                        <p className="rounded border border-yellow-900/70 bg-yellow-950/20 p-2 text-[11px] leading-4 text-yellow-200/80">
                          {item.compliance_note}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-2">
                        <a href={videoUrl} download={item.filename} className="rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700">
                          Video
                        </a>
                        <Link href={`/editor?video=${encodeURIComponent(item.id)}`} className="rounded bg-purple-700 px-3 py-1.5 text-xs text-white hover:bg-purple-600">
                          Edit
                        </Link>
                        <Link href={`/editor?video=${encodeURIComponent(item.id)}&mode=subtitles`} className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-100 hover:bg-gray-700">
                          Captions
                        </Link>
                        <Link href="/export" className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-100 hover:bg-gray-700">
                          Export
                        </Link>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
