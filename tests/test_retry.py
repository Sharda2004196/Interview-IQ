"""Retry-path tests — fully offline (stream_events/Runner stubbed, no LLM/quota).

Proves: clean-miss turns replay once silently; post-output failures never
replay (no duplicate text/scores); persistent failure surfaces resend UX.
"""

import asyncio
import json
import queue
import threading

from fastapi.testclient import TestClient

import backend.main as M


class Fake503(Exception):
    code = 503


def _scripted_stream(scripts):
    """scripts: {attempt_no: [actions]}; action = ("raise", exc) | ("yield", event)."""
    calls = {"n": 0}

    async def fake(session_id, text, user_id="local-dev"):
        calls["n"] += 1
        for action, val in scripts.get(calls["n"], []):
            if action == "raise":
                raise val
            yield val

    fake.calls = calls
    return fake


async def _fake_reply(session_id, text, user_id="local-dev"):
    yield "Q1?"


async def _noop_finalize(session_id):
    """Stub the finish-path enrichment (it calls Lite + Firestore in prod)."""
    return None


def test_start_turn_replays_on_clean_miss(monkeypatch):
    """Q1 503 before any token -> silent replay -> full Q1 streams, no error."""
    calls = {"n": 0}

    async def flaky_start(session_id, text, user_id="local-dev"):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Fake503("capacity blip")
        yield "Q1?"

    monkeypatch.setattr(M, "stream_reply", flaky_start)
    monkeypatch.setattr(M, "RETRY_DELAY_QUICK_S", 0.01)

    c, sid = _client_session()
    with c.websocket_connect(f"/ws/{sid}") as ws:
        envs = _Reader(ws).read(cap=3)
    assert calls["n"] == 2  # failed once, replayed once
    assert [e.get("type") for e in envs] == ["token"]  # clean Q1, no error frame
    assert envs[0].get("text") == "Q1?"


def test_start_retry_sends_nudge_not_duplicate_prompt(monkeypatch):
    """A clean-miss start replay must NOT re-send the verbatim start prompt.

    ADK appends the user message BEFORE the model call, so a verbatim replay
    leaves TWO setup messages in the session. The agent then reads the
    candidate as "repeating the setup prompt" and emits a bogus report — the
    0/10 No-Hire that stranded the stage page.
    """
    seen: list[str] = []

    async def flaky_start(session_id, text, user_id="local-dev"):
        seen.append(text)
        if len(seen) == 1:
            raise Fake503("capacity blip")
        yield "Q1?"

    async def fake_started(session_id, user_id="local-dev"):
        return False  # no prior model turn -> the start turn is driven

    monkeypatch.setattr(M, "stream_reply", flaky_start)
    monkeypatch.setattr(M, "interview_started", fake_started)
    monkeypatch.setattr(M, "RETRY_DELAY_QUICK_S", 0.01)

    c, sid = _client_session()
    with c.websocket_connect(f"/ws/{sid}") as ws:
        _Reader(ws).read(cap=1)
    assert len(seen) == 2, seen
    assert seen[0] != seen[1], seen  # never the verbatim start prompt again
    assert "first interview question" in seen[1].lower()


def test_reconnect_resyncs_without_replaying_start(monkeypatch):
    """A reconnect must resync the screen, NOT re-drive the start prompt.

    Each re-driven start appended another setup message to the same ADK session
    (three socket accepts after 503-driven closes = three setup prompts), which
    is exactly what made the agent bail with a bogus final report.
    """
    started = {"v": False}
    seen: list[str] = []

    async def fake_reply(session_id, text, user_id="local-dev"):
        seen.append(text)
        started["v"] = True  # the session now holds a model turn
        yield "Q1: what is Agentic AI?"

    async def fake_started(session_id, user_id="local-dev"):
        return started["v"]

    monkeypatch.setattr(M, "stream_reply", fake_reply)
    monkeypatch.setattr(M, "interview_started", fake_started)

    c, sid = _client_session()
    with c.websocket_connect(f"/ws/{sid}") as ws:  # first connect: start once
        first = _Reader(ws).read(cap=1)
    assert [e.get("type") for e in first] == ["token"], first
    assert len(seen) == 1

    with c.websocket_connect(f"/ws/{sid}") as ws:  # reconnect
        second = _Reader(ws).read(cap=1)
    assert len(seen) == 1, seen  # NO second start prompt reached the model
    assert [e.get("type") for e in second] == ["question"], second
    assert second[0].get("text") == "Q1: what is Agentic AI?"


