"""Live bridge probe (no mic): start + scripted answer through the transcript hook.

Proves: Live connect -> Runner Q1 -> speak -> answer -> score+Q2 spoken.
Run: python -u tests/live_bridge_probe.py  (spends a few Lite turns + Live TPM)
"""

import asyncio
import os
import sys

sys.path.insert(0, ".")

import interviewiq_agent.config  # noqa: F401  (loads .env)
from backend.schemas import SessionConfig
from backend.voice_bridge import VoiceBridge


async def main():
    stop = asyncio.Event()
    bridge = VoiceBridge(
        os.getenv("GOOGLE_API_KEY"),
        "voice-probe-1",
        SessionConfig(mode="A", topic="Python lists", num_questions=2),
    )
    task = asyncio.create_task(bridge.live.run(stop))
    await asyncio.sleep(10)  # let Live connect
    await bridge.start()
    await asyncio.sleep(45)  # Q1: Runner turn + speak turn
    print("SPOKEN AFTER START:", len(bridge.spoken_log), flush=True)
    await bridge._on_user_text("I do not know anything about lists.")
    await asyncio.sleep(75)  # answer: score turn + speak turn
    for i, s in enumerate(bridge.spoken_log):
        print(f"--- spoken[{i}] ({len(s)} chars): {s[:120]!r}", flush=True)
    q1 = len(bridge.spoken_log) >= 1 and "?" in bridge.spoken_log[0]
    bundled = len(bridge.spoken_log) >= 2 and (
        "Score:" in bridge.spoken_log[1] and "?" in bridge.spoken_log[1]
    )
    print("Q1 SPOKEN:", q1, "| SCORE+Q2 BUNDLED:", bundled, flush=True)
    stop.set()
    task.cancel()


asyncio.run(main())
