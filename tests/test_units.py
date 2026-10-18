"""Deterministic unit tests — no network, no LLM, no quota. Run: pytest tests/test_units.py."""

from types import SimpleNamespace

import pytest

from backend.schemas import Report, SessionConfig
from interviewiq_agent.tools.persistence import weighted_overall
from interviewiq_agent.tools.question_bank import next_question, store_questions
from interviewiq_agent.tools.retrieve_context import _chunk, _clean_query, _sparse


def ctx():
    return SimpleNamespace(state={})


# --- question bank: the locked single-question flow ---
def test_bank_dispenses_one_by_one_then_done():
    c = ctx()
    assert store_questions(["Q1?", "Q2?"], c) == {"stored": 2}
    r1 = next_question(c)
    assert (r1["question"], r1["index"], r1["done"]) == ("Q1?", 1, False)
    r2 = next_question(c)
    assert (r2["question"], r2["index"], r2["done"]) == ("Q2?", 2, False)
    r3 = next_question(c)
    assert r3["done"] is True and r3["question"] == ""


def test_bank_rejects_empty():
    with pytest.raises(ValueError):
        store_questions(["  ", ""], ctx())


def test_bank_empty_state_reports_done():
    assert next_question(ctx())["done"] is True


# --- hybrid scoring math ---
def test_weighted_rewards_trajectory():
    assert weighted_overall([4.0, 6.0, 9.0], ["easy", "medium", "hard"]) == 7.8


def test_weighted_flat_stays_put():
    assert weighted_overall([7.0, 7.0], ["medium", "medium"]) == 7.0


def test_nudge_bounded():
    with pytest.raises(ValueError):
        weighted_overall([8.0], ["medium"], nudge=2.0)
    assert weighted_overall([8.0], ["medium"], nudge=1.0) == 9.0


def test_weighted_rejects_empty():
    with pytest.raises(ValueError):
        weighted_overall([], [])


# --- RAG chunking / sparse / query ---
def test_chunk_keeps_sentences_whole():
    text = "Python is fast. FastAPI serves APIs. Docker ships containers. " * 30
    chunks = _chunk(text)
    assert all(c.strip() for c in chunks)
    for c in chunks:
        assert len(c) <= 1600  # packed near cap, never wildly over


def test_sparse_is_unit_norm():
    s = _sparse("FastAPI serves Python APIs with Docker")
    assert sorted(s.keys()) == ["indices", "values"]
    assert abs(sum(v * v for v in s["values"]) - 1.0) < 1e-6


def test_clean_query_strips_filler():
    assert _clean_query("Can you please tell me about FastAPI?") == "about fastapi"


# --- API boundary schemas ---
def test_session_config_rejects_bad_mode():
    with pytest.raises(ValueError):
        SessionConfig(mode="Z")
    assert SessionConfig(mode="A", topic="Python").num_questions == 5


def test_report_defaults():
    r = Report(session_id="s1")
    assert r.overall == 0.0 and r.per_question == [] and r.adjustment == ""


# --- WS auth frames: tokenless messages pass through untouched ---
def test_check_ws_token_passthrough():
    from backend.auth import check_ws_token

    assert check_ws_token({"text": "my answer"}, "local-dev") is None
    assert check_ws_token({"end": True}, "local-dev") is None
    assert check_ws_token({}, "local-dev") is None


# --- evaluator text extraction: backend-owned report content ---
def test_extract_eval():
    from backend.runner import _extract_eval

    payload = {"score": 7, "strengths": "Clear GIL explanation.", "gaps": "Missed free-threading."}
    assert _extract_eval(payload) == {
        "strengths": "Clear GIL explanation.",
        "gaps": "Missed free-threading.",
    }
    nested = {"result": {"response": payload}}
    assert _extract_eval(nested) == _extract_eval(payload)
    assert _extract_eval({"score": 7}) is None
    assert _extract_eval({"strengths": "", "gaps": ""}) is None
    assert _extract_eval("not json") is None


