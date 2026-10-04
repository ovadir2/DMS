"""DMS First loading: bring documents from the old (unmanaged) repository into the DMS, folder by folder
with all its content, in one of two modes:
  save    - the files are only saved in the target folder (same subfolders), as is: no registration and
            no workflow; File Linker links are moved to the new path.
  approve - the DMS approval is simulated (the steps below): each file is released in Current_ReadOnly,
            registered as Approved, and Control Audit and Approval Decisions show Created, Submitted
            (by the runner) and Approved (by DMS_FIRST_LOAD_APPROVER, e.g. dms_approval@rh.co.il).

For each file under the source folder (same relative path under the target folder):
  1. the file is taken from the target folder (when it was already moved there) or copied from the source;
  2. it is moved into <its folder>\\Current_ReadOnly\\, read-only, and its SHA-256 is computed;
  3. it is registered in the Document Register as Approved (revision from the file name, else 01),
     with Control Audit rows "DMS First loading";
  4. File Linker: when the SOURCE path is registered (WebAPI#1), it is replaced with the new
     Current_ReadOnly path (WebAPI#2).
A dry run only reports the plan. Files already loaded (registered in Current_ReadOnly) are skipped,
so a run can be repeated. Every run writes a CSV report to 04_Workflow_System\\FirstLoading.
"""
from __future__ import annotations

import csv
import hashlib
import os
import shutil
import stat
import threading
import traceback
import uuid
from datetime import datetime, timezone

from . import files
from .config import WORKFLOW_FOLDERS, Settings

REPORT_DIR = os.path.join("04_Workflow_System", "FirstLoading")
JOBS: dict[str, dict] = {}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _walk(base: str) -> set[str]:
    rels = set()
    if not os.path.isdir(base):
        return rels
    for dirpath, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in WORKFLOW_FOLDERS and not d.startswith((".", "~$"))]
        for n in names:
            if not (n.startswith(("~$", ".")) or n.lower() in files.SYSTEM_FILES):
                rels.add(os.path.relpath(os.path.join(dirpath, n), base))
    return rels


def plan(source: str, target: str) -> list[dict]:
    """Every file to load, from the source tree and from what was already moved into the target tree
    (the old source path is kept for File Linker even when the file is no longer there)."""
    out = []
    for rel in sorted(_walk(source) | _walk(target)):
        n = os.path.basename(rel)
        folder = os.path.join(target, os.path.dirname(rel))
        out.append({"source": os.path.join(source, rel), "relative": rel, "folder": folder,
                    "moved": os.path.join(folder, n), "current": os.path.join(folder, "Current_ReadOnly", n)})
    return out


