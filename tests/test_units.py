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
