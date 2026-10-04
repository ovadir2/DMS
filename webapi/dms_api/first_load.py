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
    L(f"  mode: {'save (files only, no workflow)' if mode == 'save' else f'DMS approval simulated - approver {approver}'}")
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
            row["target"] = it["moved"]
            try:
                _save_only(it, row, L, dry_run, copy_missing, update_links, linker)
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
                os.makedirs(os.path.dirname(it["current"]), exist_ok=True)
                os.replace(from_path, it["current"])
                os.chmod(it["current"], os.stat(it["current"]).st_mode & ~stat.S_IWRITE & ~stat.S_IWGRP & ~stat.S_IWOTH)
                L(f"    moved to {it['current']}, set read-only")
                sha = _sha256(it["current"])
                L(f"    SHA-256 {sha}")
                rev = f"{files.parse_revision(os.path.basename(it['current']))[1] or 1:02d}"
                title = os.path.splitext(os.path.basename(it["current"]))[0]
                doc = sp.create_document(title=title, path=it["current"], document_type=ftype, document_area=farea,
                                         owner_email=actor, control_mode=fmode, document_id=None)
                sp.update(doc["id"], {"LifecycleStatus": c["Approved_ReadOnly"], "CurrentUncPath": it["current"],
                                      "CurrentSHA256": sha, "CurrentRevision": rev, "WorkingUncPath": "", "DraftRevision": "",
                                      "LastApprovedUtc": datetime.now(timezone.utc).isoformat()})
                rel_target = os.path.relpath(it["current"], s.repository_root)
                sp.audit(document_id=doc["documentId"], event=c["Created"], from_status="", to_status=c["Approved_ReadOnly"],
                         actor=actor, details=f"DMS First loading from {it['source']}: {rel_target}. SHA-256 {sha}")
                sp.audit(document_id=doc["documentId"], event=c["SubmittedEvent"], from_status=c["Working"], to_status=c["Submitted"],
                         actor=actor, details=f"DMS First loading: submitted for approval (Approvers (chosen): {approver})")
                sp.audit(document_id=doc["documentId"], event=c["ApprovedEvent"], from_status=c["Submitted"], to_status=c["Approved_ReadOnly"],
                         actor=approver, details=f"Stage 2: DMS First loading - approved in the old repository, released as revision {rev}"
                                                 f" [file SHA-256 {sha}]")
                try:
                    sp.log_decision(workflow_id=f"{doc['documentId']}-FL{stamp}"[:40], document_id=doc["documentId"], revision=rev,
                                    approver=approver, role="Final", stage=2, decision="Approved",
                                    comment="DMS First loading: approved in the old repository")
                except Exception as e:  # noqa: BLE001 - the document is loaded; the decisions list is a record
                    L(f"    Approval Decisions row failed: {e!r}")
                L(f"    registered {doc['documentId']} (item {doc['id']}): Approved, revision {rev}, title '{title}', owner {actor}")
                L(f"    Control Audit: Created + Submitted ({actor}) + Approved ({approver}); Approval Decisions: Final, Approved")
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


def _save_only(it: dict, row: dict, L, dry_run: bool, copy_missing: bool, update_links: bool, linker) -> None:
    """Mode save: the file goes to the same place under the target, as is (no registration, no workflow)."""
    there = os.path.isfile(it["moved"])
    if dry_run:
        where = "already in the target" if there else ("copy from the source" if copy_missing else "MISSING in the target")
        row["result"] = f"plan - {where} (save, no workflow)"
        L(f"    plan: {where} -> {it['moved']} (save, no workflow)")
        if update_links and linker is not None and linker.enabled:
            row["fileLinker"] = "registered - would be updated" if linker.is_registered(it["source"]) else "not registered"
        return
    if there:
        row["result"] = "skipped - already in the target"
        L("    already in the target folder")
    elif copy_missing and os.path.isfile(it["source"]):
        os.makedirs(it["folder"], exist_ok=True)
        shutil.copy2(it["source"], it["moved"])
        row.update(result="saved", sha256=_sha256(it["moved"]))
        L(f"    saved (no workflow): {it['moved']} ({os.path.getsize(it['moved'])} bytes)")
    else:
        raise FileNotFoundError("the file is not in the target folder (copy from the source is off)")
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
