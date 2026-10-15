"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, CheckCircle, Trash, WarningCircle, X } from "@phosphor-icons/react";
import { deleteAllSessions, deleteSession, getSessions, type PastSession } from "@/lib/api";
import { useFirebaseUser } from "@/lib/firebase";
import { LoginGate } from "@/components/LoginGate";
import { TOKENS, type VerdictType, getVerdictStyle } from "@/lib/tokens";

function verdictFor(overall: number): VerdictType {
  if (overall >= 7.5) return "Strong Hire";
  if (overall >= 5.0) return "Hire";
  return "No Hire";
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function ReportsPage() {
  const gateUser = useFirebaseUser();
  const [sessions, setSessions] = useState<PastSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<boolean>(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<boolean>(false);

  useEffect(() => {
    let isMounted = true;
    getSessions()
      .then((data) => {
        if (isMounted) setSessions(data);
      })
      .catch((err: unknown) => {
        if (isMounted) setError(err instanceof Error ? err.message : "Failed to load reports");
      });
    return () => {
      isMounted = false;
    };
  }, []);

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const refresh = async () => {
    setSessions(await getSessions());
    setSelected(new Set());
    setSelecting(false);
  };

  const handleDeleteSelected = async () => {
    if (selected.size === 0 || busy) return;
    if (!window.confirm(`Delete ${selected.size} selected ${selected.size === 1 ? "session" : "sessions"}? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await Promise.allSettled([...selected].map((id) => deleteSession(id)));
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteAll = async () => {
    if (busy || !sessions || sessions.length === 0) return;
    if (!window.confirm(`Delete ALL ${sessions.length} past sessions? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await deleteAllSessions();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  if (gateUser === undefined) {
    return (
      <div className="w-full max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 space-y-6 animate-pulse">
        <div className="h-8 bg-zinc-200 dark:bg-zinc-800 rounded w-1/3" />
        <div className="h-40 bg-zinc-200 dark:bg-zinc-800 rounded-xl" />
      </div>
    );
  }
  if (gateUser === null) return <LoginGate />;

  if (sessions === null && !error) {
    return (
      <div className="w-full max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 space-y-6 animate-pulse">
        <div className="h-8 bg-zinc-200 dark:bg-zinc-800 rounded w-1/3" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="h-40 bg-zinc-200 dark:bg-zinc-800 rounded-xl" />
          <div className="h-40 bg-zinc-200 dark:bg-zinc-800 rounded-xl" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full max-w-lg mx-auto px-4 py-16 text-center space-y-4">
        <div className="w-12 h-12 rounded-full bg-rose-500/10 text-rose-500 flex items-center justify-center mx-auto">
          <WarningCircle size={24} weight="fill" />
        </div>
        <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
          Could not load past reports
        </h2>
        <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed">{error}</p>
        <div className="pt-2 flex justify-center">
          <Link
            href="/"
            className={`inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold border border-zinc-200 dark:border-white/10 ${TOKENS.radius.button} hover:bg-zinc-100 dark:hover:bg-zinc-800`}
          >
            <ArrowLeft size={14} weight="bold" />
            <span>Return to Setup</span>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 md:py-12 space-y-8">
      <div>
        <div className="flex items-center justify-between gap-3">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-xs font-mono text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
          >
            <ArrowLeft size={13} weight="bold" />
            <span>Back to Setup</span>
          </Link>
          {sessions && sessions.length > 0 && (
            <div className="flex items-center gap-2">
              {selecting ? (
                <>
                  <button
                    type="button"
                    onClick={handleDeleteSelected}
                    disabled={busy || selected.size === 0}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 ${TOKENS.radius.button} border border-rose-500/30 bg-rose-500/10 hover:bg-rose-500/20 text-rose-600 dark:text-rose-300 text-xs font-semibold transition-all duration-150 disabled:opacity-50`}
                  >
                    <Trash size={14} weight="regular" />
                    <span>Delete{selected.size > 0 ? ` (${selected.size})` : ""}</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleDeleteAll}
                    disabled={busy}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 ${TOKENS.radius.button} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 text-xs font-semibold transition-all duration-150 disabled:opacity-50`}
                  >
                    <Trash size={14} weight="regular" />
                    <span>All</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setSelecting(false);
                      setSelected(new Set());
                    }}
                    disabled={busy}
                    className="inline-flex items-center gap-1 px-2 py-1.5 text-xs font-mono text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors disabled:opacity-50"
                  >
                    <X size={14} weight="bold" />
                    <span>Cancel</span>
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => setSelecting(true)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 ${TOKENS.radius.button} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 text-xs font-semibold transition-all duration-150`}
                >
                  <Trash size={14} weight="regular" />
                  <span>Select</span>
                </button>
              )}
            </div>
          )}
        </div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100 mt-3">
          Your Past Interview Reports
        </h1>
        <p className="text-xs sm:text-sm text-zinc-600 dark:text-zinc-400 mt-1">
          Review your past interview simulations, answer scores, and custom feedback roadmaps.
        </p>
      </div>

      {sessions!.length === 0 ? (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          No interviews yet — run your first session.
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {sessions!.map((s) => {
            const verdict = verdictFor(s.overall);
            const style = getVerdictStyle(verdict);
            // Pre-metadata docs lack date/mode/topic — omit those rows instead
            // of rendering dashes. New sessions (merge-filled on End) show full cards.
            const title = s.topic || (s.mode ? `Mode ${s.mode} Interview` : "Interview Session");
            return (
              <div
                key={s.session_id}
                className={`p-5 ${TOKENS.radius.card} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900/60 shadow-sm space-y-3`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
                    {selecting && (
                      <input
                        type="checkbox"
                        checked={selected.has(s.session_id)}
                        onChange={() => toggleOne(s.session_id)}
                        aria-label={`Select ${s.session_id}`}
                        className="w-4 h-4 accent-emerald-500 cursor-pointer"
                      />
                    )}
                    {s.created_at ? formatDate(s.created_at) : `sess-${s.session_id.slice(-6)}`}
                  </span>
                  <span className="font-mono text-xs font-bold text-emerald-600 dark:text-emerald-400 px-2.5 py-1 rounded bg-emerald-500/10 border border-emerald-500/20">
                    {s.overall.toFixed(1)}/10
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {s.mode && (
                    <span className="font-mono text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 border border-zinc-200 dark:border-white/10">
                      {`Mode ${s.mode}`}
                    </span>
                  )}
                  <span
                    className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-bold border ${style.bg} ${style.border} ${style.text}`}
                  >
                    {verdict === "No Hire" ? (
                      <WarningCircle size={12} weight="fill" />
                    ) : (
                      <CheckCircle size={12} weight="fill" />
                    )}
                    <span>{verdict}</span>
                  </span>
                </div>
                <p className="text-xs sm:text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                  {title}
                </p>
                <p className="text-[11px] font-mono text-zinc-500 dark:text-zinc-400">
                  {s.rounds} {s.rounds === 1 ? "Question" : "Questions"}
                </p>
                <div className="pt-1 flex justify-end">
                  <Link
                    href={`/report/${s.session_id}`}
                    className="inline-flex items-center gap-1 text-xs font-mono text-zinc-500 dark:text-zinc-400 hover:text-emerald-500 dark:hover:text-emerald-400 transition-colors"
                  >
                    <span>View Report</span>
                    <ArrowRight size={13} weight="bold" />
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
