"""FastAPI app: sessions REST + interview WebSocket + upload + report read."""

import asyncio
import json
import os
import re
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState

from interviewiq_agent.tools.parse_file import parse_file
from interviewiq_agent.tools.retrieve_context import upsert_document

from .auth import STRICT, check_ws_token, get_current_user
from .observability import (
    drop_session as lf_drop_session,
    end_span as lf_end_span,
    flush as lf_flush,
    score_span as lf_score_span,
    start_span as lf_start_span,
)

from .runner import (
    RETRY_DELAY_QUICK_S,
    RETRY_DELAY_S,
    _is_quota_error,
    _is_retryable,
    bank_exhausted,
    build_retry_prompt,
    build_start_prompt,
    get_or_create_session,
    interview_started,
    question_bank,
    restore_qindex,
    snapshot_qindex,
    stream_events,
    stream_reply,
)
from .schemas import (
    CreateSessionResponse,
    PastSession,
    Report,
    SessionConfig,
    UploadResponse,
    WSError,
    WSScore,
    WSToken,
)

app = FastAPI(title="InterviewIQ backend")
# Browser frontend (localhost:3000 dev, Render URL in prod) talks cross-origin.
# Without this, preflights (OPTIONS) 405 and the UI can never read responses —
# even endpoints that succeed server-side, like your 200 /upload.
# FRONTEND_URL env adds the prod origin (Render); localhost always allowed.
_cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
if _frontend_url and _frontend_url not in _cors_origins:
    _cors_origins.append(_frontend_url)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
UPLOAD_DIR = Path(__file__).with_name("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Embedding + vector writes are the expensive part of an upload and they are
# paid from free-tier quota, so cap the bytes BEFORE parsing/embedding. This
# rejects after the body reaches the server (Starlette already spooled it) but
# before any model or Pinecone call.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session(config: SessionConfig, user_id: str = Depends(get_current_user)):
    # A client-chosen namespace is usable only by the account that uploaded it:
    # otherwise Mode C/D would retrieve someone else's resume as context.
    # 404 keeps "not yours" and "does not exist" indistinguishable.
    if config.file_namespace:
        from interviewiq_agent.tools.persistence import upload_owner

        existing = upload_owner(config.file_namespace)
        if existing and not _owned_by(existing, user_id):
            raise HTTPException(status_code=404, detail="Knowledge base not found.")
    session_id = f"sess-{uuid.uuid4().hex[:8]}"
    await get_or_create_session(session_id, config, user_id)
    # Seed the interview by sending the start prompt through the agent on first WS answer.
    # The stored config lives in ADK session state; WS drives the loop.
    await _remember_config(session_id, config, user_id)
    return CreateSessionResponse(session_id=session_id, user_id=user_id)


_pending_configs: dict[str, tuple[SessionConfig, str]] = {}
# Per-session interview truth, keyed by session_id at MODULE level (not handler
# locals): the frontend reconnects on drops, and a fresh handler must see the
# rounds scored before the drop. Lifetime matches _pending_configs (container
# restart wipes both anyway); entries are deleted on either end path.
_rounds: dict[str, list[float]] = {}
_probe_open: dict[str, bool] = {}
# Backend-owned report content: per-turn evaluator strengths/gaps + the raw
# answers behind them, keyed by ROUND (not by attempt — replays overwrite the
# same round idempotently) and excluding probe turns (clarifications are not
# rounds). The agent is ASKED to persist these via save_score but Lite
# routinely skips the call — these stores let the report endpoint enrich
# (or backfill) from code truth instead of hoping for obedience.
_eval_notes: dict[str, list[dict]] = {}
_answers: dict[str, dict[int, str]] = {}
# Round -> question TEXT, captured from next_question's bank frames (exact bank
# wording, 1-based index). Without this the transcript has answers but no
# questions, because nothing else records what was asked per round.
_questions: dict[str, dict[int, str]] = {}
# The agent's OWN final report text, parsed into the five report fields. This
# is exactly what the candidate saw on screen (adk-web parity) and is the
# highest-fidelity source — used before evaluator notes and the summarizer.
_report_parsed: dict[str, dict] = {}
# Sessions with an enrichment pass in flight. Prevents the finish-path pass and
# a concurrent report-page GET from both running the (slow) summarizer.
_enriching: set[str] = set()
# Last streamed turn text per session — used to RESYNC the stage page on socket
# reconnect instead of re-driving the model (which duplicates the conversation).
# _start_tries bounds how many start-family messages a session may accumulate.
_last_turn_text: dict[str, str] = {}
_start_tries: dict[str, int] = {}


def _drop_session_state(session_id: str) -> None:
    _rounds.pop(session_id, None)
    _probe_open.pop(session_id, None)
    _eval_notes.pop(session_id, None)
    _answers.pop(session_id, None)
    _questions.pop(session_id, None)
    _report_parsed.pop(session_id, None)
    _last_turn_text.pop(session_id, None)
    _start_tries.pop(session_id, None)


async def _remember_config(session_id: str, config: SessionConfig, user_id: str):
    _pending_configs[session_id] = (config, user_id)


async def _maybe_finish_interview(
    websocket: WebSocket,
    session_id: str,
    rounds: list,
    config: SessionConfig,
    ws_user: str,
    turn_scored: bool,
    reported: bool,
) -> bool:
    """Shared end-of-interview check for success AND failure paths.

    A turn can score and THEN die (reply generation 503s after the verdict).
    Without this shared check, the failure path breaks out and strands a
    completed interview on an error banner. Returns True when ended.
    """
    close_normally = (
        turn_scored
        and not _probe_open.get(session_id, False)
        and len(rounds) >= config.num_questions
    )
    # `reported` is the agent's own "Verdict:" line — a signal that does NOT
    # depend on any tool firing. Lite sometimes writes the whole report as text
    # without calling the evaluator or next_question; gating this on turn_scored
    # stranded a finished interview on the stage page with the report on screen.
    if not (close_normally or reported):
        return False
    await _ensure_final_save(session_id, rounds, config, ws_user)
    # Transcript BEFORE _drop_session_state (it wipes _rounds/_answers/_questions).
    await _persist_transcript(session_id, config, ws_user)
    await _send_safe(websocket, '{"type":"report"}')
    # Enrich the doc BEFORE dropping state. _eval_notes/_answers live only in
    # memory and _drop_session_state empties them, so a report-page GET arriving
    # after the drop can never enrich — that ordering was the bug behind the
    # same three cards in every session. Sent after the signal so navigation is
    # instant; the page polls for the text fields while this lands.
    await _finalize_enrichment(session_id)
    _drop_session_state(session_id)
    lf_flush()
    lf_drop_session(session_id)
    return True


def _start_prompt(config: SessionConfig) -> str:
    return build_start_prompt(config)


async def _send_safe(websocket: WebSocket, text: str) -> None:
    """Error-path send: never raise (socket may already be gone)."""
    try:
        await websocket.send_text(text)
    except Exception:  # noqa: BLE001 — reporting must not crash the handler
        pass


async def _sleep_or_gone(websocket: WebSocket, seconds: float) -> bool:
    """Retry-delay sleep that aborts when the client disconnects.

    Without this, a user closing the tab mid-retry leaves an orphaned turn:
    after the sleep it fires a full API round into the void — more 503s,
    more scary logs, all for nobody. Returns True when abandoned (caller
    must return immediately), False when the full delay elapsed.
    """
    end = asyncio.get_event_loop().time() + seconds
    while True:
        if websocket.client_state != WebSocketState.CONNECTED:
            return True
        remaining = end - asyncio.get_event_loop().time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(1.0, remaining))


