"use client";

import { useEffect, useRef, useState, useCallback } from "react";

export interface TurnHistory {
  qIndex: number;
  question: string;
  answer: string;
  score?: number;
}

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error" | "reconnecting";

interface UseInterviewSocketOptions {
  sessionId: string;
  onSessionEnd?: () => void;
  // False = never connect (the other mode owns the session). Both hooks mount
  // on the stage page — without this gate the voice socket speaks in text mode.
  enabled?: boolean;
}

export function useInterviewSocket({ sessionId, onSessionEnd, enabled = true }: UseInterviewSocketOptions) {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [currentQuestion, setCurrentQuestion] = useState<string>("");
  const [isStreamingQuestion, setIsStreamingQuestion] = useState<boolean>(true);
  const [currentScore, setCurrentScore] = useState<number | null>(null);
  const [history, setHistory] = useState<TurnHistory[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [currentTurnIndex, setCurrentTurnIndex] = useState<number>(1);

  // References for lifecycle management
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isExplicitlyClosedRef = useRef<boolean>(false);

  // Token batching buffer to eliminate render storms
  const tokenBufferRef = useRef<string>("");
  const flushTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Derive WebSocket URL from NEXT_PUBLIC_API_URL or default to localhost:8000
  const getWsUrl = useCallback(() => {
    const httpBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const wsBase = httpBase.replace(/^http/, "ws");
    return `${wsBase}/ws/${sessionId}`;
  }, [sessionId]);

  // Flush accumulated tokens to React state in batches (50ms)
  const flushTokens = useCallback(() => {
    if (tokenBufferRef.current) {
      const bufferedText = tokenBufferRef.current;
      tokenBufferRef.current = "";
      setCurrentQuestion((prev) => prev + bufferedText);
    }
  }, []);

  const scheduleFlush = useCallback(() => {
    if (!flushTimerRef.current) {
      flushTimerRef.current = setTimeout(() => {
        flushTokens();
        flushTimerRef.current = null;
      }, 50);
    }
  }, [flushTokens]);

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
      } catch {
        // ignore
      }
      wsRef.current = null;
    }

    try {
      setStatus(reconnectAttemptsRef.current > 0 ? "reconnecting" : "connecting");
      setErrorMessage(null);

      const ws = new WebSocket(getWsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        // Guard against stale socket instances
        if (wsRef.current !== ws) return;

        setStatus("connected");
        setErrorMessage(null);
        reconnectAttemptsRef.current = 0;
        // Identify to the backend (no-op when logged out): the server
        // verifies the token against the POST uid, then continues normally.
        // Fire-and-forget — Q1 streaming never waits for this.
        import("@/lib/firebase")
          .then(({ getIdToken }) => getIdToken())
          .then((token) => {
            if (token && wsRef.current === ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ token }));
            }
          })
          .catch(() => {
            // ignore — anonymous interview proceeds as before
          });
      };

      ws.onmessage = (event) => {
        if (wsRef.current !== ws) return;

        try {
          const data = JSON.parse(event.data);

          if (data.type === "question") {
            // Reconnect resync: REPLACE the on-screen question with the last
            // turn's text. A fresh page load has no local buffer, and appending
            // would show the question twice.
            tokenBufferRef.current = "";
            setCurrentQuestion(data.text || "");
            setIsStreamingQuestion(false);
          } else if (data.type === "token") {
            setIsStreamingQuestion(true);
            tokenBufferRef.current += data.text || "";
            scheduleFlush();
          } else if (data.type === "score") {
            // Flush any remaining tokens before applying score
            flushTokens();
            const scoreVal = typeof data.value === "number" ? data.value : parseFloat(data.value);
            setCurrentScore(scoreVal);

            // Record turn score into history
            setHistory((prev) => {
              const updated = [...prev];
              const lastIdx = updated.length - 1;
              if (lastIdx >= 0) {
                updated[lastIdx] = {
                  ...updated[lastIdx],
                  score: scoreVal,
                };
              }
              return updated;
            });
          } else if (data.type === "report") {
            // Final report signal (backend currently reports via REST; kept for forward-compat)
            flushTokens();
            if (onSessionEnd) {
              onSessionEnd();
            }
          } else if (data.type === "error") {
            setErrorMessage(data.message || "An error occurred during the session.");
          }
        } catch (e) {
          console.error("Failed to parse WebSocket message:", event.data, e);
        }
      };

      ws.onclose = () => {
        // Stale socket guard: ignore close events from previously discarded sockets
        if (wsRef.current !== ws) return;

        // Flush any buffered tokens before disconnecting
        flushTokens();

        if (isExplicitlyClosedRef.current) {
          setStatus("disconnected");
          return;
        }

        setStatus("disconnected");

        // Exponential backoff reconnection
        if (reconnectAttemptsRef.current < 5) {
          const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 8000);
          reconnectAttemptsRef.current += 1;
          setStatus("reconnecting");
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else {
          setStatus("error");
          setErrorMessage("WebSocket connection dropped. Please retry to resume.");
        }
      };

      ws.onerror = () => {
        if (wsRef.current !== ws) return;
        // Let onclose handle the reconnection logic
      };
    } catch (err) {
      console.error("WebSocket initialization error:", err);
      setStatus("error");
      setErrorMessage("Could not initialize WebSocket connection.");
    }
  }, [sessionId, getWsUrl, onSessionEnd, scheduleFlush, flushTokens]);

  useEffect(() => {
    if (!enabled) return;
    isExplicitlyClosedRef.current = false;
    // Defer the connect by a tick. React StrictMode (dev) mounts -> unmounts ->
    // mounts, so a SYNCHRONOUS connect() here leaves a throwaway socket whose
    // handler the backend accepts and drives a full start turn for — i.e. two
    // Q1 generation rounds and two set-up messages per page load. That doubled
    // request burst is the main reason 503s appear locally on the frontend but
    // not in `adk web`. Deferring lets the first cleanup cancel it: one socket.
    const connectTimer = setTimeout(() => connect(), 0);

    return () => {
      clearTimeout(connectTimer);
      // Clear timers
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
      }

      // Detach listeners and close cleanly
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

  // Send answer
  const sendAnswer = useCallback(
    (answerText: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        setErrorMessage("Cannot send answer: WebSocket is not connected.");
        return false;
      }

      if (!answerText.trim()) return false;

      // Capture the full question INCLUDING not-yet-flushed buffer (flushTokens
      // commits async; the closure value alone would drop the last ~50ms).
      const fullQuestion = tokenBufferRef.current + currentQuestion;
      flushTokens();
      setHistory((prev) => [
        ...prev,
        {
          qIndex: currentTurnIndex,
          question: fullQuestion,
          answer: answerText,
        },
      ]);

      tokenBufferRef.current = "";
      setCurrentQuestion("");
      setCurrentScore(null);
      setIsStreamingQuestion(true);
      setCurrentTurnIndex((prev) => prev + 1);

      wsRef.current.send(JSON.stringify({ text: answerText }));
      return true;
    },
    [currentTurnIndex, currentQuestion, flushTokens]
  );

  // End interview: {"end": true}
  const endInterview = useCallback(() => {
    isExplicitlyClosedRef.current = true;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ end: true }));
    }
    if (onSessionEnd) {
      onSessionEnd();
    }
  }, [onSessionEnd]);

  const retryConnection = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    connect();
  }, [connect]);

  return {
    status,
    currentQuestion,
    isStreamingQuestion,
    currentScore,
    history,
    currentTurnIndex,
    errorMessage,
    sendAnswer,
    endInterview,
    retryConnection,
  };
}
