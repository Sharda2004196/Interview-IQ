"use client";

import React, { useState, useEffect } from "react";
import { Clock } from "@phosphor-icons/react";

interface TimerProps {
  isRunning?: boolean;
  className?: string;
}

export function Timer({ isRunning = true, className = "" }: TimerProps) {
  const [seconds, setSeconds] = useState<number>(0);

  useEffect(() => {
    if (!isRunning) return;

    const interval = setInterval(() => {
      setSeconds((prev) => prev + 1);
    }, 1000);

    return () => clearInterval(interval);
  }, [isRunning]);

  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  const formatted = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;

  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-zinc-200 dark:border-white/10 bg-zinc-100/60 dark:bg-zinc-900/60 text-zinc-700 dark:text-zinc-300 font-mono text-xs ${className}`}
      aria-label={`Elapsed time: ${formatted}`}
    >
      <Clock size={13} weight="regular" className="text-emerald-500" />
      <span className="font-semibold">{formatted}</span>
    </div>
  );
}
