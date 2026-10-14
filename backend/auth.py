"""Firebase Auth — ID-token verification for the backend.

Modes (AUTH_MODE env, default "open"):
- open: no token -> DEV_USER_ID (local dev + pre-login prod keep working).
- strict: no token -> 401 everywhere (REST) / close (WS). Flip only after the
  frontend ships login, or every client breaks at once.
Bad token -> 401 always, in both modes.
"""

import os

from fastapi import Header, HTTPException

from interviewiq_agent.tools.persistence import DEV_USER_ID, _db

AUTH_MODE = os.getenv("AUTH_MODE", "open").lower()
STRICT = AUTH_MODE == "strict"


def verify_token(id_token: str) -> str:
    """Return the Firebase uid, or raise 401."""
    from firebase_admin import auth

    _db()  # ensures Admin SDK init from .env creds
    try:
        return auth.verify_id_token(id_token)["uid"]
    except Exception as ex:  # noqa: BLE001 — any failure means unauthenticated
        raise HTTPException(status_code=401, detail=f"Invalid auth token: {ex}")


async def get_current_user(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: Bearer <Firebase ID token> -> uid."""
    if not authorization:
        if STRICT:
            raise HTTPException(status_code=401, detail="Login required.")
        return DEV_USER_ID
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Use: Authorization: Bearer <token>")
    return verify_token(token)


def check_ws_token(msg: dict, expected_uid: str) -> str | None:
    """Consume a WS auth frame. Returns the authed uid, or None.

    Protocol: any client message may carry {"token": "<Firebase ID token>"}
    alongside (or instead of) its payload. The token uid must match the uid
    from POST /sessions — otherwise one user could drive another's session.
    Returns None when the frame carries no token (legacy/anonymous client).
    Raises 401 on bad or mismatched tokens, in both modes.
    """
    token = msg.get("token")
    if not token:
        return None
    uid = verify_token(token)
    if expected_uid and uid != expected_uid:
        raise HTTPException(status_code=401, detail="Token does not match session owner.")
    return uid
