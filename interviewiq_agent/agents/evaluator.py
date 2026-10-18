"""evaluator subagent — scores answers, signals follow-up vs next vs difficulty shift."""

from typing import Literal

from google.adk.agents.llm_agent import Agent
from google.adk.tools.agent_tool import AgentTool
from pydantic import BaseModel, Field

from ..config import build_model


class EvalResult(BaseModel):
    """Machine-readable verdict. Chat-facing agents read `signal`, humans read the rest."""

    score: int = Field(ge=0, le=10)
    strengths: str
    gaps: str
    signal: Literal["FOLLOW_UP", "NEXT", "EASIER", "HARDER"]


evaluator = Agent(
    model=build_model(),
    name="evaluator",
    description="Scores answers and decides follow-up vs next question vs difficulty shift.",
    instruction="""You evaluate the candidate's latest answer. Respond in exactly this shape:
Score: <0-10>
Strengths: <1-2 lines>
Gaps: <1-2 lines>
Signal: <FOLLOW_UP | NEXT | EASIER | HARDER>
Rubric: 9-10 correct+depth, 7-8 correct core, 5-6 partial, 3-4 major gaps, 0-2 wrong/empty.
Judge against DOMAIN correctness, never file similarity: retrieved context tells
you what the question is about, never what the only right answer is. A correct
answer that differs from the file's wording or approach scores FULL marks —
paraphrase and alternative valid methods are not gaps.
FOLLOW_UP only for partial answers worth one clarifying probe (max 2 per question).
EASIER after two scores below 5; HARDER after two scores above 8.""",
    output_schema=EvalResult,
    # Structural: one-way delegation only — verdict auto-returns to interviewer.
    disallow_transfer_to_parent=True,
)

# Exposed to the interviewer as a TOOL (not a subagent): tool results can never
# address the candidate, so the interviewer always speaks last — no JSON leaks,
# and score + next question bundle in one reply by construction.
evaluator_tool = AgentTool(agent=evaluator)
