"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import { SpeakerHigh } from "@phosphor-icons/react";
import { TOKENS } from "@/lib/tokens";

interface QuestionCardProps {
  question: string;
  turnIndex: number;
  isStreaming: boolean;
  totalQuestions?: number;
  // Voice mode: replay button re-speaks the settled question (user gesture,
  // so speech playback is never autoplay-blocked).
  onReplay?: () => void;
}

export function QuestionCard({
  question,
  turnIndex,
  isStreaming,
  totalQuestions,
  onReplay,
}: QuestionCardProps) {
  return (
    <div
      className={`p-6 ${TOKENS.radius.card} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900/80 shadow-sm space-y-4`}
    >
      {/* Top turn indicator */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
            Question {String(turnIndex).padStart(2, "0")}
            {totalQuestions ? ` of ${String(totalQuestions).padStart(2, "0")}` : ""}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {onReplay && question && !isStreaming && (
            <button
              type="button"
              onClick={onReplay}
              aria-label="Read question aloud"
              title="Read question aloud"
              className="inline-flex items-center justify-center w-7 h-7 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20 transition-colors"
            >
              <SpeakerHigh size={14} weight="bold" />
            </button>
          )}
          {isStreaming && (
          <div className="flex items-center gap-1.5 text-[11px] font-mono text-emerald-600 dark:text-emerald-400">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span>Agent speaking</span>
          </div>
          )}
        </div>
      </div>

      {/* Main question content or Skeleton state. No question yet (or none at
      all — the score's justification mid-stream, or the final report) shows the
      waiting skeleton: the card never renders non-question text. */}
      {!question ? (
        <div className="space-y-3 py-2 animate-pulse">
          <div className="h-4 bg-zinc-200 dark:bg-zinc-800 rounded w-3/4" />
          <div className="h-4 bg-zinc-200 dark:bg-zinc-800 rounded w-full" />
          <div className="h-4 bg-zinc-200 dark:bg-zinc-800 rounded w-5/6" />
        </div>
      ) : (
        <div className="text-base sm:text-lg font-medium leading-relaxed text-zinc-900 dark:text-zinc-100">
          <ReactMarkdown
            components={{
              p: ({ children }) => <p className="whitespace-pre-wrap">{children}</p>,
              strong: ({ children }) => <strong className="font-bold">{children}</strong>,
              h1: ({ children }) => <p className="font-bold">{children}</p>,
              h2: ({ children }) => <p className="font-bold">{children}</p>,
              h3: ({ children }) => <p className="font-bold">{children}</p>,
              ul: ({ children }) => <ul className="list-disc pl-5 space-y-1">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1">{children}</ol>,
              li: ({ children }) => <li>{children}</li>,
              code: ({ children }) => (
                <code className="font-mono text-[0.9em] px-1 rounded bg-zinc-100 dark:bg-zinc-800">
                  {children}
                </code>
              ),
            }}
          >
            {question}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}
