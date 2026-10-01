"""The signed-in user and what AD lets them see.

With DMS_AUTH_MODE=windows, IIS signs the user in (Windows Authentication, no login screen) and
passes the user's Windows token to the service (HttpPlatformHandler forwardWindowsAuthToken).
Every folder and file is then checked against its NTFS permissions with that token
(Win32 AccessCheck), so a user sees and saves only what AD allows them, even though the service
itself reads the file server with its own account. No Kerberos delegation is needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

READ, WRITE = "read", "write"
TOKEN_HEADER = "MS-ASPNETCORE-WINAUTHTOKEN"


@dataclass
class User:
    email: str
    name: str = ""
    token: object | None = None             # Windows impersonation token (windows mode only)
    _cache: dict = field(default_factory=dict, repr=False)

    def can(self, path: str, access: str = READ) -> bool:
        if self.token is None:
            return True
        key = (path.lower(), access)
        if key not in self._cache:
            self._cache[key] = _windows_access(self.token, path, access)
        return self._cache[key]

    def close(self) -> None:
        if self.token is not None:
            import win32api  # type: ignore[import-not-found]

            win32api.CloseHandle(self.token)
            self.token = None


def _windows_access(token, path: str, access: str) -> bool:
    import ntsecuritycon as nsc  # type: ignore[import-not-found]
    import pywintypes  # type: ignore[import-not-found]
    import win32security  # type: ignore[import-not-found]

    info = (win32security.OWNER_SECURITY_INFORMATION | win32security.GROUP_SECURITY_INFORMATION
            | win32security.DACL_SECURITY_INFORMATION)
    try:
        sd = win32security.GetFileSecurity(path, info)
        mapping = (nsc.FILE_GENERIC_READ, nsc.FILE_GENERIC_WRITE, nsc.FILE_GENERIC_EXECUTE, nsc.FILE_ALL_ACCESS)
        wanted = nsc.FILE_GENERIC_READ if access == READ else nsc.FILE_GENERIC_WRITE
        granted, _ = win32security.AccessCheck(sd, token, wanted, mapping)
        return bool(granted)
    except pywintypes.error:
        return False


def user_from_windows_token(header_value: str) -> User:
    """Build the user from the token handle IIS forwards (hex). The handle is duplicated into this
    process by IIS and must be closed after the request (User.close)."""
    import win32api  # type: ignore[import-not-found]
    import win32con  # type: ignore[import-not-found]
    import win32security  # type: ignore[import-not-found]

    primary = int(header_value, 16)
    try:
        token = win32security.DuplicateToken(primary, win32security.SecurityImpersonation)
        win32security.ImpersonateLoggedOnUser(token)
        try:
            email = win32api.GetUserNameEx(win32con.NameUserPrincipal)
            try:
                name = win32api.GetUserNameEx(win32con.NameDisplay)
            except Exception:  # noqa: BLE001 - the display name is cosmetic
                name = email.split("@")[0]
        finally:
            win32security.RevertToSelf()
    finally:
        win32api.CloseHandle(primary)
    return User(email=email.lower(), name=name, token=token)