# --- tolerant summary parser: Lite never honors exact-shape contracts ---
def test_parse_summary_variants():
    from backend.main import _parse_summary

    strict = (
        "VERDICT: Hire\nWHY: Solid core.\nSTUDY: Raft — read the paper\n"
        "STRENGTHS: Clear explanations.\nGAPS: Missed edge cases."
    )
    out = _parse_summary(strict)
    assert out["verdict"] == "Hire" and "Raft" in out["study_next"]

    messy = (
        "```\n- **VERDICT:** Hire\n- **WHY:** Solid core.\n"
        "- **STUDY:** Raft — read the paper\n- **STRENGTHS:** Clear.\n- **GAPS:** Gaps here.\n```"
    )
    out = _parse_summary(messy)
    assert out["verdict"] == "Hire" and out["gaps"] == "Gaps here."

    assert _parse_summary("just chatting, no fields") == {}
    assert _parse_summary("VERDICT: Maybe\nWHY: x\nSTUDY: y") == {}


# --- summarizer must actually call the model and return parsed fields ---
def test_try_summarize_returns_parsed_fields(monkeypatch):
    """Guards a dead-code regression: an over-indented block under
    `if not rounds:` made the whole call unreachable, so every report fell
    back to static placeholders while logs showed "unusable shape"."""
    import google.genai as genai

    class _Resp:
        text = (
            "VERDICT: Hire\nWHY: Solid core.\nSTUDY: Raft — read the paper\n"
            "STRENGTHS: Clear explanations.\nGAPS: Missed edge cases."
        )

    class _Models:
        def generate_content(self, model=None, contents=None):
            return _Resp()

    class _Client:
        def __init__(self, api_key=None):
            self.models = _Models()

    monkeypatch.setattr(genai, "Client", _Client)

    from backend import main as M

    M._summary_client_singleton = None  # bypass the cached client
    M._answers["unit-summarize"] = {0: "a real answer"}
    try:
        out = M._try_summarize(
            "unit-summarize",
            {"per_question": [8.0], "overall": 8.0, "topic": "T", "mode": "A"},
        )
    finally:
        M._answers.pop("unit-summarize", None)
        M._summary_client_singleton = None
    assert out["verdict"] == "Hire"
    assert out["study_next"].startswith("Raft")
    assert out["strengths"] == "Clear explanations."
    assert out["gaps"] == "Missed edge cases."
    # No rounds -> no model call, empty result (never a crash).
    assert M._try_summarize("unit-summarize", {"per_question": []}) == {}


# --- model fallback: survive per-model 503s without duplicating output ---
def _collect(llm, req=None):
    import asyncio

    from google.adk.models.llm_request import LlmRequest
    from google.genai import types

    # Real request object: FallbackLlm writes the per-backend model onto it and
    # SHALLOW-copies it per attempt (ADK's Gemini reads the model off the request).
    if req is None:
        req = LlmRequest(
            contents=[types.Content(role="user", parts=[types.Part(text="hi")])]
        )
    out = []

    async def run():
        async for r in llm.generate_content_async(req, stream=False):
            out.append(r)

    asyncio.run(run())
    return out


def _ok_llm(name="second", text="ok"):
    from google.adk.models import BaseLlm, LlmResponse
    from google.genai import types

    class Ok(BaseLlm):
        model: str = name
        reply: str = text

        async def generate_content_async(self, llm_request, stream=False):
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text=self.reply)])
            )

    return Ok()


def _raising_llm(name, exc):
    from google.adk.models import BaseLlm

    class Boom(BaseLlm):
        model: str = name

        async def generate_content_async(self, llm_request, stream=False):
            raise exc
            yield  # pragma: no cover

    return Boom()


def test_fallback_llm_switches_model_on_503():
    """A per-model 503 (UNAVAILABLE) must fall back to the next Flash-Lite model."""
    from interviewiq_agent.config import FallbackLlm

    llm = FallbackLlm(
        model="primary",
        backends=[
            _raising_llm("primary", RuntimeError("503 UNAVAILABLE: high demand")),
            _ok_llm(),
        ],
    )
    out = _collect(llm)
    assert len(out) == 1
    assert out[0].content.parts[0].text == "ok"