async def _ensure_final_save(
    session_id: str, scores: list, config: SessionConfig, user_id: str = ""
) -> None:
    """Backfill the Firestore score doc when the agent presented the report
    without calling save_score (Lite skips it at turn end). Never overwrites
    an agent-made save (which carries real difficulties + nudge); the backfill
    uses session-level difficulty and nudge 0. Always merge-fills mode/topic
    so Past Reports listing works on agent-saved docs too.
    user_id pins ownership to the socket owner — NEVER the shared dev
    identity, or a logged-in owner's report vanishes from their list."""
    import asyncio

    from interviewiq_agent.tools.persistence import _db, fill_report_meta, save_score

    def _write():
        try:
            from interviewiq_agent.tools.persistence import weighted_overall

            ref = _db().collection("scores").document(session_id)
            snap = ref.get()
            if snap.exists:
                data = snap.to_dict() or {}
                if not data.get("per_question") and scores:
                    # Hollow agent save (empty per_question → overall 0.0). The
                    # rounds we actually scored are the truth. Merge ONLY the
                    # score fields so text the agent saved survives; the
                    # enrichment pass right after fills the rest.
                    diff = config.persona.difficulty
                    vals = [float(s) for s in scores]
                    diffs = [diff] * len(vals)
                    ref.set(
                        {
                            "per_question": vals,
                            "difficulties": diffs,
                            "overall": weighted_overall(vals, diffs, 0.0),
                            "mode": config.mode,
                            "topic": config.topic,
                            "user_id": data.get("user_id") or user_id,
                        },
                        merge=True,
                    )
                    return
                fill_report_meta(session_id, config.mode, config.topic)
                return
            if not scores:
                return
            diff = config.persona.difficulty
            save_score(
                session_id,
                [float(s) for s in scores],
                [diff] * len(scores),
                mode=config.mode,
                topic=config.topic,
                user_id=user_id,
            )
        except Exception:
            pass  # report page falls back; never break the signal on save error

    await asyncio.to_thread(_write)


def _build_turns(
    rounds: list,
    bank: list[str],
    captured: dict[int, str],
    answers: dict[int, str],
) -> list[dict]:
    """Pair each scored round with its question and answer.

    Pure so it can be tested without Firestore. `bank` (stored at setup) wins
    over `captured` (next_question frames) for the question column; a round with
    neither question nor answer is dropped rather than written as an empty card.
    """
    turns: list[dict] = []
    for idx, score_value in enumerate(rounds):
        q_text = (bank[idx] if idx < len(bank) else captured.get(idx, "")).strip()
        a_text = (answers.get(idx) or "").strip()
        if not q_text and not a_text:
            continue
        try:
            turn_score = float(score_value)
        except (TypeError, ValueError):
            turn_score = 0.0
        turns.append({"q": q_text, "a": a_text, "score": turn_score})
    return turns


async def _persist_transcript(
    session_id: str, config: SessionConfig, user_id: str = ""
) -> None:
    """Backend-owned transcript: rounds -> sessions/{id}.turns in Firestore.

    Same reasoning as _ensure_final_save: the agent is ASKED to call
    save_transcript, but Lite skips it at turn end. Verified against live
    Firestore — 25 sessions had scores docs and only 8 toy docs existed in
    `sessions`, none for a real sess-* id — so the report PDF's Q&A section was
    always empty. Code truth instead: questions from the stored bank (falling
    back to captured next_question frames), answers from _answers, scores from
    _rounds. Probe turns never open a round, so they are excluded by
    construction. user_id pins ownership to the socket owner — NEVER the shared
    dev identity, or a logged-in owner's transcript is invisible to them.
    """
    import asyncio

    rounds = list(_rounds.get(session_id, []))
    if not rounds:
        return
    bank = await question_bank(session_id, user_id)
    turns = _build_turns(
        rounds, bank, _questions.get(session_id, {}), _answers.get(session_id, {})
    )
    if not turns:
        return

    def _write():
        try:
            from interviewiq_agent.tools.persistence import save_transcript

            save_transcript(
                session_id,
                mode=config.mode,
                difficulty=config.persona.difficulty,
                turns=turns,
                user_id=user_id,
            )
        except Exception:
            pass  # transcript is additive; never break the report signal

    await asyncio.to_thread(_write)


def _effective_signal(sig: str | None) -> str | None:
    """Probes are disabled in EVERY mode, so a FOLLOW_UP vote is a closed round.

    A probe used to open a round that only the next verdict closed, which meant
    two of a candidate's answers could fold into one round and the report showed
    fewer questions than were answered (3 answers -> "2 Questions", with the
    round carrying the PROBE's score and the original answer's text). The
    interviewer is now instructed never to probe (interviewer.py:39), and this
    normalization guarantees it even if the evaluator still votes FOLLOW_UP:
    one answer -> one verdict -> one round, in text and voice alike.
    """
    if sig == "FOLLOW_UP":
        return "NEXT"
    return sig


def _apply_verdict(
    rounds: list,
    answers: dict,
    probe_open: bool,
    value: float,
    sig: str | None,
    answer_text: str,
) -> bool:
    """Fold one evaluator verdict into the round bookkeeping; returns the new
    probe_open flag.

    Round-truth: rounds are closed non-FOLLOW_UP verdicts. A FOLLOW_UP opens the
    question's round with a provisional score (so a probe the candidate never
    answered still leaves a round, not a 0.0 "No Hire"); the next verdict closes
    it by overwriting — never appending, or one question would count twice.
    Answers are pinned to their round at APPEND time, keyed by round index, so a
    replay overwrites identically.
    """
    if sig == "FOLLOW_UP":
        if not probe_open:
            rounds.append(value)
            _pin_answer(answers, len(rounds) - 1, answer_text)
            return True
        if rounds:
            rounds[-1] = value  # 2nd probe: latest wins
        return True
    if probe_open:
        if rounds:
            rounds[-1] = value  # closes the probe: same question, latest score
        return False
    rounds.append(value)
    _pin_answer(answers, len(rounds) - 1, answer_text)
    return False


def _pin_answer(answers: dict, index: int, answer_text: str) -> None:
    if answer_text.strip():
        answers[index] = answer_text.strip()[:2000]


