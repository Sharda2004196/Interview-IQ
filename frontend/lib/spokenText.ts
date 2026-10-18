/**
 * What the interviewer should actually SAY out loud.
 *
 * Voice should carry the CONVERSATION, not the paperwork. The interviewer agent
 * is instructed to open every scoring reply with a mandatory
 * "Score: <n>/10 — <one line why>" first line and then append the next question
 * (interviewiq_agent/agents/interviewer.py:45). Speaking the whole reply read the
 * score and its justification aloud every single round, which made voice mode
 * drag; on the final turn it read the entire written report. Both belong on
 * screen — the score on the card, the report on the report page.
 *
 * Shares its text detection with the question card (lib/questionText.ts), which
 * additionally hides the score line entirely; the greeting/preamble strip is the
 * same in both, so voice stops narrating "Welcome to your … interview!" too.
 */

import { REPORT_MARKERS, SCORE_LINE, stripPreamble } from "@/lib/questionText";

/**
 * Returns the text worth speaking: the question, with the score line and any
 * agent-invented preamble removed. Empty string means "say nothing" (the final
 * report).
 */
export function spokenText(reply: string): string {
  const text = (reply || "").trim();
  if (!text) return "";
  if (REPORT_MARKERS.test(text)) return "";
  const question = stripPreamble(text.replace(SCORE_LINE, "").trim());
  // Nothing left after the score line (a bare score, or the score and question
  // sharing a line): speak the reply rather than going silent on a question we
  // failed to isolate.
  return question || text;
}
