"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface TurnTranscript {
  id: string;
  sender: "candidate" | "interviewer";
  text: string;
  timestamp: Date;
  lastUpdated?: number;
}

// Minimal Web Speech API typings (lib.dom lacks them; Chrome/Edge implement).
interface SpeechRecognitionResult {
  isFinal: boolean;
  [index: number]: { transcript: string };
}
interface SpeechRecognitionEvent extends Event {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResult> & { length: number };
}
interface SpeechRecognitionInstance extends EventTarget {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  continuous: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: SpeechRecognitionEvent) => void) | null;
  onerror: ((e: Event & { error?: string }) => void) | null;
  onend: (() => void) | null;
}

function getRecognitionCtor(): (new () => SpeechRecognitionInstance) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, unknown>;
  return (w.SpeechRecognition || w.webkitSpeechRecognition || null) as (
    new () => SpeechRecognitionInstance
  ) | null;
}

function pickMaleVoice(): SpeechSynthesisVoice | null {
  if (typeof window === "undefined" || !window.speechSynthesis) return null;
  const voices = window.speechSynthesis.getVoices();
  if (voices.length === 0) return null;
  const en = voices.filter((v) => v.lang.toLowerCase().startsWith("en"));
  const pool = en.length > 0 ? en : voices;
  const maleHints = ["male", "david", "daniel", "james", "george", "fred", "alex", "brian"];
  for (const hint of maleHints) {
    const found = pool.find((v) => v.name.toLowerCase().includes(hint));
    if (found) return found;
  }
  return pool.find((v) => v.lang.toLowerCase() === "en-us") || pool[0] || null;
}

