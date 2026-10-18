"""Shared model + session-state contract for the InterviewIQ agents."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))  # tools/FastAPI get keys without adk

import logging

# Silence genai's AFC advisory (our single-shot generate_content calls don't use
# Chat AFC; the warning is noise, not an error). Errors still surface.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# Single model for the whole system: gemini-3.5-flash-lite (500 RPD headroom).
# Flow compliance is structural (one-way transfers, evaluator-as-tool, schemas),
# not model-dependent. Flash/Gemma stays out: 20 RPD wall / 500s on tool calls.
_MODEL = "gemini-3.5-flash-lite"

# 503 UNAVAILABLE is per-MODEL on AI Studio ("high demand" for that one model),
# so a different Flash-Lite variant usually has capacity. The chain is tried in
# order; override without a code change via INTERVIEWIQ_MODELS (comma-separated).
_MODEL_CHAIN = [
    m.strip()
    for m in os.getenv(
        "INTERVIEWIQ_MODELS",
        "gemini-3.5-flash-lite,gemini-2.5-flash-lite,gemini-3.1-flash-lite",
    ).split(",")
    if m.strip()
]

from google.adk.models import BaseLlm, Gemini  # noqa: E402
from google.genai import types  # noqa: E402


def _retry_options() -> types.HttpRetryOptions:
    """BOUNDED client retry.

    The genai client retries 503s internally, and unbounded that turns one call
    into a multi-minute hang (measured: 560s on gemini-3.1-flash-lite). A short
    bound makes a contended model fail fast so the fallback can take over and
    the WS layer can show an honest retry instead of appearing frozen.
    """
    return types.HttpRetryOptions(
        initial_delay=1,
        attempts=int(os.getenv("INTERVIEWIQ_MODEL_ATTEMPTS", "2")),
    )


def _is_capacity_error(ex: BaseException) -> bool:
    """True for the per-model capacity signals worth falling back on
    (503 UNAVAILABLE / 429 RESOURCE_EXHAUSTED). Anything else is a real bug and
    must surface unchanged."""
    text = f"{type(ex).__name__}: {ex}".lower()
    return any(
        k in text
        for k in ("unavailable", "503", "resourceexhausted", "resource_exhausted", "429")
    )


class FallbackLlm(BaseLlm):
    """Try each Flash-Lite backend in turn on capacity errors.

    Fallback happens ONLY before any text is emitted: a mid-stream switch would
    duplicate already-sent tokens. Once anything has been yielded, the error is
    raised instead — the websocket layer replays clean misses safely.
    """

    model: str = _MODEL
    backends: list[BaseLlm] = []

    async def generate_content_async(self, llm_request, stream: bool = False):  # type: ignore[override]
        targets = self.backends or [Gemini(model=_MODEL, retry_options=_retry_options())]
        last: BaseException | None = None
        for idx, backend in enumerate(targets):
            emitted = False
            # ADK's Gemini picks the model off the REQUEST, not off the backend
            # (google_llm.py: "model = llm_request.model"), so the per-backend
            # model must be written onto the request or every attempt would hit
            # the same contended model.
            #
            # SHALLOW copy only (we rewrite one scalar field). A deep copy was
            # the first version and it crashed EVERY real fallback: ADK's
            # LlmRequest holds live client internals (a `_thread.lock`), so
            # model_copy(deep=True) raised "cannot pickle '_thread.lock' object"
            # and killed the turn instead of falling back. A synthetic request
            # in tests deep-copies fine, so the unit test passed while the real
            # path died.
            req = llm_request.model_copy()
            req.model = backend.model
            try:
                async for response in backend.generate_content_async(req, stream=stream):
                    emitted = True
                    yield response
                return
            except Exception as ex:  # noqa: BLE001 — decide, then re-raise
                last = ex
                if emitted or idx == len(targets) - 1 or not _is_capacity_error(ex):
                    raise
                logging.getLogger("interviewiq.model").warning(
                    "model %s hit capacity (%s); falling back to %s",
                    backend.model,
                    type(ex).__name__,
                    targets[idx + 1].model,
                )
        if last is not None:  # pragma: no cover — loop always returns or raises
            raise last


def build_model() -> FallbackLlm:
    """Single entry point every agent uses for its model."""
    return FallbackLlm(
        model=_MODEL,
        backends=[
            Gemini(model=name, retry_options=_retry_options()) for name in _MODEL_CHAIN
        ],
    )


def http_options() -> types.HttpOptions:
    """Bounded-retry HttpOptions for the raw-genai helper clients (retrieval
    rewrite, translate) so they cannot hang for minutes on a 503 either."""
    return types.HttpOptions(retry_options=_retry_options())


# Session state keys (managed via session.state, persona injected per session):
#   mode: A | B | C | D        difficulty: easy | medium | hard
#   persona_role, persona_tone transcript[], scores[]
