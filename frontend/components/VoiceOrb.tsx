"use client";

import React from "react";
import Orb from "@/components/bits/Orb";
import { TOKENS } from "@/lib/tokens";

export type VoiceOrbState = "idle" | "listening" | "speaking";

export interface VoiceOrbProps {
  size?: number;
  state?: VoiceOrbState;
  isActive?: boolean;
  isSpeaking?: boolean;
  className?: string;
  // "live": full motion (voice mode). "static": frozen ring + slow rotation,
  // no morphing ever (text mode — presence without competing with reading).
  motion?: "live" | "static";
}

// Emerald hue for the WebGL orb (matches the emerald accent system).
const EMERALD_HUE = 70;

export function VoiceOrb({
  size = 64,
  state,
  isActive = true,
  isSpeaking = false,
  className = "",
  motion = "live",
}: VoiceOrbProps) {
  // Infer normalized state (unchanged contract — all callers keep working).
  const effectiveState: VoiceOrbState =
    state || (isSpeaking ? "speaking" : isActive ? "listening" : "idle");

  const isIdle = effectiveState === "idle";
  const isListening = effectiveState === "listening";
  const isSpeech = effectiveState === "speaking";

  return (
    <div
      style={{ width: size, height: size }}
      className={`relative ${TOKENS.radius.orb} shrink-0 overflow-hidden bg-zinc-200 dark:bg-zinc-950 border border-zinc-300 dark:border-white/15 shadow-sm select-none ${className}`}
      aria-label={`Interviewer status: ${effectiveState}`}
    >
      {/* ReactBits Orb: live motion follows state in voice mode; text mode
          holds one frozen frame with a slow rotation, permanently. */}
      <div className={`absolute inset-0 ${isIdle ? "opacity-60 saturate-50" : "opacity-100"}`}>
        <Orb
          hue={EMERALD_HUE}
          hoverIntensity={motion === "static" ? 0 : isSpeech ? 0.9 : 0.35}
          rotateOnHover={true}
          forceHoverState={motion === "static" ? false : !isIdle}
          backgroundColor="#09090b"
          frozen={motion === "static"}
        />
      </div>

      {/* Status indicator dot (kept from the previous design language) */}
      <div className="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-white dark:bg-zinc-950 border-2 border-zinc-300 dark:border-zinc-900 flex items-center justify-center">
        <span
          className={`w-2 h-2 rounded-full transition-colors duration-200 ${
            isSpeech
              ? "bg-emerald-400 animate-pulse"
              : !isIdle
              ? "bg-emerald-500"
              : "bg-zinc-600"
          }`}
        />
      </div>
    </div>
  );
}
