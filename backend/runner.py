"""ADK Runner singleton + session helpers.

Runner owns the agent loop; InMemorySessionService holds live state.
Durable transcript/scores go to Firestore via the agent's own save tools.
"""

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from interviewiq_agent.agent import root_agent

from .schemas import SessionConfig

APP_NAME = "interviewiq"
DEV_USER_ID = "local-dev"  # replaced by Firebase Auth uid pre-deploy

_session_service = InMemorySessionService()
_runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_session_service)


def get_runner() -> Runner:
    return _runner


async def get_or_create_session(session_id: str, config: SessionConfig, user_id: str = DEV_USER_ID):
    """Create ADK session with mode/persona/difficulty seeded into state."""
    existing = await _session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if existing is not None:
        return existing
    return await _session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state={
            "user_id": user_id,
            "mode": config.mode,
            "topic": config.topic,
            "custom_questions": config.custom_questions,
            "file_namespace": config.file_namespace,
            "persona_role": config.persona.role,
            "persona_tone": config.persona.tone,
            "difficulty": config.persona.difficulty,
            "num_questions": config.num_questions,
            "voice_mode": bool(config.voice_mode),
            "transcript": [],
            "scores": [],
        },
    )


async def stream_events(session_id: str, text: str, user_id: str = DEV_USER_ID):
    """Yield ("token", str) deltas, ("score", (float, signal|None)) verdicts,
    and ("bank", dict) question-bank states for one message.

    Score events come from the evaluator tool's function-response (structural —
    they fire even if the interviewer forgets to say the score out loud).
    The signal travels WITH its score in one tuple (no cross-event pairing):
    FOLLOW_UP marks a probe (doesn't count as a round), anything else
    (NEXT/EASIER/HARDER/None) counts as a completed round.
    Bank events come from next_question's function-response ({"question",
    "index", "total", "done"}) — redundant end-of-interview evidence.
    """
    async for event in _runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if getattr(part, "text", None):
                yield ("token", part.text)
                continue
            fr = getattr(part, "function_response", None)
            response = getattr(fr, "response", None)
            if isinstance(response, dict) and "done" in response and "question" in response:
                yield ("bank", response)
                continue
            score = _extract_score(response)
            if score is not None:
                yield ("score", (score, _extract_signal(response)))
                eval_notes = _extract_eval(response)
                if eval_notes is not None:
                    yield ("eval", eval_notes)


def _is_quota_error(ex: Exception) -> bool:
    """True for model quota/rate exhaustion (429 / ResourceExhausted).

    Name + code matching (no private ADK imports): surfaces as an honest
    "wait and retry" message instead of a generic turn failure or silent stall.
    """
    if "ResourceExhausted" in type(ex).__name__:
        return True
    code = getattr(ex, "status_code", getattr(ex, "code", None))
    return code == 429


# Silent-replay delay: long enough for per-minute rate buckets to drain.
RETRY_DELAY_S = 45
# Capacity blips (503/504) usually clear in seconds — the start turn (Q1)
# replays fast so a Google hiccup doesn't feel like a dead interview.
RETRY_DELAY_QUICK_S = 15

# genai 5xx family names worth one replay (Google's own advice for 503s).
_RETRYABLE_NAMES = {"ServerError", "InternalServerError", "ServiceUnavailable"}


def _is_retryable(ex: Exception) -> bool:
    """429/503/504-class failures: ONE silent replay is safe (callers only
    replay turns that produced nothing — no duplicate text or scores)."""
    if _is_quota_error(ex):
        return True
    code = getattr(ex, "status_code", getattr(ex, "code", None))
    if code in (503, 504):
        return True
    return type(ex).__name__ in _RETRYABLE_NAMES


async def snapshot_qindex(session_id: str, user_id: str = DEV_USER_ID) -> int:
    """Current bank dispense index (0 when unknown). Saved before a turn so a
    replayed turn can roll back a dispense its dead attempt consumed."""
    sess = await _session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if sess is None:
        return 0
    try:
        return int((sess.state or {}).get("q_index", 0) or 0)
    except (TypeError, ValueError):
        return 0


async def restore_qindex(session_id: str, user_id: str, value: int) -> None:
    """Roll the bank index back (replay safety — see snapshot_qindex)."""
    sess = await _session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if sess is not None:
        try:
            sess.state["q_index"] = int(value)
        except (TypeError, ValueError, AttributeError):
            pass


async def question_bank(session_id: str, user_id: str = DEV_USER_ID) -> list[str]:
    """The session's stored question list (empty when setup never stored one).

    Authoritative question column for the transcript: store_questions writes the
    FULL bank into session state once at setup, so it survives a missed
    next_question frame or a socket reconnect. Read-only — never creates a
    session (a missing one means there is nothing to persist).
    """
    sess = await _session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if sess is None:
        return []
    bank = (sess.state or {}).get("question_bank") or []
    return [str(q).strip() for q in bank if q and str(q).strip()]


