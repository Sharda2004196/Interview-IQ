"""Langfuse tracing via native OTLP/HTTP — no Langfuse SDK dependency.

Why hand-rolled: langfuse>=4 needs opentelemetry-api>=1.45, which deadlocks
pip against google-adk 2.8.0 (otel<=1.42.1) and fails the Render Docker build.
Langfuse v4 accepts native OTLP spans at /api/public/otel (documented), so we
speak that protocol directly with httpx (already a dependency via ADK).

Same fail-closed contract: every helper swallows errors, returns None.
No keys -> fully inert. OTEL_SDK_DISABLED does not affect us (no SDK used).

Attribute map (per Langfuse native-OTel docs):
  trace name .... langfuse.trace.name
  session ...... langfuse.session.id
  user ......... langfuse.user.id
  environment .. langfuse.environment
  metadata ..... langfuse.trace.metadata.<key> (top-level, filterable)
  input/output . langfuse.observation.input / .output (JSON strings)
"""

import base64
import logging
import os
import secrets
import threading
import time

log = logging.getLogger(__name__)

_warned = False
# session_id -> trace_id (one trace per interview, spans attach to it)
_traces: dict[str, str] = {}
# Fire-and-forget send threads: tracing must never sit on the interview's
# critical path (a slow Langfuse day would slow every answer otherwise).
_lock = threading.Lock()
_pending: list[threading.Thread] = []


class _Span:
    """Opaque handle: ids + payload accumulated until end_span sends it."""

    __slots__ = ("trace_id", "span_id", "parent_id", "name", "start_ns", "attrs")

    def __init__(self, trace_id, span_id, parent_id, name, attrs):
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_id = parent_id
        self.name = name
        self.start_ns = time.time_ns()
        self.attrs = dict(attrs)


def _keys():
    pub = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sec = os.getenv("LANGFUSE_SECRET_KEY", "")
    host = (os.getenv("LANGFUSE_HOST", "") or os.getenv("LANGFUSE_BASE_URL", "")).rstrip("/")
    env = os.getenv("LANGFUSE_ENV", "development")
    if not (pub and sec and host):
        return None
    auth = base64.b64encode(f"{pub}:{sec}".encode()).decode()
    return host, auth, env


def _warn_once(msg: str, ex: Exception):
    global _warned
    if not _warned:
        log.warning("Langfuse disabled (%s: %s)", msg, ex)
        _warned = True


def get_client():
    """Compat shim: truthy when configured (keys present + httpx working)."""
    try:
        import httpx  # noqa: F401 — proves the only dependency exists

        return _keys() is not None
    except Exception as ex:  # noqa: BLE001
        _warn_once("no-http-client", ex)
        return None


def _any_value(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_any_value(i) for i in v]}}
    return {"stringValue": "" if v is None else str(v)}


def _send_async(path: str, payload: dict) -> None:
    """Queue an HTTP send on a daemon thread; never blocks the caller."""
    t = threading.Thread(target=_post, args=(path, payload), daemon=True)
    with _lock:
        _pending[:] = [p for p in _pending if p.is_alive()]
        _pending.append(t)
    t.start()


def _post(path: str, payload: dict, timeout: float = 10.0) -> bool:
    k = _keys()
    if k is None:
        return False
    host, auth, _env = k
    try:
        import httpx

        r = httpx.post(
            f"{host}{path}",
            json=payload,
            headers={
                "Authorization": f"Basic {auth}",
                "x-langfuse-ingestion-version": "4",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        if r.status_code >= 300:
            _warn_once(f"http-{r.status_code}", RuntimeError(r.text[:200]))
            return False
        return True
    except Exception as ex:  # noqa: BLE001
        _warn_once("send-failed", ex)
        return False


def trace_id_for(session_id: str) -> str | None:
    """Stable trace id per session (created once, reused by every turn span)."""
    if get_client() is None:
        return None
    if session_id not in _traces:
        _traces[session_id] = secrets.token_hex(16)
    return _traces.get(session_id)


def _base_attrs(
    session_id: str, extra_meta: dict, env: str, user_id: str | None = None
) -> dict:
    attrs = {
        "langfuse.session.id": session_id,
        "langfuse.environment": env,
    }
    # Reserved attribute Langfuse's Users view and cost-per-user rollups read.
    # Metadata (langfuse.trace.metadata.user) is NOT the same thing: it is just
    # a filterable key, so without this the trace stays anonymous in Users.
    if user_id:
        attrs["langfuse.user.id"] = user_id
    for k, v in (extra_meta or {}).items():
        attrs[f"langfuse.trace.metadata.{k}"] = v
    return attrs


def start_span(
    session_id: str,
    name: str,
    input=None,
    metadata=None,
    user_id: str | None = None,
):
    """Open a turn span (sent on end_span). Returns handle or None.

    `user_id` is the authenticated uid (Firebase), stamped as langfuse.user.id.
    """
    try:
        import json as _json

        k = _keys()
        tid = trace_id_for(session_id)
        if k is None or tid is None:
            return None
        _host, _auth, env = k
        attrs = _base_attrs(session_id, metadata, env, user_id)
        attrs["langfuse.trace.name"] = f"interview-{session_id}"
        attrs["langfuse.observation.type"] = "span"
        if input is not None:
            attrs["langfuse.observation.input"] = _json.dumps(input, default=str)
        return _Span(tid, secrets.token_hex(8), None, name, attrs)
    except Exception:  # noqa: BLE001
        return None


def end_span(span, output=None, metadata=None, level: str = "DEFAULT"):
    """Queue the span send (async thread, off the interview critical path)."""
    if span is None:
        return
    try:
        import json as _json

        if not isinstance(span, _Span):
            return
        for k, v in (metadata or {}).items():
            span.attrs[f"langfuse.trace.metadata.{k}"] = v
        span.attrs["langfuse.observation.level"] = level
        if output is not None:
            span.attrs["langfuse.observation.output"] = _json.dumps(output, default=str)
        end_ns = time.time_ns()
        otlp_span: dict = {
            "traceId": span.trace_id,
            "spanId": span.span_id,
            "name": span.name,
            "kind": 1,  # INTERNAL
            "startTimeUnixNano": str(span.start_ns),
            "endTimeUnixNano": str(end_ns),
            "attributes": [
                {"key": k, "value": _any_value(v)} for k, v in span.attrs.items()
            ],
            "status": {} if level != "ERROR" else {"code": 2},
        }
        if span.parent_id:
            otlp_span["parentSpanId"] = span.parent_id
        _send_async(
            "/api/public/otel/v1/traces",
            {"resourceSpans": [{"resource": {}, "scopeSpans": [{"scope": {}, "spans": [otlp_span]}]}]},
        )
    except Exception:  # noqa: BLE001
        pass


def score_span(span, name: str, value: float):
    """Attach a numeric score to the session trace. Never raises."""
    if span is None:
        return
    try:
        tid = span.trace_id if isinstance(span, _Span) else None
        if tid is None:
            return
        _send_async(
            "/api/public/scores",
            {"traceId": tid, "name": name, "value": float(value)},
        )
    except Exception:  # noqa: BLE001
        pass


def flush(timeout: float = 8.0):
    """Wait (bounded) for queued sends — called on session end so no span is
    lost to a container restart. Never raises, never blocks indefinitely."""
    try:
        deadline = time.monotonic() + max(0.0, timeout)
        with _lock:
            pending = list(_pending)
        for t in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            t.join(timeout=remaining)
    except Exception:  # noqa: BLE001
        pass


def drop_session(session_id: str) -> None:
    _traces.pop(session_id, None)
