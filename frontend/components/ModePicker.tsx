"use client";

import React from "react";
import { ListNumbers, Books, UserCheck, ChatText, Globe } from "@phosphor-icons/react";
import { type Mode } from "@/lib/api";
import { FileUpload } from "./FileUpload";
import { TOKENS } from "@/lib/tokens";

interface ModePickerProps {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  topic: string;
  onTopicChange: (topic: string) => void;
  customQuestionsText: string;
  onCustomQuestionsTextChange: (text: string) => void;
  fileNamespace: string;
  onFileUploaded: (namespace: string) => void;
  onFileCleared: () => void;
}

const MODES: Array<{
  id: Mode;
  badge: string;
  label: string;
  desc: string;
  icon: React.ElementType;
}> = [
  {
    id: "A",
    badge: "Mode A",
    label: "Topic Only",
    desc: "Targeted rounds on a specific framework, topic, or concept.",
    icon: ChatText,
  },
  {
    id: "B",
    badge: "Mode B",
    label: "Custom Questions",
    desc: "Paste exact list of questions to be asked sequentially.",
    icon: ListNumbers,
  },
  {
    id: "C",
    badge: "Mode C",
    label: "Knowledge Base",
    desc: "Upload technical docs, RFCs, or architecture specs as RAG context.",
    icon: Books,
  },
  {
    id: "D",
    badge: "Mode D",
    label: "Resume Persona",
    desc: "Upload candidate resume for tailored experience-based grilling.",
    icon: UserCheck,
  },
  {
    id: "E",
    badge: "Mode E",
    label: "Web / YouTube URL",
    desc: "Paste YouTube or article URL to extract & interview against.",
    icon: Globe,
  },
];

