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


def to_root(root: str, path: str | None) -> str | None:
    """The record's path expressed under the root. A record saved with a mapped drive (S:\\...) while the
    root is a UNC path (or the other way round) is translated through the real path of both."""
    if _under_root(root, path):
        return path
    if not path or ".." in path.replace("\\", "/").split("/"):
        return None
    try:
        real_root, probe = os.path.realpath(root), path
        while probe and not os.path.exists(probe) and os.path.dirname(probe) != probe:
            probe = os.path.dirname(probe)
        real_probe = os.path.realpath(probe)
        if _under_root(real_root, real_probe) or os.path.normcase(real_probe) == os.path.normcase(real_root):
            tail = os.path.relpath(path, probe)
            return os.path.normpath(os.path.join(root, os.path.relpath(real_probe, real_root), tail))
    except (OSError, ValueError):
        pass
    return None


def run_once(sp, s: Settings) -> dict:
    """One pass over the register. Returns the counts and, per record, what was done or why not."""
    c = s.choices
    rel = lambda p: os.path.relpath(p, s.repository_root) if p else p  # noqa: E731 - short paths in the audit
    done, failed, report = 0, 0, []
    for d in sp.documents(refresh=True):
        status, raw = d.get("lifecycleStatus"), d.get("workingUncPath")
        doc_id = d.get("documentId") or f"ID {d.get('id')}"
        if status not in (c["Working"], c["Submitted"], c["Approved_ReadOnly"]):
            continue
        if not raw:
            if status == c["Approved_ReadOnly"] and d.get("currentUncPath"):
                report.append({"documentId": doc_id, "result": f"current: {d['currentUncPath']}"})
            continue
        working = to_root(s.repository_root, raw)
        if not working:
            report.append({"documentId": doc_id, "result": f"skipped - the path is outside the repository root {s.repository_root}: {raw}"})
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
                details = f"{action}: {rel(working)} -> {rel(target)}. SHA-256 {_sha256(target)}"
            elif status == c["Working"] and os.path.isfile(in_submitted) and not os.path.exists(working):
                action = "ReturnToWorking"
                _set_read_only(in_submitted, False)
                details = f"{action}: {rel(in_submitted)} -> {rel(_move(in_submitted, working))}"
            elif status == c["Approved_ReadOnly"]:
                source = next((p for p in (in_submitted, working) if os.path.isfile(p)), None)
                if not source:
                    report.append({"documentId": doc_id, "result": f"skipped - approved, but the file is not at {rel(working)} or {rel(in_submitted)}"})
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
                details = f"{action}: {rel(source)} -> {rel(target)}. SHA-256 {sha}" + (f". Previous revision -> {rel(obsolete)}" if obsolete else "")
            if not details:
                where = in_submitted if os.path.isfile(in_submitted) else working
                report.append({"documentId": doc_id, "result": f"no change - {status}, file at {rel(where)}"})
            if details:
                sp.audit(document_id=d.get("documentId") or f"ID {d['id']}", event=c["FileDone"], from_status=status,
                         to_status=status, actor="RH-DMS-Workflow-Service", details=details, source=c["WorkflowService"])
                log.info("%s %s", d.get("documentId"), details)
                report.append({"documentId": doc_id, "result": details})
                done += 1
        except Exception as e:  # noqa: BLE001 - one record must not stop the others
            failed += 1
            msg = f"{action} failed for {name}: {e}"
            log.error("%s %s", d.get("documentId"), msg)
            report.append({"documentId": doc_id, "result": msg})
            try:
                sp.audit(document_id=d.get("documentId") or f"ID {d['id']}", event=c["FileFailed"], from_status=status,
                         to_status=status, actor="RH-DMS-Workflow-Service", details=msg, source=c["WorkflowService"])
            except Exception:  # noqa: BLE001
                pass
    return {"moved": done, "failed": failed, "report": report}


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
