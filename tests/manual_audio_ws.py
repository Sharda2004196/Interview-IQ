"""Manual Phase-2 loopback: proves /ws/audio wiring + Live reachability headless.

Flow: POST /sessions (1 round) -> WS /ws/audio -> expect audio_ready text ->
Q1 runs through Runner -> Live speaks it -> expect binary PCM frames.
Sends a few silence chunks (must not crash). NOT part of pytest (Live calls
+ ~2min wall time); run explicitly: .\\.venv\\Scripts\\python.exe tests\\manual_audio_ws.py
"""

import json

from fastapi.testclient import TestClient

from backend.main import app

SILENCE_100MS = bytes(3200)  # PCM16 mono @16kHz silence


def main() -> int:
    c = TestClient(app)
    r = c.post(
        "/sessions",
        json={"mode": "A", "topic": "Python GIL", "num_questions": 1},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    print("session:", sid, flush=True)

    got_ready, got_audio, errors = False, False, []
    audio_frames: list[int] = []
    with c.websocket_connect(f"/ws/audio/{sid}") as ws:
        for _ in range(400):  # ~200s cap at typical pacing
            try:
                ws.send_bytes(SILENCE_100MS)
            except Exception as ex:  # noqa: BLE001 — socket may close at report
                print("send ended:", type(ex).__name__, flush=True)
                break
            m = ws.receive()
            if "text" in m:
                try:
                    env = json.loads(m["text"])
                except ValueError:
                    continue
                print("TEXT:", env.get("type"), flush=True)
                if env.get("type") == "audio_ready":
                    got_ready = True
                elif env.get("type") == "report":
                    break  # interview over (needs a real answer; silence won't get here)
                elif env.get("type") == "error":
                    errors.append(env.get("message"))
                    break
            elif "bytes" in m:
                got_audio = True
                print("AUDIO bytes:", len(m["bytes"]), flush=True)
                audio_frames.append(len(m["bytes"]))
                if len(audio_frames) >= 5:
                    break
    print(f"audio_ready={got_ready} q1_audio={got_audio} errors={errors}", flush=True)
    print(f"first frames: {audio_frames} total_pcm={sum(audio_frames)}", flush=True)
    ok = got_ready and not errors and sum(audio_frames) > 1000
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
