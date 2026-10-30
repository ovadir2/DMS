"""The Workflow Service file moves, inside the web service
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
import subprocess
import threading
import time
from datetime import datetime

from .config import WORKFLOW_FOLDERS, Settings
from .files import exists as _exists, is_file, is_read_only

log = logging.getLogger("dms_api.file_service")


def _set_read_only(path: str, on: bool) -> None:
    mode = os.stat(path).st_mode
    os.chmod(path, (mode & ~stat.S_IWRITE & ~stat.S_IWGRP & ~stat.S_IWOTH) if on else (mode | stat.S_IWRITE))


def _protect(folder: str) -> None:
    """A folder of released documents: whoever could see the documents still can, and only the DMS may change
    them. The permissions the folder inherited - the AD groups that may see this place - are kept exactly as
    they are and left with Read and Execute; the account the DMS runs under keeps Modify, SYSTEM and the
    administrators keep Full. Nobody is given access who did not have it, so an HR folder stays as closed as
    it was. This is what scripts\\Protect-DmsReadOnly.ps1 does to the folders that already exist."""
    if os.name != "nt":
        return
    ps = r"""
$ErrorActionPreference = 'Stop'
$path = $args[0]
$keep = @((whoami), 'NT AUTHORITY\SYSTEM', 'BUILTIN\Administrators')
$read = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
$both = @([System.Security.AccessControl.InheritanceFlags]::ContainerInherit,
          [System.Security.AccessControl.InheritanceFlags]::ObjectInherit)
$acl = Get-Acl -LiteralPath $path
$acl.SetAccessRuleProtection($true, $true)
foreach ($rule in @($acl.Access)) {
  $name = $rule.IdentityReference.Value
  if ($keep -contains $name -or $rule.AccessControlType -ne 'Allow') { continue }
  $null = $acl.RemoveAccessRule($rule)
  $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($name, $read, $both, 'None', 'Allow')))
}
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule((whoami), 'Modify', $both, 'None', 'Allow')))
Set-Acl -LiteralPath $path -AclObject $acl
"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps, "--", folder],
                           capture_output=True, text=True, timeout=60)
        if r.returncode:
            log.warning("Permissions of %s: %s", folder, (r.stdout + r.stderr).strip()[:300])
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Permissions of %s: %s", folder, e)


def _move(source: str, target: str, replace: bool = False) -> str:
    """Never overwrites (an existing target gets a timestamp suffix), unless replace: then an older copy
    of the same document at the target is replaced, so the file keeps its name."""
    if os.path.exists(target) and replace and os.path.isfile(target):
        _set_read_only(target, False)
        os.remove(target)
    if os.path.exists(target):
        base, ext = os.path.splitext(target)
        target = f"{base}_{datetime.now():%Y%m%d%H%M%S}{ext}"
    folder = os.path.dirname(target)
    fresh = not os.path.isdir(folder)
    os.makedirs(folder, exist_ok=True)
    if fresh and os.path.basename(folder) in WORKFLOW_FOLDERS[2:]:
        _protect(folder)                                  # a released folder is read only for everyone but the DMS
    ro = is_read_only(source)
    if ro:
        _set_read_only(source, False)
    os.replace(source, target)
    if ro:
        _set_read_only(target, True)
    return target


def _drop_markdown(source: str) -> None:
    """The Markdown exists for the company's AI to read, and the AI is to read the revision in force and no
    other. So when a document leaves Current_ReadOnly its Markdown is not carried into Obsolete_ReadOnly -
    it is removed. The document itself is kept there, as the record of what that revision said."""
    old_md = os.path.splitext(source)[0] + ".md"
    if not is_file(old_md):
        return
    try:
        _set_read_only(old_md, False)
        os.remove(old_md)
        log.info("The Markdown of %s was removed: it is no longer the revision in force", source)
    except OSError as e:
        log.warning("The Markdown of %s was not removed: %s", source, e)


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
        while probe and not _exists(probe) and os.path.dirname(probe) != probe:
            probe = os.path.dirname(probe)
        real_probe = os.path.realpath(probe)
        if _under_root(real_root, real_probe) or os.path.normcase(real_probe) == os.path.normcase(real_root):
            tail = os.path.relpath(path, probe)
            return os.path.normpath(os.path.join(root, os.path.relpath(real_probe, real_root), tail))
    except (OSError, ValueError):
        pass
    return None


