"""Who is calling. entra: Entra ID access token (single sign-on). header: a trusted reverse proxy
(IIS / Entra Application Proxy) sets the user's UPN in a header. dev: a fixed user for testing."""
from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import HTTPException, Request

from .config import Settings


@lru_cache(maxsize=4)
def _jwks(tenant_id: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys")


def current_user(request: Request) -> str:
    s: Settings = request.app.state.settings
    if s.auth_mode == "dev":
        if not s.dev_user:
            raise HTTPException(500, "DMS_DEV_USER is not set")
        return s.dev_user
    if s.auth_mode == "header":
        user = request.headers.get(s.user_header)
        if not user:
            raise HTTPException(401, "Not signed in")
        if "@" not in user:
            raise HTTPException(401, f"{s.user_header} must hold the user's email (UPN), got {user!r}")
        return user.lower()
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Not signed in")
    try:
        token = auth[7:]
        key = _jwks(s.tenant_id).get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=[s.api_audience, f"api://{s.api_audience}"],
                            issuer=f"https://login.microsoftonline.com/{s.tenant_id}/v2.0")
    except Exception as e:  # noqa: BLE001 - any token problem is a 401
        raise HTTPException(401, f"Invalid token: {e}") from e
    user = claims.get("preferred_username") or claims.get("upn") or claims.get("email")
    if not user:
        raise HTTPException(401, "The token has no user name")
    return user.lower()
