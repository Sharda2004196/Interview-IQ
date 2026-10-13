"""Manual voice interview — no frontend needed. Talk, hear the interviewer reply.

Run:  .venv\\Scripts\\python.exe tests/manual_voice.py --topic "Python lists"
      (Ctrl+C to stop. Optional: --mode B --questions "Q1|Q2" | --num 3)

Needs: working mic + speakers, GOOGLE_API_KEY + PINECONE_API_KEY in
interviewiq_agent/.env. Transcripts print here so you can verify by eye.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, ".")

import interviewiq_agent.config  # noqa: F401  (loads .env)
import pyaudio
from backend.schemas import SessionConfig
from backend.voice_bridge import VoiceBridge

RATE = 16000
CHUNK = 1024


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="A")
    ap.add_argument("--topic", default="Python lists")
    ap.add_argument("--questions", default="")
    ap.add_argument("--num", type=int, default=3)
    args = ap.parse_args()

    config = SessionConfig(
        mode=args.mode,
        topic=args.topic,
        custom_questions=[q for q in args.questions.split("|") if q.strip()],
        num_questions=args.num,
    )
    bridge = VoiceBridge(os.getenv("GOOGLE_API_KEY"), "voice-manual-1", config)

    pa = pyaudio.PyAudio()
    print("--- input devices ---", flush=True)
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info.get("maxInputChannels", 0) > 0:
            mark = " <== DEFAULT" if i == pa.get_default_input_device_info()["index"] else ""
            print(f"[{i}] {info['name']}{mark}", flush=True)
    mic = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True,
                  frames_per_buffer=CHUNK)
    speaker = pa.open(format=pyaudio.paInt16, channels=1, rate=24000, output=True)
    loop = asyncio.get_running_loop()

    async def mic_pump():
        try:
            while True:
                data = await loop.run_in_executor(None, mic.read, CHUNK, False)
                await bridge.live.send_audio(data)
        except Exception as ex:  # noqa: BLE001 — mic must fail loudly, not silently
            print(f"\nMIC ERROR (typing still works): {ex}", flush=True)

    async def type_pump():
        """Typed fallback: type answers here, they ride the same pipeline."""
        while True:
            line = await loop.run_in_executor(None, input, "YOU (type)> ")
            if line.strip():
                await heard(line.strip())

    async def play_pcm(pcm: bytes):
        await loop.run_in_executor(None, speaker.write, pcm)

    async def heard(text: str):
        print(f"\nYOU: {text}", flush=True)
        await bridge._on_user_text(text)

    agent_buf: list[str] = []

    async def said(text: str):
        agent_buf.append(text)

    async def turn_done():
        if agent_buf:
            print(f"\nAGENT: {''.join(agent_buf)}", flush=True)
            agent_buf.clear()

    bridge.live.on_model_audio = play_pcm
    bridge.live.on_user_transcript = heard
    bridge.live.on_model_text = said
    bridge.live.on_turn_complete = turn_done

    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(bridge.live.run(stop)),
        asyncio.create_task(mic_pump()),
        asyncio.create_task(type_pump()),
    ]
    await asyncio.sleep(8)
    print("=== connected — starting interview, speak after the question ===", flush=True)
    await bridge.start()
    try:
        await stop.wait()  # runs until Ctrl+C
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        mic.close()
        speaker.close()
        pa.terminate()


asyncio.run(main())