# Free-tier guard: one Render instance + several Gemini calls per turn means
# parallel interviews contend for CPU and the per-minute quota. Slots bound
# SIMULTANEOUS interviews, not users. Keyed by session and refcounted so a
# reconnect reuses its own slot — a flaky network must never push someone out
# of their own interview. Single-process state is fine because the app runs on
# one instance (min-instances=0); scaling to two instances would need Redis.
MAX_CONCURRENT_INTERVIEWS = int(os.getenv("MAX_CONCURRENT_INTERVIEWS", "3"))
_active_interviews: dict[str, int] = {}  # session_id -> live socket count


def _acquire_slot(session_id: str) -> bool:
    """Reserve a live-interview slot. True = proceed.

    Already-active session -> always allowed (refcount++). Otherwise a new
    DISTINCT session only fits while fewer than MAX_CONCURRENT_INTERVIEWS are
    active. No await between check and mutation, so it is atomic on the loop.
    """
    if session_id in _active_interviews:
        _active_interviews[session_id] += 1
        return True
    if len(_active_interviews) >= MAX_CONCURRENT_INTERVIEWS:
        return False
    _active_interviews[session_id] = 1
    return True


def _release_slot(session_id: str) -> None:
    """Drop one live socket for `session_id`; idempotent, never negative."""
    remaining = _active_interviews.get(session_id, 0) - 1
    if remaining > 0:
        _active_interviews[session_id] = remaining
    else:
        _active_interviews.pop(session_id, None)


