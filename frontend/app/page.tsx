"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, FileText, SpinnerGap, WarningCircle } from "@phosphor-icons/react";
import { ModePicker } from "@/components/ModePicker";
import { PersonaPanel } from "@/components/PersonaPanel";
import { createSession, type Mode, type Persona, type SessionConfig } from "@/lib/api";
import { TOKENS } from "@/lib/tokens";

export default function SetupPage() {
  const router = useRouter();

  // Mode state
  const [mode, setMode] = useState<Mode>("A");
  const [topic, setTopic] = useState<string>("");
  const [customQuestionsText, setCustomQuestionsText] = useState<string>("");
  const [fileNamespace, setFileNamespace] = useState<string>("");

  // Persona state
  const [persona, setPersona] = useState<Persona>({
    role: "Senior tech interviewer",
    tone: "encouraging but rigorous",
    difficulty: "medium",
    voice: "default",
  });
  const [numQuestions, setNumQuestions] = useState<number>(5);
  const [isVoiceMode, setIsVoiceMode] = useState<boolean>(false);

  // Form submission state
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    // Validation
    if (mode === "A" && !topic.trim()) {
      setErrorMessage("Please enter an interview topic (e.g., 'Distributed Systems').");
      return;
    }

    if (mode === "B") {
      const qList = customQuestionsText
        .split("\n")
        .map((q) => q.trim())
        .filter(Boolean);
      if (qList.length === 0) {
        setErrorMessage("Please enter at least one custom question.");
        return;
      }
    }

    if ((mode === "C" || mode === "D") && !fileNamespace) {
      setErrorMessage(
        mode === "C"
          ? "Please upload a document to use as knowledge base context."
          : "Please upload a resume for personalized grilling."
      );
      return;
    }

    if (mode === "E") {
      const url = topic.trim();
      if (!url) {
        setErrorMessage("Please enter a YouTube or web article URL.");
        return;
      }
      const urlPattern = /^(https?:\/\/|(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/)/i;
      if (!urlPattern.test(url) && !url.startsWith("http")) {
        setErrorMessage("Please enter a valid URL (e.g. https://youtu.be/... or https://example.com/...)");
        return;
      }
    }

    setIsSubmitting(true);

    try {
      const customQuestions =
        mode === "B"
          ? customQuestionsText
              .split("\n")
              .map((q) => q.trim())
              .filter(Boolean)
          : [];

      const payload: SessionConfig = {
        mode,
        topic: topic.trim(),
        custom_questions: customQuestions,
        file_namespace: mode === "C" || mode === "D" ? fileNamespace : "",
        persona,
        num_questions: mode === "B" && customQuestions.length > 0 ? customQuestions.length : numQuestions,
      };

      const result = await createSession(payload);
      if (result.session_id) {
        const voiceQuery = isVoiceMode ? "&voice=true" : "";
        router.push(`/stage/${result.session_id}?n=${payload.num_questions}${voiceQuery}`);
      } else {
        throw new Error("Invalid session response received from server.");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to connect to backend server";
      setErrorMessage(msg);
      setIsSubmitting(false);
    }
  };

  return (
    <div className="w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 md:py-10 flex-1 flex flex-col justify-center">
      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Top Header */}
        <div className="border-b border-zinc-200 dark:border-white/10 pb-5">
          <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-2">
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
                New Interview
              </h1>
              <p className="text-xs sm:text-sm text-zinc-600 dark:text-zinc-400 mt-1">
                Pick a mode, tune the interviewer, start when ready.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
                Target: {numQuestions} {numQuestions === 1 ? "Round" : "Rounds"}
              </span>
              <button
                type="button"
                onClick={() => router.push("/reports")}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 ${TOKENS.radius.button} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 text-xs font-semibold transition-all duration-150 active:scale-[0.98]`}
              >
                <FileText size={14} weight="regular" className="text-emerald-500" />
                <span>Past Reports</span>
              </button>
            </div>
          </div>
        </div>

        {/* Two-Column Responsive Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          {/* Left Column: Mode & Inputs (7 cols) */}
          <div className="lg:col-span-7">
            <ModePicker
              mode={mode}
              onModeChange={setMode}
              topic={topic}
              onTopicChange={setTopic}
              customQuestionsText={customQuestionsText}
              onCustomQuestionsTextChange={setCustomQuestionsText}
              fileNamespace={fileNamespace}
              onFileUploaded={(ns) => setFileNamespace(ns)}
              onFileCleared={() => setFileNamespace("")}
            />
          </div>

          {/* Right Column: Persona & Difficulty (5 cols) */}
          <div className="lg:col-span-5">
            <PersonaPanel
              persona={persona}
              onPersonaChange={setPersona}
              numQuestions={numQuestions}
              onNumQuestionsChange={setNumQuestions}
              isVoiceMode={isVoiceMode}
              onVoiceModeChange={setIsVoiceMode}
            />
          </div>
        </div>

        {/* Inline Error Alert */}
        {errorMessage && (
          <div className="p-3.5 rounded-lg border border-rose-500/30 bg-rose-500/10 flex items-center gap-2 text-xs text-rose-500 dark:text-rose-400">
            <WarningCircle size={16} weight="fill" className="shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Bottom CTA Area */}
        <div className="pt-4 border-t border-zinc-200 dark:border-white/10 flex flex-col sm:flex-row items-center justify-end gap-4">
          <button
            type="submit"
            disabled={isSubmitting}
            className={`w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-2.5 ${TOKENS.radius.button} bg-emerald-500 hover:bg-emerald-600 text-zinc-950 font-semibold text-sm transition-all duration-150 active:scale-[0.98] shadow-sm hover:shadow-emerald-500/20 disabled:opacity-60 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50`}
          >
            {isSubmitting ? (
              <>
                <SpinnerGap size={16} weight="bold" className="animate-spin" />
                <span>Initializing...</span>
              </>
            ) : (
              <>
                <span>Start interview</span>
                <ArrowRight size={16} weight="bold" />
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