def relocate(root: str, path: str | None, sha: str | None = None) -> str | None:
    """A file recorded under an older layout of the repository (e.g. ...\\01_Management\\Quality\\Quality and
    Standards\\... before it became 01_General\\Quality and Standards\\...): the longest end of the old path that
    exists under the root, or under one of its top folders. With a recorded SHA-256 the content must match."""
    if not path:
        return None
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    try:
        tops = [root] + [os.path.join(root, d) for d in sorted(os.listdir(root)) if os.path.isdir(os.path.join(root, d))]
    except OSError:
        return None
    for i in range(1, len(parts)):                               # longest tail first
        for base in tops:
            candidate = os.path.join(base, *parts[i:])
            if os.path.isfile(candidate) and (not sha or _sha256(candidate).lower() == sha.lower()):
                return candidate
    return None


def find_file(root: str, path: str | None, sha: str | None = None) -> str | None:
    """Where the record's file actually is now. A record keeps the path the file had when it was written, and
    the file moves on its own: an approval takes it to Current_ReadOnly, a submission to Submitted, a return
    back to Working. The file is looked for at the recorded path, then under each workflow folder of the same
    place (and without one, for a path that names a workflow folder it has since left), and last by relocate
    for a repository that was laid out differently."""
    here = to_root(root, path)
    if _exists_file(here):
        return here
    if here:
        name, parent = os.path.basename(here), os.path.dirname(here)
        folder = os.path.dirname(parent) if os.path.basename(parent) in WORKFLOW_FOLDERS else parent
        for candidate in [os.path.join(folder, w, name) for w in WORKFLOW_FOLDERS] + [os.path.join(folder, name)]:
            if _exists_file(candidate):
                return candidate
        found = find_submitted(folder, name)     # Submitted keeps older runs under a name with a timestamp
        if found:
            return found
    return relocate(root, path, sha)


def _exists_file(path: str | None) -> bool:
    return bool(path) and is_file(path)


def find_submitted(folder: str, name: str) -> str | None:
    """The document's file in <folder>\\Submitted: its own name, or (older runs) the name with a timestamp suffix."""
    exact = os.path.join(folder, "Submitted", name)
    if os.path.isfile(exact):
        return exact
    base, ext = os.path.splitext(name)
    pattern = re.compile(re.escape(base) + r"_\d{14}" + re.escape(ext) + "$", re.I)
    try:
        hits = [os.path.join(folder, "Submitted", f) for f in os.listdir(os.path.join(folder, "Submitted")) if pattern.match(f)]
    except OSError:
        return None
    return max(hits, key=os.path.getmtime) if hits else None


def return_to_working(root: str, working_path: str | None) -> str | None:
    """Withdrawn or rejected: the file goes back from Submitted to its own place, with its own name, writable.
    Returns what was done, or None when there was nothing to move."""
    working = to_root(root, working_path)
    if not working or os.path.exists(working):
        return None
    name, parent = os.path.basename(working), os.path.dirname(working)
    folder = os.path.dirname(parent) if os.path.basename(parent) in WORKFLOW_FOLDERS else parent
    source = find_submitted(folder, name)
    if not source:
        return None
    _set_read_only(source, False)
    target = _move(source, working)
    rel = lambda p: os.path.relpath(p, root)  # noqa: E731
    return f"ReturnToWorking: {rel(source)} -> {rel(target)}"