# --- backend-owned transcript: rounds -> Q&A turns (was never persisted) ---
def test_pdf_report_renders_transcript_turns():
    """The PDF's per-question breakdown is built ONLY from turns, so with the
    old empty-turns world it rendered nothing — no Q&A and no scores."""
    from backend.report_pdf import build_report_pdf

    empty = build_report_pdf({"session_id": "s", "overall": 5.0}, [])
    filled = build_report_pdf(
        {"session_id": "s", "overall": 5.0, "per_question": [7.0, 4.0]},
        [
            {"q": "What is an AI agent?", "a": "A program that perceives and acts.", "score": 7.0},
            {"q": "Explain tool use.", "a": "It calls functions.", "score": 4.0},
        ],
    )
    assert empty.startswith(b"%PDF") and filled.startswith(b"%PDF")
    assert len(filled) > len(empty)


def test_build_turns_pairs_question_answer_and_score():
    from backend import main as M

    turns = M._build_turns(
        rounds=[7.0, 5.0],
        bank=["Q1?", "Q2?"],
        captured={},
        answers={0: "a1", 1: "a2"},
    )
    assert turns == [
        {"q": "Q1?", "a": "a1", "score": 7.0},
        {"q": "Q2?", "a": "a2", "score": 5.0},
    ]


def test_build_turns_falls_back_to_captured_questions():
    """A short/absent stored bank must not drop the questions captured from
    next_question frames — otherwise the PDF shows answers with no question."""
    from backend import main as M

    turns = M._build_turns(
        rounds=[6.0, 4.0],
        bank=["Q1?"],
        captured={1: "Q2-from-frame"},
        answers={0: "a1", 1: "a2"},
    )
    assert [t["q"] for t in turns] == ["Q1?", "Q2-from-frame"]


def test_build_turns_keeps_a_missing_answer_but_drops_empty_rounds():
    """A scored round with no captured text is noise; a scored round with a
    question but a lost answer is still the truth and must be kept."""
    from backend import main as M

    assert M._build_turns([8.0], [], {}, {}) == []
    assert M._build_turns([8.0], ["Q1?"], {}, {}) == [
        {"q": "Q1?", "a": "", "score": 8.0}
    ]


def _fold_verdicts(verdicts):
    """Drive one session's score frames through the real bookkeeping."""
    from backend import main as M

    rounds, answers, probe_open = [], {}, False
    for value, sig, answer in verdicts:
        sig = M._effective_signal(sig)
        probe_open = M._apply_verdict(
            rounds, answers, probe_open, value, sig, answer
        )
    return rounds, answers


def test_follow_up_never_eats_a_round():
    """Regression: 3 answers came back as a "2 Questions" report.

    The evaluator votes FOLLOW_UP whenever an answer is thin, and a FOLLOW_UP
    used to open a probe round that the NEXT answer closed — so two answers
    folded into one round, the report showed fewer questions than were answered,
    and the surviving round carried the PROBE's score against the original
    answer's text. One answer is one round now, in every mode.
    """
    verdicts = [
        (6.0, "NEXT", "a1"),
        (6.0, "FOLLOW_UP", "a2"),
        (3.0, "NEXT", "a3"),
        (4.0, "FOLLOW_UP", "a4"),
        (1.0, "NEXT", "a5"),
    ]
    rounds, answers = _fold_verdicts(verdicts)
    assert rounds == [6.0, 6.0, 3.0, 4.0, 1.0]
    assert answers == {0: "a1", 1: "a2", 2: "a3", 3: "a4", 4: "a5"}


def test_effective_signal_always_normalizes_follow_up():
    """Probes are off in every mode, so the evaluator's FOLLOW_UP vote can never
    restructure the rounds — only the score/difficulty signals survive."""
    from backend import main as M

    assert M._effective_signal("FOLLOW_UP") == "NEXT"
    assert M._effective_signal("EASIER") == "EASIER"
    assert M._effective_signal("HARDER") == "HARDER"
    assert M._effective_signal(None) is None


