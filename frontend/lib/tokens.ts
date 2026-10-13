/**
 * InterviewIQ Design Tokens — Master System Tokens
 * Strictly following docs/frontend-brief.md & docs/skills/taste-SKILL.md
 * 
 * Rules:
 * - Single accent: Emerald (#10b981)
 * - Single exception: Muted Red (#f43f5e) strictly reserved for "No Hire" verdict pill
 * - Dark default, consistent light mode
 * - Fixed radius scale: rounded-xl (12px) for cards, rounded-lg (8px) for buttons/inputs, rounded-full for pills
 * - Icon stroke: 1.5
 */

export const TOKENS = {
  colors: {
    accent: {
      primary: "#10b981", // emerald-500
      hover: "#059669",   // emerald-600
      active: "#047857",  // emerald-700
      subtle: "rgba(16, 185, 129, 0.12)",
      border: "rgba(16, 185, 129, 0.25)",
      glow: "rgba(16, 185, 129, 0.15)",
    },
    verdict: {
      strongHire: {
        bg: "bg-emerald-500/15",
        border: "border-emerald-500/40",
        text: "text-emerald-400 dark:text-emerald-300",
      },
      hire: {
        bg: "bg-emerald-500/10",
        border: "border-emerald-500/30",
        text: "text-emerald-500 dark:text-emerald-400",
      },
      noHire: {
        bg: "bg-rose-500/15",
        border: "border-rose-500/40",
        text: "text-rose-400 dark:text-rose-300",
      },
    },
  },
  typography: {
    fontSans: "var(--font-geist-sans)",
    fontMono: "var(--font-geist-mono)",
  },
  radius: {
    card: "rounded-xl",       // 12px
    input: "rounded-lg",      // 8px
    button: "rounded-lg",     // 8px
    badge: "rounded-full",    // Pill
    orb: "rounded-full",      // 64px VoiceOrb
  },
  iconStrokeWidth: 1.5,
} as const;

export type VerdictType = "Strong Hire" | "Hire" | "No Hire";

export function getVerdictStyle(verdict: VerdictType) {
  switch (verdict) {
    case "Strong Hire":
      return TOKENS.colors.verdict.strongHire;
    case "Hire":
      return TOKENS.colors.verdict.hire;
    case "No Hire":
      return TOKENS.colors.verdict.noHire;
  }
}
