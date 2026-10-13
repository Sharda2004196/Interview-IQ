"""Diag: what happens during Q1? Logs envelope types, then exits."""

import json
import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from backend.main import app

c = TestClient(app)
sid = c.post("/sessions", json={"mode": "A", "topic": "Python lists", "num_questions": 2}).json()["session_id"]
with c.websocket_connect(f"/ws/{sid}") as ws:
    n_tokens = 0
    for i in range(120):
        m = json.loads(ws.receive_text())
        if m["type"] == "token":
            n_tokens += 1
            if n_tokens <= 3 or n_tokens % 20 == 0:
                print(f"token#{n_tokens}: {m['text'][:60]!r}", flush=True)
        else:
            print(f"[{m['type']}] {str(m)[:120]}", flush=True)
    print("hit 120 cap", flush=True)