def test_apply_verdict_keeps_the_probe_contract_for_safety():
    """_effective_signal means FOLLOW_UP should never reach _apply_verdict, but
    the overwrite contract stays: an explicitly open round is closed by the next
    verdict instead of duplicating the question."""
    from backend import main as M

    rounds, answers, open_ = [], {}, False
    open_ = M._apply_verdict(rounds, answers, open_, 5.0, "FOLLOW_UP", "main")
    assert (rounds, open_) == ([5.0], True)
    open_ = M._apply_verdict(rounds, answers, open_, 9.0, "NEXT", "probe")
    assert (rounds, open_) == ([9.0], False)
    assert answers == {0: "main"}  # the round still shows the main answer


def test_question_bank_reads_state_and_tolerates_missing_session():
    """The transcript's question column comes from session state, so it survives
    a missed next_question frame or a socket reconnect."""
    import asyncio

    from backend import runner as R

    async def run():
        await R._session_service.create_session(
            app_name=R.APP_NAME,
            user_id="unit-user",
            session_id="unit-bank-1",
            state={"question_bank": ["Q1?", "Q2?"]},
        )
        found = await R.question_bank("unit-bank-1", "unit-user")
        missing = await R.question_bank("unit-bank-absent", "unit-user")
        return found, missing

    found, missing = asyncio.run(run())
    assert found == ["Q1?", "Q2?"]
    assert missing == []


def test_fallback_llm_sets_request_model_per_backend():
    """ADK's Gemini reads the model off the REQUEST, so the fallback must write
    each backend's model onto it — otherwise the retry hits the same model."""
    from google.adk.models import BaseLlm, LlmResponse
    from google.genai import types

    from interviewiq_agent.config import FallbackLlm

    seen = []

    class Rec(BaseLlm):
        model: str = "primary-flash-lite"
        blow_up: bool = False

        async def generate_content_async(self, llm_request, stream=False):
            seen.append(llm_request.model)
            if self.blow_up:
                raise RuntimeError("503 UNAVAILABLE")
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text="ok")])
            )

    llm = FallbackLlm(
        model="primary-flash-lite",
        backends=[Rec(blow_up=True), Rec(model="second-flash-lite")],
    )
    _collect(llm)
    assert seen == ["primary-flash-lite", "second-flash-lite"]


def test_fallback_llm_does_not_fall_back_mid_stream():
    """Once ANY text has been emitted, a later failure must surface — switching
    models then would duplicate the tokens already sent to the client."""
    from google.adk.models import BaseLlm, LlmResponse
    from google.genai import types

    from interviewiq_agent.config import FallbackLlm

    class HalfThenBoom(BaseLlm):
        model: str = "half"

        async def generate_content_async(self, llm_request, stream=False):
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text="partial")])
            )
            raise RuntimeError("503 UNAVAILABLE")

    llm = FallbackLlm(model="primary", backends=[HalfThenBoom(), _ok_llm()])
    try:
        _collect(llm)
        raise AssertionError("expected the 503 to propagate, not fall back")
    except RuntimeError as ex:
        assert "503" in str(ex)
    # (the fallback model was never reached, so no second response was produced)


def test_fallback_llm_reraises_non_capacity_errors():
    """A real bug (bad request) must NOT be masked by a fallback attempt."""
    from interviewiq_agent.config import FallbackLlm

    llm = FallbackLlm(
        model="primary",
        backends=[_raising_llm("primary", ValueError("bad request")), _ok_llm()],
    )
    try:
        _collect(llm)
        raise AssertionError("expected ValueError to propagate")
    except ValueError as ex:
        assert "bad request" in str(ex)


