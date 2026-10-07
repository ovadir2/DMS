"""Windows sign-in for other PCs when the pilot runs on a PC (dev mode, Start-DmsPlayground -Share).

Without it, everyone who opens the shared page is the PC owner (DMS_DEV_USER). With it (DMS_REMOTE_SIGNIN=ntlm,
the default on Windows), a request from another PC must sign in with the person's own domain account: the
browser (or Word) does it by itself when the address is in the Local intranet zone, else it asks once for
RH\\name and password. The password goes to the domain controller (NTLM through Windows SSPI), never to the DMS.
After that a signed cookie keeps the person signed in for HOURS. Requests from the PC itself stay DMS_DEV_USER.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time

COOKIE = "dms_signin"
HOURS = 10
LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost", "testclient")
_SECRET = secrets.token_bytes(32)                     # new on every start: the cookies of an older run are void
_PENDING: dict[tuple, tuple[float, object]] = {}      # connection -> NTLM handshake in progress
_DONE: dict[tuple, tuple[float, str, str]] = {}       # connection -> signed in (NTLM signs in the connection)
_LOCK = threading.Lock()


def is_local(request) -> bool:
    return (request.client.host if request.client else "") in LOCAL_HOSTS


def connection(request) -> tuple:
    return (request.client.host, request.client.port) if request.client else ("", 0)


def _mac(value: str) -> str:
    return hmac.new(_SECRET, value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def cookie_for(email: str, account: str) -> str:
    value = f"{email}|{account}|{int(time.time() + HOURS * 3600)}"
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii") + "." + _mac(value)


def from_cookie(raw: str) -> tuple[str, str] | None:
    try:
        data, mac = raw.rsplit(".", 1)
        value = base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8")
        email, account, until = value.split("|")
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(mac, _mac(value)) or int(until) < time.time():
        return None
    return email, account


def signed_in(conn: tuple) -> tuple[str, str] | None:
    """A connection that already signed in (Word and some browsers do not repeat the header on it)."""
    with _LOCK:
        hit = _DONE.get(conn)
        if not hit or hit[0] < time.time() - 120:
            _DONE.pop(conn, None)
            return None
        _DONE[conn] = (time.time(), hit[1], hit[2])
        return hit[1], hit[2]


def remember(conn: tuple, email: str, account: str) -> None:
    with _LOCK:
        _DONE[conn] = (time.time(), email, account)


def _server_context():
    import sspi  # type: ignore[import-not-found]  # pywin32
    return sspi.ServerAuth("NTLM")


def _account(ctx) -> str:
    import sspicon  # type: ignore[import-not-found]
    return ctx.ctxt.QueryContextAttributes(sspicon.SECPKG_ATTR_NAMES)


def accept(conn: tuple, token: bytes) -> tuple[bytes | None, str | None]:
    """One NTLM step. (challenge, None): send the challenge back (401). (None, 'RH\\name'): signed in.
    Raises when Windows refuses (wrong password, unknown account)."""
    now = time.time()
    with _LOCK:
        for k in [k for k, (t, _) in _PENDING.items() if t < now - 60]:
            _PENDING.pop(k, None)
        ctx = _PENDING.pop(conn, (0, None))[1]
    if ctx is None or token[8:9] == b"\x01":          # NTLM message 1 (negotiate) starts a new handshake
        ctx = _server_context()
    err, out = ctx.authorize(token)
    if err == 0:
        return None, _account(ctx)
    with _LOCK:
        _PENDING[conn] = (now, ctx)
    return out[0].Buffer, None