def run(job: dict, sp, s: Settings, linker, actor: str, *, source: str, target: str, document_type: str | None,
        document_area: str | None, control_mode: str | None, dry_run: bool, copy_missing: bool, update_links: bool,
        classify=None, mode: str = "approve", approver: str | None = None) -> None:
    """document_type / document_area None: each file inherits them from its blueprint folder (classify)."""
    c = s.choices
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    job["stamp"] = stamp
    log_path = _log_path(s, stamp, dry_run)
    job["log"] = log_path
    logf = open(log_path, "a", encoding="utf-8-sig") if log_path else None

    def L(msg: str) -> None:
        """Full trace, written line by line (complete even if the run stops)."""
        if logf:
            logf.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}  {msg}\n")
            logf.flush()

    L(f"DMS First loading {'(DRY RUN) ' if dry_run else ''}started by {actor}")
    L(f"  source: {source}")
    L(f"  target: {target}")
    L(f"  document type: {document_type or 'from the blueprint folder'} | area: {document_area or 'from the blueprint folder'}"
      f" | control mode: {control_mode or 'from the blueprint folder'}")
    L(f"  copy missing from source: {copy_missing} | update File Linker: {update_links} (configured: {bool(linker and linker.enabled)})")
    approver = (approver or s.first_load_approver or actor).lower()
    L(f"  mode: {'save - approved by DMS: Current_ReadOnly, registered as Collaboration (no workflow)' if mode == 'save' else f'DMS approval simulated - approver {approver}'}")
    items = plan(source, target)
    L(f"  files found: {len(items)} (source and target trees, without workflow folders and system files)")
    job.update(total=len(items), done=0, rows=[])
    registered = {os.path.normcase(os.path.normpath(p)) for d in sp.documents(refresh=True)
                  for p in (d.get("currentUncPath"), d.get("workingUncPath")) if p}
    for it in items:
        row = {"source": it["source"], "target": it["current"], "documentId": "", "revision": "", "sha256": "",
               "documentType": "", "documentArea": "", "result": "", "fileLinker": ""}
        L(f"[{job['done'] + 1}/{len(items)}] {it['relative']}")
        L(f"    source path: {it['source']} (exists: {os.path.isfile(it['source'])})")
        L(f"    in target:   {it['moved']} (exists: {os.path.isfile(it['moved'])})")
        if mode == "save":
            try:
                _save_only(it, row, L, dry_run, copy_missing, update_links, linker, s, sp, actor, classify)
            except Exception as e:  # noqa: BLE001 - one file must not stop the others
                row["result"] = f"error - {e}"
                L(f"    ERROR: {e!r}")
            job["rows"].append(row)
            job["done"] += 1
            continue
        try:
            bp = classify(it["folder"]) if classify and not (document_type and document_area and control_mode) else {}
            ftype, farea = document_type or bp.get("documentType"), document_area or bp.get("documentArea")
            fmode = control_mode or bp.get("controlMode")
            row.update(documentType=ftype or "", documentArea=farea or "")
            L(f"    type: {ftype or '-'} | area: {farea or '-'} | control mode: {fmode or '-'}"
              + (" (from the blueprint folder)" if bp else ""))
            if os.path.normcase(os.path.normpath(it["current"])) in registered:
                row["result"] = "skipped - already loaded"
                L(f"    skipped: already registered at {it['current']}")
            elif not ftype or not farea:
                raise ValueError("no document type or area: this folder does not set them in the blueprint; choose them for the run")
            elif dry_run:
                where = "in the target" if os.path.isfile(it["moved"]) else ("copy from the source" if copy_missing else "MISSING in the target")
                row["result"] = f"plan - {where} -> Current_ReadOnly"
                L(f"    plan: {where} -> {it['current']}")
                if update_links and linker is not None and linker.enabled:
                    row["fileLinker"] = "registered - would be updated" if linker.is_registered(it["source"]) else "not registered"
                    L(f"    File Linker WebAPI#1 ({it['source']}): {row['fileLinker']}")
            else:
                if os.path.isfile(it["moved"]):
                    from_path = it["moved"]
                    L("    taken from the target folder (moved there before)")
                elif copy_missing and os.path.isfile(it["source"]):
                    os.makedirs(it["folder"], exist_ok=True)
                    from_path = it["moved"]
                    shutil.copy2(it["source"], from_path)
                    L(f"    copied from the source to {from_path} ({os.path.getsize(from_path)} bytes)")
                else:
                    raise FileNotFoundError("the file is not in the target folder (copy from the source is off)")
                if os.path.exists(it["current"]):
                    raise FileExistsError("a file with this name is already in Current_ReadOnly")
                doc, sha, rev, title = _approve_like_the_dms(sp, s, it, from_path, ftype, farea, fmode, actor, approver, L)
                registered.add(os.path.normcase(os.path.normpath(it["current"])))
                row.update(documentId=doc["documentId"], revision=rev, sha256=sha, result="loaded")
                if update_links and linker is not None and linker.enabled:
                    try:
                        found = linker.is_registered(it["source"])
                        L(f"    File Linker WebAPI#1 ({it['source']}): {'registered' if found else 'not registered'}")
                        if found:
                            linker.replace(it["source"], it["current"])
                            L(f"    File Linker WebAPI#2: {it['source']} -> {it['current']} OK")
                            row["fileLinker"] = "updated"
                            sp.audit(document_id=doc["documentId"], event=c["StatusChanged"], from_status=c["Approved_ReadOnly"],
                                     to_status=c["Approved_ReadOnly"], actor=actor,
                                     details=f"File Linker link moved: {it['source']} -> {it['current']}")
                        else:
                            row["fileLinker"] = "not registered"
                    except Exception as e:  # noqa: BLE001 - the document is loaded; report the link problem
                        row["fileLinker"] = f"error - {e}"
                        L(f"    File Linker ERROR: {e!r}")
        except Exception as e:  # noqa: BLE001 - one file must not stop the others
            row["result"] = f"error - {e}"
            L(f"    ERROR: {e!r}")
            L("    " + traceback.format_exc().strip().replace("\n", "\n    "))
            if not dry_run:
                try:
                    sp.audit(document_id=f"FIRST-LOAD-{stamp}", event=c["FileFailed"], from_status="", to_status="",
                             actor=actor, details=f"DMS First loading failed for {it['source']} -> {it['current']}: {e}",
                             source=c["WorkflowService"])
                except Exception as ae:  # noqa: BLE001
                    L(f"    Control Audit write failed: {ae!r}")
        job["rows"].append(row)
        job["done"] += 1
    job["report"] = _write_report(s, job)
    counts: dict[str, int] = {}
    for r in job["rows"]:
        key = r["result"].split(" - ")[0]
        counts[key] = counts.get(key, 0) + 1
    L(f"Finished: {len(items)} files - " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    L(f"  File Linker: {sum(1 for r in job['rows'] if r['fileLinker'] == 'updated')} updated, "
      f"{sum(1 for r in job['rows'] if r['fileLinker'].startswith('error'))} errors")
    L(f"  CSV report: {job['report']}")
    summary = (f"DMS First loading{' (dry run)' if dry_run else ''}: {source} -> {target}. {len(items)} files - "
               + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
               + f". Trace log: {log_path}. CSV: {job['report']}")
    try:
        failed = any(r["result"].startswith("error") for r in job["rows"])
        audit_id = sp.audit(document_id=f"FIRST-LOAD-{stamp}", event=c["FileFailed" if failed else "FileDone"],
                            from_status="", to_status="", actor=actor, details=summary, source=c["WorkflowService"])
        L(f"  Control Audit summary row: FIRST-LOAD-{stamp}")
        if logf:
            logf.close()
            logf = None
        if audit_id and hasattr(sp, "attach"):
            for path in (log_path, job["report"]):
                if path and os.path.isfile(path):
                    sp.attach(audit_id, os.path.basename(path), path)
    except Exception as e:  # noqa: BLE001 - the run is done; the trace stays on the file server
        L(f"  Control Audit summary / attachments failed: {e!r}")
        job["auditError"] = str(e)
    if logf:
        logf.close()
    job["state"] = "finished"


def _approve_like_the_dms(sp, s: Settings, it: dict, working: str, ftype, farea, fmode, actor: str, approver: str, L):
    """The DMS approval of one file, step by step as on the page and in the file service, with the same
    Document Register fields and Control Audit / Approval Decisions rows; the approver is `approver`."""
    from .file_service import _move, _set_read_only
    c = s.choices
    rel = lambda p: os.path.relpath(p, s.repository_root)  # noqa: E731
    title = os.path.splitext(os.path.basename(working))[0]
    rev = f"{files.parse_revision(os.path.basename(working))[1] or 1:02d}"
    # 1. registered in Working (as "Start workflow" on the page)
    doc = sp.create_document(title=title, path=working, document_type=ftype, document_area=farea,
                             owner_email=actor, control_mode=fmode, document_id=None)
    did = doc["documentId"]
    sp.update(doc["id"], {"DraftRevision": rev})
    sp.audit(document_id=did, event=c["Created"], from_status="", to_status=c["Working"], actor=actor,
             details=f"Registered by DMS First loading from {it['source']}: {rel(working)}")
    L(f"    1 registered {did} (item {doc['id']}) in Working, revision {rev}, owner {actor}")
    # 2. submitted for approval, the approver chosen
    sp.update(doc["id"], {"LifecycleStatus": c["Submitted"]})
    submitted_utc = datetime.now(timezone.utc)
    sp.audit(document_id=did, event=c["SubmittedEvent"], from_status=c["Working"], to_status=c["Submitted"], actor=actor,
             details=f"Submitted by DMS First loading. Approvers (chosen): {approver}")
    L(f"    2 submitted, approver {approver}")
    # 3. the file service locks it in Submitted
    sub = _move(working, os.path.join(os.path.dirname(working), "Submitted", os.path.basename(working)), replace=True)
    sha = _sha256(sub)
    sp.audit(document_id=did, event=c["FileDone"], from_status=c["Submitted"], to_status=c["Submitted"],
             actor="RH-DMS-Workflow-Service", details=f"MoveToSubmitted: {rel(working)} -> {rel(sub)}. SHA-256 {sha}",
             source=c["WorkflowService"])
    L(f"    3 file -> {sub} (SHA-256 {sha})")
    # 4. approved by the approver
    sp.update(doc["id"], {"LifecycleStatus": c["Approved_ReadOnly"], "LastApprovedUtc": datetime.now(timezone.utc).isoformat()})
    sp.audit(document_id=did, event=c["ApprovedEvent"], from_status=c["Submitted"], to_status=c["Approved_ReadOnly"],
             actor=approver, details=f"Stage 1: approved in the old repository (DMS First loading) [file SHA-256 {sha}]")
    try:
        sp.log_decision(workflow_id=f"{did}-{submitted_utc.strftime('%Y%m%dT%H')}"[:40], document_id=did, revision=rev,
                        approver=approver, role="Mandatory", stage=1, decision="Approved",
                        comment="Approved in the old repository (DMS First loading)")
    except Exception as e:  # noqa: BLE001 - the decisions list is a record; the approval stands
        L(f"    Approval Decisions row failed: {e!r}")
    L(f"    4 approved by {approver} (Control Audit + Approval Decisions)")
    # 5. the file service releases it: Current_ReadOnly, read-only, register updated
    cur = _move(sub, it["current"])
    _set_read_only(cur, True)
    sha = _sha256(cur)
    sp.update(doc["id"], {"CurrentUncPath": cur, "CurrentSHA256": sha, "WorkingUncPath": "",
                          "CurrentRevision": rev, "DraftRevision": ""})
    sp.audit(document_id=did, event=c["FileDone"], from_status=c["Approved_ReadOnly"], to_status=c["Approved_ReadOnly"],
             actor="RH-DMS-Workflow-Service", details=f"PromoteToCurrent: {rel(sub)} -> {rel(cur)}. SHA-256 {sha}",
             source=c["WorkflowService"])
    L(f"    5 released: {cur}, read-only, revision {rev} current")
    try:
        os.rmdir(os.path.dirname(sub))                       # the Submitted folder, when it is left empty
    except OSError:
        pass
    return doc, sha, rev, title


def _save_only(it: dict, row: dict, L, dry_run: bool, copy_missing: bool, update_links: bool, linker,
               s: Settings, sp, actor: str, classify=None) -> None:
    """Mode save: released as a formal approval, approved by the DMS itself - the file goes to Current_ReadOnly
    in its folder, read only, registered in the Document Register (Approved by DMS, control mode Collaboration)
    with a Control Audit row (SHA-256); no workflow. The owner (who ran it) can share it with a customer."""
    from .file_service import _move, _set_read_only
    from . import noworkflow
    there, done = os.path.isfile(it["moved"]), os.path.isfile(it["current"])
    if dry_run:
        where = "already released" if done else ("in the target" if there else ("copy from the source" if copy_missing else "MISSING in the target"))
        row["result"] = f"plan - {where} -> Current_ReadOnly (approved by DMS, no workflow)"
        L(f"    plan: {where} -> {it['current']} (approved by DMS, no workflow)")
        if update_links and linker is not None and linker.enabled:
            row["fileLinker"] = "registered - would be updated" if linker.is_registered(it["source"]) else "not registered"
        return
    if done:
        row["result"] = "skipped - already released"
        L(f"    already in {it['current']}")
        return
    if there:
        cur = _move(it["moved"], it["current"])
        L("    taken from the target folder (moved there before)")
    elif copy_missing and os.path.isfile(it["source"]):
        os.makedirs(os.path.dirname(it["current"]), exist_ok=True)
        shutil.copy2(it["source"], it["current"])
        cur = it["current"]
    else:
        raise FileNotFoundError("the file is not in the target folder (copy from the source is off)")
    _set_read_only(cur, True)
    noworkflow.mark(s.repository_root, cur)
    doc = noworkflow.release(sp, s, cur, actor, f"First loading save only, from {it['source']}", classify)
    row.update(result="released - approved by DMS", sha256=doc.get("currentSHA256") or _sha256(cur), target=cur,
               documentId=doc.get("documentId") or "", revision=doc.get("currentRevision") or "",
               documentType=doc.get("documentType") or "", documentArea=doc.get("documentArea") or "")
    L(f"    released (approved by DMS, no workflow): {cur}, read-only, registered {doc.get('documentId')} (Collaboration)")
    it = {**it, "moved": cur}
    if update_links and linker is not None and linker.enabled and os.path.normcase(it["source"]) != os.path.normcase(it["moved"]):
        try:
            if linker.is_registered(it["source"]):
                linker.replace(it["source"], it["moved"])
                row["fileLinker"] = "updated"
                L(f"    File Linker WebAPI#2: {it['source']} -> {it['moved']} OK")
            else:
                row["fileLinker"] = "not registered"
        except Exception as e:  # noqa: BLE001
            row["fileLinker"] = f"error - {e}"
            L(f"    File Linker ERROR: {e!r}")


def _log_path(s: Settings, stamp: str, dry_run: bool) -> str | None:
    folder = os.path.join(s.repository_root, REPORT_DIR)
    try:
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, f"FirstLoading_{stamp}{'_dry-run' if dry_run else ''}.log")
    except OSError:
        return None


def _write_report(s: Settings, job: dict) -> str | None:
    folder = os.path.join(s.repository_root, REPORT_DIR)
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"FirstLoading_{job['stamp']}{'_dry-run' if job['dryRun'] else ''}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["source", "target", "documentId", "revision", "sha256", "documentType", "documentArea", "result", "fileLinker"])
            w.writeheader()
            w.writerows(job["rows"])
        return path
    except OSError:
        return None


def start(sp, s: Settings, linker, actor: str, **kw) -> dict:
    job = {"id": uuid.uuid4().hex[:12], "state": "running", "dryRun": kw["dry_run"], "source": kw["source"],
           "target": kw["target"], "total": 0, "done": 0, "rows": [], "report": None, "log": None, "actor": actor}
    JOBS[job["id"]] = job

    def work():
        try:
            run(job, sp, s, linker, actor, **kw)
        except Exception as e:  # noqa: BLE001
            job.update(state="failed", error=str(e))

    threading.Thread(target=work, name=f"first-load-{job['id']}", daemon=True).start()
    return job
