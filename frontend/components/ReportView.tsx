"use client";

import React from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import {
  ArrowLeft,
  FileArrowDown,
  ArrowClockwise,
  CheckCircle,
  WarningCircle,
  Sparkle,
  BookOpen,
  Scales,
} from "@phosphor-icons/react";
import { type Report } from "@/lib/api";
import { TOKENS, type VerdictType, getVerdictStyle } from "@/lib/tokens";

interface ReportViewProps {
  report: Report;
}

export function ReportView({ report }: ReportViewProps) {
  // Agent-stored verdict wins (it judged the actual session); thresholds are
  // the fallback for backfilled/legacy docs that predate verdict storage.
  const stored =
    report.verdict === "Strong Hire" || report.verdict === "Hire" || report.verdict === "No Hire"
      ? (report.verdict as VerdictType)
      : null;
  const getVerdict = (score: number): VerdictType => {
    if (score >= 7.5) return "Strong Hire";
    if (score >= 5.0) return "Hire";
    return "No Hire";
  };

  const verdict = stored ?? getVerdict(report.overall);
  const verdictStyle = getVerdictStyle(verdict);
  const formattedOverall = Number.isInteger(report.overall)
    ? report.overall.toFixed(1)
    : report.overall.toFixed(1);

  const handlePrint = () => {
    if (typeof window !== "undefined") {
      window.print();
    }
  };

  // Parse study items if multiline or comma-separated
  const studyItems = report.study_next
    ? report.study_next
        .split(/\n|•|\*/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
    : [];

  return (
    <div className="w-full max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 md:py-12 space-y-8">
      {/* Top Header Actions (Hidden in Print) */}
      <div className="no-print flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-zinc-200 dark:border-white/10">
        <div>
          <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
            Session Evaluation · {report.session_id}
          </span>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100 mt-0.5">
            Technical Assessment Report
          </h1>
        </div>

        <div className="flex items-center gap-3 w-full sm:w-auto">
          <Link
            href="/reports"
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-mono text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
          >
            <ArrowLeft size={14} weight="bold" />
            <span>Past Reports</span>
          </Link>
          <button
            type="button"
            onClick={handlePrint}
            className={`inline-flex items-center justify-center gap-2 px-4 py-2 ${TOKENS.radius.button} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-800 dark:text-zinc-200 text-xs font-semibold transition-all duration-150 active:scale-[0.98] shadow-sm`}
          >
            <FileArrowDown size={16} weight="regular" className="text-emerald-500" />
            <span>Download PDF</span>
          </button>

          <Link
            href="/"
            className={`inline-flex items-center justify-center gap-2 px-4 py-2 ${TOKENS.radius.button} bg-emerald-500 hover:bg-emerald-600 text-zinc-950 text-xs font-semibold transition-all duration-150 active:scale-[0.98] shadow-sm`}
          >
            <ArrowClockwise size={16} weight="bold" />
            <span>New session</span>
          </Link>
        </div>
      </div>

      {/* Top Metrics Hero Card */}
      <div
        className={`p-6 sm:p-8 ${TOKENS.radius.card} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900/70 shadow-sm flex flex-col md:flex-row items-center justify-between gap-6`}
      >
        {/* Left: Overall Score & Progress */}
        <div className="flex items-center gap-6">
          <div className="relative flex items-center justify-center w-24 h-24 shrink-0">
            <svg width={96} height={96} className="transform -rotate-90">
              <circle
                cx={48}
                cy={48}
                r={40}
                stroke="currentColor"
                strokeWidth={7}
                fill="transparent"
                className="text-zinc-200 dark:text-zinc-800"
              />
              <circle
                cx={48}
                cy={48}
                r={40}
                stroke="currentColor"
                strokeWidth={7}
                fill="transparent"
                strokeDasharray={2 * Math.PI * 40}
                strokeDashoffset={
                  2 * Math.PI * 40 - (Math.min(report.overall, 10) / 10) * (2 * Math.PI * 40)
                }
                strokeLinecap="round"
                className="text-emerald-500 transition-all duration-500"
              />
            </svg>
            <div className="absolute flex flex-col items-center justify-center text-center">
              <span className="font-mono text-2xl font-bold text-zinc-900 dark:text-zinc-50 leading-none">
                {formattedOverall}
              </span>
              <span className="font-mono text-[10px] text-zinc-500 dark:text-zinc-400">/10</span>
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                Overall Performance
              </span>
            </div>
            <div className="flex items-center gap-3">
              <span
                className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono font-bold border ${verdictStyle.bg} ${verdictStyle.border} ${verdictStyle.text}`}
              >
                {verdict === "No Hire" ? (
                  <WarningCircle size={14} weight="fill" />
                ) : (
                  <CheckCircle size={14} weight="fill" />
                )}
                <span>{verdict}</span>
              </span>
            </div>
            <p className="text-xs text-zinc-600 dark:text-zinc-400 max-w-sm">
              {report.verdict_why ||
                "Evaluated across technical correctness, system trade-offs, and communication clarity."}
            </p>
          </div>
        </div>

        {/* Right: Round count & adjustment note */}
        <div className="w-full md:w-auto md:text-right border-t md:border-t-0 pt-4 md:pt-0 border-zinc-200 dark:border-white/10 space-y-2">
          <div>
            <span className="text-[11px] font-mono text-zinc-500 dark:text-zinc-400 block uppercase">
              Evaluated Rounds
            </span>
            <span className="font-mono text-base font-bold text-zinc-800 dark:text-zinc-200">
              {report.per_question.length} {report.per_question.length === 1 ? "Question" : "Questions"}
            </span>
          </div>

          {report.adjustment && (
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-zinc-100 dark:bg-zinc-800 border border-zinc-200 dark:border-white/10 text-[11px] font-mono text-zinc-600 dark:text-zinc-400">
              <Scales size={13} weight="regular" className="text-emerald-500 shrink-0" />
              <span>Nudge: {report.adjustment}</span>
            </div>
          )}
        </div>
      </div>

      {/* Per-Question Breakdown Section (Hairline Dividers, NOT cards) */}
      <div className="space-y-4">
        <div>
          <h2 className="text-sm font-mono uppercase tracking-wider text-zinc-900 dark:text-zinc-100 font-bold">
            Round-by-Round Breakdown
          </h2>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Individual round performance scores and agent analysis.
          </p>
        </div>

        <div className="border border-zinc-200 dark:border-white/10 rounded-xl bg-white dark:bg-zinc-900/40 divide-y divide-zinc-200 dark:divide-white/10 overflow-hidden shadow-sm">
          {report.per_question.map((score, idx) => (
            <div
              key={idx}
              className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-zinc-50/50 dark:hover:bg-zinc-900/60 transition-colors"
            >
              <div className="flex items-center gap-3">
                <span className="w-7 h-7 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-mono text-xs font-bold flex items-center justify-center shrink-0 border border-zinc-200 dark:border-white/10">
                  {String(idx + 1).padStart(2, "0")}
                </span>
                <div>
                  <h3 className="text-xs sm:text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                    Question Round {idx + 1}
                  </h3>
                  <p className="text-[11px] text-zinc-500 dark:text-zinc-400 font-mono">
                    Targeted technical evaluation
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold text-emerald-600 dark:text-emerald-400 px-2.5 py-1 rounded bg-emerald-500/10 border border-emerald-500/20">
                  {typeof score === "number" ? score.toFixed(1) : score}/10
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Strengths & Gaps Analysis Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Strengths */}
        <div
          className={`p-5 ${TOKENS.radius.card} border border-emerald-500/20 bg-emerald-500/5 dark:bg-emerald-500/10 space-y-3`}
        >
          <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
            <Sparkle size={18} weight="fill" />
            <h3 className="text-xs font-mono uppercase tracking-wider font-bold">
              Demonstrated Strengths
            </h3>
          </div>
          <div className="text-xs sm:text-sm text-zinc-700 dark:text-zinc-300 leading-relaxed whitespace-pre-wrap">
            <ReactMarkdown
              components={{
                p: ({ children }) => <span>{children}</span>,
                strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
              }}
            >
              {report.strengths ||
                "Demonstrated solid technical grasp of architectural concepts and system tradeoffs."}
            </ReactMarkdown>
          </div>
        </div>

        {/* Gaps / Growth Areas */}
        <div
          className={`p-5 ${TOKENS.radius.card} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900/60 space-y-3`}
        >
          <div className="flex items-center gap-2 text-zinc-800 dark:text-zinc-200">
            <WarningCircle size={18} weight="regular" className="text-zinc-500" />
            <h3 className="text-xs font-mono uppercase tracking-wider font-bold">
              Key Growth Areas
            </h3>
          </div>
          <div className="text-xs sm:text-sm text-zinc-700 dark:text-zinc-300 leading-relaxed whitespace-pre-wrap">
            <ReactMarkdown
              components={{
                p: ({ children }) => <span>{children}</span>,
                strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
              }}
            >
              {report.gaps ||
                "Could elaborate more on failure edge cases, latency boundaries, and recovery strategies under load."}
            </ReactMarkdown>
          </div>
        </div>
      </div>

      {/* Study Next Action Plan */}
      <div
        className={`p-5 sm:p-6 ${TOKENS.radius.card} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900/60 space-y-3`}
      >
        <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100">
          <BookOpen size={18} weight="regular" className="text-emerald-500" />
          <h3 className="text-xs font-mono uppercase tracking-wider font-bold">
            Recommended Study Topics
          </h3>
        </div>

        {studyItems.length > 0 ? (
          <ul className="space-y-2">
            {studyItems.map((item, idx) => (
              <li
                key={idx}
                className="flex items-start gap-2.5 text-xs sm:text-sm text-zinc-700 dark:text-zinc-300"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0 mt-1.5" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs sm:text-sm text-zinc-600 dark:text-zinc-400">
            {report.study_next || "Review distributed locking patterns, consensus mechanisms, and database indexing strategies."}
          </p>
        )}
      </div>
    </div>
  );
}