def _client_session(num_questions=1):
    c = TestClient(M.app)
    r = c.post(
        "/sessions",
        json={"mode": "A", "topic": "t", "num_questions": num_questions},
    )
    assert r.status_code == 200, r.text
    return c, r.json()["session_id"]


class _Reader:
    """One pump thread per connection — abandoned pumps steal messages."""

    def __init__(self, ws):
        self.q: queue.Queue = queue.Queue()

        def pump():
            try:
                while True:
                    self.q.put(("ok", ws.receive_text()))
            except Exception as ex:  # noqa: BLE001 — closed socket ends the pump
                self.q.put(("err", ex))

        threading.Thread(target=pump, daemon=True).start()

    def read(self, cap=10, timeout=8):
        """Blocking receives with a hard timeout — a regression must FAIL, not hang."""
        out = []
        for _ in range(cap):
            try:
                kind, val = self.q.get(timeout=timeout)
            except queue.Empty:
                break
            if kind == "err":
                break
            out.append(json.loads(val))
        return out


def test_clean_miss_replays_once_then_scores(monkeypatch):
    fake = _scripted_stream(
        {1: [("raise", Fake503("boom"))], 2: [("yield", ("score", (8.0, "NEXT")))]}
    )
    saved = {}
    monkeypatch.setattr(M, "stream_events", fake)
    monkeypatch.setattr(M, "stream_reply", _fake_reply)
    monkeypatch.setattr(M, "RETRY_DELAY_S", 0.01)

    async def fake_save(sid, scores, config, user_id=""):
        saved["scores"] = list(scores)

    monkeypatch.setattr(M, "_ensure_final_save", fake_save)
    monkeypatch.setattr(M, "_finalize_enrichment", _noop_finalize)

    c, sid = _client_session()
    with c.websocket_connect(f"/ws/{sid}") as ws:
        rd = _Reader(ws)
        rd.read(cap=1)  # start turn Q1 (exactly one token)
        ws.send_text(json.dumps({"text": "ans"}))
        envs = rd.read(cap=5)
    kinds = [e.get("type") for e in envs]
    assert {"score", "report"} <= set(kinds), envs
    assert fake.calls["n"] == 2  # failed once, replayed once
    assert saved["scores"] == [8.0]  # single score — never duplicated


def test_reported_instead_of_probing_routes_to_report(monkeypatch):
    """Bank exhausted + FOLLOW_UP verdict + streamed 'Verdict:' line (the agent
    reported instead of probing) must end the interview with a report signal —
    not strand the socket open on a dead probe."""
    fake = _scripted_stream(
        {
            1: [
                ("yield", ("score", (4.0, "FOLLOW_UP"))),
                ("yield", ("token", "Score: 4/10. Interview Report. Verdict: No Hire.")),
            ]
        }
    )
    monkeypatch.setattr(M, "stream_events", fake)
    monkeypatch.setattr(M, "stream_reply", _fake_reply)

    async def fake_exhausted(session_id, user_id="local-dev"):
        return True

    monkeypatch.setattr(M, "bank_exhausted", fake_exhausted)
    monkeypatch.setattr(M, "_finalize_enrichment", _noop_finalize)

    c, sid = _client_session()
    with c.websocket_connect(f"/ws/{sid}") as ws:
        rd = _Reader(ws)
        rd.read(cap=1)  # start turn Q1
        ws.send_text(json.dumps({"text": "ans"}))
        envs = rd.read(cap=6)
    kinds = [e.get("type") for e in envs]
    assert "score" in kinds, envs
    assert "report" in kinds, envs  # routed despite the open probe


