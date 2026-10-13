"""VoiceBridge — welds the Live audio session to the ADK Runner brain.

Loop: mic audio -> Live input_transcription -> Runner pipeline (bank,
evaluator, RAG, scores, saves — everything text already proves) -> reply
text -> Live speaks it verbatim.

Feedback-loop guard: only INPUT transcriptions (mic) feed the Runner.
OUTPUT transcriptions (our own speech) are logged, never re-fed.
"""

import asyncio
import logging

from .runner import (
    RETRY_DELAY_S,
    _is_quota_error,
    _is_retryable,
    build_start_prompt,
    get_or_create_session,
    restore_qindex,
    snapshot_qindex,
    stream_events,
)
from .schemas import SessionConfig
from .voice import VoiceSession

log = logging.getLogger(__name__)

# Utterance assembly: Live VAD emits one transcription per pause-separated
# fragment, NOT per answer. The client signals a FINISHED answer explicitly
# (tap Mic when done -> {"type":"answer_done"}); the silence window below is
# only a backstop for clients that never signal (set wide so thinking pauses
# never split an answer into scored fragments).
UTTERANCE_SILENCE_S = 8.0

# "default" persona voice -> Live prebuilt voice. Unknown names pass through;
# the server rejects bad ones loudly at connect, which is what we want.
VOICES = {"default": "Charon"}

_SPEAK_VERBATIM = "Repeat the following sentence EXACTLY, word for word: "
_TRANSPORT_INSTRUCTION = (
    "You are the voice of an interviewer. The interviewer tells you exact "
    "sentences to speak — repeat each one verbatim, nothing added. "
    "You also hear the candidate's microphone directly: NEVER answer it, "
    "NEVER repeat it, NEVER speak to it — only transcribe it faithfully. "
    "Your voice sounds ONLY when given an exact sentence. Any other speech, "
    "including echoing the candidate, is a critical failure. "
    "Never narrate your own actions: never say the word transcribing, never "
    "use brackets, never describe what you are doing. Speak interview content "
    "only, or stay completely silent."
)


