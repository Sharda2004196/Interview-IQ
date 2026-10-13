"""Firebase Auth — ID-token verification for the backend.

Local rule: no token -> DEV_USER_ID (adk web + manual testing never break).
Bad token -> 401. Strict-everywhere enforcement comes at deploy.
"""

from fastapi import Header, HTTPException

from interviewiq_agent.tools.persistence import DEV_USER_ID, _db


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
        return DEV_USER_ID
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Use: Authorization: Bearer <token>")
    return verify_token(token)
