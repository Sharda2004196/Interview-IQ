"""Offline debounce proof: fragments within the silence window fuse into ONE turn.

No network (Live/Runner never start; _on_user_text is stubbed). Slow by design
(~2s wall time) — keep in the suite, it guards the partial-answer-scoring bug.
"""

import asyncio

from backend.schemas import SessionConfig
from backend.voice_bridge import VoiceBridge


def _bridge(monkeypatch=None):
    return VoiceBridge(
        api_key="dummy", session_id="s", config=SessionConfig(mode="A"), user_id="u"
    )


def test_fragments_fuse_into_one_turn(monkeypatch):
    import backend.voice_bridge as vb

    monkeypatch.setattr(vb, "UTTERANCE_SILENCE_S", 0.3)

    async def scenario():
        b = _bridge()
        calls: list[str] = []

        async def fake_turn(text: str):
            calls.append(text)

        b._on_user_text = fake_turn  # type: ignore[method-assign]
        await b._handle_user_transcript("Eh, AI agent is like an LLM.")
        await asyncio.sleep(0.1)
        await b._handle_user_transcript("That's the like main difference.")
        await asyncio.sleep(0.8)
        return calls

    assert asyncio.run(scenario()) == [
        "Eh, AI agent is like an LLM. That's the like main difference."
    ]


def test_close_flushes_partial():
    async def scenario():
        b = _bridge()
        calls: list[str] = []

        async def fake_turn(text: str):
            calls.append(text)

        b._on_user_text = fake_turn  # type: ignore[method-assign]
        await b._handle_user_transcript("unfinished thought")
        await b.close()
        return calls

    assert asyncio.run(scenario()) == ["unfinished thought"]
