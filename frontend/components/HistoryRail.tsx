"use client";

import React, { useState } from "react";
import { ClockCounterClockwise, CaretDown, CaretUp, CheckCircle } from "@phosphor-icons/react";
import { type TurnHistory } from "@/lib/useInterviewSocket";
import { TOKENS } from "@/lib/tokens";

interface HistoryRailProps {
  history: TurnHistory[];
}

export function HistoryRail({ history }: HistoryRailProps) {
  const [isExpanded, setIsExpanded] = useState<boolean>(true);

  return (
    <div className={`border border-zinc-200 dark:border-white/10 ${TOKENS.radius.card} bg-white dark:bg-zinc-900/60 shadow-sm overflow-hidden`}>
      {/* Header with expand/collapse */}
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3.5 flex items-center justify-between hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors text-left"
        aria-expanded={isExpanded}
      >
        <div className="flex items-center gap-2">
          <ClockCounterClockwise size={16} weight="bold" className="text-emerald-500" />
          <span className="text-xs font-mono font-semibold uppercase tracking-wider text-zinc-900 dark:text-zinc-100">
            Round History
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
            {history.length}
          </span>
        </div>
        {isExpanded ? (
          <CaretUp size={14} weight="bold" className="text-zinc-400" />
        ) : (
          <CaretDown size={14} weight="bold" className="text-zinc-400" />
        )}
      </button>

      {/* History Items */}
      {isExpanded && (
        <div className="border-t border-zinc-200 dark:border-white/10 p-3 max-h-[calc(100vh-280px)] overflow-y-auto space-y-3">
          {history.length === 0 ? (
            <div className="py-6 text-center text-xs text-zinc-500 dark:text-zinc-400">
              <p>No completed rounds yet.</p>
              <p className="text-[11px] mt-1 text-zinc-400 dark:text-zinc-500">
                Answer your current question to log round scores.
              </p>
            </div>
          ) : (
            history.map((turn, index) => (
              <div
                key={index}
                className="p-3 rounded-lg border border-zinc-200 dark:border-white/5 bg-zinc-50 dark:bg-zinc-950/60 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] font-bold text-zinc-500 dark:text-zinc-400 uppercase">
                    Q{String(turn.qIndex).padStart(2, "0")}
                  </span>
                  {turn.score !== undefined ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 dark:text-emerald-400">
                      <CheckCircle size={10} weight="fill" />
                      {turn.score}/10
                    </span>
                  ) : (
                    <span className="text-[10px] font-mono text-zinc-400 animate-pulse">
                      Scoring...
                    </span>
                  )}
                </div>
                <p className="text-xs font-medium text-zinc-800 dark:text-zinc-200 line-clamp-2">
                  {turn.question}
                </p>
                <div className="pt-1 border-t border-zinc-200/60 dark:border-white/5">
                  <p className="text-[11px] text-zinc-600 dark:text-zinc-400 italic line-clamp-2">
                    &quot;{turn.answer}&quot;
                  </p>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
