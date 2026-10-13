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

    async def fake_save(sid, scores, config):
        saved["scores"] = list(scores)

    monkeypatch.setattr(M, "_ensure_final_save", fake_save)

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