@app.websocket("/ws/{session_id}")
async def interview_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    # Flips to True only when this socket actually reserved a slot, so the
    # finally below cannot decrement someone else's interview on an early return.
    holds_slot = False
    # .get, NOT .pop: the frontend reconnects on drops, and a consumed config
    # turned every reconnect into "Unknown session" (the death loop you saw).
    pending = _pending_configs.get(session_id)
    try:
        if pending is None:
            await _send_safe(
                websocket,
                WSError(message="Unknown session — POST /sessions first.").model_dump_json(),
            )
            return
        config, ws_user = pending
        # Slots are reserved AFTER the pending check: a stray connect to an
        # unknown session id must not consume capacity.
        if not _acquire_slot(session_id):
            await _send_safe(
                websocket,
                WSError(
                    message="All interview slots are busy — try again in a minute."
                ).model_dump_json(),
            )
            try:
                await websocket.close()
            except RuntimeError:
                pass
            return
        holds_slot = True
        # WS auth state: any client message may carry {"token": ...} (verified
        # against the POST uid, consumed, never treated as an answer). Strict
        # mode refuses answers until a valid token has been seen.
        ws_authed = False
        # Closed rounds (non-FOLLOW_UP verdicts) + whether a probe is open.
        # A FOLLOW_UP opens a round that only the next verdict closes — ending
        # on bank state closed interviews on top of unanswered probes.
        # Module-level (reconnect-safe): a dropped socket's replacement handler
        # must inherit already-scored rounds, or End saves an empty report.
        rounds = _rounds.setdefault(session_id, [])
        _probe_open.setdefault(session_id, False)
        turn_meta = {"mode": config.mode, "user": ws_user, "socket": "text"}
        try:
            q1_parts: list[str] = []
            if await interview_started(session_id, ws_user):
                # The interview already began — this is a reconnect (or a second
                # handler after a drop). Re-driving the start prompt here appends
                # a SECOND setup message to the SAME ADK session (ADK persists
                # the user message before the model call), so the agent reads the
                # candidate as "repeating the setup prompt" and bails with a
                # bogus 0/10 No-Hire report. Resync the screen instead.
                resume = _last_turn_text.get(session_id)
                if resume:
                    await _send_safe(
                        websocket, json.dumps({"type": "question", "text": resume})
                    )
            else:
                start_tries = _start_tries.get(session_id, 0)
                if start_tries >= 4:
                    # Several failed start messages are already in the session;
                    # one more reads as spam and tempts the agent into inventing
                    # a report to escape. Fail honestly instead.
                    await _send_safe(
                        websocket,
                        WSError(
                            message="The interviewer is temporarily unavailable "
                            "(model capacity). Please start a new interview."
                        ).model_dump_json(),
                    )
                    return
                _start_tries[session_id] = start_tries + 1
                start_span = lf_start_span(
                    session_id,
                    "turn-0-start",
                    input={"mode": config.mode, "topic": config.topic,
                            "num_questions": config.num_questions},
                    metadata=turn_meta,
                    user_id=ws_user,
                )
                # Start-turn burst protection (same clean-miss rule as answer
                # turns): a 503/429 before ANY token streamed replays after a
                # short wait. The replay uses a NUDGE that says "continue", never
                # the verbatim start prompt (already in the session).
                for start_attempt in range(2):
                    q0 = await snapshot_qindex(session_id, ws_user)
                    q1_saw_output = False
                    st0 = asyncio.get_event_loop().time()
                    waited_start = 0.0
                    try:
                        async for delta in stream_reply(
                            session_id,
                            _start_prompt(config)
                            if start_attempt == 0
                            else build_retry_prompt("start"),
                            ws_user,
                        ):
                            q1_saw_output = True
                            q1_parts.append(delta)
                            await websocket.send_text(WSToken(text=delta).model_dump_json())
                        break
                    except WebSocketDisconnect:
                        lf_end_span(start_span, output={"status": "client-disconnected"})
                        return  # client hung up mid-stream; nothing to report to
                    except Exception as ex:  # noqa: BLE001 — replay once, else honest error
                        if _is_retryable(ex) and start_attempt == 0 and not q1_saw_output:
                            lf_end_span(
                                start_span,
                                output={"status": "superseded-by-replay"},
                                metadata={"error": f"{type(ex).__name__}: {ex}"},
                                level="WARNING",
                            )
                            await restore_qindex(session_id, ws_user, q0)
                            if await _sleep_or_gone(websocket, RETRY_DELAY_QUICK_S):
                                lf_end_span(start_span, output={"status": "abandoned-client-gone"})
                                return
                            waited_start += RETRY_DELAY_QUICK_S
                            continue
                        lf_end_span(
                            start_span,
                            output={"status": "failed"},
                            metadata={"error": f"{type(ex).__name__}: {ex}"},
                            level="ERROR",
                        )
                        await _send_safe(
                            websocket,
                            WSError(message=f"Start failed ({type(ex).__name__}); retry.").model_dump_json(),
                        )
                        return
                _last_turn_text[session_id] = "".join(q1_parts)
                lf_end_span(
                    start_span,
                    output={"q1": "".join(q1_parts)},
                    metadata={
                        "duration_s": round(asyncio.get_event_loop().time() - st0 - waited_start, 2),
                        "waited_s": round(waited_start, 2),
                    },
                )
        except WebSocketDisconnect:
            return  # client hung up mid-stream; nothing to report to
        except Exception as ex:  # noqa: BLE001 — one bad turn must not kill the interview
            await _send_safe(
                websocket,
                WSError(message=f"Start failed ({type(ex).__name__}); retry.").model_dump_json(),
            )
            return
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_safe(
                    websocket,
                    WSError(message="Send JSON: {\"text\": \"...\"} or {\"end\": true}.").model_dump_json(),
                )
                continue
            # WS auth frame: {"token": ...} is verified against the POST uid,
            # consumed, and never treated as an answer. Token-only frames set
            # the flag and wait; combined frames fall through to normal
            # answer/End processing below. Zero added latency (no waiting).
            try:
                if check_ws_token(msg, ws_user):
                    ws_authed = True
                    if not msg.get("text") and not msg.get("end"):
                        continue
            except HTTPException as ex:
                await _send_safe(
                    websocket,
                    WSError(message=f"Auth rejected ({ex.detail}).").model_dump_json(),
                )
                try:
                    await websocket.close()
                except RuntimeError:
                    pass
                return
            except Exception as ex:  # noqa: BLE001 — e.g. Firebase not configured
                await _send_safe(
                    websocket,
                    WSError(message=f"Auth unavailable ({type(ex).__name__}).").model_dump_json(),
                )
                try:
                    await websocket.close()
                except RuntimeError:
                    pass
                return
            if STRICT and not ws_authed:
                await _send_safe(
                    websocket,
                    WSError(message="Login required — reconnect with a token.").model_dump_json(),
                )
                try:
                    await websocket.close()
                except RuntimeError:
                    pass
                return
            if msg.get("end"):
                async for delta in stream_reply(
                    session_id, "The user ended the interview. Give the final report now.", ws_user
                ):
                    await websocket.send_text(WSToken(text=delta).model_dump_json())
                # Same safety net as auto-end: if the agent's own save failed
                # or was skipped, persist the rounds actually scored (empty when
                # nothing was answered — an honest 0, not a lost score).
                await _ensure_final_save(session_id, rounds, config, ws_user)
                await _persist_transcript(session_id, config, ws_user)
                await _finalize_enrichment(session_id)
                _drop_session_state(session_id)
                lf_flush()
                lf_drop_session(session_id)
                return
            # Burst protection: ONE silent replay when a retryable error
            # (429/503/504) kills a turn BEFORE it produced anything. Replaying
            # later would double-stream text and double-count scores, so the
            # replay only fires on a clean miss. The bank index is snapshotted
            # and rolled back so a dead attempt can't eat a dispense.
            for attempt in range(2):
                # Round-truth (not bank-truth): rounds = closed non-FOLLOW_UP
                # verdicts. The turn completing round N swallows text (phantom
                # Q(N+1) can never display); only a FOLLOW_UP probe may stream.
                # Bank exhaustion stays as a redundant swallow guard.
                rounds_before = len(rounds)
                final_turn = rounds_before >= max(config.num_questions - 1, 0)
                pre_exhausted = await bank_exhausted(session_id, ws_user)
                guard = pre_exhausted or final_turn
                q0 = await snapshot_qindex(session_id, ws_user)
                turn_scored, turn_signal, saw_output = False, None, False
                bank_done = False
                saw_verdict = False  # "Verdict:" streamed with bank exhausted =
                turn_tail = ""  # agent reported instead of probing; end below
                # Raw text for THIS turn — parsed into report fields at turn
                # end so a report written without tools still lands + routes.
                turn_text: list[str] = []
                answer_text = msg.get("text", "") or ""
                round_no = len(rounds) + 1
                t0 = asyncio.get_event_loop().time()
                waited = 0.0  # retry-sleep excluded from duration_s below
                span = lf_start_span(
                    session_id,
                    f"round-{round_no}-attempt-{attempt}",
                    input={"answer": answer_text},
                    metadata={**turn_meta, "round": round_no, "attempt": attempt},
                    user_id=ws_user,
                )
                try:
                    events = stream_events(
                        session_id,
                        answer_text if attempt == 0 else build_retry_prompt("answer"),
                        ws_user,
                    )
                    async for kind, payload in events:
                        if kind == "score":
                            turn_scored = True
                            saw_output = True
                            value, sig = payload  # (float, signal|None)
                            turn_signal = _effective_signal(sig)
                            # Replay-safe: re-folding the same verdict yields the
                            # same rounds/answers, so a retried turn can't double
                            # count.
                            _probe_open[session_id] = _apply_verdict(
                                rounds,
                                _answers.setdefault(session_id, {}),
                                _probe_open.get(session_id, False),
                                value,
                                turn_signal,
                                answer_text,
                            )
                            lf_score_span(span, "round_score", value)
                            await websocket.send_text(WSScore(value=value).model_dump_json())
                        elif kind == "eval":
                            # Evaluator's own words — backend-owned report content
                            # (survives even when the agent skips save_score).
                            _eval_notes.setdefault(session_id, []).append(payload)
                        elif kind == "bank":
                            bank_done = bool(payload.get("done"))
                            # Capture the exact bank question for its round
                            # (index is 1-based). This is the ONLY place the
                            # question text is recorded — the report parser sees
                            # the turn text, not per-round questions.
                            q_text = (payload.get("question") or "").strip()
                            try:
                                q_idx = int(payload.get("index", 0)) - 1
                            except (TypeError, ValueError):
                                q_idx = -1
                            if q_text and q_idx >= 0:
                                _questions.setdefault(session_id, {})[q_idx] = q_text
                            continue  # state reads cover exhaustion; no action needed
                        elif kind == "token":
                            # Capture ALWAYS — even when the final-turn guard
                            # swallows display. The report parser needs the
                            # text, and a swallowed report must still route.
                            turn_text.append(payload)
                            # Verdict marker survives chunk splits: check the
                            # previous tail JOINED with this chunk, then keep
                            # only the tail (a marker fully inside one chunk
                            # must not be truncated away before the check).
                            # The interviewer MUST end every report with a
                            # "Verdict:" line and never writes it elsewhere.
                            combined = (turn_tail + payload).lower()
                            if "verdict:" in combined:
                                saw_verdict = True
                            turn_tail = (turn_tail + payload)[-16:]
                            if guard and turn_signal != "FOLLOW_UP" and not saw_verdict:
                                continue  # hide phantom question text; still parsed
                            saw_output = True
                            await websocket.send_text(WSToken(text=payload).model_dump_json())
                        else:
                            continue
                except WebSocketDisconnect:
                    lf_end_span(span, output={"status": "client-disconnected"})
                    return
                except Exception as ex:  # noqa: BLE001 — replay once, else resend UX
                    if _is_retryable(ex) and attempt == 0 and not saw_output:
                        lf_end_span(
                            span,
                            output={"status": "superseded-by-replay"},
                            metadata={"error": f"{type(ex).__name__}: {ex}"},
                            level="WARNING",
                        )
                        await restore_qindex(session_id, ws_user, q0)
                        if await _sleep_or_gone(websocket, RETRY_DELAY_S):
                            return  # client left mid-retry; nothing to replay for
                        waited += RETRY_DELAY_S
                        continue
                    if _is_quota_error(ex):
                        message = (
                            "AI quota exhausted — wait a minute, then resend your "
                            "answer. Nothing was scored."
                        )
                    else:
                        message = f"Turn failed ({type(ex).__name__}); resend answer."
                    # Unswallowed traceback: this path silently turned real bugs
                    # into a one-line user message, which is why a mid-interview
                    # TypeError was invisible in `docker logs` and looked like
                    # "the interview just stopped early".
                    import logging as _logging

                    _logging.getLogger(__name__).exception(
                        "turn failed session=%s type=%s scored=%s",
                        session_id,
                        type(ex).__name__,
                        turn_scored,
                    )
                    lf_end_span(
                        span,
                        output={"status": "failed"},
                        metadata={"error": f"{type(ex).__name__}: {ex}"},
                        level="ERROR",
                    )
                    # Same text adoption as the clean path: an agent that wrote
                    # the report and THEN 503'd still has a routable report.
                    parsed = _parse_report_text("".join(turn_text)) if turn_text else {}
                    if saw_verdict and parsed:
                        _report_parsed[session_id] = parsed
                    if not turn_scored and parsed.get("score") is not None:
                        turn_scored = True
                        rounds.append(parsed["score"])
                        if answer_text.strip():
                            _answers.setdefault(session_id, {})[len(rounds) - 1] = (
                                answer_text.strip()[:2000]
                            )
                    # Scored-then-died: the verdict already landed (badge is up,
                    # round counted) and only the reply text 503'd. If rounds
                    # are complete — or the agent already showed its Verdict
                    # line — END instead of stranding on an error banner.
                    if await _maybe_finish_interview(
                        websocket, session_id, rounds, config, ws_user,
                        turn_scored=turn_scored, reported=saw_verdict,
                    ):
                        return
                    await _send_safe(
                        websocket,
                        WSError(message=message).model_dump_json(),
                    )
                    break
                # Adopt the agent's OWN report text. Parsing it lets the report
                # show exactly what the candidate saw, and rescues the score
                # when the evaluator tool never fired (rounds would stay empty).
                if turn_text:
                    _last_turn_text[session_id] = "".join(turn_text)
                parsed = _parse_report_text("".join(turn_text)) if turn_text else {}
                if saw_verdict and parsed:
                    _report_parsed[session_id] = parsed
                if not turn_scored and parsed.get("score") is not None:
                    turn_scored = True
                    rounds.append(parsed["score"])
                    if answer_text.strip():
                        _answers.setdefault(session_id, {})[len(rounds) - 1] = (
                            answer_text.strip()[:2000]
                        )
                    lf_score_span(span, "round_score_text", parsed["score"])
                    await websocket.send_text(
                        WSScore(value=parsed["score"]).model_dump_json()
                    )
                lf_end_span(
                    span,
                    output={"scored": turn_scored, "signal": turn_signal},
                    metadata={
                        "duration_s": round(asyncio.get_event_loop().time() - t0 - waited, 2),
                        "waited_s": round(waited, 2),
                    },
                )
                # End ONLY on closed rounds: len(rounds) >= N with no open probe.
                # Backfill saves rounds only, so the report always shows exactly N.
                # Second trigger — reported-instead-of-probing: bank exhausted
                # and the turn streamed the mandatory "Verdict:" line (the agent
                # chose the report over its FOLLOW_UP probe). Without this the
                # interview strands: report on screen, socket open, no routing.
                reported = saw_verdict
                if await _maybe_finish_interview(
                    websocket, session_id, rounds, config, ws_user,
                    turn_scored=turn_scored, reported=reported,
                ):
                    return
                break
    except WebSocketDisconnect:
        pass
    finally:
        if holds_slot:
            _release_slot(session_id)


