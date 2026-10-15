"use client";

import React, { useState } from "react";
import { Brain, GoogleLogo, Target, FileText, Stack } from "@phosphor-icons/react";
import { signInWithGoogle } from "@/lib/firebase";
import { TOKENS } from "@/lib/tokens";

/**
 * Full gate for logged-out visitors. Rendered by every route when there is
 * no Firebase user: setup, stage, report, past reports. Same system as the
 * app (zinc + single emerald accent, Geist + mono, dual-mode).
 */
export function LoginGate() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSignIn = async () => {
    setBusy(true);
    setError(null);
    try {
      await signInWithGoogle();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed. Try again.");
      setBusy(false);
    }
  };

  return (
    <div className="w-full max-w-md mx-auto px-4 sm:px-6 py-14 md:py-20 flex-1 flex flex-col justify-center">
      <div className="flex flex-col items-start gap-5">
        <div className="w-12 h-12 rounded-xl bg-emerald-500/15 dark:bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
          <Brain size={26} weight="bold" />
        </div>

        <div>
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            Sign in to start interviewing
          </h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400 mt-2 leading-relaxed max-w-[52ch]">
            Five interview modes, adaptive scoring, and a verdict report. Your sessions stay yours.
          </p>
        </div>

        <button
          type="button"
          onClick={handleSignIn}
          disabled={busy}
          className={`w-full inline-flex items-center justify-center gap-2.5 px-6 py-3 ${TOKENS.radius.button} bg-emerald-500 hover:bg-emerald-600 text-zinc-950 font-semibold text-sm transition-all duration-150 active:scale-[0.98] shadow-sm hover:shadow-emerald-500/20 disabled:opacity-60 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50`}
        >
          <GoogleLogo size={18} weight="bold" />
          <span>{busy ? "Opening Google…" : "Continue with Google"}</span>
        </button>

        {error && (
          <p className="text-xs text-rose-500 dark:text-rose-400 leading-relaxed">{error}</p>
        )}

        <div className="w-full divide-y divide-zinc-200 dark:divide-white/10 border-t border-b border-zinc-200 dark:border-white/10">
          <div className="flex items-center gap-3 py-3">
            <Stack size={16} weight="regular" className="text-emerald-500 shrink-0" />
            <span className="text-xs font-mono text-zinc-600 dark:text-zinc-400">
              Topic, custom, docs, resume, or YouTube link
            </span>
          </div>
          <div className="flex items-center gap-3 py-3">
            <Target size={16} weight="regular" className="text-emerald-500 shrink-0" />
            <span className="text-xs font-mono text-zinc-600 dark:text-zinc-400">
              Difficulty adapts to every answer
            </span>
          </div>
          <div className="flex items-center gap-3 py-3">
            <FileText size={16} weight="regular" className="text-emerald-500 shrink-0" />
            <span className="text-xs font-mono text-zinc-600 dark:text-zinc-400">
              Scored report with verdict, kept per account
            </span>
          </div>
        </div>

        <p className="text-[11px] font-mono text-zinc-400 dark:text-zinc-500">
          Free tier. Sign-in only, no spam.
        </p>
      </div>
    </div>
  );
}
