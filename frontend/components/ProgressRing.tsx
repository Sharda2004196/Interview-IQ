"use client";

import React from "react";

interface ProgressRingProps {
  current: number;
  total: number;
  size?: number;
  strokeWidth?: number;
}

export function ProgressRing({
  current,
  total,
  size = 44,
  strokeWidth = 3.5,
}: ProgressRingProps) {
  const safeTotal = Math.max(total, 1);
  const safeCurrent = Math.min(Math.max(current, 0), safeTotal);
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progressRatio = safeCurrent / safeTotal;
  const strokeDashoffset = circumference - progressRatio * circumference;

  return (
    <div
      className="relative flex items-center justify-center shrink-0"
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuenow={safeCurrent}
      aria-valuemin={1}
      aria-valuemax={safeTotal}
      aria-label={`Interview progress: question ${safeCurrent} of ${safeTotal}`}
    >
      <svg width={size} height={size} className="transform -rotate-90">
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="transparent"
          className="text-zinc-200 dark:text-zinc-800"
        />
        {/* Animated Progress circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="transparent"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          className="text-emerald-500 transition-all duration-300 ease-out"
        />
      </svg>
      {/* Center text in mono */}
      <span className="absolute font-mono text-[11px] font-bold text-zinc-800 dark:text-zinc-200">
        {safeCurrent}/{safeTotal}
      </span>
    </div>
  );
}
