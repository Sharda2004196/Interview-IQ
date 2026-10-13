"use client";

import React, { useEffect, useRef } from "react";
import { ChatCircleDots, User, Robot } from "@phosphor-icons/react";
import { type TranscriptEntry } from "@/lib/useVoiceSession";
import { TOKENS } from "@/lib/tokens";

interface LiveTranscriptPaneProps {
  transcripts: TranscriptEntry[];
  voiceOrbState?: "idle" | "listening" | "speaking";
}

export function LiveTranscriptPane({
  transcripts,
  voiceOrbState = "idle",
}: LiveTranscriptPaneProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest message whenever transcripts update
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [transcripts, voiceOrbState]);

  return (
    <div
      className={`border border-zinc-200 dark:border-white/10 ${TOKENS.radius.card} bg-white dark:bg-zinc-900/60 shadow-sm overflow-hidden flex flex-col`}
    >
      {/* Pane Header */}
      <div className="px-4 py-3 border-b border-zinc-200 dark:border-white/10 flex items-center justify-between bg-zinc-50/50 dark:bg-zinc-950/40">
        <div className="flex items-center gap-2">
          <ChatCircleDots size={16} weight="bold" className="text-emerald-500" />
          <span className="text-xs font-mono font-semibold uppercase tracking-wider text-zinc-900 dark:text-zinc-100">
            Voice Transcript
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
            Spoken Turns
          </span>
        </div>

        {voiceOrbState === "speaking" && (
          <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-emerald-500 animate-pulse">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span>Interviewer Speaking</span>
          </span>
        )}
      </div>

      {/* Transcript Stream Area */}
      <div
        ref={scrollContainerRef}
        className="p-4 space-y-3.5 max-h-[360px] min-h-[180px] overflow-y-auto"
      >
        {transcripts.length === 0 ? (
          <div className="py-8 text-center text-xs text-zinc-500 dark:text-zinc-400 space-y-1">
            <p className="font-medium text-zinc-700 dark:text-zinc-300">
              Voice transcript ready
            </p>
            <p className="text-[11px] text-zinc-400 dark:text-zinc-500">
              Read-aloud questions and your spoken answers will appear here turn by turn.
            </p>
          </div>
        ) : (
          transcripts.map((entry) => {
            const isInterviewer = entry.sender === "interviewer";
            return (
              <div
                key={entry.id}
                className={`flex gap-3 items-start ${
                  isInterviewer ? "justify-start" : "justify-end"
                }`}
              >
                {isInterviewer && (
                  <div className="w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0 mt-0.5 border border-emerald-500/30">
                    <Robot size={13} weight="bold" />
                  </div>
                )}

                <div
                  className={`max-w-[85%] sm:max-w-[75%] p-3 rounded-lg text-xs leading-relaxed ${
                    isInterviewer
                      ? "bg-zinc-100 dark:bg-zinc-800/80 text-zinc-800 dark:text-zinc-200 border border-zinc-200 dark:border-white/5"
                      : "bg-emerald-500/15 border border-emerald-500/30 text-emerald-950 dark:text-emerald-200"
                  }`}
                >
                  <div className="flex items-center justify-between gap-4 mb-1">
                    <span
                      className={`font-mono text-[10px] font-bold uppercase ${
                        isInterviewer
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-emerald-700 dark:text-emerald-300"
                      }`}
                    >
                      {isInterviewer ? "Interviewer" : "Candidate (You)"}
                    </span>
                    <span className="font-mono text-[9px] text-zinc-400 dark:text-zinc-500">
                      {entry.timestamp.toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap">{entry.text}</p>
                </div>

                {!isInterviewer && (
                  <div className="w-6 h-6 rounded-full bg-zinc-200 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 flex items-center justify-center shrink-0 mt-0.5 border border-zinc-300 dark:border-white/10">
                    <User size={13} weight="bold" />
                  </div>
                )}
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
