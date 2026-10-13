"""Scripted interview-flow contract test (backend TestClient, live LLM).

Contract: Q1 single question -> answer -> score envelope + 'Score:' line + Q2
bundled -> end -> report tokens. Run after EVERY agent/prompt edit:
    .venv\Scripts\python.exe tests/test_interview_flow.py
Exit 0 = flow holds; nonzero = drift, do not ship the edit.
"""

import json
import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from backend.main import app

CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: bool):
    CHECKS.append((name, ok))
    print(("PASS" if ok else "FAIL"), "-", name)


def collect(ws, want: str, cap: int = 80) -> tuple[str, dict]:
    """Read envelopes until one of type `want` (or cap). Returns (tokens, found)."""
    tokens, found = "", {}
    for _ in range(cap):
        m = json.loads(ws.receive_text())
        if m["type"] == "token":
            tokens += m.get("text", "")
        if m["type"] == want:
            found = m
            break
    return tokens, found


def main() -> int:
    c = TestClient(app)
    r = c.post("/sessions", json={"mode": "A", "topic": "Python lists", "num_questions": 2})
    check("session created", r.status_code == 200)
    sid = r.json()["session_id"]

    with c.websocket_connect(f"/ws/{sid}") as ws:
        q1, _ = collect(ws, "__never__", cap=60)
        check("Q1 asked", "?" in q1)
        check("Q1 is single (<=2 '?')", q1.count("?") <= 2)

        ws.send_text(json.dumps({"text": "I do not know anything about lists."}))
        a1, score = collect(ws, "score", cap=80)
        check("score envelope fired", bool(score))
        check("score line spoken", "Score:" in a1)
        check("Q2 bundled", a1.count("?") >= 1)

        ws.send_text(json.dumps({"end": True}))
        rep, _ = collect(ws, "__never__", cap=80)
        check("report tokens flow", len(rep.strip()) > 0)

    failed = [n for n, ok in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
