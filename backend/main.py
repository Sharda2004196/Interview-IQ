"""FastAPI app: sessions REST + interview WebSocket + upload + report read."""

import asyncio
import json
import os
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
    build_start_prompt,
    get_or_create_session,
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


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session(config: SessionConfig, user_id: str = Depends(get_current_user)):
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


def _drop_session_state(session_id: str) -> None:
    _rounds.pop(session_id, None)
    _probe_open.pop(session_id, None)


async def _remember_config(session_id: str, config: SessionConfig, user_id: str):
    _pending_configs[session_id] = (config, user_id)


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
            if _db().collection("scores").document(session_id).get().exists:
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


@app.websocket("/ws/{session_id}")
async def interview_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
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
            start_span = lf_start_span(
                session_id,
                "turn-0-start",
                input={"mode": config.mode, "topic": config.topic,
                        "num_questions": config.num_questions},
                metadata=turn_meta,
            )
            # Start-turn burst protection (same clean-miss rule as answer turns):
            # a 503/429 before ANY token streamed replays Q1 silently after a
            # short wait. Without this, Google capacity blips kill Q1 and force
            # a manual Retry that regenerates everything from scratch.
            for start_attempt in range(2):
                q0 = await snapshot_qindex(session_id, ws_user)
                q1_saw_output = False
                st0 = asyncio.get_event_loop().time()
                waited_start = 0.0
                try:
                    async for delta in stream_reply(session_id, _start_prompt(config), ws_user):
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
                answer_text = msg.get("text", "") or ""
                round_no = len(rounds) + 1
                t0 = asyncio.get_event_loop().time()
                waited = 0.0  # retry-sleep excluded from duration_s below
                span = lf_start_span(
                    session_id,
                    f"round-{round_no}-attempt-{attempt}",
                    input={"answer": answer_text},
                    metadata={**turn_meta, "round": round_no, "attempt": attempt},
                )
                try:
                    events = stream_events(session_id, answer_text, ws_user)
                    async for kind, payload in events:
                        if kind == "score":
                            turn_scored = True
                            saw_output = True
                            value, sig = payload  # (float, signal|None)
                            turn_signal = sig
                            if sig == "FOLLOW_UP":
                                _probe_open[session_id] = True
                            else:
                                _probe_open[session_id] = False
                                rounds.append(value)
                            lf_score_span(span, "round_score", value)
                            await websocket.send_text(WSScore(value=value).model_dump_json())
                        elif kind == "bank":
                            continue  # state reads cover exhaustion; no action needed
                        elif guard and turn_signal != "FOLLOW_UP":
                            continue
                        else:
                            saw_output = True
                            await websocket.send_text(WSToken(text=payload).model_dump_json())
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
                    lf_end_span(
                        span,
                        output={"status": "failed"},
                        metadata={"error": f"{type(ex).__name__}: {ex}"},
                        level="ERROR",
                    )
                    await _send_safe(
                        websocket,
                        WSError(message=message).model_dump_json(),
                    )
                    break
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
                if (
                    turn_scored
                    and not _probe_open[session_id]
                    and len(rounds) >= config.num_questions
                ):
                    await _ensure_final_save(session_id, rounds, config, ws_user)
                    await _send_safe(websocket, '{"type":"report"}')
                    _drop_session_state(session_id)
                    lf_flush()
                    lf_drop_session(session_id)
                    return
                break
    except WebSocketDisconnect:
        pass


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
    """Delete one past session (score + transcript docs). Idempotent: always 200."""
    from interviewiq_agent.tools.persistence import _db

    db = _db()
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
async def upload(file: UploadFile, namespace: str = "default"):
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}-{file.filename}"
    dest.write_bytes(await file.read())
    parsed = parse_file(str(dest))
    n = upsert_document(parsed["text"], namespace, doc_name=parsed["file"])
    return UploadResponse(
        file=parsed["file"], chars=parsed["chars"], chunks=n["chunks"], namespace=namespace
    )


@app.get("/sessions/{session_id}/report", response_model=Report)
async def read_report(session_id: str):
    """Report persisted by the agent's save tools (needs Firebase creds in .env)."""
    from interviewiq_agent.tools.persistence import _db

    doc = _db().collection("scores").document(session_id).get()
    data = doc.to_dict() or {}
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
async def read_report_pdf(session_id: str):
    """PDF download built from the same Firestore docs as the JSON report."""
    from fastapi.responses import Response

    from interviewiq_agent.tools.persistence import _db

    from .report_pdf import build_report_pdf

    db = _db()
    score = db.collection("scores").document(session_id).get().to_dict() or {}
    sess = db.collection("sessions").document(session_id).get().to_dict() or {}
    pdf = build_report_pdf(
        {
            "session_id": session_id,
            "overall": score.get("overall", 0.0),
            "per_question": score.get("per_question", []),
            "adjustment": score.get("nudge_reason", ""),
        },
        sess.get("turns", []),
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=report-{session_id}.pdf"},
    )
