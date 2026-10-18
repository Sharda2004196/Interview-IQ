"""save_transcript / save_score tools — Firestore persistence (Spark free tier).

Auth is skipped locally per plan (single dev user_id); Firebase Auth plugs in
pre-deploy. Service-account creds come from .env (Docker-friendly, no key file).
Client inits lazily so `adk web` loads without creds; calls raise a clear error.
"""

import os

from google.adk.tools import FunctionTool, ToolContext

from .. import config  # noqa: F401 — side effect: loads interviewiq_agent/.env

DEV_USER_ID = "local-dev"  # replaced by Firebase Auth uid pre-deploy

# Hybrid scoring: deterministic weighted core + bounded (±1) judgment nudge.
# Weight = position (later answers count more — you warmed up) × difficulty.
_DIFF_WEIGHT = {"easy": 1.0, "medium": 2.0, "hard": 3.0}
_NUDGE_LIMIT = 1.0


def weighted_overall(
    per_question: list[float], difficulties: list[str], nudge: float = 0.0
) -> float:
    """Deterministic overall: later + harder answers weigh more. Pure function."""
    if not per_question:
        raise ValueError("weighted_overall got no scores")
    if abs(nudge) > _NUDGE_LIMIT:
        raise ValueError(f"nudge {nudge} exceeds ±{_NUDGE_LIMIT}")
    weights = [
        (i + 1) * _DIFF_WEIGHT.get((difficulties[i] if i < len(difficulties) else "medium"), 2.0)
        for i in range(len(per_question))
    ]
    mean = sum(s * w for s, w in zip(per_question, weights)) / sum(weights)
    return round(max(0.0, min(10.0, mean + nudge)), 1)


def _db():
    import firebase_admin
    from firebase_admin import credentials, firestore

    project_id = os.getenv("FIREBASE_PROJECT_ID")
    client_email = os.getenv("FIREBASE_CLIENT_EMAIL")
    private_key = (os.getenv("FIREBASE_PRIVATE_KEY") or "").replace("\\n", "\n")
    if not all([project_id, client_email, private_key]):
        raise RuntimeError(
            "FIREBASE_PROJECT_ID / FIREBASE_CLIENT_EMAIL / FIREBASE_PRIVATE_KEY "
            "missing in interviewiq_agent/.env"
        )
    if not firebase_admin._apps:
        firebase_admin.initialize_app(
            credentials.Certificate(
                {
                    "project_id": project_id,
                    "client_email": client_email,
                    "private_key": private_key,
                    "type": "service_account",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            ),
            {"projectId": project_id},
        )
    return firestore.client()


def _uid(tool_context: ToolContext | None) -> str:
    """Real uid from session state; local-dev when absent (adk web, tests)."""
    if tool_context is not None:
        try:
            return tool_context.state.get("user_id", DEV_USER_ID) or DEV_USER_ID
        except Exception:
            pass
    return DEV_USER_ID


def save_transcript(
    session_id: str,
    mode: str,
    difficulty: str,
    turns: list[dict],
    user_id: str = "",
    tool_context: ToolContext | None = None,
) -> dict:
    """Persist Q&A turns. turns=[{"q":..,"a":..,"score":..}]. Returns {"turns": n}.

    user_id pins ownership exactly like save_score: the agent's tool call
    resolves it from session state, while the backend backfill passes the
    socket's uid explicitly (no ToolContext, must NOT fall back to the shared
    dev identity, or a logged-in owner's transcript is invisible to them).
    """
    _db().collection("sessions").document(session_id).set(
        {
            "user_id": user_id or _uid(tool_context),
            "mode": mode,
            "difficulty": difficulty,
            "turns": turns,
        },
        merge=True,
    )
    return {"turns": len(turns)}


def save_score(
    session_id: str,
    per_question: list[float],
    difficulties: list[str],
    nudge: float = 0.0,
    nudge_reason: str = "",
    mode: str = "",
    topic: str = "",
    user_id: str = "",
    strengths: str = "",
    gaps: str = "",
    study_next: str = "",
    verdict: str = "",
    verdict_why: str = "",
    tool_context: ToolContext | None = None,
) -> dict:
    """Persist scores. Overall is COMPUTED here (weighted mean + bounded nudge),
    never invented — quote the returned overall in the final report.

    mode/topic feed Past Reports listing (agent passes what it knows; the
    backend backfill passes session config). created_at orders the list.
    user_id pins the owner: the agent's tool call resolves it from session
    state; the backend backfill passes the socket's uid explicitly (it has no
    ToolContext, and must NOT fall back to the shared dev identity, or the
    report becomes invisible to a logged-in owner).
    """
    from firebase_admin import firestore as _fs

    overall = weighted_overall(per_question, difficulties, nudge)
    _db().collection("scores").document(session_id).set(
        {
            "user_id": user_id or _uid(tool_context),
            "per_question": per_question,
            "difficulties": difficulties,
            "nudge": nudge,
            "nudge_reason": nudge_reason,
            "overall": overall,
            "mode": mode,
            "topic": topic,
            "strengths": strengths,
            "gaps": gaps,
            "study_next": study_next,
            "verdict": verdict,
            "verdict_why": verdict_why,
            "created_at": _fs.SERVER_TIMESTAMP,
        }
    )
    return {"overall": overall}


def fill_report_meta(session_id: str, mode: str, topic: str) -> None:
    """Merge mode/topic (+created_at when absent) into an existing score doc.

    Heals agent-saved docs from runs where the model didn't pass metadata —
    Past Reports needs these fields on every doc, old and new.
    """
    from firebase_admin import firestore as _fs

    ref = _db().collection("scores").document(session_id)
    snap = ref.get()
    if not snap.exists:
        return
    data = snap.to_dict() or {}
    patch = {}
    if not data.get("mode") and mode:
        patch["mode"] = mode
    if not data.get("topic") and topic:
        patch["topic"] = topic
    if data.get("created_at") is None:
        patch["created_at"] = _fs.SERVER_TIMESTAMP
    if patch:
        ref.set(patch, merge=True)


save_transcript_tool = FunctionTool(save_transcript)
save_score_tool = FunctionTool(save_score)
