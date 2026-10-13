"use client";

import { useEffect, useRef, useState, useCallback } from "react";

export type VoiceConnectionStatus =
  | "connecting"
  | "connected"
  | "disconnected"
  | "error"
  | "reconnecting";

export interface AudioReadyConfig {
  inRate: number;
  outRate: number;
}

interface UseVoiceSocketOptions {
  sessionId: string;
  onAudioReady?: (config: AudioReadyConfig) => void;
  onBinaryFrame?: (data: ArrayBuffer) => void;
  onTranscript?: (sender: "candidate" | "interviewer", text: string) => void;
  onStatus?: (phase: string) => void;
  onSessionEnd?: () => void;
  onError?: (message: string) => void;
  // False = never connect (text mode owns the session — no mic, no voice).
  enabled?: boolean;
}

export function useVoiceSocket({
  sessionId,
  onAudioReady,
  onBinaryFrame,
  onTranscript,
  onStatus,
  onSessionEnd,
  onError,
  enabled = true,
}: UseVoiceSocketOptions) {
  const [status, setStatus] = useState<VoiceConnectionStatus>("connecting");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isExplicitlyClosedRef = useRef<boolean>(false);

  // Callbacks refs to avoid stale closures
  const onAudioReadyRef = useRef(onAudioReady);
  onAudioReadyRef.current = onAudioReady;
  const onBinaryFrameRef = useRef(onBinaryFrame);
  onBinaryFrameRef.current = onBinaryFrame;
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;
  const onStatusRef = useRef(onStatus);
  onStatusRef.current = onStatus;
  const onSessionEndRef = useRef(onSessionEnd);
  onSessionEndRef.current = onSessionEnd;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  // Derive WebSocket URL from NEXT_PUBLIC_API_URL or default to localhost:8000
  const getWsUrl = useCallback(() => {
    const httpBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const wsBase = httpBase.replace(/^http/, "ws");
    return `${wsBase}/ws/audio/${sessionId}`;
  }, [sessionId]);

  const connect = useCallback(() => {
    if (!sessionId) return;

    // Clean up any existing socket before opening a new one
    if (wsRef.current) {
      try {
        wsRef.current.onopen = null;
        wsRef.current.onmessage = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.close();
      } catch (e) {
        // ignore
      }
      wsRef.current = null;
    }

    try {
      setStatus(reconnectAttemptsRef.current > 0 ? "reconnecting" : "connecting");
      setErrorMessage(null);

      const ws = new WebSocket(getWsUrl());
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        // Guard against stale socket instances
        if (wsRef.current !== ws) return;

        setStatus("connected");
        setErrorMessage(null);
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = (event) => {
        if (wsRef.current !== ws) return;

        // Binary frame from server: 24kHz PCM reply
        if (event.data instanceof ArrayBuffer) {
          if (onBinaryFrameRef.current) {
            onBinaryFrameRef.current(event.data);
          }
          return;
        }

        // Text frame: JSON control envelopes
        if (typeof event.data === "string") {
          try {
            const data = JSON.parse(event.data);
            if (data.type === "audio_ready") {
              if (onAudioReadyRef.current) {
                onAudioReadyRef.current({
                  inRate: data.in_rate || 16000,
                  outRate: data.out_rate || 24000,
                });
              }
            } else if (data.type === "user_transcript") {
              if (onTranscriptRef.current && data.text) {
                onTranscriptRef.current("candidate", data.text);
              }
            } else if (data.type === "agent_transcript") {
              if (onTranscriptRef.current && data.text) {
                onTranscriptRef.current("interviewer", data.text);
              }
            } else if (data.type === "status") {
              if (onStatusRef.current && data.phase) {
                onStatusRef.current(data.phase);
              }
            } else if (data.type === "report") {
              if (onSessionEndRef.current) {
                onSessionEndRef.current();
              }
            } else if (data.type === "error") {
              const msg = data.message || "Voice session error.";
              setErrorMessage(msg);
              if (onErrorRef.current) {
                onErrorRef.current(msg);
              }
            }
          } catch (e) {
            console.error("Failed to parse voice text message:", event.data, e);
          }
        }
      };

      ws.onclose = () => {
        if (wsRef.current !== ws) return;

        if (isExplicitlyClosedRef.current) {
          setStatus("disconnected");
          return;
        }

        setStatus("disconnected");

        // Exponential backoff reconnection up to 5 attempts
        if (reconnectAttemptsRef.current < 5) {
          const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 8000);
          reconnectAttemptsRef.current += 1;
          setStatus("reconnecting");
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else {
          setStatus("error");
          setErrorMessage("Live voice connection dropped. Please retry or switch to text mode.");
        }
      };

      ws.onerror = () => {
        if (wsRef.current !== ws) return;
        // Let onclose handle reconnect logic
      };
    } catch (err) {
      console.error("Voice WebSocket initialization error:", err);
      setStatus("error");
      setErrorMessage("Could not initialize voice WebSocket connection.");
    }
  }, [sessionId, getWsUrl]);

  useEffect(() => {
    if (!enabled) return;
    isExplicitlyClosedRef.current = false;
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        const socket = wsRef.current;
        wsRef.current = null;
        socket.onopen = null;
        socket.onmessage = null;
        socket.onclose = null;
        socket.onerror = null;
        socket.close();
      }
    };
  }, [connect, enabled]);

  // Send binary audio frames to server (16kHz PCM16)
  const sendBinary = useCallback((data: ArrayBuffer | Uint8Array | ArrayBufferLike) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
      return true;
    }
    return false;
  }, []);

  // Send a JSON control frame (e.g. {"type":"answer_done"} = answer complete).
  const sendControl = useCallback((obj: Record<string, unknown>) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(obj));
      return true;
    }
    return false;
  }, []);

  const retryConnection = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    connect();
  }, [connect]);

  const disconnect = useCallback(() => {
    isExplicitlyClosedRef.current = true;
    if (wsRef.current) {
      wsRef.current.close();
    }
  }, []);

  return {
    status,
    errorMessage,
    sendBinary,
    sendControl,
    retryConnection,
    disconnect,
  };
}
