"use client";

import React, { useState, use, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  WarningCircle,
  ArrowClockwise,
  StopCircle,
  PaperPlaneRight,
  ChatText,
  SpeakerHigh,
} from "@phosphor-icons/react";
import { useInterviewSocket } from "@/lib/useInterviewSocket";
import { useTurnVoice } from "@/lib/useTurnVoice";
import { spokenText } from "@/lib/spokenText";
import { questionText } from "@/lib/questionText";
import { useFirebaseUser } from "@/lib/firebase";
import { LoginGate } from "@/components/LoginGate";
import VoicePill from "@/components/bits/VoicePill";
import { VoiceOrb } from "@/components/VoiceOrb";
import { ProgressRing } from "@/components/ProgressRing";
import { Timer } from "@/components/Timer";
import { QuestionCard } from "@/components/QuestionCard";
import { ScoreReveal } from "@/components/ScoreReveal";
import { HistoryRail } from "@/components/HistoryRail";
import { LiveTranscriptPane } from "@/components/LiveTranscriptPane";
import { TOKENS } from "@/lib/tokens";

export default function StagePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = use(params);
  const sessionId = resolvedParams.id;
  const router = useRouter();

  const [answerInput, setAnswerInput] = useState<string>("");
  const gateUser = useFirebaseUser();
  const [isVoice, setIsVoice] = useState<boolean>(false);
  const [totalRounds, setTotalRounds] = useState<number>(1);
  // Text-mode orb energy (state only — the effect lives below, after the
  // socket hooks, so it can read the live question text).
  const [textSpeaking, setTextSpeaking] = useState(false);
  const lastQRef = useRef<string>("");

  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const n = parseInt(search.get("n") || "", 10);
    if (Number.isFinite(n) && n > 0) setTotalRounds(n);
    if (search.get("voice") === "true" || search.get("voice") === "1") {
      setIsVoice(true);
    }
  }, []);

  const handleSessionEnd = useCallback(() => {
    router.push(`/report/${sessionId}`);
  }, [router, sessionId]);

  // Text Mode Socket Hook — the brain in BOTH modes. Voice is a browser
  // STT/TTS shell over this same socket (no Live audio socket anymore).
  const textSocket = useInterviewSocket({
    sessionId,
    onSessionEnd: handleSessionEnd,
  });

  // Turn-based voice shell (browser speech recognition + synthesis).
  const turnVoice = useTurnVoice({
    enabled: isVoice,
    onFinalAnswer: (text) => {
      setAnswerInput((prev) => (prev ? `${prev} ${text}` : text));
    },
  });
  const lastSpokenRef = useRef<string>("");
  const latestQuestionRef = useRef<string>("");
  latestQuestionRef.current = textSocket.currentQuestion;
  // The card shows the QUESTION and nothing else. A turn's raw text also carries
  // the agent's own "Welcome to your … interview!" preamble, the mandated
  // "Score: …" line, and — on the final turn, or a reconnect resync — the whole
  // written report. All display filtering lives in lib/questionText.ts; the
  // socket, transcript and report are untouched.
  const shownQuestion = questionText(textSocket.currentQuestion);

  // Speak each settled question aloud. Settle-debounce (not the socket's
  // streaming flag — it never clears): streaming batches reset the timer,
  // speech fires 1.5s after the last batch lands, exactly once per question.
  // Only the QUESTION is spoken: the mandatory "Score: …" line is stripped and
  // the final report is skipped entirely (spokenText), so voice mode stops
  // narrating the score and the full report after every round.
  useEffect(() => {
    if (!isVoice) return;
    const q = textSocket.currentQuestion;
    if (!q || q === lastSpokenRef.current) return;
    const t = window.setTimeout(() => {
      if (latestQuestionRef.current === q && lastSpokenRef.current !== q) {
        lastSpokenRef.current = q;
        const spoken = spokenText(q);
        if (spoken) turnVoice.speak(spoken);
      }
    }, 1500);
    return () => window.clearTimeout(t);
  }, [isVoice, textSocket.currentQuestion, turnVoice]);

  // Text-mode orb energy: the socket's streaming flag never clears, so derive
  // it here — energetic while token batches land, calm 1.5s after they stop
  // (same settle behavior as voice mode's speech states).
  useEffect(() => {
    if (isVoice) return;
    const q = textSocket.currentQuestion;
    if (q && q !== lastQRef.current) {
      lastQRef.current = q;
      setTextSpeaking(true);
    }
    const t = window.setTimeout(() => setTextSpeaking(false), 1500);
    return () => window.clearTimeout(t);
  }, [isVoice, textSocket.currentQuestion]);

  // Active status based on mode
  const activeStatus = textSocket.status;
  const activeErrorMessage = isVoice
    ? turnVoice.error || textSocket.errorMessage
    : textSocket.errorMessage;
  const isConnected = activeStatus === "connected";
  const isConnecting = activeStatus === "connecting" || activeStatus === "reconnecting";

  const displayIndex = Math.min(textSocket.history.length + 1, totalRounds);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!answerInput.trim() || !isConnected) return;

    const sent = textSocket.sendAnswer(answerInput);
    if (sent) {
      setAnswerInput("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSwitchToText = () => {
    turnVoice.cancelSpeech();
    setIsVoice(false);
    router.push(`/stage/${sessionId}?n=${totalRounds}`);
  };

  if (gateUser === undefined) {
    return (
      <div className="w-full max-w-7xl mx-auto px-4 py-6 space-y-4 animate-pulse">
        <div className="h-16 bg-zinc-200 dark:bg-zinc-800 rounded-xl" />
        <div className="h-48 bg-zinc-200 dark:bg-zinc-800 rounded-xl" />
      </div>
    );
  }
  if (gateUser === null) return <LoginGate />;

  return (
    <div className="w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 flex flex-col gap-6">
      {/* Error / Reconnect Banner */}
      {(activeStatus === "disconnected" || activeStatus === "error" || activeErrorMessage) && (
        <div className="p-3.5 rounded-lg border border-rose-500/30 bg-rose-500/10 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs text-rose-500 dark:text-rose-400">
          <div className="flex items-center gap-2">
            <WarningCircle size={18} weight="fill" className="shrink-0" />
            <span className="font-medium">
              {activeErrorMessage ||
                (activeStatus === "reconnecting"
                  ? "Reconnecting to interview server..."
                  : "WebSocket disconnected from backend.")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {isVoice && (
              <button
                type="button"
                onClick={handleSwitchToText}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200/80 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 font-semibold transition-colors border border-zinc-200 dark:border-white/10"
              >
                <ChatText size={13} weight="bold" />
                <span>Switch to text</span>
              </button>
            )}
            <button
              type="button"
              onClick={textSocket.retryConnection}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-600 dark:text-rose-300 font-semibold transition-colors"
            >
              <ArrowClockwise size={13} weight="bold" />
              <span>Retry</span>
            </button>
          </div>
        </div>
      )}

      {/* Stage Header */}
      <div className={`p-4 sm:p-5 ${TOKENS.radius.card} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900/60 shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4`}>
        {/* Left: VoiceOrb avatar slot + Persona info */}
        <div className="flex items-center gap-3.5">
          <VoiceOrb
            size={56}
            state={isVoice ? turnVoice.orbState : undefined}
            isActive={isConnected}
            isSpeaking={isVoice ? turnVoice.orbState === "speaking" : textSpeaking}
            motion={isVoice ? "live" : "static"}
          />
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm sm:text-base font-bold text-zinc-900 dark:text-zinc-100">
                Technical Interviewer
              </h2>
              <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-white/10">
                {sessionId}
              </span>
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                {isVoice ? "Voice Round" : "Live Text Session"}
              </p>
              <span className="inline-flex items-center gap-1 text-[11px] font-mono text-zinc-400">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    isConnected
                      ? "bg-emerald-500"
                      : isConnecting
                      ? "bg-amber-500 animate-pulse"
                      : "bg-rose-500"
                  }`}
                />
                <span className="capitalize">{activeStatus}</span>
              </span>
            </div>
          </div>
        </div>

        {/* Right: Progress Ring + Timer + End CTA */}
        <div className="flex items-center gap-3 w-full sm:w-auto justify-between sm:justify-end">
          <div className="flex items-center gap-3">
            <ProgressRing current={displayIndex} total={totalRounds} size={42} />
            <Timer isRunning={isConnected} />
          </div>

          <button
            type="button"
            onClick={textSocket.endInterview}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 ${TOKENS.radius.button} border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-800/80 hover:bg-rose-500/10 hover:border-rose-500/30 hover:text-rose-500 text-zinc-700 dark:text-zinc-300 text-xs font-medium transition-all duration-150 active:scale-[0.98]`}
            >
              <StopCircle size={15} weight="regular" />
              <span className="hidden sm:inline">End interview</span>
            </button>
        </div>
      </div>

      {/* Main Two-Column Stage Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start flex-1">
        {/* Left: Question Card + Voice Live Card + Score Reveal + Answer Input (8 cols) */}
        <div className="lg:col-span-8 space-y-4 flex flex-col">
          {/* Voice status card + ALWAYS the question card: speech is an
          enhancement, the question must be readable even if playback is
          blocked or unavailable. */}
          {isVoice ? (
            <>
            <div className={`p-6 ${TOKENS.radius.card} border border-emerald-500/30 bg-emerald-500/10 dark:bg-emerald-500/10 shadow-sm space-y-4`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                    Voice Round
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs font-mono text-emerald-400">
                  {turnVoice.orbState === "speaking" ? (
                    <span className="flex items-center gap-1.5">
                      <SpeakerHigh size={15} weight="bold" className="animate-pulse" />
                      <span>Interviewer Speaking</span>
                    </span>
                  ) : turnVoice.listening ? (
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
                      <span>Listening for answer...</span>
                    </span>
                  ) : (
                    <span className="text-zinc-500 dark:text-zinc-400">Mic off — tap to answer</span>
                  )}
                </div>
              </div>

              <div className="py-2">
                <p className="text-sm sm:text-base text-zinc-800 dark:text-zinc-200 leading-relaxed font-medium">
                  Questions are read aloud. Tap the mic, answer at your pace, then submit —
                  every answer is scored exactly like a text round.
                </p>
                {turnVoice.listening && turnVoice.interim && (
                  <p className="mt-2 text-sm text-zinc-400 italic">“{turnVoice.interim}”</p>
                )}
              </div>

              {/* VoicePill mic control lives in the answer row (see form footer):
              tap to answer, tap to finish, slide left to discard */}

              <div className="pt-2 border-t border-emerald-500/20 flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400 font-mono">
                <span>Voice: browser speech in/out · Scoring: text socket</span>
                <button
                  type="button"
                  onClick={handleSwitchToText}
                  className="text-emerald-400 hover:underline hover:text-emerald-300"
                >
                  Switch to Text Mode →
                </button>
              </div>
            </div>
            <QuestionCard
              question={shownQuestion}
              turnIndex={displayIndex}
              totalQuestions={totalRounds}
              isStreaming={textSocket.isStreamingQuestion || isConnecting}
              onReplay={() => {
                const spoken = spokenText(textSocket.currentQuestion);
                if (spoken) turnVoice.speak(spoken, false);
              }}
            />
            </>
          ) : (
            <QuestionCard
              question={shownQuestion}
              turnIndex={displayIndex}
              totalQuestions={totalRounds}
              isStreaming={textSocket.isStreamingQuestion || isConnecting}
            />
          )}

          {/* Transcript Pane for Voice Mode */}
          {isVoice && (
            <LiveTranscriptPane
              transcripts={turnVoice.transcripts}
              voiceOrbState={turnVoice.orbState}
            />
          )}

          {/* Slide-in Score Reveal */}
          <ScoreReveal
            score={textSocket.currentScore}
            turnIndex={Math.max(textSocket.history.length, 1)}
          />

          {/* Answer Input Box (Available in text mode and as backup in voice mode) */}
          <form
            onSubmit={handleSubmit}
            className={`p-4 ${TOKENS.radius.card} border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900/60 shadow-sm space-y-3`}
          >
            <div className="flex items-center justify-between">
              <label
                htmlFor="answer-textarea"
                className="text-xs font-mono uppercase tracking-wider text-zinc-500 dark:text-zinc-400"
              >
                {isVoice ? "Type Answer (Optional Backup)" : "Your Answer"}
              </label>
              <span className="text-[11px] font-mono text-zinc-400 dark:text-zinc-500">
                {answerInput.length} chars
              </span>
            </div>

            <textarea
              id="answer-textarea"
              rows={isVoice ? 2 : 4}
              value={answerInput}
              onChange={(e) => setAnswerInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={!isConnected}
              placeholder={
                isVoice
                  ? "Tap the mic and speak, or type here..."
                  : isConnected
                  ? "Formulate your technical answer here. Be specific about trade-offs, complexity, and system design choices..."
                  : "Connecting to interviewer agent..."
              }
              className={`w-full p-3 text-xs sm:text-sm text-zinc-900 dark:text-zinc-100 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 ${TOKENS.radius.input} focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 placeholder:text-zinc-400 dark:placeholder:text-zinc-600 resize-none disabled:opacity-50`}
            />

            <div className="flex items-center justify-between gap-3 pt-1">
              <span className="hidden sm:inline-block text-[11px] font-mono text-zinc-400 dark:text-zinc-500">
                Press <kbd className="px-1 py-0.5 rounded bg-zinc-200 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700">Cmd/Ctrl + Enter</kbd> to submit
              </span>

              <div className="ml-auto flex items-center gap-2.5">
                {isVoice && (
                  <>
                    {!turnVoice.listening && (
                      <span className="text-[11px] font-mono text-zinc-500 dark:text-zinc-400 whitespace-nowrap">
                        Dictate
                      </span>
                    )}
                    <VoicePill
                      size={36}
                      accentColor="#34d399"
                      iconColor="#a1a1aa"
                      background="rgba(16,185,129,0.14)"
                      reactive="simulated"
                      slideToCancel={true}
                      ariaLabel={turnVoice.listening ? "Finish answer" : "Dictate answer"}
                      onStart={() => turnVoice.startListening()}
                      onStop={({ reason }) => {
                        if (reason === "cancel") turnVoice.cancelListening();
                        else turnVoice.stopListening();
                      }}
                    />
                  </>
                )}

              <button
                type="submit"
                disabled={!isConnected || !answerInput.trim()}
                className={`inline-flex items-center justify-center gap-1.5 px-5 py-2 ${TOKENS.radius.button} bg-emerald-500 hover:bg-emerald-600 text-zinc-950 font-semibold text-xs transition-all duration-150 active:scale-[0.98] shadow-sm hover:shadow-emerald-500/20 disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50`}
              >
                <span>Submit answer</span>
                <PaperPlaneRight size={14} weight="bold" />
              </button>
              </div>
            </div>
          </form>
        </div>

        {/* Right: Round History Rail (4 cols) */}
        <div className="lg:col-span-4">
          <HistoryRail history={textSocket.history} />
        </div>
      </div>
    </div>
  );
}
