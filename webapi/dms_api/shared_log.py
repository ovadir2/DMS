"""The share log of each customer: <root>\\02_Customers\\<Customer>\\Shared\\DMS-Shared-Log.csv (DMS_SHARED_LOG).
One row is appended for every file shared with the customer, by any user, and for every share that expired.
UTF-8 with BOM, so Excel shows Hebrew correctly. The file is read only for everyone: read-only attribute, and on
Windows its permissions are Read for users (no rename, no delete, no edit); only the account the DMS runs under
may change it, and the DMS only appends."""
from __future__ import annotations

import csv
import logging
import os
import stat
import subprocess
import threading
from datetime import datetime, timezone

from .config import Settings

HEADER = ["Date (UTC)", "Action", "Shared by", "Shared with", "Document ID", "Title", "Revision", "File",
          "Exchange link", "Available until"]
_lock = threading.Lock()
log = logging.getLogger("dms_api.shared_log")


def _read_only(p: str, on: bool) -> None:
    mode = os.stat(p).st_mode
    os.chmod(p, (mode & ~stat.S_IWRITE & ~stat.S_IWGRP & ~stat.S_IWOTH) if on else (mode | stat.S_IWRITE))


def protect(p: str) -> None:
    """Windows: own permissions on the log, not inherited from the folder - Read for Authenticated Users and
    Users, Full for SYSTEM and Administrators, Modify for the DMS account. Rename and delete need Delete,
    which users then do not have."""
    if os.name != "nt":
        return
    try:
        me = subprocess.run(["whoami"], capture_output=True, text=True, timeout=10).stdout.strip()
        r = subprocess.run(["icacls", p, "/inheritance:r", "/grant:r", "*S-1-5-11:(R)", "*S-1-5-32-545:(R)",
                            "*S-1-5-18:(F)", "*S-1-5-32-544:(F)", f"{me}:(M)"], capture_output=True, text=True, timeout=30)
        if r.returncode:
            log.warning("Share log permissions of %s: %s", p, (r.stdout + r.stderr).strip())
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Share log permissions of %s: %s", p, e)


def path_for(s: Settings, customer: str) -> str | None:
    if not s.shared_log:
        return None
    return os.path.join(s.repository_root, s.customers_folder, customer, *s.shared_log.replace("\\", "/").split("/"))


def append(s: Settings, customer: str, rows: list[dict]) -> str | None:
    """Append rows (keys as HEADER) to the customer's log; creates the Shared folder and the file if missing."""
    p = path_for(s, customer)
    if not p or not rows:
        return None
    folder = os.path.join(s.repository_root, s.customers_folder, customer)
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"The customer folder {customer} was not found under {s.customers_folder}")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    with _lock:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        new = not os.path.exists(p)
        if not new:
            _read_only(p, False)
        with open(p, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(HEADER)
            for r in rows:
                w.writerow([r.get("Date (UTC)") or now, *[r.get(h, "") for h in HEADER[1:]]])
        _read_only(p, True)
        if new:
            protect(p)
    return p
