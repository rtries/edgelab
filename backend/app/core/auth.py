"""Auth — verifies Supabase-issued JWTs and resolves the request's user.

For a 2-3 person invite-only test, there is no signup flow on our side:
users are created directly in the Supabase dashboard (or via a magic
link you send them), and Supabase issues the token. We only verify it.

Supabase Auth JWTs are HS256, signed with the project's JWT secret
(Project Settings -> API -> JWT Secret in the Supabase dashboard). We
verify the signature and expiry and trust the `sub` claim as the stable
user id — that id is what every per-user data root is namespaced by.

`AUTH_DISABLED=true` skips verification and returns a fixed dev user;
it exists for local development and the test suite only, and must
never be set in a deployed environment. `app/main.py` refuses to start
with it set unless api_env == "development".
"""
from __future__ import annotations

import jwt
from fastapi import Header, HTTPException

from app.core.config import settings

DEV_USER_ID = "dev-local"


class AuthUser:
    __slots__ = ("id", "email")

    def __init__(self, id: str, email: str | None = None) -> None:  # noqa: A002
        self.id = id
        self.email = email


def get_current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    if settings.auth_disabled:
        return AuthUser(id=DEV_USER_ID, email="dev@local")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_JWT_SECRET is not configured on the server",
        )
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="token missing subject")
    return AuthUser(id=user_id, email=payload.get("email"))
