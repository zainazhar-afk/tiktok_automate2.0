"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { createClient, type Session, type SupabaseClient, type User } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || "";
const requireAuth = process.env.NEXT_PUBLIC_REQUIRE_AUTH === "true";

let client: SupabaseClient | null = null;

export function isAuthEnabled() {
  return requireAuth;
}

export function getSupabaseClient() {
  if (!requireAuth) return null;
  if (!supabaseUrl || !supabaseKey) return null;
  if (!client) {
    client = createClient(supabaseUrl, supabaseKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
  }
  return client;
}

export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabaseClient();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token || null;
}

export function withAccessToken(url: string, token?: string | null) {
  if (!token) return url;
  const joiner = url.includes("?") ? "&" : "?";
  return `${url}${joiner}access_token=${encodeURIComponent(token)}`;
}

interface AuthContextValue {
  enabled: boolean;
  configured: boolean;
  loading: boolean;
  session: Session | null;
  user: User | null;
  accessToken: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const supabase = getSupabaseClient();
  const configured = !requireAuth || Boolean(supabase);
  const [loading, setLoading] = useState(requireAuth && Boolean(supabase));
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    if (!supabase) {
      return;
    }
    let mounted = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!mounted) return;
      setSession(data.session || null);
      setLoading(false);
    });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setLoading(false);
    });
    return () => {
      mounted = false;
      listener.subscription.unsubscribe();
    };
  }, [supabase]);

  const signIn = useCallback(async (email: string, password: string) => {
    if (!supabase) throw new Error("Supabase Auth is not configured");
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
  }, [supabase]);

  const signUp = useCallback(async (email: string, password: string) => {
    if (!supabase) throw new Error("Supabase Auth is not configured");
    const { error } = await supabase.auth.signUp({ email, password });
    if (error) throw error;
  }, [supabase]);

  const signOut = useCallback(async () => {
    if (!supabase) return;
    const { error } = await supabase.auth.signOut();
    if (error) throw error;
    setSession(null);
  }, [supabase]);

  const value = useMemo<AuthContextValue>(() => ({
    enabled: requireAuth,
    configured,
    loading,
    session,
    user: session?.user || null,
    accessToken: session?.access_token || null,
    signIn,
    signUp,
    signOut,
  }), [configured, loading, session, signIn, signOut, signUp]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!auth.enabled) return <>{children}</>;
  if (!auth.configured) {
    return (
      <main className="mx-auto flex min-h-[calc(100vh-56px)] w-full max-w-xl items-center px-4 py-10">
        <div className="w-full rounded-lg border border-red-900 bg-red-950/30 p-5 text-sm text-red-100">
          Supabase Auth is required but the public Supabase URL/key are not configured.
        </div>
      </main>
    );
  }
  if (auth.loading) {
    return (
      <main className="mx-auto flex min-h-[calc(100vh-56px)] w-full max-w-xl items-center justify-center px-4 py-10 text-sm text-gray-400">
        Loading account...
      </main>
    );
  }
  if (auth.user) return <>{children}</>;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "signin") await auth.signIn(email.trim(), password);
      else await auth.signUp(email.trim(), password);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-[calc(100vh-56px)] w-full max-w-md items-center px-4 py-10">
      <form onSubmit={submit} className="w-full rounded-lg border border-gray-800 bg-gray-950 p-5 shadow-2xl">
        <div className="mb-5">
          <h1 className="text-xl font-semibold text-white">Sign in to TikTok Automate</h1>
          <p className="mt-1 text-sm text-gray-400">Protected workspace access for paid accounts.</p>
        </div>
        {error && (
          <div className="mb-4 rounded border border-red-800 bg-red-950/40 p-3 text-sm text-red-200">
            {error}
          </div>
        )}
        <div className="mb-4 grid grid-cols-2 rounded bg-gray-900 p-1 text-sm">
          <button
            type="button"
            onClick={() => setMode("signin")}
            className={`rounded px-3 py-2 ${mode === "signin" ? "bg-purple-700 text-white" : "text-gray-400"}`}
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => setMode("signup")}
            className={`rounded px-3 py-2 ${mode === "signup" ? "bg-purple-700 text-white" : "text-gray-400"}`}
          >
            Create account
          </button>
        </div>
        <label className="mb-3 grid gap-1 text-sm text-gray-300">
          Email
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-white outline-none focus:border-purple-500"
          />
        </label>
        <label className="mb-5 grid gap-1 text-sm text-gray-300">
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            minLength={8}
            className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-white outline-none focus:border-purple-500"
          />
        </label>
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded bg-purple-600 px-4 py-3 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {submitting ? "Working..." : mode === "signin" ? "Sign in" : "Create account"}
        </button>
      </form>
    </main>
  );
}