@app.websocket("/ws/audio/{session_id}")
async def audio_ws(websocket: WebSocket, session_id: str):
    """Phase 2 voice socket (server VAD, barge-in native to Live).

    Contract (for the frontend client):
    - Client -> server binary frames: PCM16 mono @16kHz mic chunks (any size).
    - Client -> server text frames: {"type":"answer_done"} when the user taps
      Mic-done = the answer is COMPLETE, fire its single Runner turn NOW.
      (Silence backstop exists server-side, but explicit always wins.)
    - Server -> client binary frames: Live reply PCM @24kHz (play as-is).
    - Server -> client text frames: JSON control envelopes —
      {"type":"audio_ready","in_rate":16000,"out_rate":24000} on connect,
      {"type":"user_transcript","text"} as you speak (display only),
      {"type":"agent_transcript","text"} as the voice speaks (display only),
      {"type":"status","phase":"evaluating"} while a turn runs (display only),
      {"type":"report"} when N rounds close, {"type":"error",...} on failure.
    Brain path mirrors the text socket: same Runner session state, same
    round-truth end rule (kept inside VoiceBridge).

    PARKED: Live voice is disabled by default (VOICE_LIVE_ENABLED != "true").
    Voice mode now runs turn-based browser STT/TTS over the text socket —
    this endpoint stays for a possible future return, it is NOT the voice path.
    """
    from .voice_bridge import VoiceBridge

    await websocket.accept()
    if os.getenv("VOICE_LIVE_ENABLED", "false").lower() != "true":
        await _send_safe(
            websocket,
            WSError(
                message="Live voice is parked — use turn-based voice mode."
            ).model_dump_json(),
        )
        try:
            await websocket.close()
        except RuntimeError:
            pass
        return
    pending = _pending_configs.get(session_id)
    if pending is None:
        await _send_safe(
            websocket, WSError(message="Unknown session — POST /sessions first.").model_dump_json()
        )
        return
    config, ws_user = pending
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        await _send_safe(
            websocket, WSError(message="GOOGLE_API_KEY missing — voice unavailable.").model_dump_json()
        )
        return

    # Voice discipline: NO follow-up probes in voice mode, ever. Spoken
    # probes feel like cross-questioning and strand partial answers; the
    # interviewer instruction obeys this state flag (answer -> evaluate ->
    # next round, strictly). Session must exist first (bridge.start would
    # create it later — too late for Q1's turn).
    from .runner import _session_service, APP_NAME

    await get_or_create_session(session_id, config, ws_user)
    config.voice_mode = True  # same flag the text-socket voice path sets
    _voice_sess = await _session_service.get_session(
        app_name=APP_NAME, user_id=ws_user, session_id=session_id
    )
    if _voice_sess is not None:
        _voice_sess.state["voice_mode"] = True

    stop = asyncio.Event()
    outbox: asyncio.Queue = asyncio.Queue()
    bridge = VoiceBridge(api_key, session_id, config, ws_user)

    async def _emit_report():
        await outbox.put(("text", '{"type":"report"}'))
        stop.set()

    async def _emit_audio(pcm: bytes):
        await outbox.put(("bytes", pcm))

    async def _emit_transcript(kind: str, text: str):
        await outbox.put(("text", json.dumps({"type": f"{kind}_transcript", "text": text})))

    async def _emit_status(phase: str):
        await outbox.put(("text", json.dumps({"type": "status", "phase": phase})))

    async def _emit_error(message: str):
        await outbox.put(("text", json.dumps({"type": "error", "message": message})))

    bridge.on_report_due = _emit_report
    bridge.on_transcript = _emit_transcript
    bridge.on_status = _emit_status
    bridge.on_error = _emit_error
    bridge.live.on_model_audio = _emit_audio
    await outbox.put(
        ("text", json.dumps({"type": "audio_ready", "in_rate": 16000, "out_rate": 24000}))
    )

    async def _sender():
        try:
            while True:
                kind, payload = await outbox.get()
                if kind == "bytes":
                    await websocket.send_bytes(payload)
                else:
                    await websocket.send_text(payload)
        except (WebSocketDisconnect, RuntimeError):
            stop.set()

    live_task = asyncio.create_task(bridge.live.run(stop))
    sender_task = asyncio.create_task(_sender())
    # Q1 must wait for the Live socket: send_text drops while unconnected.
    for _ in range(150):
        if bridge.live._session is not None or stop.is_set():
            break
        await asyncio.sleep(0.2)
    if bridge.live._session is None:
        await _send_safe(
            websocket,
            WSError(message="Live voice unavailable — use text mode.").model_dump_json(),
        )
        stop.set()
        start_task = None
    else:
        start_task = asyncio.create_task(bridge.start())
    try:
        while not stop.is_set():
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                break
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data:
                await bridge.live.send_audio(bytes(data))
                continue
            text = msg.get("text")
            if text:
                # Explicit end-of-answer (Mic toggle): fire the single turn now.
                try:
                    if json.loads(text).get("type") == "answer_done":
                        await bridge.answer_complete()
                except (ValueError, AttributeError):
                    pass
    finally:
        stop.set()
        await asyncio.sleep(1.5)  # drain report frame + trailing audio
        try:
            await bridge.close()  # flush trailing partial answer into one turn
        except Exception:  # noqa: BLE001 — teardown must not raise
            pass
        for t in (sender_task, live_task, start_task):
            if t is not None:
                t.cancel()
        await asyncio.gather(
            *[t for t in (sender_task, live_task, start_task) if t is not None],
            return_exceptions=True,
        )
        try:
            await websocket.close()
        except RuntimeError:
            pass


