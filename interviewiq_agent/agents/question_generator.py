"""question_generator — builds question sets for modes A/B/C/D.

Invoked as a TOOL (AgentTool) by the interviewer, never via transfer: the list
comes back as structured data inside one continuous turn, so there is no
handoff boundary where the flow can stall (the old "ready"-then-silence bug).
"""

from google.adk.agents.llm_agent import Agent
from google.adk.tools.agent_tool import AgentTool
from pydantic import BaseModel, Field

from ..config import _MODEL
from ..tools.fetch_url import fetch_url_tool
from ..tools.parse_file import parse_file_tool
from ..tools.retrieve_context import retrieve_context_tool, upsert_document_tool


class QuestionBank(BaseModel):
    """Machine-readable set. The interviewer stores it, never quotes it raw."""

    questions: list[str] = Field(min_length=1)


question_generator = Agent(
    model=_MODEL,
    name="question_generator",
    description="Generates interview questions for the active session mode.",
    instruction="""You generate interview questions. The session mode tells you how:
- Mode A (topic only): create interview-level questions for the given topic/domain.
- Mode B (custom set): return the user's pasted questions unchanged, in order.
- Mode C (uploaded file): call parse_file ONLY when you have a FULL absolute path
  (starts with C:\\, C:/, or /) — then upsert_document to index it, and use
  retrieve_context to pull exact facts before writing questions. A bare filename
  is NOT a path — NEVER call parse_file with one. If the file was ATTACHED in chat (you can see its content
  in the conversation, no absolute path was given): read it directly from the
  conversation, detect its topic/field, generate questions from it, and skip
  parse/upsert entirely (attached files are not on disk — nothing to index).
- Mode D (resume): same pipeline as C — parse, index, then generate personalized
  questions targeting what is actually on the resume.
- Mode E (link): call fetch_url on the URL (YouTube -> captions, article ->
  clean text), then upsert_document to index it, then detect its topic/field
  and generate interview-level questions grounded in it. Use retrieve_context
  to pull exact facts before writing questions. If fetch_url errors, report the
  problem plainly and ask for a different link — never invent questions.
Build the FULL set (default 5, or the requested num_questions) in ONE go.
Match the session difficulty. Never invent resume facts — only use provided data.
Output ONLY the question list via the schema. No prose, no greeting, no questions
back to anyone — data out, nothing else.""",
    tools=[parse_file_tool, fetch_url_tool, upsert_document_tool, retrieve_context_tool],
    output_schema=QuestionBank,
    # Belt-and-suspenders: never transferred to anymore, but cannot grab the mic.
    disallow_transfer_to_parent=True,
)

# Interviewer's data call: returns {"questions": [...]} inside the same turn.
question_generator_tool = AgentTool(agent=question_generator)
