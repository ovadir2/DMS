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
    ad: object | None = None                # dev mode with DMS_DEV_AD_CHECK: the user's AD access (AuthZ, see AdUser)
    acting_from: str = ""                   # a super user acting as this user ("Acting as"): the super user's email
    _cache: dict = field(default_factory=dict, repr=False)

    def can(self, path: str, access: str = READ) -> bool:
        if self.token is None and self.ad is None:
            return True
        key = (path.lower(), access)
        if key not in self._cache:
            self._cache[key] = (self.ad.can(path, access) if self.ad is not None
                                else _windows_access(self.token, path, access))
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


class AdUser:
    """What a domain user may do on the file server, from their AD groups, without their login: the Windows
    AuthZ API (the same as Explorer's "Effective Access" tab). Used in dev mode with DMS_DEV_AD_CHECK to test
    the AD / NTFS permissions as another user. Needs a domain PC; the groups are read once per user."""
    _rm = None
    _users: dict = {}

    def __init__(self, upn: str):
        import ctypes
        from ctypes import wintypes
        self._ct, self._wt = ctypes, wintypes
        adv, az = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("authz", use_last_error=True)
        self._adv, self._az = adv, az
        sid, size, dom, dsize, use = ctypes.create_string_buffer(68), wintypes.DWORD(68), ctypes.create_unicode_buffer(256), wintypes.DWORD(256), wintypes.DWORD()
        if not adv.LookupAccountNameW(None, upn, sid, ctypes.byref(size), dom, ctypes.byref(dsize), ctypes.byref(use)):
            raise PermissionError(f"AD: {upn} was not found (error {ctypes.get_last_error()})")
        if AdUser._rm is None:
            rm = ctypes.c_void_p()
            if not az.AuthzInitializeResourceManager(1, None, None, None, "DMS", ctypes.byref(rm)):  # 1: no audit
                raise PermissionError(f"AD: AuthZ is not available (error {ctypes.get_last_error()})")
            AdUser._rm = rm

        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]
        self._ctx = ctypes.c_void_p()
        if not az.AuthzInitializeContextFromSid(0, sid, AdUser._rm, None, LUID(0, 0), None, ctypes.byref(self._ctx)):
            raise PermissionError(f"AD: the groups of {upn} cannot be read (error {ctypes.get_last_error()})")
        self.upn, self._sid = upn, sid

    @classmethod
    def get(cls, upn: str) -> "AdUser":
        if upn not in cls._users:
            cls._users[upn] = cls(upn)
        return cls._users[upn]

    def can(self, path: str, access: str = READ) -> bool:
        ct, wt = self._ct, self._wt

        class REQUEST(ct.Structure):
            _fields_ = [("DesiredAccess", wt.DWORD), ("PrincipalSelfSid", ct.c_void_p), ("ObjectTypeList", ct.c_void_p),
                        ("ObjectTypeListLength", wt.DWORD), ("OptionalArguments", ct.c_void_p)]

        class REPLY(ct.Structure):
            _fields_ = [("ResultListLength", wt.DWORD), ("GrantedAccessMask", ct.POINTER(wt.DWORD)),
                        ("SaclEvaluationResults", ct.POINTER(wt.DWORD)), ("Error", ct.POINTER(wt.DWORD))]
        info = 0x1 | 0x2 | 0x4                                   # owner, group, DACL
        need = wt.DWORD()
        self._adv.GetFileSecurityW(path, info, None, 0, ct.byref(need))
        if not need.value:
            return False
        sd = ct.create_string_buffer(need.value)
        if not self._adv.GetFileSecurityW(path, info, sd, need, ct.byref(need)):
            return False
        granted, error = wt.DWORD(), wt.DWORD()
        reply = REPLY(1, ct.pointer(granted), None, ct.pointer(error))
        req = REQUEST(0x02000000, None, None, 0, None)           # MAXIMUM_ALLOWED
        if not self._az.AuthzAccessCheck(0, self._ctx, ct.byref(req), None, sd, None, 0, ct.byref(reply), None):
            return False
        wanted = 0x120089 if access == READ else 0x120116       # FILE_GENERIC_READ / FILE_GENERIC_WRITE
        return error.value == 0 and (granted.value & wanted) == wanted


_UPN: dict = {}


def upn_of(account: str) -> str:
    """RH\\name -> name@rh.co.il (the user principal name in AD), "" when it cannot be found (not Windows, no domain)."""
    if account in _UPN:
        return _UPN[account]
    upn = ""
    try:
        import ctypes
        from ctypes import wintypes
        size = wintypes.ULONG(512)
        buf = ctypes.create_unicode_buffer(512)
        # TranslateNameW(name, NameSamCompatible=2, NameUserPrincipal=8, out, size)
        if ctypes.WinDLL("secur32").TranslateNameW(account, 2, 8, buf, ctypes.byref(size)):
            upn = buf.value.lower()
    except (OSError, AttributeError):
        pass
    _UPN[account] = upn
    return upn