def test_follow_up_then_end_still_records_round(monkeypatch):
    """A scored answer whose verdict is FOLLOW_UP must still count as a round
    when the interview ends with the probe unanswered. Previously it recorded
    nothing → 0 questions / 0.0 'No Hire' for a real 6/10 answer, and the
    summarizer was skipped (no answers), leaving study/verdict as placeholders."""
    fake = _scripted_stream(
        {
            1: [
                ("yield", ("score", (6.0, "FOLLOW_UP"))),
                ("yield", ("eval", {"strengths": "S", "gaps": "G"})),
            ]
        }
    )
    monkeypatch.setattr(M, "stream_events", fake)
    monkeypatch.setattr(M, "stream_reply", _fake_reply)
    monkeypatch.setattr(M, "RETRY_DELAY_S", 0.01)

    saved = {}

    async def fake_save(sid, scores, config, user_id=""):
        saved["scores"] = list(scores)

    monkeypatch.setattr(M, "_ensure_final_save", fake_save)
    monkeypatch.setattr(M, "_finalize_enrichment", _noop_finalize)

    c, sid = _client_session(num_questions=1)
    with c.websocket_connect(f"/ws/{sid}") as ws:
        rd = _Reader(ws)
        rd.read(cap=1)  # start turn Q1
        ws.send_text(json.dumps({"text": "my answer"}))
        envs = rd.read(cap=3)
        assert any(e.get("type") == "score" for e in envs), envs
        ws.send_text(json.dumps({"end": True}))
        rd.read(cap=3)  # report text streaming from the End path
    assert saved.get("scores") == [6.0], saved  # provisional round kept


def test_follow_up_verdict_is_its_own_round(monkeypatch):
    """Two answers = two rounds, even when the evaluator votes FOLLOW_UP.

    Probes are disabled in every mode (interviewer.py:39 + _effective_signal),
    so the old open-probe bookkeeping — which folded the second answer into the
    first round's slot, reporting "2 Questions" for a 3-answer interview — is
    gone. Nothing is double-counted either way: each score lands in exactly one
    round.
    """
    fake = _scripted_stream(
        {
            1: [("yield", ("score", (5.0, "FOLLOW_UP")))],
            2: [("yield", ("score", (8.0, "NEXT")))],
        }
    )
    monkeypatch.setattr(M, "stream_events", fake)
    monkeypatch.setattr(M, "stream_reply", _fake_reply)

    saved = {}

    async def fake_save(sid, scores, config, user_id=""):
        saved["scores"] = list(scores)

    monkeypatch.setattr(M, "_ensure_final_save", fake_save)
    monkeypatch.setattr(M, "_finalize_enrichment", _noop_finalize)

    c, sid = _client_session(num_questions=2)
    with c.websocket_connect(f"/ws/{sid}") as ws:
        rd = _Reader(ws)
        rd.read(cap=1)  # start turn Q1
        ws.send_text(json.dumps({"text": "ans1"}))
        rd.read(cap=3)  # FOLLOW_UP score — a closed round now
        ws.send_text(json.dumps({"text": "ans2"}))
        rd.read(cap=5)  # NEXT score + report signal (2 of 2 rounds)
    assert saved.get("scores") == [5.0, 8.0], saved  # appended, neither lost


