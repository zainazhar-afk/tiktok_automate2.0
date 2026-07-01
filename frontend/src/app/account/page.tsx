"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createCheckoutSession,
  createPortalSession,
  getAccountStatus,
  updateRightsAttestation,
  type AccountStatus,
} from "@/lib/api";

function UsageMeter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div className="rounded border border-gray-800 bg-gray-950/50 p-3">
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span className="font-medium text-gray-200">{label}</span>
        <span className="text-xs text-gray-500">{used} / {limit}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-gray-800">
        <div className="h-full rounded-full bg-purple-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function AccountPage() {
  const [status, setStatus] = useState<AccountStatus | null>(null);
  const [rightsAccepted, setRightsAccepted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const usageItems = useMemo(() => Object.entries(status?.usage || {}), [status]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await getAccountStatus();
      setStatus(next);
      setRightsAccepted(next.rights_accepted);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(timer);
  }, [refresh]);

  const saveRights = async () => {
    setBusy("rights");
    setError(null);
    try {
      const next = await updateRightsAttestation(rightsAccepted);
      setStatus(next);
      setRightsAccepted(next.rights_accepted);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const goToBilling = async (kind: "checkout" | "portal") => {
    setBusy(kind);
    setError(null);
    try {
      const next = kind === "checkout" ? await createCheckoutSession() : await createPortalSession();
      if (next.url) window.location.href = next.url;
      else setError("Billing provider did not return a redirect URL");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-white">Account</h1>
        <p className="mt-1 text-sm text-gray-400">Subscription, usage, and publishing rights.</p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/40 p-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {loading && <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 text-sm text-gray-400">Loading account...</div>}

      {status && (
        <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
          <section className="space-y-4">
            <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-medium text-gray-200">Subscription</h2>
                  <p className="mt-1 text-xs text-gray-500">{status.email || status.user_id}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <span className="rounded bg-purple-600/20 px-2 py-1 text-xs font-medium text-purple-200">
                    {status.plan}
                  </span>
                  <span className={`rounded px-2 py-1 text-xs font-medium ${status.subscription_active ? "bg-green-600/20 text-green-200" : "bg-red-600/20 text-red-200"}`}>
                    {status.subscription_status}
                  </span>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  onClick={() => void goToBilling("checkout")}
                  disabled={busy !== null || !status.stripe_configured}
                  className="rounded bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-40"
                >
                  {busy === "checkout" ? "Opening..." : "Subscribe"}
                </button>
                <button
                  onClick={() => void goToBilling("portal")}
                  disabled={busy !== null || !status.stripe_customer_id || !status.stripe_configured}
                  className="rounded bg-gray-800 px-4 py-2 text-sm font-medium text-gray-200 hover:bg-gray-700 disabled:opacity-40"
                >
                  {busy === "portal" ? "Opening..." : "Manage billing"}
                </button>
              </div>
              {!status.stripe_configured && (
                <p className="mt-3 text-xs text-yellow-300">Stripe is not configured in this environment.</p>
              )}
            </div>

            <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
              <h2 className="mb-3 text-sm font-medium text-gray-200">Monthly Usage</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {usageItems.map(([key, item]) => (
                  <UsageMeter key={key} label={item.label} used={item.used} limit={item.limit} />
                ))}
              </div>
            </div>
          </section>

          <aside className="space-y-4">
            <div className="rounded-lg border border-gray-700 bg-gray-900 p-4">
              <h2 className="text-sm font-medium text-gray-200">Rights Attestation</h2>
              <label className="mt-3 flex items-start gap-3 text-sm text-gray-300">
                <input
                  type="checkbox"
                  checked={rightsAccepted}
                  onChange={(event) => setRightsAccepted(event.target.checked)}
                  className="mt-1 accent-purple-500"
                />
                <span>
                  I confirm I own or have commercial rights to the source media I upload, download, edit, render, or export.
                </span>
              </label>
              <button
                onClick={saveRights}
                disabled={busy !== null || rightsAccepted === status.rights_accepted}
                className="mt-4 w-full rounded bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-40"
              >
                {busy === "rights" ? "Saving..." : "Save attestation"}
              </button>
              {status.rights_required && !status.rights_accepted && (
                <p className="mt-3 text-xs text-yellow-300">Publishing and rendering actions are blocked until this is accepted.</p>
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
