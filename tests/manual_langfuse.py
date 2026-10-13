"""Manual Langfuse connectivity proof: sends ONE labeled test trace and flushes.

Run: .\\.venv\\Scripts\\python.exe tests\\manual_langfuse.py
Then open Langfuse dashboard -> Traces -> look for "connectivity-test".
Proves: keys + host + SDK export path end-to-end (incl. OTEL_DISABLED env).
NOT part of pytest (writes to your Cloud project); run explicitly.
"""

import time

import interviewiq_agent.config  # noqa: F401 — side effect: loads interviewiq_agent/.env

from backend.observability import end_span, flush, get_client, start_span


def main() -> int:
    c = get_client()
    if c is None:
        print("NO CLIENT — check LANGFUSE_PUBLIC_KEY/SECRET_KEY/BASE_URL in .env")
        return 1
    sid = f"connectivity-{int(time.time())}"
    span = start_span(
        sid, "connectivity-test", input={"ping": "hello"}, metadata={"origin": "manual"}
    )
    if span is None:
        print("SPAN NOT CREATED — client inert, see warning above")
        return 1
    end_span(span, output={"pong": "world"})
    flush()
    try:
        from backend.observability import _traces

        tid = _traces.get(sid)
        print("TRACE ID:", tid)
        print("URL:", c.get_trace_url(tid) if tid else "(unknown)")
    except Exception:  # noqa: BLE001
        pass
    print("SENT — check dashboard Traces for 'connectivity-test'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