def test_report_text_without_tools_still_routes_and_scores(monkeypatch):
    """The agent can write the whole report as text WITHOUT calling any tool
    (Lite does this under load). The backend must parse that text: adopt the
    score and route on the Verdict line instead of stranding the stage page.
    This is the exact failure that left the report on screen, unrouted."""
    report = (
        "Score: 7/10 — Solid foundational understanding.\n"
        "Interview Report\n"
        "Strengths:\n• Accurately identified core concepts.\n"
        "Gaps:\n• Missed planning, tool use, and memory.\n"
        "What to Study Next:\n1. ReAct framework\n2. Tool use\n"
        "Verdict: Hire — Solid foundational understanding.\n"
    )

    async def fake_stream(session_id, text, user_id="local-dev"):
        yield ("token", report)  # one chunk, no score/eval/bank events at all

    async def fake_exhausted(session_id, user_id="local-dev"):
        return False  # no bank stored either — zilch from the agent

    monkeypatch.setattr(M, "stream_events", fake_stream)
    monkeypatch.setattr(M, "stream_reply", _fake_reply)
    monkeypatch.setattr(M, "bank_exhausted", fake_exhausted)

    saved = {}

    async def fake_save(sid, scores, config, user_id=""):
        saved["scores"] = list(scores)

    monkeypatch.setattr(M, "_ensure_final_save", fake_save)

    captured = {}

    async def fake_finalize(sid):
        captured["parsed"] = dict(M._report_parsed.get(sid, {}))

    monkeypatch.setattr(M, "_finalize_enrichment", fake_finalize)

    c, sid = _client_session(num_questions=1)
    with c.websocket_connect(f"/ws/{sid}") as ws:
        rd = _Reader(ws)
        rd.read(cap=1)  # start turn Q1
        ws.send_text(json.dumps({"text": "my answer"}))
        envs = rd.read(cap=6)
    kinds = [e.get("type") for e in envs]
    assert "score" in kinds, envs  # text score adopted -> badge actually shows
    assert "report" in kinds, envs  # routed, not stranded
    assert saved.get("scores") == [7.0], saved
    assert captured.get("parsed", {}).get("verdict") == "Hire", captured
    assert "ReAct" in captured.get("parsed", {}).get("study_next", ""), captured


def test_scored_then_died_still_routes_to_report(monkeypatch):
    """Verdict lands (badge up, round counted) and the reply text THEN 503s:
    a completed interview must route to the report, not strand on an error."""
    fake = _scripted_stream(
        {
            1: [
                ("yield", ("score", (6.0, "NEXT"))),
                ("raise", Fake503("reply died")),
            ]
        }
    )
    monkeypatch.setattr(M, "stream_events", fake)
    monkeypatch.setattr(M, "stream_reply", _fake_reply)
    monkeypatch.setattr(M, "RETRY_DELAY_S", 0.01)
    monkeypatch.setattr(M, "_finalize_enrichment", _noop_finalize)

    c, sid = _client_session()
    with c.websocket_connect(f"/ws/{sid}") as ws:
        rd = _Reader(ws)
        rd.read(cap=1)  # start turn Q1
        ws.send_text(json.dumps({"text": "ans"}))
        envs = rd.read(cap=5)
    kinds = [e.get("type") for e in envs]
    assert "score" in kinds, envs
    assert "report" in kinds, envs  # ended, not stranded
    assert "error" not in kinds, envs  # no error banner for a done interview


def test_finish_enriches_before_dropping_state(monkeypatch):
    """Enrichment must run while _answers/_eval_notes still exist. Dropping
    state first left every report rendering the frontend's static placeholders
    (the "same three cards every session" bug)."""
    fake = _scripted_stream(
        {
            1: [
                ("yield", ("score", (8.0, "NEXT"))),
                ("yield", ("eval", {"strengths": "S", "gaps": "G"})),
            ]
        }
    )
    monkeypatch.setattr(M, "stream_events", fake)
    monkeypatch.setattr(M, "stream_reply", _fake_reply)
    monkeypatch.setattr(M, "RETRY_DELAY_S", 0.01)

    async def fake_save(sid, scores, config, user_id=""):
        return None

    monkeypatch.setattr(M, "_ensure_final_save", fake_save)

    seen = {}

    async def record_finalize(sid):
        seen["answers"] = dict(M._answers.get(sid, {}))
        seen["notes"] = list(M._eval_notes.get(sid, []))

    monkeypatch.setattr(M, "_finalize_enrichment", record_finalize)

    c, sid = _client_session(num_questions=1)
    with c.websocket_connect(f"/ws/{sid}") as ws:
        rd = _Reader(ws)
        rd.read(cap=1)  # start turn Q1
        ws.send_text(json.dumps({"text": "my answer"}))
        envs = rd.read(cap=5)
    assert "report" in [e.get("type") for e in envs], envs
    # State was still alive when enrichment ran — proven by non-empty capture.
    assert seen.get("answers") == {0: "my answer"}, seen
    assert seen.get("notes") == [{"strengths": "S", "gaps": "G"}], seen


