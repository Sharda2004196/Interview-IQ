"use client";

import React from "react";
import { motion, useReducedMotion } from "motion/react";
import { Sparkle, CheckCircle } from "@phosphor-icons/react";
import { TOKENS } from "@/lib/tokens";

interface ScoreRevealProps {
  score: number | null;
  turnIndex: number;
}

export function ScoreReveal({ score, turnIndex }: ScoreRevealProps) {
  const shouldReduceMotion = useReducedMotion();

  if (score === null || score === undefined) {
    return null;
  }

  // Format score to 1 decimal place or integer
  const formattedScore = Number.isInteger(score) ? score.toString() : score.toFixed(1);

  return (
    <motion.div
      initial={shouldReduceMotion ? { opacity: 1 } : { opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className={`p-4 ${TOKENS.radius.card} border border-emerald-500/30 bg-emerald-500/10 dark:bg-emerald-500/15 shadow-sm flex items-center justify-between gap-4`}
    >
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
          <Sparkle size={18} weight="fill" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs uppercase font-semibold text-emerald-600 dark:text-emerald-400">
              Evaluation (Question {String(turnIndex).padStart(2, "0")})
            </span>
          </div>
          <p className="text-xs text-zinc-600 dark:text-zinc-300 mt-0.5">
            Turn response evaluated by scoring agent.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <div className="text-right">
          <span className="font-mono text-lg font-bold text-emerald-600 dark:text-emerald-400">
            {formattedScore}
          </span>
          <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">/10</span>
        </div>
        <CheckCircle size={20} weight="fill" className="text-emerald-500 shrink-0" />
      </div>
    </motion.div>
  );
}
