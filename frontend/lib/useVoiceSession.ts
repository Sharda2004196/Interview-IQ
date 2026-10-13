"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import {
  useVoiceSocket,
  type AudioReadyConfig,
  type VoiceConnectionStatus,
} from "@/lib/useVoiceSocket";

export type VoiceOrbState = "idle" | "listening" | "speaking";

export interface TranscriptEntry {
  id: string;
  sender: "candidate" | "interviewer";
  text: string;
  timestamp: Date;
  lastUpdated?: number;
}

interface UseVoiceSessionOptions {
  sessionId: string;
  onSessionEnd?: () => void;
  // False = text mode: no socket, no mic, no audio — ever.
  enabled?: boolean;
}

export function useVoiceSession({ sessionId, onSessionEnd, enabled = true }: UseVoiceSessionOptions) {
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [micBlocked, setMicBlocked] = useState<boolean>(false);
  const [isAudioReady, setIsAudioReady] = useState<boolean>(false);
  const [voiceOrbState, setVoiceOrbState] = useState<VoiceOrbState>("idle");
  // Server turn phase ("evaluating" while the brain runs) — cleared when speech
  // resumes or a new answer starts, so it can never stick on screen.
  const [turnPhase, setTurnPhase] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);

  // Audio Context & Stream Refs
  const micStreamRef = useRef<MediaStream | null>(null);
  const micAudioCtxRef = useRef<AudioContext | null>(null);
  const micProcessorRef = useRef<ScriptProcessorNode | null>(null);

  const playbackAudioCtxRef = useRef<AudioContext | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);

  const isMutedRef = useRef(isMuted);
  isMutedRef.current = isMuted;

  // Handle incoming audio_ready text envelope
  const handleAudioReady = useCallback((config: AudioReadyConfig) => {
    setIsAudioReady(true);
    setSessionError(null);

    // Initialize 24kHz Playback AudioContext
    try {
      if (!playbackAudioCtxRef.current || playbackAudioCtxRef.current.state === "closed") {
        const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const ctx = new AudioCtx({ sampleRate: config.outRate || 24000 });
        playbackAudioCtxRef.current = ctx;
        nextPlayTimeRef.current = ctx.currentTime;
      } else if (playbackAudioCtxRef.current.state === "suspended") {
        playbackAudioCtxRef.current.resume();
      }
    } catch (err) {
      console.error("Failed to initialize playback AudioContext:", err);
    }
  }, []);

  // Handle incoming binary PCM24k chunks from Gemini Live API
  const handleBinaryFrame = useCallback((data: ArrayBuffer) => {
    if (!playbackAudioCtxRef.current) return;
    setTurnPhase(null);

    // Flip VoiceOrb to speaking state
    setVoiceOrbState("speaking");
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
    }
    silenceTimerRef.current = setTimeout(() => {
      setVoiceOrbState(isMutedRef.current ? "idle" : "listening");
    }, 800);

    try {
      const ctx = playbackAudioCtxRef.current;
      if (ctx.state === "suspended") {
        ctx.resume();
      }

      // Convert 16-bit signed PCM (Int16) to 32-bit Float [-1.0, 1.0]
      const int16Array = new Int16Array(data);
      if (int16Array.length === 0) return;

      const float32Array = new Float32Array(int16Array.length);
      for (let i = 0; i < int16Array.length; i++) {
        float32Array[i] = int16Array[i] / 32768.0;
      }

      // Create AudioBuffer @ 24kHz
      const audioBuffer = ctx.createBuffer(1, float32Array.length, 24000);
      audioBuffer.copyToChannel(float32Array, 0);

      // Create BufferSource and schedule gaplessly
      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);

      const currentTime = ctx.currentTime;
      const startTime = Math.max(currentTime, nextPlayTimeRef.current);
      source.start(startTime);
      nextPlayTimeRef.current = startTime + audioBuffer.duration;
    } catch (err) {
      console.error("Error decoding / scheduling playback audio frame:", err);
    }
  }, []);

  // Coalesce incoming transcript fragments per §4c:
  // Consecutive frames from the SAME speaker append into ONE bubble (space-joined);
  // Open a NEW bubble only when the speaker flips or after >3s of silence from that speaker.
  // Timestamps per bubble (first-frame time), never per fragment.
  const handleTranscript = useCallback((sender: "candidate" | "interviewer", text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (sender === "candidate") setTurnPhase(null);

    const nowMs = Date.now();

    setTranscripts((prev) => {
      if (prev.length === 0) {
        return [
          {
            id: `tx-${nowMs}-${Math.random().toString(36).substring(2, 6)}`,
            sender,
            text: trimmed,
            timestamp: new Date(nowMs),
            lastUpdated: nowMs,
          },
        ];
      }

      const lastIndex = prev.length - 1;
      const last = prev[lastIndex];
      const timeSinceLastUpdate = nowMs - (last.lastUpdated ?? last.timestamp.getTime());

      if (last.sender === sender && timeSinceLastUpdate <= 3000) {
        const updatedEntry: TranscriptEntry = {
          ...last,
          text: last.text ? `${last.text} ${trimmed}` : trimmed,
          lastUpdated: nowMs,
        };
        const next = [...prev];
        next[lastIndex] = updatedEntry;
        return next;
      }

      return [
        ...prev,
        {
          id: `tx-${nowMs}-${Math.random().toString(36).substring(2, 6)}`,
          sender,
          text: trimmed,
          timestamp: new Date(nowMs),
          lastUpdated: nowMs,
        },
      ];
    });
  }, []);

  const handleVoiceError = useCallback((msg: string) => {
    setSessionError(msg);
  }, []);

  const handleStatus = useCallback((phase: string) => {
    setTurnPhase(phase);
  }, []);

  // Initialize useVoiceSocket hook
  const {
    status,
    errorMessage: socketError,
    sendBinary,
    sendControl,
    retryConnection,
    disconnect,
  } = useVoiceSocket({
    sessionId,
    onAudioReady: handleAudioReady,
    onBinaryFrame: handleBinaryFrame,
    onTranscript: handleTranscript,
    onStatus: handleStatus,
    onSessionEnd,
    onError: handleVoiceError,
    enabled,
  });

  // Start Mic Capture Pipeline @ 16kHz with mandatory constraints (§4d)
  const startMicCapture = useCallback(async () => {
    if (micStreamRef.current) return;

    try {
      setMicBlocked(false);
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          // Ask the device for 16kHz natively: skips the resampler entirely
          // when honored (Chrome on most hardware does).
          sampleRate: { ideal: 16000 },
          channelCount: { ideal: 1 },
        },
      });
      micStreamRef.current = stream;

      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const micCtx = new AudioCtx();
      micAudioCtxRef.current = micCtx;

      const source = micCtx.createMediaStreamSource(stream);
      // Process input in 4096 sample buffers (or ~100ms)
      const processor = micCtx.createScriptProcessor(4096, 1, 1);
      micProcessorRef.current = processor;

      const inputSampleRate = micCtx.sampleRate;
      const targetSampleRate = 16000;

      processor.onaudioprocess = (e) => {
        if (isMutedRef.current) return;

        const inputData = e.inputBuffer.getChannelData(0);
        let pcmData: Int16Array;

        // Resample down to 16kHz with LINEAR interpolation. (Nearest-neighbor
        // here garbles consonants — the "wrong words" transcription bug.)
        if (inputSampleRate !== targetSampleRate) {
          const ratio = inputSampleRate / targetSampleRate;
          const targetLength = Math.round(inputData.length / ratio);
          pcmData = new Int16Array(targetLength);

          for (let i = 0; i < targetLength; i++) {
            const pos = i * ratio;
            const i0 = Math.floor(pos);
            const i1 = Math.min(i0 + 1, inputData.length - 1);
            const frac = pos - i0;
            const s = Math.max(-1, Math.min(1,
              inputData[i0] * (1 - frac) + inputData[i1] * frac
            ));
            pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }
        } else {
          pcmData = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            const s = Math.max(-1, Math.min(1, inputData[i]));
            pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }
        }

        sendBinary(pcmData.buffer as ArrayBuffer);
      };

      source.connect(processor);
      processor.connect(micCtx.destination);
      setVoiceOrbState(isMutedRef.current ? "idle" : "listening");
    } catch (err) {
      console.warn("Microphone access denied or failed:", err);
      setMicBlocked(true);
      setSessionError("Microphone blocked — use text mode.");
      setVoiceOrbState("idle");
    }
  }, [sendBinary]);

  // Stop Mic Capture Pipeline
  const stopMicCapture = useCallback(() => {
    if (micProcessorRef.current) {
      try {
        micProcessorRef.current.disconnect();
      } catch (e) {
        // ignore
      }
      micProcessorRef.current = null;
    }

    if (micAudioCtxRef.current) {
      try {
        micAudioCtxRef.current.close();
      } catch (e) {
        // ignore
      }
      micAudioCtxRef.current = null;
    }

    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach((t) => t.stop());
      micStreamRef.current = null;
    }
  }, []);

  // Cleanup on unmount — including the SOCKET: without disconnect() a
  // navigated-away page keeps its audio session alive server-side (and keeps
  // speaking if still mounted in a background tab).
  useEffect(() => {
    if (!enabled) return;
    startMicCapture();

    return () => {
      disconnect();
      stopMicCapture();

      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
      }

      if (playbackAudioCtxRef.current) {
        try {
          playbackAudioCtxRef.current.close();
        } catch (e) {
          // ignore
        }
        playbackAudioCtxRef.current = null;
      }
    };
  }, [startMicCapture, stopMicCapture, disconnect, enabled]);

  // Toggle Mute — muting MEANS "my answer is complete": tell the server to fire
  // its single Runner turn now (deterministic end-of-answer, no timeout guess).
  const toggleMute = useCallback(() => {
    setIsMuted((prev) => {
      const next = !prev;
      if (next) {
        sendControl({ type: "answer_done" });
        setVoiceOrbState("idle");
      } else {
        setVoiceOrbState("listening");
      }
      return next;
    });
  }, [sendControl]);

  const combinedError = sessionError || socketError || (micBlocked ? "Microphone blocked — use text mode." : null);

  return {
    status: (status as VoiceConnectionStatus),
    isMuted,
    isAudioReady,
    voiceOrbState,
    turnPhase,
    transcripts,
    errorMessage: combinedError,
    toggleMute,
    retryConnection,
    disconnect,
  };
}