def _extract_signal(response) -> str | None:
    """Find the evaluator's signal vote, tolerating nesting (mirrors _extract_score)."""
    if isinstance(response, dict):
        if response.get("signal") in ("FOLLOW_UP", "NEXT", "EASIER", "HARDER"):
            return response["signal"]
        for v in response.values():
            found = _extract_signal(v)
            if found is not None:
                return found
    if isinstance(response, (list, tuple)):
        for v in response:
            found = _extract_signal(v)
            if found is not None:
                return found
    return None


def _extract_eval(response) -> dict | None:
    """Find {"strengths": str, "gaps": str} in a function-response payload,
    tolerating nesting (mirrors _extract_score). Partial verdicts count — a
    turn with only strengths still enriches the report; the summarizer covers
    whatever text is missing."""
    if isinstance(response, dict):
        s, g = response.get("strengths"), response.get("gaps")
        s = s.strip() if isinstance(s, str) else ""
        g = g.strip() if isinstance(g, str) else ""
        if s or g:
            return {"strengths": s, "gaps": g}
        for v in response.values():
            found = _extract_eval(v)
            if found is not None:
                return found
    if isinstance(response, (list, tuple)):
        for v in response:
            found = _extract_eval(v)
            if found is not None:
                return found
    if isinstance(response, str):
        import json

        try:
            return _extract_eval(json.loads(response))
        except (ValueError, TypeError):
            return None
    return None


def _extract_score(response) -> float | None:
    """Find {"score": n} in a function-response payload, tolerating nesting."""
    if isinstance(response, dict):
        if isinstance(response.get("score"), (int, float)):
            return float(response["score"])
        for v in response.values():
            found = _extract_score(v)
            if found is not None:
                return found
    if isinstance(response, (list, tuple)):
        for v in response:
            found = _extract_score(v)
            if found is not None:
                return found
    if isinstance(response, str):
        import json

        try:
            return _extract_score(json.loads(response))
        except (ValueError, TypeError):
            return None
    return None


async def stream_reply(session_id: str, text: str, user_id: str = DEV_USER_ID):
    """Back-compat token-only stream (tests / simple clients)."""
    async for kind, payload in stream_events(session_id, text, user_id):
        if kind == "token":
            yield payload


async def bank_exhausted(session_id: str, user_id: str = DEV_USER_ID) -> bool:
    """True when every banked question has been dispensed (q_index >= len).

    Code-truth end-of-interview check: the agent sometimes reports straight
    after the Nth answer without calling next_question again, so no
    done=True event fires in that turn. State doesn't lie. Probe turns don't
    advance q_index, so follow-ups can never trigger this early.
    """
    sess = await _session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if sess is None:
        return False
    state = sess.state or {}
    bank = state.get("question_bank", [])
    return bool(bank) and int(state.get("q_index", 0) or 0) >= len(bank)


def build_start_prompt(config: SessionConfig) -> str:
    """First-turn driver shared by WS and voice: seeds mode/persona into Runner."""
    base = (
        f"Start the interview. Mode={config.mode}. Topic='{config.topic}'. "
        f"Persona: {config.persona.role}, tone {config.persona.tone}, "
        f"difficulty {config.persona.difficulty}. Ask {config.num_questions} questions. "
    )
    if config.mode == "B" and config.custom_questions:
        base += "Use exactly these questions in order: " + " | ".join(config.custom_questions)
    if config.mode in ("C", "D", "E") and config.file_namespace:
        base += f"Indexed content is under namespace '{config.file_namespace}'. "
    return base + "Ask the first question now."


def build_retry_prompt(stage: str) -> str:
    """Nudge for a clean-miss retry (503/429 before ANY output streamed).

    ADK appends the caller's message to the session BEFORE the model call, so
    the original text is already in the conversation. Re-sending it verbatim
    duplicates the turn — the agent reads the candidate as "repeating" itself,
    and for the start prompt it concludes the interview is over and emits a
    bogus final report. Send a distinct nudge instead: the instruction to keep
    going without repeating the message that is already in the history.
    """
    if stage == "start":
        return "Continue: ask the first interview question now."
    return "Continue: evaluate the candidate's last answer, then proceed."


async def interview_started(session_id: str, user_id: str = DEV_USER_ID) -> bool:
    """True once the interviewer has produced ANY event — i.e. the interview has
    actually begun.

    The start turn must be driven exactly ONCE per session. A socket reconnect
    re-entered the start turn and appended a SECOND setup message to the same
    ADK session (ADK persists the user message even when the model call fails),
    so the agent saw the candidate "repeating the setup prompt" and bailed with
    a bogus 0/10 No-Hire report. This probe is how the WS handler decides to
    resync the screen instead of re-driving the model.
    """
    try:
        sess = await _session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
    except Exception:  # noqa: BLE001 — a probe must never block the interview
        return False
    if sess is None:
        return False
    return any(ev.author != "user" and ev.content for ev in sess.events)
