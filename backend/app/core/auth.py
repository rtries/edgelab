"""Auth — verifies Supabase-issued JWTs and resolves the request's user.

For a 2-3 person invite-only test, there is no signup flow on our side:
users are created directly in the Supabase dashboard (or via a magic
link you send them), and Supabase issues the token. We only verify it.

Supabase projects created since the JWT signing key migration issue
tokens signed with an ASYMMETRIC key (ES256/RS256) by default, verified
against Supabase's public JWKS endpoint
(`<project-url>/auth/v1/.well-known/jwks.json`) — no shared secret
required, and this is the primary path. Older projects still on the
legacy shared HS256 secret are supported as a fallback if
`SUPABASE_JWT_SECRET` is configured (Project Settings -> JWT Keys ->
Legacy JWT Secret) and the JWKS path fails.

We verify the signature and expiry and trust the `sub` claim as the
stable user id — that id is what every per-user data root is
namespaced by.

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

_jwks_client: "jwt.PyJWKClient | None" = None


class AuthUser:
    __slots__ = ("id", "email")

    def __init__(self, id: str, email: str | None = None) -> None:  # noqa: A002
        self.id = id
        self.email = email


def _get_jwks_client() -> "jwt.PyJWKClient | None":
    """Lazily built and cached — one client reused across requests, which
    is what gives us Supabase's key caching/rotation handling for free."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client
    if not settings.supabase_url:
        return None
    jwks_url = settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
    _jwks_client = jwt.PyJWKClient(jwks_url)
    return _jwks_client


def _decode(token: str) -> dict:
    """Try the modern asymmetric JWKS path first (what current Supabase
    projects use by default), then fall back to the legacy shared HS256
    secret for older projects that still use it. Raises jwt.PyJWTError
    (or a subclass) if neither works."""
    jwks_client = _get_jwks_client()
    if jwks_client is not None:
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
            )
        except jwt.PyJWTError:
            if not settings.supabase_jwt_secret:
                raise
            # fall through to the legacy secret below

    if settings.supabase_jwt_secret:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

    raise HTTPException(
        status_code=500,
        detail="neither SUPABASE_URL (for JWKS) nor SUPABASE_JWT_SECRET "
               "is configured on the server",
    )


def get_current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    if settings.auth_disabled:
        return AuthUser(id=DEV_USER_ID, email="dev@local")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = _decode(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="token missing subject")
    return AuthUser(id=user_id, email=payload.get("email"))
