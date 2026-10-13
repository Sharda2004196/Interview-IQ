"use client";

import React from "react";
import { UserGear, Gauge, Microphone, ChatText, Hash } from "@phosphor-icons/react";
import { type Difficulty, type Persona } from "@/lib/api";
import { TOKENS } from "@/lib/tokens";

interface PersonaPanelProps {
  persona: Persona;
  onPersonaChange: (updated: Persona) => void;
  numQuestions: number;
  onNumQuestionsChange: (n: number) => void;
  isVoiceMode?: boolean;
  onVoiceModeChange?: (isVoice: boolean) => void;
}

const ROLES = [
  "Senior tech interviewer",
  "Staff infrastructure engineer",
  "Principal architect",
  "Engineering manager",
  "FAANG bar raiser",
];

const TONES = [
  "encouraging but rigorous",
  "neutral and objective",
  "challenging and skeptical",
  "collaborative peer-like",
];

const DIFFICULTIES: Array<{
  id: Difficulty;
  label: string;
  badge: string;
}> = [
  { id: "easy", label: "Junior / Mid", badge: "EASY" },
  { id: "medium", label: "Senior", badge: "MED" },
  { id: "hard", label: "Staff / Principal", badge: "HARD" },
];

export function PersonaPanel({
  persona,
  onPersonaChange,
  numQuestions,
  onNumQuestionsChange,
  isVoiceMode = false,
  onVoiceModeChange,
}: PersonaPanelProps) {
  const updateField = <K extends keyof Persona>(field: K, value: Persona[K]) => {
    onPersonaChange({
      ...persona,
      [field]: value,
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <label className="block text-xs font-mono uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-2">
          Interviewer Persona &amp; Round Limits
        </label>
      </div>

      <div className={`p-5 ${TOKENS.radius.card} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900/60 shadow-sm space-y-5`}>
        {/* Role Selector */}
        <div className="space-y-1.5">
          <label
            htmlFor="persona-role"
            className="flex items-center gap-1.5 text-xs font-mono uppercase tracking-wider text-zinc-600 dark:text-zinc-300"
          >
            <UserGear size={14} weight="regular" className="text-emerald-500" />
            <span>Interviewer Role</span>
          </label>
          <input
            id="persona-role"
            type="text"
            list="role-suggestions"
            value={persona.role}
            onChange={(e) => updateField("role", e.target.value)}
            className={`w-full px-3.5 py-2 text-xs text-zinc-900 dark:text-zinc-100 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 ${TOKENS.radius.input} focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500`}
          />
          <datalist id="role-suggestions">
            {ROLES.map((r) => (
              <option key={r} value={r} />
            ))}
          </datalist>
        </div>

        {/* Tone Selector */}
        <div className="space-y-1.5">
          <label
            htmlFor="persona-tone"
            className="block text-xs font-mono uppercase tracking-wider text-zinc-600 dark:text-zinc-300"
          >
            Interviewer Tone
          </label>
          <input
            id="persona-tone"
            type="text"
            list="tone-suggestions"
            value={persona.tone}
            onChange={(e) => updateField("tone", e.target.value)}
            className={`w-full px-3.5 py-2 text-xs text-zinc-900 dark:text-zinc-100 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 ${TOKENS.radius.input} focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500`}
          />
          <datalist id="tone-suggestions">
            {TONES.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </div>

        {/* Difficulty Stepper */}
        <div className="space-y-2">
          <label className="flex items-center gap-1.5 text-xs font-mono uppercase tracking-wider text-zinc-600 dark:text-zinc-300">
            <Gauge size={14} weight="regular" className="text-emerald-500" />
            <span>Difficulty Target</span>
          </label>
          <div className="grid grid-cols-3 gap-2">
            {DIFFICULTIES.map((d) => {
              const active = persona.difficulty === d.id;
              return (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => updateField("difficulty", d.id)}
                  className={`flex flex-col items-center py-2 px-1 text-center ${TOKENS.radius.button} border transition-all duration-150 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 ${
                    active
                      ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-semibold ring-1 ring-emerald-500/30"
                      : "border-zinc-200 dark:border-white/10 hover:border-zinc-300 dark:hover:border-white/20 bg-zinc-50 dark:bg-zinc-950 text-zinc-600 dark:text-zinc-400"
                  }`}
                >
                  <span className="font-mono text-[10px] font-bold">{d.badge}</span>
                  <span className="text-[11px] mt-0.5 truncate">{d.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Question Count Stepper */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-1.5 text-xs font-mono uppercase tracking-wider text-zinc-600 dark:text-zinc-300">
              <Hash size={14} weight="regular" className="text-emerald-500" />
              <span>Questions Count</span>
            </label>
            <span className="font-mono text-xs font-semibold text-emerald-600 dark:text-emerald-400 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20">
              {numQuestions} {numQuestions === 1 ? "round" : "rounds"}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={1}
              max={10}
              step={1}
              value={numQuestions}
              onChange={(e) => onNumQuestionsChange(parseInt(e.target.value, 10) || 5)}
              className="w-full h-1.5 bg-zinc-200 dark:bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-emerald-500"
            />
          </div>
          <div className="flex justify-between text-[10px] font-mono text-zinc-400 dark:text-zinc-500">
            <span>1 (Quick)</span>
            <span>5 (Standard)</span>
            <span>10 (Full Loop)</span>
          </div>
        </div>

        {/* Interview Transport: Voice vs Text */}
        <div className="space-y-2 pt-2 border-t border-zinc-200 dark:border-white/10">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-mono uppercase tracking-wider text-zinc-700 dark:text-zinc-300">
              <Microphone size={14} weight="regular" className="text-emerald-500" />
              <span>Interview Format</span>
            </span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium tracking-wide uppercase bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
              {isVoiceMode ? "Voice" : "Text Mode"}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2 pt-1">
            <button
              type="button"
              onClick={() => onVoiceModeChange?.(false)}
              className={`flex items-center justify-center gap-1.5 py-2 px-3 text-xs ${TOKENS.radius.button} border transition-all duration-150 active:scale-[0.98] ${
                !isVoiceMode
                  ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-semibold"
                  : "border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-zinc-950 text-zinc-600 dark:text-zinc-400"
              }`}
            >
              <ChatText size={14} weight="bold" />
              <span>Text Round</span>
            </button>

            <button
              type="button"
              onClick={() => onVoiceModeChange?.(true)}
              className={`flex items-center justify-center gap-1.5 py-2 px-3 text-xs ${TOKENS.radius.button} border transition-all duration-150 active:scale-[0.98] ${
                isVoiceMode
                  ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-semibold ring-1 ring-emerald-500/30"
                  : "border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-zinc-950 text-zinc-600 dark:text-zinc-400"
              }`}
            >
              <Microphone size={14} weight="bold" />
              <span>Voice Round</span>
            </button>
          </div>

          <p className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-relaxed">
            {isVoiceMode
              ? "Spoken interview with live transcription."
              : "Type answers, scored as you go."}
          </p>
        </div>
      </div>
    </div>
  );
}