def run_once(sp, s: Settings, only: str = "") -> dict:
    """One pass over the register, or over one document (`only`, its Document ID): the DMS runs it for that
    document the moment an approval ends, so the file is where the record says without waiting for a pass.
    Returns the counts and, per record, what was done or why not."""
    c = s.choices
    rel = lambda p: os.path.relpath(p, s.repository_root) if p else p  # noqa: E731 - short paths in the audit
    done, failed, report = 0, 0, []
    for d in sp.documents(refresh=True):
        status, raw = d.get("lifecycleStatus"), d.get("workingUncPath")
        doc_id = d.get("documentId") or f"ID {d.get('id')}"
        if only and doc_id != only:
            continue
        if status not in (c["Working"], c["Submitted"], c["Approved_ReadOnly"]):
            continue
        if d.get("currentUncPath"):
            # The revision in force, whatever the document's own status is: a document whose next revision is
            # in work still has one, and it is read only on the file server and carries its Markdown too.
            held = to_root(s.repository_root, d["currentUncPath"])
            if held and is_file(held):
                if not is_read_only(held):
                    try:
                        _set_read_only(held, True)
                        log.info("%s: %s was writable and is read only again", doc_id, held)
                    except OSError as e:
                        log.warning("%s stayed writable: %s", held, e)
                if not is_file(os.path.splitext(held)[0] + ".md"):
                    try:        # the revision in force always has its Markdown, whoever released it
                        from . import markdown
                        if markdown.write_beside(held, d):
                            log.info("%s: Markdown written beside %s", doc_id, held)
                    except Exception as e:  # noqa: BLE001
                        log.info("%s has no Markdown beside it: %s", held, e)
        if not raw:
            if status == c["Approved_ReadOnly"] and d.get("currentUncPath"):
                cur = to_root(s.repository_root, d["currentUncPath"])
                if not (cur and os.path.isfile(cur)):              # recorded under an older layout of the repository
                    moved = relocate(s.repository_root, d["currentUncPath"], d.get("currentSHA256"))
                    if moved:
                        sp.update(d["id"], {"CurrentUncPath": moved})
                        details = f"CurrentUncPath corrected (the repository was reorganized): {d['currentUncPath']} -> {rel(moved)}"
                        sp.audit(document_id=doc_id, event=c["FileDone"], from_status=status, to_status=status,
                                 actor="RH-DMS-Workflow-Service", details=details, source=c["WorkflowService"])
                        report.append({"documentId": doc_id, "result": details})
                        done += 1
                        continue
                if cur and os.path.isfile(cur) and not is_read_only(cur):   # an approved file must stay read only
                    _set_read_only(cur, True)
                report.append({"documentId": doc_id, "result": f"current: {d['currentUncPath']}"})
            continue
        working = to_root(s.repository_root, raw)
        if not working:
            report.append({"documentId": doc_id, "result": f"skipped - the path is outside the repository root {s.repository_root}: {raw}"})
            continue
        name, parent = os.path.basename(working), os.path.dirname(working)
        folder = os.path.dirname(parent) if os.path.basename(parent) in WORKFLOW_FOLDERS else parent
        in_submitted = find_submitted(folder, name) or os.path.join(folder, "Submitted", name)
        action = details = None
        try:
            if status == c["Submitted"] and os.path.isfile(working):
                action = "MoveToSubmitted"
                target = _move(working, os.path.join(folder, "Submitted", name), replace=True)
                _set_read_only(target, not s.submitted_editable)   # editable: owner and approvers add remarks
                details = f"{action}: {rel(working)} -> {rel(target)}. SHA-256 {_sha256(target)}"
            elif status == c["Working"] and os.path.isfile(in_submitted) and not os.path.exists(working):
                action = "ReturnToWorking"
                details = return_to_working(s.repository_root, working)
            elif status == c["Approved_ReadOnly"]:
                source = next((p for p in (in_submitted, working) if os.path.isfile(p)), None)
                landed = os.path.join(folder, "Current_ReadOnly", re.sub(r"_DRAFT(?=\.[^.]+$|$)", "", name, flags=re.I))
                same = os.path.normcase(os.path.normpath(landed)) == os.path.normcase(os.path.normpath(
                    to_root(s.repository_root, d.get("currentUncPath")) or ""))      # the previous revision, not this one
                if not source and os.path.isfile(landed) and not same:
                    # moved on an earlier run, but SharePoint was not updated then (error): finish it now
                    action = "PromoteToCurrent"
                    sha = _sha256(landed)
                    values = {"CurrentUncPath": landed, "CurrentSHA256": sha, "WorkingUncPath": ""}
                    if d.get("draftRevision"):
                        values.update(CurrentRevision=d["draftRevision"], DraftRevision="")
                    sp.update(d["id"], values)
                    details = f"{action} (completed, the record was not updated before): {rel(landed)}. SHA-256 {sha}"
                    source = None
                elif not source:
                    report.append({"documentId": doc_id, "result": f"skipped - approved, but the file is not at {rel(working)} or {rel(in_submitted)}"})
                    continue
            if status == c["Approved_ReadOnly"] and source:
                action = "PromoteToCurrent"
                obsolete = None
                old = d.get("currentUncPath")
                if _under_root(s.repository_root, old) and os.path.isfile(old):
                    obsolete = _move(old, os.path.join(folder, "Obsolete_ReadOnly", os.path.basename(old)))
                    _set_read_only(obsolete, True)
                    _drop_markdown(old)                # the AI never quotes a revision that is not in force
                current_name = re.sub(r"_DRAFT(?=\.[^.]+$|$)", "", name, flags=re.I)
                target = _move(source, os.path.join(folder, "Current_ReadOnly", current_name))
                _set_read_only(target, True)
                try:        # beside it, the same document as Markdown: what the company's AI reads
                    from . import markdown
                    markdown.write_beside(target, d)
                except Exception as e:  # noqa: BLE001 - a release is not held up by its Markdown
                    log.info("%s has no Markdown beside it: %s", target, e)
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
