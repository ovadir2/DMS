"""The register against the file server: what the DMS believes, and what is actually there.

Files and folders removed on the file server itself - outside the DMS - leave the register holding documents
whose file is gone, Markdown beside nothing, files checked out of nowhere and blueprint folders missing from
the skeleton. The DMS cannot see that happen; this pass looks.

A file that merely moved is not gone: each record's file is looked for where the workflow would have taken it
(Working, Submitted, Current_ReadOnly, Obsolete_ReadOnly) before anything is called missing, and a record that
is found again is written back with the path it really has.

    cd C:\\DMS-Pilot\\app\\webapi
    .venv\\Scripts\\python.exe -m dms_api.reconcile            # what it would change
    .venv\\Scripts\\python.exe -m dms_api.reconcile --write    # change it
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from . import blueprint, checkout, files
from .config import Settings

log = logging.getLogger("dms_api.reconcile")


def run(s: Settings, write: bool, report: str = "", sp=None) -> int:
    from . import file_service
    root = s.repository_root
    rows: list[tuple] = []
    if sp is None:
        if s.sharepoint == "memory":
            from .memory import MemorySharePoint
            sp = MemorySharePoint(s)
        else:
            from .sharepoint import SharePoint
            sp = SharePoint(s)
    c = s.choices
    gone = found = dropped = 0

    for d in sp.documents():
        if (d.get("lifecycleStatus") or "") == c["Archived"]:
            continue
        for key, field in (("currentUncPath", "CurrentUncPath"), ("workingUncPath", "WorkingUncPath")):
            was = d.get(key) or ""
            if not was:
                continue
            now = file_service.find_file(root, was, d.get("currentSHA256") if key == "currentUncPath" else None)
            if now and os.path.normcase(os.path.normpath(now)) != os.path.normcase(os.path.normpath(was)):
                print(f"moved        {d.get('documentId')}: {was}\n          -> {now}")
                rows.append(("moved", d.get("documentId") or "", was, now))
                found += 1
                if write:
                    sp.update(d["id"], {field: now})
                continue
            if now:
                continue
            print(f"gone         {d.get('documentId')}: {was}")
            rows.append(("gone", d.get("documentId") or "", was, ""))
            gone += 1
            if not write:
                continue
            # The record stays - it is the history of a controlled document - but it no longer claims a file
            # that is not there, and the audit says when the DMS noticed.
            values = {field: ""}
            if key == "currentUncPath":
                values["LifecycleStatus"] = c["Archived"]
            sp.update(d["id"], values)
            sp.audit(document_id=d.get("documentId") or "", event=c["StatusChanged"],
                     from_status=d.get("lifecycleStatus") or "", to_status=c["Archived"] if key == "currentUncPath" else
                     (d.get("lifecycleStatus") or ""), actor=s.dev_user or "dms",
                     details=f"The file is no longer on the file server (removed outside the DMS): {was}")

    # Markdown beside nothing: it is what the AI reads, and a document that is gone must not answer.
    for folder, _dirs, names in os.walk(root):
        if os.path.basename(folder).lower() != "current_readonly":
            continue
        for name in names:
            if not name.lower().endswith(".md"):
                continue
            stem = os.path.splitext(name)[0].lower()
            if any(os.path.splitext(x)[0].lower() == stem and not x.lower().endswith(".md") for x in names):
                continue
            stale = os.path.join(folder, name)
            print(f"markdown     {stale} (the document it was written from is gone)")
            rows.append(("markdown", "", stale, ""))
            dropped += 1
            if write:
                try:
                    os.chmod(stale, os.stat(stale).st_mode | 0o200)
                    os.remove(stale)
                except OSError as e:
                    print(f"FAILED       {stale}: {e}")

    # A file checked out of a place that no longer exists can never come back by itself.
    held = checkout.read(root)
    for key, entry in list(held.items()):
        if files.is_file(entry.get("path") or ""):
            continue
        print(f"checked out  {entry.get('path')} ({entry.get('by')}) - the file is gone")
        rows.append(("checkout", entry.get("by") or "", entry.get("path") or "", ""))
        dropped += 1
        if write:
            held.pop(key, None)
    if write:
        checkout.write(root, held)

    # The skeleton itself: a blueprint folder somebody removed.
    missing = [p for p in blueprint.folder_list() if "<" not in p and not os.path.isdir(os.path.join(root, p))]
    for p in missing:
        print(f"blueprint    {p} is missing from the skeleton")
        rows.append(("blueprint", "", p, ""))
    if missing:
        print("\nRun scripts\\New-DmsFileServerTree.ps1 to put the blueprint folders back "
              "(-CompleteExisting for the customers as well).")

    print(f"\n{gone} document{'' if gone == 1 else 's'} whose file is gone, {found} found again somewhere else, "
          f"{dropped} leftover{'' if dropped == 1 else 's'}, {len(missing)} blueprint folder"
          f"{'' if len(missing) == 1 else 's'} missing"
          + ("" if write else "  (nothing changed: add --write)"))
    if report:
        with open(report, "w", encoding="utf-8-sig", newline="") as out:
            out.write("what,documentId,path,now\n")
            for row in rows:
                out.write(",".join('"' + str(x).replace('"', '""') + '"' for x in row) + "\n")
        print(f"report: {report}")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = Settings.from_env()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--write", action="store_true", help="change the register (without it, only says what it would do)")
    p.add_argument("--report", default="", help="write what was found to this CSV (UTF-8)")
    a = p.parse_args()
    if not s.repository_root or not os.path.isdir(s.repository_root):
        print(f"The repository root was not found: {s.repository_root!r}", file=sys.stderr)
        return 2
    print(f"{'Fixing' if a.write else 'Checking'} the register against {s.repository_root}\n")
    return run(s, a.write, a.report)


if __name__ == "__main__":
    raise SystemExit(main())