def test_persistent_failure_surfaces_resend(monkeypatch):
    fake = _scripted_stream({1: [("raise", Fake503("x"))], 2: [("raise", Fake503("x"))]})
    monkeypatch.setattr(M, "stream_events", fake)
    monkeypatch.setattr(M, "stream_reply", _fake_reply)
    monkeypatch.setattr(M, "RETRY_DELAY_S", 0.01)

    c, sid = _client_session()
    with c.websocket_connect(f"/ws/{sid}") as ws:
        rd = _Reader(ws)
        rd.read(cap=1)  # start turn Q1 (exactly one token)
        ws.send_text(json.dumps({"text": "ans"}))
        envs = rd.read(cap=5)
    assert fake.calls["n"] == 2  # exactly one replay, then surfaced
    assert any(e.get("type") == "error" and "Fake503" in e.get("message", "") for e in envs)


def test_post_output_failure_never_replays(monkeypatch):
    # NOTE: num_questions=2 — on a final turn the swallow guard eats tokens by
    # design, so the post-output case needs a non-final turn to be meaningful.
    fake = _scripted_stream(
        {1: [("yield", ("token", "hi ")), ("raise", Fake503("late"))]}
    )
    monkeypatch.setattr(M, "stream_events", fake)
    monkeypatch.setattr(M, "stream_reply", _fake_reply)
    monkeypatch.setattr(M, "RETRY_DELAY_S", 0.01)

    c, sid = _client_session(num_questions=2)
    with c.websocket_connect(f"/ws/{sid}") as ws:
        rd = _Reader(ws)
        rd.read(cap=1)  # start turn Q1 (exactly one token)
        ws.send_text(json.dumps({"text": "ans"}))
        envs = rd.read(cap=5)
    assert fake.calls["n"] == 1  # streamed text must never double-print
    assert [e.get("type") for e in envs].count("token") == 1
    assert any(e.get("type") == "error" for e in envs)


def test_voice_replay_then_round(monkeypatch):
    import backend.voice_bridge as vb
    from backend.schemas import SessionConfig

    fake = _scripted_stream(
        {
            1: [("raise", Fake503("boom"))],
            2: [("yield", ("score", (7.0, "NEXT"))), ("yield", ("token", "done"))],
        }
    )
    monkeypatch.setattr(vb, "stream_events", fake)
    monkeypatch.setattr(vb, "RETRY_DELAY_S", 0.01)

    async def scenario():
        b = vb.VoiceBridge(
            api_key="dummy",
            session_id="s",
            config=SessionConfig(mode="A", num_questions=1),
            user_id="u",
        )
        ended = await b._run_turn("ans")
        return ended, b.rounds, fake.calls["n"]

    ended, rounds, calls = asyncio.run(scenario())
    assert (ended, rounds, calls) == (True, [7.0], 2)


def test_is_retryable_matrix():
    from backend.runner import _is_retryable

    class Name503(Exception):
        code = 503

    class Name504(Exception):
        code = 504

    class Name429(Exception):
        code = 429

    class Exhausted(Exception):
        pass

    Exhausted.__name__ = "_ResourceExhaustedError"

    class Name500(Exception):
        code = 500

    assert _is_retryable(Name503("x")) is True
    assert _is_retryable(Name504("x")) is True
    assert _is_retryable(Name429("x")) is True
    assert _is_retryable(Exhausted("x")) is True
    assert _is_retryable(Name500("x")) is False
    assert _is_retryable(ValueError("x")) is False


def test_sleep_or_gone():
    """Retry sleep aborts fast on disconnect, waits fully when connected."""
    from types import SimpleNamespace

    from starlette.websockets import WebSocketState

    async def scenario():
        gone = SimpleNamespace(client_state=WebSocketState.DISCONNECTED)
        t0 = asyncio.get_event_loop().time()
        assert await M._sleep_or_gone(gone, 30) is True
        assert asyncio.get_event_loop().time() - t0 < 5
        live = SimpleNamespace(client_state=WebSocketState.CONNECTED)
        assert await M._sleep_or_gone(live, 0.05) is False

    asyncio.run(scenario())