class VoiceBridge:
    def __init__(self, api_key: str, session_id: str, config: SessionConfig, user_id: str = "local-dev"):
        self.session_id = session_id
        self.config = config
        self.user_id = user_id
        self.spoken_log: list[str] = []  # test hook + audit trail
        # Closed rounds (same round-truth as the text socket: FOLLOW_UP probes
        # don't count; interview ends at N).
        self.rounds: list[float] = []
        self.pending_probe = False
        # Set by the WS endpoint: no-arg async/sync callback fired once the
        # Nth round closes (endpoint sends {"type":"report"} + closes).
        self.on_report_due = None
        # Set by the WS endpoint: async/sync fn(kind, text) receiving live
        # transcripts for UI display. kind is "user" (mic) or "agent" (voice).
        # Display-only: the Runner is fed separately, never from these frames.
        self.on_transcript = None
        # Utterance assembly buffer (see UTTERANCE_SILENCE_S).
        self._utterance_parts: list[str] = []
        self._utterance_task: asyncio.Task | None = None
        self.live = VoiceSession(
            api_key,
            system_instruction=_transport_prompt(config),
            voice_name=VOICES.get(config.persona.voice, config.persona.voice),
        )
        self.live.on_user_transcript = self._handle_user_transcript
        self.live.on_model_text = self._handle_model_text

    async def _call(self, fn_name: str, *args):
        fn = getattr(self, fn_name, None)
        if fn is not None:
            if asyncio.iscoroutinefunction(fn):
                await fn(*args)
            else:
                fn(*args)

    async def _emit_transcript(self, kind: str, text: str) -> None:
        fn = self.on_transcript
        if fn is None or not (text or "").strip():
            return
        if asyncio.iscoroutinefunction(fn):
            await fn(kind, text)
        else:
            fn(kind, text)

    async def _handle_user_transcript(self, text: str):
        await self._emit_transcript("user", text)
        part = (text or "").strip()
        if not part:
            return
        self._utterance_parts.append(part)
        # Restart the silence window: only a full pause means "answer done".
        if self._utterance_task is not None and not self._utterance_task.done():
            self._utterance_task.cancel()
        self._utterance_task = asyncio.create_task(self._flush_after_silence())

    async def _flush_after_silence(self) -> None:
        try:
            await asyncio.sleep(UTTERANCE_SILENCE_S)
        except asyncio.CancelledError:
            return  # newer fragment arrived; its own timer owns the flush
        utterance = " ".join(self._utterance_parts).strip()
        self._utterance_parts = []
        self._utterance_task = None
        if utterance:
            await self._on_user_text(utterance)

    async def close(self) -> None:
        """Flush a trailing partial answer, stop timers (called on socket end)."""
        await self.answer_complete()

    async def answer_complete(self) -> None:
        """Client-declared end of answer: cancel the silence timer and fire the
        single Runner turn for everything accumulated so far, immediately."""
        if self._utterance_task is not None and not self._utterance_task.done():
            self._utterance_task.cancel()
        utterance = " ".join(self._utterance_parts).strip()
        self._utterance_parts = []
        self._utterance_task = None
        if utterance:
            await self._on_user_text(utterance)

    async def _handle_model_text(self, text: str):
        await self._log_only(text)
        await self._emit_transcript("agent", text)

    async def _log_only(self, text: str):
        log.debug("live spoke %d chars (not re-fed)", len(text))

    async def start(self):
        """Seed ADK state, drive Q1 through Runner, speak it."""
        await get_or_create_session(self.session_id, self.config, self.user_id)
        await self._run_turn(build_start_prompt(self.config))

    async def _on_user_text(self, text: str):
        if text.strip():
            await self._run_turn(text)

    async def _run_turn(self, text: str) -> bool:
        """Run one Runner turn, speak the reply. Returns True if N rounds closed."""
        await self._call("on_status", "evaluating")
        # Same burst protection as the text socket: one silent replay when a
        # retryable error kills the turn before it produced anything.
        q0 = await snapshot_qindex(self.session_id, self.user_id)
        for attempt in range(2):
            tokens: list[str] = []
            turn_scored = False
            saw_output = False
            try:
                async for kind, payload in stream_events(self.session_id, text, self.user_id):
                    if kind == "token":
                        tokens.append(payload)
                        saw_output = True
                    elif kind == "score":
                        turn_scored = True
                        saw_output = True
                        value, sig = payload  # (float, signal|None)
                        # Voice discipline: EVERY verdict closes a round. Probes are
                        # banned in voice mode, so a stray FOLLOW_UP still counts —
                        # otherwise one disobedient probe strands the interview open.
                        self.pending_probe = False
                        self.rounds.append(value)
                        log.info("voice turn score: %s (%s)", value, sig)
                    else:  # ("bank", dict) — brain-internal; voice speaks the words
                        log.debug("bank state: %s", payload)
            except Exception as ex:  # noqa: BLE001 — quota/outage must surface, not stall
                if _is_retryable(ex) and attempt == 0 and not saw_output:
                    await restore_qindex(self.session_id, self.user_id, q0)
                    await asyncio.sleep(RETRY_DELAY_S)
                    continue
                if _is_quota_error(ex):
                    await self.live.send_text(
                        _SPEAK_VERBATIM
                        + "Sorry — my brain hit its limit. Please repeat your answer in a minute."
                    )
                    await self._call(
                        "on_error",
                        "AI quota exhausted — wait a minute, then answer again. Nothing was scored.",
                    )
                    return False
                raise
            break
        reply = "".join(tokens).strip()
        if reply:
            self.spoken_log.append(reply)
            await self.live.send_text(_SPEAK_VERBATIM + reply)
        ended = (
            turn_scored
            and not self.pending_probe
            and len(self.rounds) >= self.config.num_questions
        )
        if ended and self.on_report_due is not None:
            fn = self.on_report_due
            if asyncio.iscoroutinefunction(fn):
                await fn()
            else:
                fn()
        return ended


def _transport_prompt(config: SessionConfig) -> str:
    return (
        f"{_TRANSPORT_INSTRUCTION} Persona color: {config.persona.role}, "
        f"{config.persona.tone}. Topic: {config.topic or config.mode}."
    )