// Chrome stalls utterances past ~15s: split into sentence-sized chunks.
function chunkForSpeech(text: string, maxLen = 180): string[] {
  const sentences = text.match(/[^.!?]+[.!?]+["']?\s*|[^.!?]+$/g) || [text];
  const chunks: string[] = [];
  let current = "";
  for (const s of sentences) {
    const piece = s.trim();
    if (!piece) continue;
    if ((current + " " + piece).trim().length > maxLen && current) {
      chunks.push(current.trim());
      current = piece;
    } else {
      current = (current + " " + piece).trim();
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks.length > 0 ? chunks : [text];
}

interface UseTurnVoiceOptions {
  enabled?: boolean;
  // Fired once per completed spoken answer (final transcript).
  onFinalAnswer?: (text: string) => void;
}

export function useTurnVoice({ enabled = true, onFinalAnswer }: UseTurnVoiceOptions) {
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [interim, setInterim] = useState("");
  const [transcripts, setTranscripts] = useState<TurnTranscript[]>([]);
  const [micBlocked, setMicBlocked] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const finalRef = useRef("");
  // True from mic-tap-on until mic-tap-off: recognition auto-restarts across
  // silence pauses, so thinking pauses NEVER split an answer. Finalizing
  // happens ONLY on explicit tap-off.
  const wantListeningRef = useRef(false);
  // Set when the user discards an answer (pill slide-cancel): onend must NOT
  // finalize anything into the box or transcript.
  const discardRef = useRef(false);
  // Text that was asked to be spoken but never started (autoplay block before
  // first user gesture). Replayed on first pointer/key interaction, silently.
  const pendingSpeechRef = useRef<string | null>(null);
  const onFinalRef = useRef(onFinalAnswer);
  onFinalRef.current = onFinalAnswer;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const utterQueueRef = useRef<SpeechSynthesisUtterance[]>([]);

  const sttSupported = getRecognitionCtor() !== null;
  const ttsSupported =
    typeof window !== "undefined" && "speechSynthesis" in window;

  const pushEntry = useCallback((sender: TurnTranscript["sender"], text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const now = Date.now();
    setTranscripts((prev) => [
      ...prev,
      {
        id: `tv-${now}-${Math.random().toString(36).slice(2, 6)}`,
        sender,
        text: trimmed,
        timestamp: new Date(now),
        lastUpdated: now,
      },
    ]);
  }, []);

  const cancelSpeech = useCallback(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    utterQueueRef.current = [];
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  // Warm the voice list on mount: Chrome loads voices asynchronously and
  // getVoices() returns [] on first call, leaving utterances voiceless.
  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    const warm = () => window.speechSynthesis.getVoices();
    warm();
    window.speechSynthesis.addEventListener("voiceschanged", warm);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", warm);
  }, []);

  const speak = useCallback(
    (text: string, appendTranscript = true) => {
      if (!enabledRef.current) return;
      if (typeof window === "undefined" || !window.speechSynthesis) {
        setError("Speech playback not supported in this browser.");
        return;
      }
      const trimmed = text.trim();
      if (!trimmed) return;
      if (appendTranscript) pushEntry("interviewer", trimmed);
      pendingSpeechRef.current = trimmed;
      const synth = window.speechSynthesis;
      const start = () => {
        try {
          utterQueueRef.current = [];
          const chunks = chunkForSpeech(trimmed);
          chunks.forEach((chunk, i) => {
            const utter = new SpeechSynthesisUtterance(chunk);
            const voice = pickMaleVoice();
            if (voice) utter.voice = voice;
            utter.rate = 1;
            if (i === 0) {
              utter.onstart = () => {
                pendingSpeechRef.current = null;
                setSpeaking(true);
              };
            }
            if (i === chunks.length - 1) {
              utter.onend = () => setSpeaking(false);
              utter.onerror = () => setSpeaking(false);
            }
            utterQueueRef.current.push(utter);
            synth.speak(utter);
          });
        } catch {
          setError("Speech playback failed.");
          setSpeaking(false);
        }
      };
      // Chrome bug: cancel() in the same tick eats a following speak().
      // Only cancel when something is actually playing, then yield a tick.
      if (synth.speaking || synth.pending) {
        synth.cancel();
        setSpeaking(false);
        window.setTimeout(() => {
          if (enabledRef.current) start();
        }, 120);
      } else {
        start();
      }
    },
    [pushEntry]
  );

  // Autoplay unlock: speech before the first page gesture is dropped silently
  // by the browser. First interaction replays the pending question, no duplicate
  // transcript entry (it was logged on the original call).
  useEffect(() => {
    const unlock = () => {
      if (pendingSpeechRef.current) {
        const t = pendingSpeechRef.current;
        pendingSpeechRef.current = null;
        speak(t, false);
      }
    };
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, [speak]);

  // One recognition instance. With continuous=true Chrome still ends the
  // session on long silence — onend restarts silently while the user still
  // wants the mic (wantListeningRef), so pauses never end anything.
  const startRecognition = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    try {
      recognitionRef.current?.abort();
    } catch {
      // ignore
    }
    try {
      const rec = new Ctor();
      rec.lang = "en-US";
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      rec.continuous = true;
      rec.onresult = (e) => {
        let interimText = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const res = e.results[i];
          const alt = res[0]?.transcript || "";
          if (res.isFinal) finalRef.current = (finalRef.current + " " + alt).trim();
          else interimText += alt;
        }
        setInterim(interimText);
      };
      rec.onerror = (e) => {
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          wantListeningRef.current = false;
          setListening(false);
          setMicBlocked(true);
          setError("Microphone blocked — allow mic access or type your answer.");
        } else if (e.error !== "aborted" && !wantListeningRef.current) {
          setListening(false);
        }
        // "no-speech" and network blips: onend below restarts when still wanted.
      };
      rec.onend = () => {
        if (wantListeningRef.current && enabledRef.current) {
          // Silence pause — restart quietly, keep accumulating into ONE answer.
          window.setTimeout(() => {
            if (wantListeningRef.current && enabledRef.current) startRecognition();
          }, 150);
        } else {
          // Explicit tap-off: finalize the single accumulated answer —
          // unless it was a discard (slide-cancel).
          setListening(false);
          setInterim("");
          if (discardRef.current) {
            discardRef.current = false;
            finalRef.current = "";
            return;
          }
          const final = finalRef.current.trim();
          if (final) {
            pushEntry("candidate", final);
            onFinalRef.current?.(final);
          }
        }
      };
      recognitionRef.current = rec;
      rec.start();
    } catch {
      if (wantListeningRef.current) {
        setError("Could not start the microphone.");
        setListening(false);
      }
    }
  }, [pushEntry]);

  // Mic tap-on: stays open across pauses until YOU tap off. Interrupts any
  // agent speech first (no talking over each other).
  const startListening = useCallback(() => {
    if (!enabledRef.current) return;
    if (!getRecognitionCtor()) {
      setMicBlocked(true);
      setError("Speech recognition not supported — use Chrome/Edge or type your answer.");
      return;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
    }
    discardRef.current = false;
    wantListeningRef.current = true;
    finalRef.current = "";
    setInterim("");
    setError(null);
    setMicBlocked(false);
    setListening(true);
    startRecognition();
  }, [startRecognition]);

  // Mic tap-off: the ONLY thing that finalizes the answer (single bubble).
  const stopListening = useCallback(() => {
    wantListeningRef.current = false;
    discardRef.current = false;
    try {
      recognitionRef.current?.stop();
    } catch {
      setListening(false);
    }
  }, []);

  // Slide-cancel / discard: stop the mic and throw the take away.
  const cancelListening = useCallback(() => {
    discardRef.current = true;
    wantListeningRef.current = false;
    try {
      recognitionRef.current?.stop();
    } catch {
      setListening(false);
      setInterim("");
    }
  }, []);

  const toggleMic = useCallback(() => {
    if (listening) stopListening();
    else startListening();
  }, [listening, startListening, stopListening]);

  // Teardown: never hold mic or speech after unmount/disable.
  useEffect(() => {
    if (!enabled) {
      wantListeningRef.current = false;
      try {
        recognitionRef.current?.abort();
      } catch {
        // ignore
      }
      if (typeof window !== "undefined" && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
      setListening(false);
      setSpeaking(false);
    }
    return () => {
      try {
        recognitionRef.current?.abort();
      } catch {
        // ignore
      }
      if (typeof window !== "undefined" && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
    };
  }, [enabled]);

  const orbState: "idle" | "listening" | "speaking" = speaking
    ? "speaking"
    : listening
    ? "listening"
    : "idle";

  return {
    listening,
    speaking,
    interim,
    transcripts,
    micBlocked,
    error,
    sttSupported,
    ttsSupported,
    orbState,
    startListening,
    stopListening,
    cancelListening,
    toggleMic,
    speak,
    cancelSpeech,
  };
}