export function ModePicker({
  mode,
  onModeChange,
  topic,
  onTopicChange,
  customQuestionsText,
  onCustomQuestionsTextChange,
  fileNamespace,
  onFileUploaded,
  onFileCleared,
}: ModePickerProps) {
  return (
    <div className="space-y-6">
      {/* Mode Selector Header */}
      <div>
        <label className="block text-xs font-mono uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-2">
          Interview Mode
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {MODES.map((m) => {
            const Icon = m.icon;
            const isSelected = mode === m.id;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => onModeChange(m.id)}
                className={`flex flex-col items-start p-3 ${TOKENS.radius.card} border text-left transition-all duration-150 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 ${
                  isSelected
                    ? "border-emerald-500/40 bg-emerald-500/10 dark:bg-emerald-500/15 ring-1 ring-emerald-500/30"
                    : "border-zinc-200 dark:border-white/10 hover:border-zinc-300 dark:hover:border-white/20 bg-white dark:bg-zinc-900/40"
                }`}
              >
                <div className="flex items-center justify-between w-full mb-1.5">
                  <span
                    className={`font-mono text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded ${
                      isSelected
                        ? "bg-emerald-500 text-zinc-950 font-bold"
                        : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400"
                    }`}
                  >
                    {m.badge}
                  </span>
                  <Icon
                    size={16}
                    weight={isSelected ? "bold" : "regular"}
                    className={isSelected ? "text-emerald-500" : "text-zinc-400"}
                  />
                </div>
                <span className="text-xs font-medium text-zinc-900 dark:text-zinc-100">
                  {m.label}
                </span>
                <span className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-tight mt-0.5 line-clamp-2">
                  {m.desc}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Dynamic Mode Content Area */}
      <div className={`p-4 ${TOKENS.radius.card} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900/60 shadow-sm`}>
        {mode === "A" && (
          <div className="space-y-2">
            <label
              htmlFor="topic-input"
              className="block text-xs font-mono uppercase tracking-wider text-zinc-500 dark:text-zinc-400"
            >
              Interview Topic / Focus Area
            </label>
            <input
              id="topic-input"
              type="text"
              value={topic}
              onChange={(e) => onTopicChange(e.target.value)}
              placeholder="e.g. Distributed Consensus (Raft/Paxos), Postgres Query Optimization..."
              className={`w-full px-3.5 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 ${TOKENS.radius.input} focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 placeholder:text-zinc-400 dark:placeholder:text-zinc-600`}
            />
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
              The AI interviewer generates deep, sequential technical questions on this topic.
            </p>
          </div>
        )}

        {mode === "B" && (
          <div className="space-y-2">
            <label
              htmlFor="custom-questions-textarea"
              className="block text-xs font-mono uppercase tracking-wider text-zinc-500 dark:text-zinc-400"
            >
              Custom Question Script
            </label>
            <textarea
              id="custom-questions-textarea"
              rows={5}
              value={customQuestionsText}
              onChange={(e) => onCustomQuestionsTextChange(e.target.value)}
              placeholder={"1. Explain how virtual memory paging works.\n2. How would you design an LRU cache in O(1)?\n3. Describe an incident where you debugged a memory leak."}
              className={`w-full px-3.5 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 ${TOKENS.radius.input} font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 placeholder:text-zinc-400 dark:placeholder:text-zinc-600 resize-none`}
            />
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
              Paste one question per line. The agent will ask these exact questions with adaptive follow-ups.
            </p>
          </div>
        )}

        {mode === "C" && (
          <div className="space-y-3">
            <FileUpload
              label="Technical Document / Knowledge Base"
              description="Upload system design docs, RFCs, or code architecture specs"
              namespace={fileNamespace}
              onUploadSuccess={(ns) => onFileUploaded(ns)}
              onClear={onFileCleared}
            />
            <div className="space-y-1.5">
              <label
                htmlFor="kb-topic-focus"
                className="block text-xs font-mono uppercase tracking-wider text-zinc-500 dark:text-zinc-400"
              >
                Focus Angle (Optional)
              </label>
              <input
                id="kb-topic-focus"
                type="text"
                value={topic}
                onChange={(e) => onTopicChange(e.target.value)}
                placeholder="e.g. Failure recovery mechanisms, scaling limits..."
                className={`w-full px-3.5 py-2 text-xs text-zinc-900 dark:text-zinc-100 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 ${TOKENS.radius.input} focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 placeholder:text-zinc-400 dark:placeholder:text-zinc-600`}
              />
            </div>
          </div>
        )}

        {mode === "D" && (
          <div className="space-y-3">
            <FileUpload
              label="Candidate Resume / Profile"
              description="Upload PDF or text resume for deep personalized background grilling"
              namespace={fileNamespace}
              onUploadSuccess={(ns) => onFileUploaded(ns)}
              onClear={onFileCleared}
            />
            <div className="space-y-1.5">
              <label
                htmlFor="resume-target-role"
                className="block text-xs font-mono uppercase tracking-wider text-zinc-500 dark:text-zinc-400"
              >
                Target Role / Focus (Optional)
              </label>
              <input
                id="resume-target-role"
                type="text"
                value={topic}
                onChange={(e) => onTopicChange(e.target.value)}
                placeholder="e.g. Senior Backend / Distributed Systems Engineer..."
                className={`w-full px-3.5 py-2 text-xs text-zinc-900 dark:text-zinc-100 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 ${TOKENS.radius.input} focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 placeholder:text-zinc-400 dark:placeholder:text-zinc-600`}
              />
            </div>
          </div>
        )}

        {mode === "E" && (
          <div className="space-y-2">
            <label
              htmlFor="url-input"
              className="block text-xs font-mono uppercase tracking-wider text-zinc-500 dark:text-zinc-400"
            >
              YouTube Video or Web Article URL
            </label>
            <input
              id="url-input"
              type="url"
              value={topic}
              onChange={(e) => onTopicChange(e.target.value)}
              placeholder="https://youtu.be/... or https://example.com/system-design-article"
              className={`w-full px-3.5 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 ${TOKENS.radius.input} font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 placeholder:text-zinc-400 dark:placeholder:text-zinc-600`}
            />
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
              The backend fetches transcripts or web content automatically and indexes it into the RAG engine for targeted questions.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
