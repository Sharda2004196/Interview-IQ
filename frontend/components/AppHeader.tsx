"use client";

import React from "react";
import Link from "next/link";
import { Brain } from "@phosphor-icons/react";
import { ThemeToggle } from "./ThemeToggle";
import { AuthButton } from "./AuthButton";
import { TOKENS } from "@/lib/tokens";

export function AppHeader() {
  return (
    <header className="sticky top-0 z-40 w-full h-14 bg-zinc-50/80 dark:bg-zinc-950/80 backdrop-blur-md border-b border-zinc-200 dark:border-white/10 transition-colors">
      <div className="max-w-7xl mx-auto h-full px-4 sm:px-6 lg:px-8 flex items-center justify-between">
        {/* Brand / Logo */}
        <Link
          href="/"
          className="flex items-center gap-2.5 group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 rounded-lg p-1 -m-1"
        >
          <div className="w-8 h-8 rounded-lg bg-emerald-500/15 dark:bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-600 dark:text-emerald-400 group-hover:scale-105 transition-transform duration-150">
            <Brain size={18} weight="bold" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-semibold tracking-tight text-zinc-900 dark:text-zinc-100 text-base">
              Interview<span className="text-emerald-600 dark:text-emerald-400 font-bold">IQ</span>
            </span>
          </div>
        </Link>

        {/* Right tools */}
        <div className="flex items-center gap-3">
          <div className="hidden md:flex items-center gap-2 px-2.5 py-1 rounded-full border border-zinc-200 dark:border-white/10 bg-zinc-100/50 dark:bg-zinc-900/50 text-xs text-zinc-600 dark:text-zinc-400 font-mono">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span>Agent Live</span>
          </div>
          <ThemeToggle />
          <AuthButton />
        </div>
      </div>
    </header>
  );
}
