"use client";

import React, { useEffect, useState } from "react";
import { Sun, Moon } from "@phosphor-icons/react";
import { useTheme } from "./ThemeProvider";
import { TOKENS } from "@/lib/tokens";

export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggleTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div
        className={`w-9 h-9 ${TOKENS.radius.button} border border-zinc-200 dark:border-white/10 bg-zinc-100 dark:bg-zinc-900/80 ${className}`}
        aria-hidden="true"
      />
    );
  }

  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className={`relative inline-flex items-center justify-center w-9 h-9 ${TOKENS.radius.button} border border-zinc-200 dark:border-white/10 bg-zinc-100 hover:bg-zinc-200/80 dark:bg-zinc-900 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 hover:text-zinc-950 dark:hover:text-white transition-colors duration-150 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 ${className}`}
    >
      {isDark ? (
        <Sun size={18} weight="regular" className="transition-transform duration-200" />
      ) : (
        <Moon size={18} weight="regular" className="transition-transform duration-200" />
      )}
    </button>
  );
}
