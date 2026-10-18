"""Pydantic boundary schemas — every client/server payload validated here.

Tools return plain dicts (ADK serializes from hints); anything crossing
HTTP/WS uses these models.
"""

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["A", "B", "C", "D", "E"]
Difficulty = Literal["easy", "medium", "hard"]


class Persona(BaseModel):
    role: str = "Senior tech interviewer"
    tone: str = "encouraging but rigorous"
    difficulty: Difficulty = "medium"
    voice: str = "default"  # mapped to Live API voice config in Phase 2


class SessionConfig(BaseModel):
    mode: Mode
    topic: str = ""
    custom_questions: list[str] = Field(default_factory=list)  # mode B
    file_namespace: str = ""  # modes C/D: Pinecone namespace of the upload
    persona: Persona = Field(default_factory=Persona)
    num_questions: int = 5
    # Turn-based voice (browser STT/TTS) runs over the text socket, so the mode
    # must be explicit — it drives the interviewer's "never probe" rule and the
    # backend's round bookkeeping. Set by the setup screen's voice toggle.
    voice_mode: bool = False


class CreateSessionResponse(BaseModel):
    session_id: str
    user_id: str = "local-dev"


class PastSession(BaseModel):
    """One Past Reports card: newest-first summary (verdict derived client-side)."""

    session_id: str
    mode: str = ""
    topic: str = ""
    rounds: int = 0
    overall: float = 0.0
    created_at: str = ""  # ISO timestamp; "" for pre-metadata docs


class QATurn(BaseModel):
    q: str
    a: str
    score: float = 0.0


class Report(BaseModel):
    session_id: str
    per_question: list[float] = Field(default_factory=list)
    overall: float = 0.0
    strengths: str = ""
    gaps: str = ""
    study_next: str = ""
    verdict: str = ""  # agent's verdict; "" = derive from overall thresholds
    verdict_why: str = ""
    adjustment: str = ""  # nudge reason when the interviewer applied ±1


class UploadResponse(BaseModel):
    file: str
    chars: int
    chunks: int
    namespace: str


# --- WebSocket envelopes: client -> server ---
class WSStart(BaseModel):
    type: Literal["start"] = "start"
    config: SessionConfig


class WSAnswer(BaseModel):
    type: Literal["answer"] = "answer"
    text: str


class WSEnd(BaseModel):
    type: Literal["end"] = "end"


# --- WebSocket envelopes: server -> client ---
class WSToken(BaseModel):
    type: Literal["token"] = "token"
    text: str


class WSScore(BaseModel):
    type: Literal["score"] = "score"
    value: float


class WSReport(BaseModel):
    type: Literal["report"] = "report"
    report: Report


class WSError(BaseModel):
    type: Literal["error"] = "error"
    message: str
