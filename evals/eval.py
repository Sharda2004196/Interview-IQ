"""Live LLM evals (spends Lite quota, ~8 calls). Run: python evals/eval.py
Writes evals/results.json. Exit 0 = all bands hold.

Bands are ranges, not exact scores — LLM judgment wobbles ±1 by design.
"""

import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from interviewiq_agent.agents.evaluator import evaluator
from interviewiq_agent.agents.question_generator import question_generator

APP = "interviewiq-eval"
UID = "eval"
results: list[dict] = []


async def ask(agent, text: str) -> str:
    svc = InMemorySessionService()
    run = Runner(agent=agent, app_name=APP, session_service=svc)
    sid = f"e-{len(results)}"
    await svc.create_session(app_name=APP, user_id=UID, session_id=sid)
    out = ""
    async for ev in run.run_async(
        user_id=UID,
        session_id=sid,
        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
    ):
        if ev.content and ev.content.parts:
            for p in ev.content.parts:
                if getattr(p, "text", None):
                    out += p.text
    return out


def clean_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


async def eval_case(name: str, agent, prompt: str, check) -> None:
    try:
        out = await ask(agent, prompt)
        ok, detail = check(out)
    except Exception as ex:  # noqa: BLE001 — eval must report, not crash
        ok, detail = False, f"error: {type(ex).__name__}: {str(ex)[:150]}"
    results.append({"case": name, "pass": ok, "detail": detail})
    print(("PASS" if ok else "FAIL"), "-", name, "|", detail, flush=True)


EVAL_Q = "Question: What is a Python decorator? Answer the candidate below."


async def main() -> int:
    await eval_case(
        "strong answer scores 8-10/NEXT",
        evaluator,
        f"{EVAL_Q}\nCandidate: A decorator is a callable taking a function and returning a wrapped function, applied with @syntax. Common for logging, auth, caching; functools.wraps preserves metadata.",
        lambda o: ((lambda d: (8 <= d["score"] <= 10 and d["signal"] == "NEXT", str(d)))(
            clean_json(o)
        )),
    )
    await eval_case(
        "partial answer scores 4-6/FOLLOW_UP",
        evaluator,
        f"{EVAL_Q}\nCandidate: A decorator wraps a function to add extra behavior, written with @ above the function. Used for logging.",
        lambda o: ((lambda d: (4 <= d["score"] <= 6 and d["signal"] == "FOLLOW_UP", str(d)))(
            clean_json(o)
        )),
    )
    await eval_case(
        "wrong answer scores 0-3",
        evaluator,
        f"{EVAL_Q}\nCandidate: A decorator is a design pattern for interior decoration of houses.",
        lambda o: ((lambda d: (0 <= d["score"] <= 3, str(d)))(clean_json(o))),
    )
    await eval_case(
        "correct-but-different scores >=7 (file is not the answer key)",
        evaluator,
        "Question: Name a Python web framework. File context: Our stack uses Flask. "
        "\nCandidate: FastAPI — async, Starlette-based, Pydantic validation, auto OpenAPI docs.",
        lambda o: ((lambda d: (d["score"] >= 7, str(d)))(clean_json(o))),
    )
    await eval_case(
        "generator returns exactly 3",
        question_generator,
        "Mode A, topic Python lists, medium difficulty, 3 questions. Output ONLY the list.",
        lambda o: ((lambda d: (len(d.get("questions", [])) == 3, str(d)[:150]))(
            clean_json(o)
        )),
    )
    # groundedness check with live Pinecone (no LLM judgment involved):
    from interviewiq_agent.tools.retrieve_context import retrieve_context, upsert_document

    upsert_document(
        "Our team deploys on Fly.io with Postgres and Redis. Framework: FastAPI.",
        "eval-ns",
        "eval-doc",
    )
    r = retrieve_context("Where does the team deploy?", "eval-ns", top_k=2)
    hit = any("Fly.io" in m["text"] for m in r["matches"])
    results.append(
        {
            "case": "groundedness: retrieval cites the ingested fact",
            "pass": hit,
            "detail": str(r["matches"][0]["text"][:100]) if r["matches"] else "no matches",
        }
    )
    print(("PASS" if hit else "FAIL"), "- groundedness", flush=True)
    from pinecone import Pinecone
    import interviewiq_agent.config  # noqa: F401  (loads .env)
    import os

    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    pc.Index(os.getenv("PINECONE_INDEX", "interviewiq-kb")).delete(
        delete_all=True, namespace="eval-ns"
    )

    passed = sum(1 for r in results if r["pass"])
    summary = {
        "at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    with open("evals/results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n{passed}/{len(results)} evals passed (see evals/results.json)", flush=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
