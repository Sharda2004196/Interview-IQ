"""question_bank tools — code-enforced single-question flow.

The generator stores the FULL set once; the interviewer dispenses EXACTLY ONE
per call. The LLM can never emit 3-at-once because it only ever receives one.
State lives in ADK session state (per-session, survives restarts via Firestore).
"""

from google.adk.tools import FunctionTool, ToolContext


def store_questions(questions: list[str], tool_context: ToolContext) -> dict:
    """Generator calls once per session. Returns {"stored": n}.

    Truncates to the session's num_questions (seeded by the backend): the
    generator is an LLM and routinely builds 5 despite "ask 3". Code wins
    over obedience — the bank is EXACTLY N, so progress and end-of-interview
    can trust it. Never pads (can't invent questions); keeps all when fewer.
    """
    clean = [q.strip() for q in questions if q and q.strip()]
    if not clean:
        raise ValueError("store_questions got an empty list")
    try:
        want = int(tool_context.state.get("num_questions", 0) or 0)
    except (TypeError, ValueError):
        want = 0
    bank = clean[:want] if 0 < want < len(clean) else clean
    tool_context.state["question_bank"] = bank
    tool_context.state["q_index"] = 0
    return {"stored": len(bank)}


def next_question(tool_context: ToolContext) -> dict:
    """Interviewer calls once per turn. Returns {"question","index","total","done"}."""
    bank = tool_context.state.get("question_bank", [])
    idx = tool_context.state.get("q_index", 0)
    if idx >= len(bank):
        return {"question": "", "index": idx, "total": len(bank), "done": True}
    tool_context.state["q_index"] = idx + 1
    return {"question": bank[idx], "index": idx + 1, "total": len(bank), "done": False}


store_questions_tool = FunctionTool(store_questions)
next_question_tool = FunctionTool(next_question)