def test_fallback_llm_never_deep_copies_the_request():
    """The retry path must stay SHALLOW.

    Regression: the first fallback implementation deep-copied the request, and
    every REAL fallback died with "TypeError: cannot pickle '_thread.lock'
    object" — ADK's LlmRequest carries live client internals. A synthetic
    request deep-copies happily, so the original tests passed while the real
    thing crashed. This pins the shallow-copy contract directly.
    """
    from unittest import mock

    from google.adk.models.llm_request import LlmRequest

    from interviewiq_agent.config import FallbackLlm

    real = LlmRequest.model_copy
    deep_calls = []

    def guarded(self, *, update=None, deep=False):
        if deep:
            deep_calls.append(1)
            raise TypeError("cannot pickle '_thread.lock' object")
        return real(self, update=update, deep=deep)

    llm = FallbackLlm(
        model="primary",
        backends=[_raising_llm("primary", RuntimeError("503 UNAVAILABLE")), _ok_llm()],
    )
    with mock.patch.object(LlmRequest, "model_copy", guarded):
        out = _collect(llm)

    assert deep_calls == []
    assert out  # the fallback still produced a response


def test_fallback_llm_does_not_mutate_the_callers_request():
    """Each attempt writes the model onto its own shallow copy, so the caller's
    request (shared by ADK across the call) keeps its original model."""
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types

    from interviewiq_agent.config import FallbackLlm

    req = LlmRequest(
        model="original-model",
        contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
    )
    llm = FallbackLlm(
        model="primary",
        backends=[_raising_llm("primary", RuntimeError("503 UNAVAILABLE")), _ok_llm()],
    )
    _collect(llm, req=req)
    assert req.model == "original-model"


# --- agent report-text parser: the UI's five fields, from the agent's text ---
def test_parse_report_text_real_shape():
    """The exact shape the agent streams (parsed so the UI can show it without
    a second model call). Mirrors the reported-stuck report verbatim."""
    from backend.main import _parse_report_text

    text = (
        "Score: 7/10 — Solid foundational understanding of agent autonomy and "
        "coordination, though missing deeper architectural details.\n"
        "Interview Report\n"
        "Per-Question Scores:\n"
        "• Q1: 7/10 (Easy)\n"
        "Overall Score: 7/10\n"
        "Strengths:\n"
        "• Accurately identified core concepts of autonomy and multi-agent coordination.\n"
        "Gaps:\n"
        "• The candidate provided a basic definition mentioning autonomy and "
        "coordination, but missed key differences such as planning, tool use, "
        "memory, and iterative execution versus single-turn response generation.\n"
        "What to Study Next:\n"
        "1. Planning and Reasoning loops in LLMs (e.g., ReAct framework)\n"
        "2. Tool use and environment interaction in AI agents\n"
        "3. State management and memory persistence\n"
        "Verdict: Hire — Solid foundational understanding of agent autonomy and "
        "coordination, though missing deeper architectural details.\n"
    )
    out = _parse_report_text(text)
    assert out["score"] == 7.0
    assert "Accurately identified core concepts" in out["strengths"]
    assert "missed key differences" in out["gaps"]
    assert "ReAct" in out["study_next"] and "State management" in out["study_next"]
    assert out["verdict"] == "Hire"
    assert out["verdict_why"].startswith("Solid foundational understanding")


def test_parse_report_text_markdown_variant():
    from backend.main import _parse_report_text

    text = (
        "**Score:** 9/10 — excellent.\n"
        "**Strengths:** clear, precise.\n"
        "**Key Growth Areas:** none major.\n"
        "**Recommended Study Topics:**\n- Raft — read the paper\n- CRDTs\n"
        "**Verdict:** Strong Hire — outstanding.\n"
    )
    out = _parse_report_text(text)
    assert out["score"] == 9.0
    assert out["strengths"] == "clear, precise."
    assert out["gaps"] == "none major."
    assert "Raft" in out["study_next"]
    assert out["verdict"] == "Strong Hire"
    assert out["verdict_why"] == "outstanding."


# --- quota classifier: honest errors, no private ADK imports ---
def test_is_quota_error():
    from backend.runner import _is_quota_error

    class FakeResourceExhausted(Exception):
        pass

    FakeResourceExhausted.__name__ = "_ResourceExhaustedError"
    assert _is_quota_error(FakeResourceExhausted("q")) is True

    class Fake429(Exception):
        code = 429

    assert _is_quota_error(Fake429("q")) is True

    class Fake500(Exception):
        code = 500

    assert _is_quota_error(Fake500("x")) is False
    assert _is_quota_error(ValueError("x")) is False
