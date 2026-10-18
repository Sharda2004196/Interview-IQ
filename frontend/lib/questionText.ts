/**
 * What the QUESTION CARD shows: the question, and nothing else.
 *
 * The card renders a turn's streamed reply verbatim, and a reply is more than a
 * question:
 *   - the agent may open with its own preamble ("Welcome to your Agentic AI
 *     interview! Let's start with the first question:"),
 *   - every scoring reply starts with the mandatory "Score: <n>/10 — …" line
 *     plus its justification,
 *   - the final turn IS the written report, and on a reconnect the backend
 *     resyncs the last turn's raw text (main.py:424-427), so the whole report
 *     flashed up in the card as plain text and then vanished.
 * The report belongs on the report page; the score belongs to the score chip /
 * round history. This is a DISPLAY filter only — no socket, transcript,
 * Firestore, or report code is involved.
 */

// The mandatory "Score: 6/10 — why…" line, optionally **bold**. `[^\n]*` keeps
// the match inside that line, so a question can never be eaten.
export const SCORE_LINE =
  /^\s*\**\s*score\s*:\s*\d+(?:\.\d+)?\s*\/\s*10\b[^\n]*\n?/i;

// Mid-stream the same line arrives in pieces ("Sco", "Score: 6", "Score: 6/10 …").
const SCORE_START = /^\s*\**\s*sco/i;

// The final report is for the report page. Every report ends with the mandatory
// "Verdict:" line (interviewiq_agent/agents/interviewer.py:63) and carries its
// own headings. Anchored to the start of a line so a QUESTION that merely
// mentions the word ("what if the verdict is wrong?") is unaffected.
export const REPORT_MARKERS =
  /(?:^|\n)\s*\**\s*(?:verdict\s*:|interview\s+report|per-?question\s+scores|overall\s+score\s*:)/i;

// Openers the agent invents on its own. Tier 1 is conversational filler: safe to
// drop whenever a question follows anywhere in the turn. Tier 2 are lead-ins
// that can carry context ("Here's the scenario:"), dropped only when the very
// next line IS the question. The bank question is the line carrying the "?".
const GREETING_LINE =
  /^(?:welcome\b|hi\b|hello\b|hey\b|good\s+(?:morning|afternoon|evening)\b|sure\b|great\b|excellent\b|okay\b|ok\b|alright\b|thanks\b|thank\s+you\b|of\s+course\b|absolutely\b|got\s+it\b)/i;
const LEADIN_LINE = /^(?:let'?s\b|let\s+us\b|now\b|here(?:'s|\s+is)\b)/i;

function nextNonEmpty(lines: string[], from: number): string | null {
  for (let j = from; j < lines.length; j += 1) {
    const line = lines[j].trim();
    if (line) return line;
  }
  return null;
}

/**
 * Drops leading greeting/preamble lines, never the last remaining line and
 * never a line carrying context. A greeting only goes when a question follows;
 * a lead-in only when the next line is the question itself ("Here's the
 * scenario:" followed by a scenario line survives).
 */
export function stripPreamble(text: string): string {
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length - 1) {
    const line = lines[i].replace(/[*_]/g, "").trim();
    if (!line) {
      i += 1;
      continue; // leading blank line
    }
    if (line.includes("?")) break; // the question starts here
    const rest = lines.slice(i + 1).join("\n");
    const next = nextNonEmpty(lines, i + 1);
    if (next === null) break;
    const greeting = GREETING_LINE.test(line);
    const leadIn = !greeting && LEADIN_LINE.test(line) && next.endsWith("?");
    if (!greeting && !leadIn) break;
    if (greeting && !rest.includes("?")) break; // nothing question-shaped after it
    i += 1;
  }
  return lines.slice(i).join("\n").trim();
}

/**
 * The question a turn is asking, or "" when the turn is not asking one yet —
 * a score line (or its justification mid-stream), or the final report. An empty
 * string is the signal for the card to show its waiting state instead of text.
 */
export function questionText(reply: string): string {
  const text = (reply || "").trim();
  if (!text) return "";
  if (REPORT_MARKERS.test(text)) return ""; // report → report page only
  const body = text.replace(SCORE_LINE, "").trim();
  if (!body) return ""; // a bare score line
  // A scoring reply that has not reached its question yet is the score's
  // justification ("Score: 6/10 — Correctly noted that memory…"), which the
  // score chip already shows. Once the question lands it contains a "?".
  if (!body.includes("?") && SCORE_START.test(text)) return "";
  return stripPreamble(body);
}
