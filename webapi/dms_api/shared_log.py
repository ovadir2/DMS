"""The share log of each customer: <root>\\02_Customers\\<Customer>\\Shared\\DMS-Shared-Log.csv (DMS_SHARED_LOG).
One row is appended for every file shared with the customer, by any user, and for every share that expired.
UTF-8 with BOM, so Excel shows Hebrew correctly."""
from __future__ import annotations

import csv
import os
import threading
from datetime import datetime, timezone

from .config import Settings

HEADER = ["Date (UTC)", "Action", "Shared by", "Shared with", "Document ID", "Title", "Revision", "File",
          "Exchange link", "Available until"]
_lock = threading.Lock()


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
        with open(p, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(HEADER)
            for r in rows:
                w.writerow([r.get("Date (UTC)") or now, *[r.get(h, "") for h in HEADER[1:]]])
    return p
