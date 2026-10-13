"""Live API voice transport — session manager for realtime interviews.

Design: the Live session owns AUDIO (mic in, voice out). The ADK Runner keeps
owning the BRAIN (bank, evaluator, RAG, scores). This module shuttles between
them via transcriptions; Runner wiring lands in the next step (hooks below).

Lifetime (per official session-management docs):
- context-window compression (sliding window) -> session past 15-min cap.
- session resumption handle -> survives ~10-min connection resets (GoAway).
- resumption tokens honored ~2hr (AI Studio).
"""

import asyncio
import logging

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

# Docs-blessed preview id (no 3.5 live model exists; 3.8-live is the alt).
LIVE_MODEL = "gemini-3.1-flash-live-preview"


def build_config(
    system_instruction: str,
    voice_name: str = "Charon",
    resume_handle: str | None = None,
) -> types.LiveConnectConfig:
    """Live session config: audio+text out, transcriptions on, unlimited session."""
    return types.LiveConnectConfig(
        # AUDIO only: this model rejects AUDIO+TEXT combos. Model reply text
        # still arrives via output_audio_transcription (no audio parsing needed).
        response_modalities=["AUDIO"],
        system_instruction=system_instruction,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()
        ),
        session_resumption=types.SessionResumptionConfig(handle=resume_handle),
    )


class VoiceSession:
    """One interview's Live connection. Register hooks, then run()."""

    def __init__(self, api_key: str, system_instruction: str, voice_name: str = "Charon"):
        self._client = genai.Client(api_key=api_key)
        self._instruction = system_instruction
        self._voice = voice_name
        self._session = None
        self._send_lock = asyncio.Lock()
        self.resume_handle: str | None = None
        self.on_user_transcript = None  # async fn(str) — next step: feed Runner
        self.on_model_text = None  # async fn(str) — model reply transcript
        self.on_model_audio = None  # async fn(bytes) — PCM to speaker socket

    async def _call(self, fn_name: str, *args):
        fn = getattr(self, fn_name, None)
        if fn is not None:
            if asyncio.iscoroutinefunction(fn):
                await fn(*args)
            else:
                fn(*args)

    async def run(self, stop: asyncio.Event):
        """Connect (resuming if possible); auto-reconnect on GoAway until stop."""
        attempt = 0
        while not stop.is_set():
            try:
                async with self._client.aio.live.connect(
                    model=LIVE_MODEL,
                    config=build_config(
                        self._instruction, self._voice, self.resume_handle
                    ),
                ) as session:
                    self._session = session
                    attempt = 0
                    await self._pump(session, stop)
            except Exception as ex:  # noqa: BLE001 — transport must self-heal
                attempt += 1
                wait = min(2 * attempt, 30)
                log.warning(
                    "live connection dropped (%s: %r) — reconnect #%d in %ss",
                    type(ex).__name__,
                    ex,
                    attempt,
                    wait,
                )
                self._session = None
                await asyncio.sleep(wait)

    async def _pump(self, session, stop: asyncio.Event):
        async for msg in session.receive():
            if stop.is_set():
                return
            if getattr(msg, "go_away", None) is not None:
                log.info("GoAway, reconnecting with handle=%s", self.resume_handle)
                return  # exit context -> run() reconnects with stored handle
            upd = getattr(msg, "session_resumption_update", None)
            if upd is not None and getattr(upd, "new_handle", None):
                self.resume_handle = upd.new_handle
            sc = getattr(msg, "server_content", None)
            if sc is None:
                continue
            if getattr(sc, "input_transcription", None) is not None:
                await self._call("on_user_transcript", sc.input_transcription.text)
            # Model reply text (AUDIO-only modalities: no text parts, use this).
            if getattr(sc, "output_transcription", None) is not None:
                await self._call("on_model_text", sc.output_transcription.text)
            mt = getattr(sc, "model_turn", None)
            if mt is not None:
                for part in mt.parts or []:
                    if getattr(part, "text", None):
                        await self._call("on_model_text", part.text)
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and getattr(inline, "data", None):
                        await self._call("on_model_audio", inline.data)
            if getattr(sc, "generation_complete", None) is True:
                await self._call("on_turn_complete")

    async def send_audio(self, pcm: bytes, mime_type: str = "audio/pcm;rate=16000"):
        # One websocket: concurrent send_audio + send_text collide -> server
        # aborts with 1008. The lock serializes all sends; the None-guard drops
        # audio during reconnect windows instead of error-looping.
        if self._session is None:
            return
        async with self._send_lock:
            await self._session.send_realtime_input(
                audio=types.Blob(data=pcm, mime_type=mime_type)
            )

    async def send_text(self, text: str):
        if self._session is None:
            log.warning("send_text dropped (no connection)")
            return
        async with self._send_lock:
            await self._session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)])
            )
