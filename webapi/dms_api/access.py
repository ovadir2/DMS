"""Department access on the file server for a new customer (DMS_ACCESS_SCRIPT=1).

The rules are in scripts/dms-access.csv and scripts/Set-DmsAccess.ps1 (IT runs it once for the whole tree): each
department folder under 01_General has its AD groups, and the parallel folders of every customer get the same groups.
When the DMS creates a customer it runs that script for the new customer only, so it gets the same access as the
others. The account of the DMS must be allowed to change permissions there (it is the owner of the folders it makes).
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger("dms_api")
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "Set-DmsAccess.ps1"


def _run(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    if r.returncode:
        logger.warning("Access: Set-DmsAccess failed (%s): %s", r.returncode, out[-2000:])
    else:
        logger.info("Access: %s", out[-2000:])


RUN = [_run]                         # the tests replace it


def new_customer(root: str, customer: str) -> None:
    """In the background: the page does not wait for it."""
    if os.name != "nt" and RUN[0] is _run:
        return
    args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
            "-Root", root, "-Customer", customer, "-Apply"]
    threading.Thread(target=RUN[0], args=(args,), daemon=True, name="dms-access").start()
