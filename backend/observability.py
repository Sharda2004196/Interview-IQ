"""Langfuse tracing — one trace per interview session, one span per turn.

Fail-closed design: every helper swallows its own errors and returns None.
Tracing must NEVER break an interview (bad keys, no network, SDK drift).
No keys in env -> fully inert (local dev without Langfuse keeps working).
"""

import logging
import os

log = logging.getLogger(__name__)

_client = None
_warned = False
# session_id -> trace_id (one trace per interview, spans attach to it)
_traces: dict[str, str] = {}


def _keys():
    pub = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sec = os.getenv("LANGFUSE_SECRET_KEY", "")
    host = os.getenv("LANGFUSE_HOST", "") or os.getenv("LANGFUSE_BASE_URL", "")
    env = os.getenv("LANGFUSE_ENV", "development")
    if not (pub and sec and host):
        return None
    return pub, sec, host, env


def get_client():
    """Singleton Langfuse client, or None when unconfigured/broken."""
    global _client, _warned
    if _client is not None:
        return _client
    try:
        from langfuse import Langfuse

        k = _keys()
        if k is None:
            return None
        pub, sec, host, env = k
        _client = Langfuse(
            public_key=pub, secret_key=sec, host=host, environment=env
        )
        return _client
    except Exception as ex:  # noqa: BLE001 — tracing is best-effort
        if not _warned:
            log.warning("Langfuse disabled (%s: %s)", type(ex).__name__, ex)
            _warned = True
        return None


def trace_id_for(session_id: str) -> str | None:
    """Stable trace id per session (created once, reused by every turn span)."""
    if session_id not in _traces:
        try:
            c = get_client()
            if c is None:
                return None
            _traces[session_id] = c.create_trace_id()
        except Exception:  # noqa: BLE001
            return None
    return _traces.get(session_id)


def start_span(session_id: str, name: str, input=None, metadata=None):
    """Open a turn span under the session's trace. Returns span or None."""
    try:
        c = get_client()
        tid = trace_id_for(session_id)
        if c is None or tid is None:
            return None
        return c.start_observation(
            trace_context={"trace_id": tid},
            name=name,
            input=input,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001
        return None


def end_span(span, output=None, metadata=None, level: str = "DEFAULT"):
    """Close a span with output. Never raises."""
    if span is None:
        return
    try:
        span.update(output=output, metadata=metadata or {}, level=level)
        span.end()
    except Exception:  # noqa: BLE001
        pass


def score_span(span, name: str, value: float):
    """Attach a numeric score (e.g. round score) to a span. Never raises."""
    if span is None:
        return
    try:
        span.score(name=name, value=float(value))
    except Exception:  # noqa: BLE001
        pass


def flush():
    """Push buffered spans. Called on session end; never raises."""
    try:
        c = get_client()
        if c is not None:
            c.flush()
    except Exception:  # noqa: BLE001
        pass


def drop_session(session_id: str) -> None:
    _traces.pop(session_id, None)
