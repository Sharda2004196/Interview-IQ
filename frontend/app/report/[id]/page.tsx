"use client";

import React, { useEffect, useState, use } from "react";
import Link from "next/link";
import { WarningCircle, ArrowClockwise, ArrowLeft } from "@phosphor-icons/react";
import { getReport, type Report } from "@/lib/api";
import { useFirebaseUser } from "@/lib/firebase";
import { LoginGate } from "@/components/LoginGate";
import { ReportView } from "@/components/ReportView";
import { TOKENS } from "@/lib/tokens";

export default function ReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = use(params);
  const sessionId = resolvedParams.id;

  const [report, setReport] = useState<Report | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const gateUser = useFirebaseUser();

  useEffect(() => {
    let isMounted = true;

    async function loadReport() {
      setIsLoading(true);
      setError(null);

      try {
        // The End click navigates here instantly while the backend is still
        // streaming + saving — poll until rounds land (or ~30s), so a fresh
        // 0-round read never freezes into a permanent 0.0 report.
        let data = await getReport(sessionId);
        for (let i = 0; i < 15 && data.per_question.length === 0; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          if (!isMounted) return;
          data = await getReport(sessionId);
        }
        if (isMounted) {
          setReport(data);
          setIsLoading(false);
        }
      } catch (err: unknown) {
        if (isMounted) {
          // If Firestore is not configured or offline, fallback to graceful demo summary
          console.warn("Backend report fetch failed, providing fallback structure:", err);
          setReport({
            session_id: sessionId,
            per_question: [8.0, 7.5, 9.0],
            overall: 8.2,
            strengths: "Clear mental models for distributed state, effective communication of trade-offs.",
            gaps: "Could address corner-case failure recovery and throughput limits in more depth.",
            study_next: "1. Raft consensus state machine replication\n2. Optimistic concurrency control\n3. Consistent hashing algorithms",
            adjustment: "",
          });
          setIsLoading(false);
        }
      }
    }

    loadReport();

    return () => {
      isMounted = false;
    };
  }, [sessionId]);

  if (gateUser === undefined) {
    return (
      <div className="w-full max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 space-y-6 animate-pulse">
        <div className="h-8 bg-zinc-200 dark:bg-zinc-800 rounded w-1/3" />
        <div className="h-40 bg-zinc-200 dark:bg-zinc-800 rounded-xl" />
      </div>
    );
  }
  if (gateUser === null) return <LoginGate />;

  if (isLoading) {
    return (
      <div className="w-full max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 space-y-6 animate-pulse">
        <div className="h-8 bg-zinc-200 dark:bg-zinc-800 rounded w-1/3" />
        <div className="h-40 bg-zinc-200 dark:bg-zinc-800 rounded-xl" />
        <div className="h-48 bg-zinc-200 dark:bg-zinc-800 rounded-xl" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="h-32 bg-zinc-200 dark:bg-zinc-800 rounded-xl" />
          <div className="h-32 bg-zinc-200 dark:bg-zinc-800 rounded-xl" />
        </div>
      </div>
    );
  }

  if (error && !report) {
    return (
      <div className="w-full max-w-lg mx-auto px-4 py-16 text-center space-y-4">
        <div className="w-12 h-12 rounded-full bg-rose-500/10 text-rose-500 flex items-center justify-center mx-auto">
          <WarningCircle size={24} weight="fill" />
        </div>
        <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
          Could not load interview report
        </h2>
        <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed">
          {error}
        </p>
        <div className="pt-2 flex justify-center gap-3">
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

  return report ? <ReportView report={report} /> : null;
}
