"""Who is calling.

windows: IIS Windows Authentication, the login of the person at the PC (no login screen). AD/NTFS
         decide what they see (security.py). The default for the company network.
entra:   Entra ID access token (single sign-on from outside the network, e.g. Application Proxy).
header:  a trusted reverse proxy puts the user's email in a header.
dev:     a fixed user, for testing only.
"""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

import jwt
from fastapi import HTTPException, Request

from .config import Settings
from .security import TOKEN_HEADER, User, user_from_windows_token


@lru_cache(maxsize=4)
def _jwks(tenant_id: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys")


def _resolve(request: Request) -> User:
    s: Settings = request.app.state.settings
    if s.auth_mode == "windows":
        handle = request.headers.get(TOKEN_HEADER)
        if not handle:
            raise HTTPException(401, "Windows sign-in is missing. Enable Windows Authentication in IIS.")
        return user_from_windows_token(handle)
    if s.auth_mode == "dev":
        if not s.dev_user:
            raise HTTPException(500, "DMS_DEV_USER is not set")
        return User(email=s.dev_user.lower(), name=s.dev_user.split("@")[0])
    if s.auth_mode == "header":
        user = request.headers.get(s.user_header)
        if not user:
            raise HTTPException(401, "Not signed in")
        if "@" not in user:
            raise HTTPException(401, f"{s.user_header} must hold the user's email (UPN), got {user!r}")
        return User(email=user.lower())
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
    email = claims.get("preferred_username") or claims.get("upn") or claims.get("email")
    if not email:
        raise HTTPException(401, "The token has no user name")
    return User(email=email.lower(), name=claims.get("name", ""))


def current_user(request: Request) -> Iterator[User]:
    user = _resolve(request)
    try:
        yield user
    finally:
        user.close()