@app.get("/sessions", response_model=list[PastSession])
async def list_sessions(user_id: str = Depends(get_current_user)):
    """Past Reports: newest-first session summaries for this user (max 50)."""
    from interviewiq_agent.tools.persistence import _db

    docs = (
        _db()
        .collection("scores")
        .where("user_id", "==", user_id)
        .limit(200)
        .stream()
    )
    out: list[PastSession] = []
    for d in docs:
        if not d.id.startswith("sess-"):
            continue  # eval fixtures share the dev uid; not real interviews
        s = d.to_dict() or {}
        ts = s.get("created_at")
        out.append(
            PastSession(
                session_id=d.id,
                mode=s.get("mode", "") or "",
                topic=s.get("topic", "") or "",
                rounds=len(s.get("per_question", []) or []),
                overall=float(s.get("overall", 0.0) or 0.0),
                created_at=ts.isoformat() if hasattr(ts, "isoformat") else "",
            )
        )
    # Newest-first in code: dated docs (ISO sorts lexically) before undated.
    out.sort(key=lambda i: (i.created_at != "", i.created_at), reverse=True)
    return out[:50]


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user_id: str = Depends(get_current_user)):
    """Delete one past session (score + transcript docs). Idempotent: always 200.

    Ownership: a doc that exists and belongs to someone else answers 404 (same
    rule as the report routes). Deletion is destructive, so it must never be
    cross-account; a MISSING doc still returns 200 so retries stay idempotent.
    """
    from interviewiq_agent.tools.persistence import _db

    db = _db()
    existing = db.collection("scores").document(session_id).get()
    if existing.exists and not _owned_by(existing.to_dict() or {}, user_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    batch = db.batch()
    batch.delete(db.collection("scores").document(session_id))
    batch.delete(db.collection("sessions").document(session_id))
    batch.commit()
    return {"deleted": session_id}


@app.delete("/sessions")
async def delete_all_sessions(user_id: str = Depends(get_current_user)):
    """Delete ALL past sessions for this user (score + transcript docs)."""
    from interviewiq_agent.tools.persistence import _db

    db = _db()
    count = 0
    batch = db.batch()
    for coll in ("scores", "sessions"):
        for d in db.collection(coll).where("user_id", "==", user_id).stream():
            batch.delete(d.reference)
            count += 1
            if count % 400 == 0:  # batch cap safety
                batch.commit()
                batch = db.batch()
    batch.commit()
    return {"deleted_count": count}


@app.get("/healthz")
async def healthz():
    """Render health check: fast, dependency-free (never touches Firestore)."""
    return {"ok": True}


@app.head("/healthz")
async def healthz_head():
    """Uptime monitors ping HEAD by default — same 200, empty body."""
    from fastapi.responses import Response

    return Response(status_code=200)


@app.post("/upload", response_model=UploadResponse)
async def upload(
    file: UploadFile,
    namespace: str = "default",
    user_id: str = Depends(get_current_user),
):
    """Auth-gated ingestion.

    Pins the client-chosen namespace to this caller and validates it first: a
    logged-in user may only append chunks to a namespace they own. Unrecorded
    namespaces stay writable (legacy/shared local-dev), and no token in strict
    mode means no writes into the vector index at all.
    """
    from interviewiq_agent.tools.persistence import save_upload_owner, upload_owner

    # Refuse a foreign namespace before touching disk or the vector index, so a
    # denied request cannot append chunks to someone else's resume.
    existing = upload_owner(namespace)
    if existing and not _owned_by(existing, user_id):
        raise HTTPException(status_code=403, detail="Namespace unavailable.")
    # Read at most cap+1: reading the whole body first would let one huge
    # upload exhaust the 512 MB instance BEFORE the 413 is ever raised.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(data) // (1024 * 1024)} MB). Max 5 MB.",
        )
    # Path(...).name strips any "../" in the client-supplied filename: the uuid
    # prefix does not stop traversal on its own.
    safe_name = Path(file.filename or "upload.bin").name
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}-{safe_name}"
    dest.write_bytes(data)
    parsed = parse_file(str(dest))
    n = upsert_document(parsed["text"], namespace, doc_name=parsed["file"])
    save_upload_owner(namespace, user_id, parsed["file"])
    return UploadResponse(
        file=parsed["file"], chars=parsed["chars"], chunks=n["chunks"], namespace=namespace
    )


async def _finalize_enrichment(session_id: str) -> None:
    """Persist backend-owned report content while the session's in-memory eval
    notes/answers still exist. Best-effort by design: the report page retries
    its own GET, and static placeholders remain honest on a total failure.

    Must run BEFORE _drop_session_state — see _maybe_finish_interview."""
    try:
        await _enriched_scores(session_id)
    except Exception:  # noqa: BLE001 — enrichment must never break the signal
        pass


