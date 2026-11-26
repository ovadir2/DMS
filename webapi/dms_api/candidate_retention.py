"""Rejected candidates are not kept for ever: a folder in Candidates_Obsolete_ReadOnly is deleted once it
has been there longer than HR said to keep it (DMS_CANDIDATE_RETENTION_MONTHS). A CV is personal data of
somebody who does not work here and never did, and keeping it without a reason is the thing to avoid.

Nothing is deleted while the setting is empty or zero, which is how the DMS ships: HR decides the number.
Each deletion is one Control Audit row, so what was removed and when is still answerable afterwards.
Runs once a day inside the DMS.
"""
from __future__ import annotations

import logging
import os
import shutil
import stat
import threading
import time
from datetime import datetime, timedelta, timezone

from .config import Settings

log = logging.getLogger("dms_api.candidate_retention")

DAYS_A_MONTH = 30.44                      # a retention period in months, counted in days, as HR means it


def _obsolete_root(s: Settings) -> str:
    return os.path.join(s.repository_root, *s.candidates_obsolete.replace("/", "\\").split("\\"))


def _moved_utc(folder: str) -> datetime:
    """When the folder was put in the archive: the folder's own time, which the move sets."""
    return datetime.fromtimestamp(os.path.getmtime(folder), timezone.utc)


def _writable(folder: str) -> None:
    """The archive is read only - that is the point of it - so the flags come off before a delete."""
    for here, dirs, names in os.walk(folder):
        for n in list(dirs) + names:
            path = os.path.join(here, n)
            try:
                os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
            except OSError:
                pass


def due(s: Settings, now: datetime | None = None) -> list[tuple[str, datetime]]:
    """The archived candidate folders whose retention period has passed, oldest first."""
    months = s.candidate_retention_months
    if months <= 0:
        return []
    root = _obsolete_root(s)
    if not os.path.isdir(root):
        return []
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=months * DAYS_A_MONTH)
    out = []
    try:
        with os.scandir(root) as it:
            for e in it:
                if e.is_dir():
                    when = _moved_utc(e.path)
                    if when <= cutoff:
                        out.append((e.path, when))
    except OSError as e:
        log.warning("the candidate archive could not be read: %s", e)
        return []
    return sorted(out, key=lambda x: x[1])


def run_once(sp, s: Settings, now: datetime | None = None) -> list[str]:
    """Delete what is due. Returns the folders that went."""
    gone = []
    for folder, when in due(s, now):
        name = os.path.basename(folder)
        try:
            _writable(folder)
            shutil.rmtree(folder)
        except OSError as e:
            log.warning("%s was not deleted: %s", folder, e)
            continue
        gone.append(folder)
        details = (f"Candidate folder deleted after the retention period "
                   f"({s.candidate_retention_months} months): {folder}, archived {when:%Y-%m-%d}")
        try:
            c = s.choices
            sp.audit(document_id=f"HR-{name}", event=c["PermissionChanged"], from_status="", to_status="",
                     actor="RH-DMS-Workflow-Service", details=details, source=c["WorkflowService"])
        except Exception as e:  # noqa: BLE001 - the folder is gone; the audit is written where it can be
            log.warning("the deletion of %s was not written to the Control Audit: %s", name, e)
        log.info("%s", details)
    return gone


def start(sp, s: Settings, every: int = 24 * 3600) -> threading.Thread | None:
    if s.candidate_retention_months <= 0:
        return None

    def loop():
        time.sleep(300)                   # not while the DMS is still starting
        while True:
            try:
                run_once(sp, s)
            except Exception as e:  # noqa: BLE001 - keep the loop alive
                log.error("the candidate retention run failed: %s", e)
            time.sleep(every)

    t = threading.Thread(target=loop, name="dms-candidate-retention", daemon=True)
    t.start()
    log.info("Candidate retention started: an archived candidate folder is deleted after %s months",
             s.candidate_retention_months)
    return t
