"""The Workflow Service file moves (scripts/Invoke-DmsWorkflowService.ps1), inside the web service
for the pilot (DMS_FILE_SERVICE_SECONDS > 0). Per Document Register record:

  Submitted  file in its own place  -> <folder>\\Submitted, read-only
  Approved   file in Submitted/own  -> previous current -> Obsolete_ReadOnly; file -> Current_ReadOnly
                                       (without "_DRAFT"), read-only; CurrentUncPath, CurrentSHA256 written back
  Working    file in Submitted      -> back to its own place (rejected), writable

A record in Submitted is never updated, so the approval flow (DC-P1) is not triggered again.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import stat
import threading
import time
from datetime import datetime

from .config import WORKFLOW_FOLDERS, Settings
from .files import is_read_only

log = logging.getLogger("dms_api.file_service")


def _set_read_only(path: str, on: bool) -> None:
    mode = os.stat(path).st_mode
    os.chmod(path, (mode & ~stat.S_IWRITE & ~stat.S_IWGRP & ~stat.S_IWOTH) if on else (mode | stat.S_IWRITE))


def _move(source: str, target: str) -> str:
    """Never overwrites: an existing target gets a timestamp suffix."""
    if os.path.exists(target):
        base, ext = os.path.splitext(target)
        target = f"{base}_{datetime.now():%Y%m%d%H%M%S}{ext}"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    ro = is_read_only(source)
    if ro:
        _set_read_only(source, False)
    os.replace(source, target)
    if ro:
        _set_read_only(target, True)
    return target


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _under_root(root: str, path: str | None) -> bool:
    if not path or ".." in path.replace("\\", "/").split("/"):
        return False
    r, p = os.path.normcase(os.path.normpath(root)), os.path.normcase(os.path.normpath(path))
    return p.startswith(r.rstrip("\\/") + os.sep)


def run_once(sp, s: Settings) -> dict:
    c = s.choices
    done, failed = 0, 0
    for d in sp.documents(refresh=True):
        status, working = d.get("lifecycleStatus"), d.get("workingUncPath")
        if not working or status not in (c["Working"], c["Submitted"], c["Approved_ReadOnly"]) or not _under_root(s.repository_root, working):
            continue
        name, parent = os.path.basename(working), os.path.dirname(working)
        folder = os.path.dirname(parent) if os.path.basename(parent) in WORKFLOW_FOLDERS else parent
        in_submitted = os.path.join(folder, "Submitted", name)
        action = details = None
        try:
            if status == c["Submitted"] and os.path.isfile(working):
                action = "MoveToSubmitted"
                target = _move(working, in_submitted)
                _set_read_only(target, True)
                details = f"{action}: {working} -> {target}. SHA-256 {_sha256(target)}"
            elif status == c["Working"] and os.path.isfile(in_submitted) and not os.path.exists(working):
                action = "ReturnToWorking"
                _set_read_only(in_submitted, False)
                details = f"{action}: {in_submitted} -> {_move(in_submitted, working)}"
            elif status == c["Approved_ReadOnly"]:
                source = next((p for p in (in_submitted, working) if os.path.isfile(p)), None)
                if not source:
                    continue
                action = "PromoteToCurrent"
                obsolete = None
                old = d.get("currentUncPath")
                if _under_root(s.repository_root, old) and os.path.isfile(old):
                    obsolete = _move(old, os.path.join(folder, "Obsolete_ReadOnly", os.path.basename(old)))
                    _set_read_only(obsolete, True)
                current_name = re.sub(r"_DRAFT(?=\.[^.]+$|$)", "", name, flags=re.I)
                target = _move(source, os.path.join(folder, "Current_ReadOnly", current_name))
                _set_read_only(target, True)
                sha = _sha256(target)
                values = {"CurrentUncPath": target, "CurrentSHA256": sha, "WorkingUncPath": ""}
                if d.get("draftRevision"):
                    values.update(CurrentRevision=d["draftRevision"], DraftRevision="")
                sp.update(d["id"], values)
                details = f"{action}: {source} -> {target}. SHA-256 {sha}" + (f". Previous revision -> {obsolete}" if obsolete else "")
            if details:
                sp.audit(document_id=d.get("documentId") or f"ID {d['id']}", event=c["FileDone"], from_status=status,
                         to_status=status, actor="RH-DMS-Workflow-Service", details=details, source=c["WorkflowService"])
                log.info("%s %s", d.get("documentId"), details)
                done += 1
        except Exception as e:  # noqa: BLE001 - one record must not stop the others
            failed += 1
            msg = f"{action} failed for {name}: {e}"
            log.error("%s %s", d.get("documentId"), msg)
            try:
                sp.audit(document_id=d.get("documentId") or f"ID {d['id']}", event=c["FileFailed"], from_status=status,
                         to_status=status, actor="RH-DMS-Workflow-Service", details=msg, source=c["WorkflowService"])
            except Exception:  # noqa: BLE001
                pass
    return {"moved": done, "failed": failed}


def start(sp, s: Settings) -> threading.Thread:
    def loop():
        while True:
            try:
                run_once(sp, s)
            except Exception as e:  # noqa: BLE001 - keep the loop alive
                log.error("file service run failed: %s", e)
            time.sleep(s.file_service_seconds)

    t = threading.Thread(target=loop, name="dms-file-service", daemon=True)
    t.start()
    log.info("File service started, every %s s", s.file_service_seconds)
    return t