# --- agent report-text parsing (adk-web parity: the streamed text IS the report)
# The interviewer writes the final report as text. Parsing it lets the UI show
# exactly what the candidate saw — no second model call, and it survives the
# agent skipping every tool (Lite does this under load).
_RPT_SCORE = re.compile(r"score\s*:\s*(\d+(?:\.\d+)?)\s*/\s*10", re.I)
_RPT_VERDICT = re.compile(r"verdict\s*:\s*(.+)", re.I)
_RPT_HEADS = [
    (
        "strengths",
        re.compile(r"^(?:\*\*|__)?\s*(?:key\s+)?strengths\s*(?:\*\*|__)?\s*:?\s*(.*)$", re.I),
    ),
    (
        "gaps",
        re.compile(
            r"^(?:\*\*|__)?\s*(?:key\s+)?(?:gaps|growth\s+areas|weaknesses)\s*"
            r"(?:\*\*|__)?\s*:?\s*(.*)$",
            re.I,
        ),
    ),
    (
        "study_next",
        re.compile(
            r"^(?:\*\*|__)?\s*(?:what\s+to\s+study\s+next|study\s+next|"
            r"recommended\s+study\s+topics|topics\s+to\s+study)\s*(?:\*\*|__)?\s*:?\s*(.*)$",
            re.I,
        ),
    ),
]
_RPT_OTHER_HEAD = re.compile(
    r"^(?:\*\*|__)?\s*(?:interview\s+report|per-?question\s+scores|scores|"
    r"overall\s+score|summary|score|verdict)\b",
    re.I,
)


def _clean_bullet(line: str) -> str:
    line = re.sub(r"^[-*•]\s*", "", line.strip())
    return re.sub(r"^\d+[.)]\s*", "", line).strip()


def _text_score(text: str) -> float | None:
    """First 'Score: N/10' in the agent's text — the turn's headline score.
    Markdown emphasis is stripped first (agents bold the label)."""
    m = _RPT_SCORE.search((text or "").replace("**", "").replace("__", ""))
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    return value if 0.0 <= value <= 10.0 else None


def _parse_report_text(text: str) -> dict:
    """Parse the agent's streamed report into report fields.

    Returns any of: score, strengths, gaps, study_next, verdict, verdict_why.
    Tolerant of markdown bold, bullets, and numbered lists.
    """
    out: dict = {}
    section: str | None = None
    buf: dict[str, list[str]] = {"strengths": [], "gaps": [], "study_next": []}

    for raw in (text or "").splitlines():
        line = raw.strip().replace("**", "").replace("__", "")
        if not line:
            continue
        if "score" not in out:
            value = _text_score(line)
            if value is not None:
                out["score"] = value
        mv = _RPT_VERDICT.search(line)
        if mv:
            val = mv.group(1).strip().strip("*_` ")
            head = re.split(r"\s*[—–-]\s*|\s*:\s*", val, maxsplit=1)[0].strip()
            if head in ("Strong Hire", "Hire", "No Hire"):
                out["verdict"] = head
                rest = val[len(head):].lstrip(" —–-:").strip().strip("*_` ")
                if rest:
                    out["verdict_why"] = rest[:300]
            section = None
            continue
        matched = None
        for key, rx in _RPT_HEADS:
            m2 = rx.match(line)
            if m2:
                matched = (key, (m2.group(1) or "").strip())
                break
        if matched:
            section, inline = matched
            if inline:
                buf[section].append(_clean_bullet(inline))
            continue
        if _RPT_OTHER_HEAD.match(line):
            section = None
            continue
        if section in buf:
            buf[section].append(_clean_bullet(line))

    for key, parts in buf.items():
        joined = "\n".join(p for p in parts if p)
        if joined:
            out[key] = joined[:1200]
    return out


async def _enriched_scores(session_id: str, user_id: str | None = None) -> dict:
    """Scores doc, enriched when the agent left text fields empty.

    Priority (each fills only blanks; anything already saved wins):
    1. The agent's OWN parsed report text (_report_parsed) — no model call.
    2. Per-turn evaluator notes captured backend-side.
    3. One summarizer Lite call for whatever is still blank (rare).
    Every failure path returns the raw doc (placeholders stay honest).

    ``user_id`` is the HTTP caller for ownership checks (None = internal
    backend caller, ungated).
    """
    from interviewiq_agent.tools.persistence import _db

    ref = _db().collection("scores").document(session_id)
    snap = ref.get()
    if not snap.exists:
        # Never synthesize a doc from enrichment alone — a doc holding only
        # strengths/gaps (no per_question/overall/user_id) is a phantom that
        # pollutes nothing and misleads everything. No doc → report defaults.
        return {}
    data = snap.to_dict() or {}
    # Ownership gate BEFORE any enrichment write: a foreign caller must never
    # cause a patch to someone else's doc. user_id=None is the internal
    # final-save path, which has no HTTP caller.
    if user_id is not None and not _owned_by(data, user_id):
        raise HTTPException(status_code=404, detail="Report not found.")
    notes = [n for n in _eval_notes.get(session_id, []) if n.get("strengths") or n.get("gaps")]
    parsed = _report_parsed.get(session_id) or {}
    answers = _answers.get(session_id, {})
    if not notes and not parsed and not answers:
        return data  # nothing backend-owned to enrich with
    if session_id in _enriching:
        return data  # another pass is in flight; the poller re-reads shortly

    _enriching.add(session_id)
    try:
        patch: dict = {}
        # 1) The agent's OWN report text wins — highest fidelity, and it costs
        #    no model call (the content the candidate already saw on screen).
        for key in ("strengths", "gaps", "study_next", "verdict", "verdict_why"):
            if not data.get(key) and parsed.get(key):
                patch[key] = parsed[key]
        # 2) Per-turn evaluator notes fill any still-blank strengths/gaps.
        if not data.get("strengths") and not patch.get("strengths") and notes:
            patch["strengths"] = "\n".join(
                f"• {n['strengths']}" for n in notes[:10] if n.get("strengths")
            )[:2000]
        if not data.get("gaps") and not patch.get("gaps") and notes:
            patch["gaps"] = "\n".join(
                f"• {n['gaps']}" for n in notes[:10] if n.get("gaps")
            )[:2000]
        # 3) Summarizer ONLY for what is still blank — rare once the text parsed.
        merged = {**data, **patch}
        needs_gen = (
            not merged.get("study_next")
            or not merged.get("verdict_why")
            or not merged.get("strengths")
            or not merged.get("gaps")
        ) and answers
        if needs_gen:
            gen = await asyncio.to_thread(_summarize_session, session_id, data)
            if gen:
                if not merged.get("verdict") and gen.get("verdict") in (
                    "Strong Hire", "Hire", "No Hire",
                ):
                    patch["verdict"] = gen["verdict"]
                if not merged.get("verdict_why") and gen.get("verdict_why"):
                    patch["verdict_why"] = gen["verdict_why"]
                if not merged.get("study_next") and gen.get("study_next"):
                    patch["study_next"] = gen["study_next"]
                if not merged.get("strengths") and gen.get("strengths"):
                    patch["strengths"] = gen["strengths"]
                if not merged.get("gaps") and gen.get("gaps"):
                    patch["gaps"] = gen["gaps"]
        if patch:
            try:
                ref.set(patch, merge=True)
                data = {**data, **patch}
            except Exception:  # noqa: BLE001 — read still succeeds with raw doc
                pass
        return data
    finally:
        _enriching.discard(session_id)


