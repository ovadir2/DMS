"""Who is calling.

windows: IIS Windows Authentication, the login of the person at the PC (no login screen). AD/NTFS
         decide what they see (security.py). The default for the company network.
entra:   Entra ID access token (single sign-on from outside the network, e.g. Application Proxy).
header:  a trusted reverse proxy puts the user's email in a header.
dev:     a fixed user, for testing only (DMS_DEV_USERS: others to act as, header X-DMS-Dev-User;
         DMS_DEV_AD_CHECK: their AD / NTFS access is checked, except DMS_ADMINS). Other PCs sign in with
         their own Windows account (DMS_REMOTE_SIGNIN=ntlm, ntlm.py).
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
        remote = getattr(request.state, "remote_user", None)   # another PC, signed in with its Windows account
        email = (remote[0] if remote else s.dev_user).lower()
        user = User(email=email, name=(remote[1].split("\\")[-1] if remote else email.split("@")[0]))
        if (s.dev_ad_check or remote) and not _super(s, email):   # super users are not checked
            _with_ad(user, email)
        return user
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


def _super(s: Settings, email: str) -> bool:
    """A DMS super user (DMS_ADMINS), or the person who runs the DMS in dev mode."""
    return email in s.admins or (s.auth_mode == "dev" and email == (s.dev_user or "").lower())


def _with_ad(user: User, account: str) -> None:
    from .security import AdUser
    try:
        user.ad = AdUser.get(account)
    except Exception as e:  # noqa: BLE001 - say why, do not show everything
        raise HTTPException(403, f"AD check for {user.email}: {e}") from None


def _acting(request: Request, real: User) -> User:
    """ "Acting as" (super users only, the ⋮ menu): see and act as another user, with that user's AD rights.
    DMS_DEV_USERS limits who can be chosen; empty = anyone. Any other request keeps the real user."""
    s: Settings = request.app.state.settings
    target = (request.headers.get("X-DMS-Dev-User") or "").strip().lower()
    if not target or target == real.email or not _super(s, real.email):
        return real
    if s.dev_users and target not in s.dev_users:
        return real
    email = target
    if "@" not in target:                                      # a domain account (RH\name): its email (UPN) from AD,
        from .security import upn_of                           # SharePoint knows people only by email
        email = upn_of(target) or target
    user = User(email=email, name=email.split("@")[0].split("\\")[-1], acting_from=real.email)
    real.close()
    if (s.auth_mode == "windows" or s.dev_ad_check) and email not in s.admins:
        _with_ad(user, target)                                 # that user's AD / NTFS rights
    return user


def current_user(request: Request) -> Iterator[User]:
    user = _acting(request, _resolve(request))
    try:
        yield user
    finally:
        user.close()
