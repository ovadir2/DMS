"""The signed-in user and what AD lets them see.

With DMS_AUTH_MODE=windows, IIS signs the user in (Windows Authentication, no login screen) and
passes the user's Windows token to the service (HttpPlatformHandler forwardWindowsAuthToken).
Every folder and file is then checked against its NTFS permissions with that token
(Win32 AccessCheck), so a user sees and saves only what AD allows them, even though the service
itself reads the file server with its own account. No Kerberos delegation is needed.
"""
from __future__ import annotations

import os

from dataclasses import dataclass, field

READ, WRITE = "read", "write"
TOKEN_HEADER = "MS-ASPNETCORE-WINAUTHTOKEN"          # the ASP.NET Core module (ANCM) forwards the user's token here
TOKEN_HEADERS = (TOKEN_HEADER, "X-IIS-WindowsAuthToken")   # HttpPlatformHandler calls the same thing X-IIS-WindowsAuthToken


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


FILE_GENERIC_READ, FILE_GENERIC_WRITE, FILE_GENERIC_EXECUTE, FILE_ALL_ACCESS = 0x120089, 0x120116, 0x1200A0, 0x1F01FF
MAXIMUM_ALLOWED = 0x02000000
# What the DMS asks for. The whole of FILE_GENERIC_WRITE was asked for before, and that also demands
# FILE_WRITE_EA, FILE_WRITE_ATTRIBUTES, READ_CONTROL and SYNCHRONIZE: a folder whose group is given Modify in
# Explorer has them all, but one set by hand - "Write" without extended attributes, Modify with attributes
# taken out, rights given on the share and not on the folder - does not, and the person was then told they
# may not save here while Explorer let them. Adding a file needs exactly these two bits.
NEEDED = {READ: 0x0001 | 0x0080,                 # FILE_READ_DATA (list a folder) | FILE_READ_ATTRIBUTES
          WRITE: 0x0002 | 0x0004}                # FILE_WRITE_DATA (add a file) | FILE_APPEND_DATA (add a folder)
STRICT = {READ: FILE_GENERIC_READ, WRITE: FILE_GENERIC_WRITE}


def _needed(access: str) -> int:
    """DMS_STRICT_ACCESS_CHECK=1 asks for the full generic right again, as the DMS did until now."""
    table = STRICT if os.environ.get("DMS_STRICT_ACCESS_CHECK", "").strip().lower() in ("1", "true", "yes", "on") else NEEDED
    return table.get(access, table[READ])


def _windows_access(token, path: str, access: str) -> bool:
    """Does this user's token allow read / write on this path? Win32 AccessCheck, the same answer as
    Explorer's "Effective Access". Called through ctypes: win32security.AccessCheck is missing from
    some pywin32 builds, and the DMS must not depend on which build is installed."""
    import ctypes
    from ctypes import wintypes

    class GENERIC_MAPPING(ctypes.Structure):
        _fields_ = [("GenericRead", wintypes.DWORD), ("GenericWrite", wintypes.DWORD),
                    ("GenericExecute", wintypes.DWORD), ("GenericAll", wintypes.DWORD)]

    class PRIVILEGE_SET(ctypes.Structure):                  # room for one privilege: AccessCheck asks for none
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Control", wintypes.DWORD),
                    ("Privilege", wintypes.BYTE * 12)]

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    info = 0x1 | 0x2 | 0x4                                  # owner, group, DACL
    try:
        need = wintypes.DWORD()
        adv.GetFileSecurityW(path, info, None, 0, ctypes.byref(need))
        if not need.value:
            return False
        sd = ctypes.create_string_buffer(need.value)
        if not adv.GetFileSecurityW(path, info, sd, need, ctypes.byref(need)):
            return False
        mapping = GENERIC_MAPPING(FILE_GENERIC_READ, FILE_GENERIC_WRITE, FILE_GENERIC_EXECUTE, FILE_ALL_ACCESS)
        privileges, size = PRIVILEGE_SET(), wintypes.DWORD(ctypes.sizeof(PRIVILEGE_SET))
        granted, allowed = wintypes.DWORD(), wintypes.BOOL()
        # Everything this user is allowed here, in one answer, and the DMS then looks for the bits it needs.
        # Asking AccessCheck for a fixed right instead says only yes or no, and never which bit was missing.
        ok = adv.AccessCheck(sd, wintypes.HANDLE(int(token)), wintypes.DWORD(MAXIMUM_ALLOWED),
                             ctypes.byref(mapping), ctypes.byref(privileges), ctypes.byref(size),
                             ctypes.byref(granted), ctypes.byref(allowed))
        if not ok:
            return False
        need = _needed(access)
        return (granted.value & need) == need
    except OSError:
        return False


def granted_mask(user: "User", path: str) -> int:
    """Everything this person is allowed on that path, as the mask Windows answers with. For the diagnostics
    page: what the DMS saw, beside what it needed, so a refusal can be read instead of guessed at."""
    if user.ad is not None:
        return user.ad.granted(path)
    if user.token is None:
        return FILE_ALL_ACCESS
    import ctypes
    from ctypes import wintypes

    class GENERIC_MAPPING(ctypes.Structure):
        _fields_ = [("GenericRead", wintypes.DWORD), ("GenericWrite", wintypes.DWORD),
                    ("GenericExecute", wintypes.DWORD), ("GenericAll", wintypes.DWORD)]

    class PRIVILEGE_SET(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Control", wintypes.DWORD),
                    ("Privilege", wintypes.BYTE * 12)]

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    try:
        need = wintypes.DWORD()
        adv.GetFileSecurityW(path, 0x7, None, 0, ctypes.byref(need))
        if not need.value:
            return 0
        sd = ctypes.create_string_buffer(need.value)
        if not adv.GetFileSecurityW(path, 0x7, sd, need, ctypes.byref(need)):
            return 0
        mapping = GENERIC_MAPPING(FILE_GENERIC_READ, FILE_GENERIC_WRITE, FILE_GENERIC_EXECUTE, FILE_ALL_ACCESS)
        privileges, size = PRIVILEGE_SET(), wintypes.DWORD(ctypes.sizeof(PRIVILEGE_SET))
        granted, allowed = wintypes.DWORD(), wintypes.BOOL()
        if not adv.AccessCheck(sd, wintypes.HANDLE(int(user.token)), wintypes.DWORD(MAXIMUM_ALLOWED),
                               ctypes.byref(mapping), ctypes.byref(privileges), ctypes.byref(size),
                               ctypes.byref(granted), ctypes.byref(allowed)):
            return 0
        return granted.value
    except OSError:
        return 0


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

    def granted(self, path: str) -> int:
        """Everything this person's AD groups allow on that path, as Windows answers it."""
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
        if error.value:
            return 0
        return granted.value

    def can(self, path: str, access: str = READ) -> bool:
        need = _needed(access)
        return (self.granted(path) & need) == need


def may_see(email: str, path: str, access: str = READ) -> bool | None:
    """May that person read (or write) this path, by their AD groups alone - without their login and without
    anything on their PC? None when the question cannot be answered here (not Windows, no domain, the account
    is not in AD): the caller then lets it pass rather than blocking on a check it could not make."""
    if os.name != "nt" or not email or not path:
        return None
    try:
        return AdUser.get(email).can(path, access)
    except (PermissionError, OSError, AttributeError):
        return None


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