def _summarize_session(session_id: str, data: dict) -> dict:
    """Enrichment content for one session. Retries the single Lite call up to
    3× (~8s apart): 503 season kills most first attempts. Invoked at interview
    finish (before _drop_session_state) and memoized into the doc, so retries
    never duplicate. Final failure is LOGGED (silent {} cost an hour of
    debugging once already); placeholders stay honest."""
    import logging as _logging

    for attempt in range(3):
        try:
            out = _try_summarize(session_id, data)
            if out:
                return out
        except Exception as ex:  # noqa: BLE001 — retryable until attempts run out
            if attempt < 2:
                import time as _time

                _time.sleep(2)
                continue
            _logging.getLogger(__name__).warning(
                "summarizer gave up for %s after 3 tries (%s: %s)",
                session_id, type(ex).__name__, str(ex)[:160],
            )
            return {}
    _logging.getLogger(__name__).warning(
        "summarizer returned unusable shape for %s", session_id
    )
    return {}


def _parse_summary(text: str) -> dict:
    """Tolerant shape parser for the summarizer reply. Lite rarely honors
    'EXACTLY these lines' — it wraps in fences, bullets, bold keys. Accept
    all of that; reject only genuinely missing content."""
    import re

    out: dict = {}
    for raw in (text or "").splitlines():
        line = raw.strip().strip("`").strip()
        line = re.sub(r"^[-*•\d.)\s]+", "", line).strip()
        line = line.replace("**", "")
        m = re.match(r"^(verdict|why|study|strengths|gaps)\s*[:\-–]\s*(.+)$", line, re.I)
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2).strip()
        if key == "verdict" and val in ("Strong Hire", "Hire", "No Hire"):
            out["verdict"] = val
        elif key == "why" and val:
            out["verdict_why"] = val[:300]
        elif key == "study" and val:
            out["study_next"] = val[:800]
        elif key == "strengths" and val:
            out["strengths"] = val[:800]
        elif key == "gaps" and val:
            out["gaps"] = val[:800]
    return out if out.get("verdict") and out.get("study_next") else {}


_summary_client_singleton = None


def _summary_client():
    """One shared genai client for the summarizer.

    A throwaway genai.Client(...) per call gets collected mid-request and dies
    with "Cannot send a request, as the client has been closed" (genai's
    continuation path re-touches the client after the first response) — which
    silently killed every verdict/study enrichment. Reuse one client instead.
    """
    global _summary_client_singleton
    if _summary_client_singleton is None:
        import os

        from google import genai

        _summary_client_singleton = genai.Client(
            api_key=os.getenv("GOOGLE_API_KEY", "")
        )
    return _summary_client_singleton


def _try_summarize(session_id: str, data: dict) -> dict:
    """One Lite call → verdict + why + study + strengths + gaps. Strict shape;
    {} on any deviation (placeholders stay instead of invented content).
    Exceptions propagate to the retrying caller — no silent swallowing here."""
    from interviewiq_agent.config import _MODEL

    rounds = []
    answers = _answers.get(session_id, {})
    for i, s in enumerate(data.get("per_question", []) or []):
        a = answers.get(i, "")
        rounds.append(f"Round {i + 1}: score {s}/10. Answer: {a[:600]}")
    if not rounds:
        return {}
    prompt = (
        "You are grading metadata, not chatting. Interview topic: "
        f"{data.get('topic') or data.get('mode', '')}. Overall: {data.get('overall')}/10.\n"
        + "\n".join(rounds)
        + "\nRespond EXACTLY these five lines, nothing else:\n"
        "VERDICT: <Strong Hire | Hire | No Hire>\n"
        "WHY: <one line>\n"
        "STUDY: <2-4 topics as 'topic — what to practice', separated by ' | '>\n"
        "STRENGTHS: <2-3 lines on what the candidate demonstrably did well>\n"
        "GAPS: <2-3 lines on concrete misses>"
    )
    try:
        resp = _summary_client().models.generate_content(model=_MODEL, contents=prompt)
    except RuntimeError as ex:
        if "closed" in str(ex).lower():
            # Poisoned transport: drop it so the caller's retry rebuilds one.
            global _summary_client_singleton
            _summary_client_singleton = None
        raise
    parsed = _parse_summary(resp.text or "")
    if not parsed:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "summarizer shape miss for five-line contract; raw head: %r",
            (resp.text or "")[:300],
        )
    return parsed


def _owned_by(data: dict, user_id: str) -> bool:
    """May `user_id` use this owned doc (score/report/namespace record)?

    Missing owner = legacy doc (written before user_id was pinned) -> readable,
    and DEV_USER_ID = the shared local-dev bucket -> readable (local dev and
    probe scripts). Anything else must match the caller exactly.

    The same rule covers `uploads/{namespace}` records: an empty owner means
    the namespace predates ownership and stays usable.

    Legacy docs stay readable on purpose: they predate ownership and are already
    invisible to Past Reports (that listing filters by user_id), so denying them
    would only break direct links to old sessions.
    """
    from interviewiq_agent.tools.persistence import DEV_USER_ID

    owner = str(data.get("user_id") or "")
    if not owner or owner == DEV_USER_ID:
        return True
    return owner == user_id


@app.get("/sessions/{session_id}/report", response_model=Report)
async def read_report(session_id: str, user_id: str = Depends(get_current_user)):
    """Report: agent-saved content when present, backend-enriched otherwise.

    Ownership: missing or foreign owner answers 404 (not 403) so the route
    never confirms that another user's session id exists.
    """
    data = await _enriched_scores(session_id, user_id)
    return Report(
        session_id=session_id,
        per_question=data.get("per_question", []),
        overall=data.get("overall", 0.0),
        strengths=data.get("strengths", "") or "",
        gaps=data.get("gaps", "") or "",
        study_next=data.get("study_next", "") or "",
        verdict=data.get("verdict", "") or "",
        verdict_why=data.get("verdict_why", "") or "",
        adjustment=data.get("nudge_reason", ""),
    )


@app.get("/sessions/{session_id}/report.pdf")
async def read_report_pdf(session_id: str, user_id: str = Depends(get_current_user)):
    """PDF download built from the SAME enriched report the web page shows.

    Reading the raw `scores` doc here used to drop every LLM-written field
    (strengths/gaps/study_next/verdict_why), because only _enriched_scores()
    fills those. Delegating to read_report() keeps the two artefacts identical
    by construction — and means a later auth/ownership check on that endpoint
    covers the download too.
    """
    from fastapi.responses import Response

    from interviewiq_agent.tools.persistence import _db

    from .report_pdf import build_report_pdf

    report = await read_report(session_id, user_id)
    sess = _db().collection("sessions").document(session_id).get().to_dict() or {}
    pdf = build_report_pdf(report.model_dump(), sess.get("turns", []))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=report-{session_id}.pdf"},
    )
