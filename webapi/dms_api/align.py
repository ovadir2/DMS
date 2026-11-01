"""The DMS against the file server, in one pass.

Files and folders are added and removed on the file server itself - a copy dropped into a folder, a document
deleted, a folder renamed by hand. The DMS cannot see any of that happen. This looks at both sides and puts
them back in step:

1. a record whose file moved is pointed at it; a record whose file is gone is archived and says so (reconcile)
2. a file sitting in Current_ReadOnly that the DMS does not know is reported - and with --register it is
   registered as released without workflow, the same as "Release without workflow" on the page
3. a released file that is not read only is made read only, and the folder it sits in is hardened
4. a dashboard page released into Current_ReadOnly is put back in its folder (dashboards)
5. Markdown is written for what has none, and removed where it does not belong (backfill)
6. blueprint folders missing from the skeleton are listed

Nothing is deleted from SharePoint, and nothing changes without --write.

    cd C:\\DMS-Pilot\\app\\webapi
    .venv\\Scripts\\python.exe -m dms_api.align              # what it would do
    .venv\\Scripts\\python.exe -m dms_api.align --write      # do it
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from . import files
from .config import WORKFLOW_FOLDERS, Settings

log = logging.getLogger("dms_api.align")
RELEASED = ("current_readonly", "obsolete_readonly")
SKIP = (".md", ".tmp", ".lnk")


def _register_of(sp) -> dict:
    out: dict[str, dict] = {}
    for d in sp.documents():
        for key in ("currentUncPath", "workingUncPath"):
            p = d.get(key)
            if p:
                out[os.path.normcase(os.path.normpath(p))] = d
    return out


def run(s: Settings, write: bool, register: bool = False, sp=None) -> int:
    from . import backfill, dashboards, file_service, noworkflow, reconcile
    if sp is None:
        if s.sharepoint == "memory":
            from .memory import MemorySharePoint
            sp = MemorySharePoint(s)
        else:
            from .sharepoint import SharePoint
            sp = SharePoint(s)
    root = s.repository_root

    print("=== Records against the files")
    reconcile.run(s, write, sp=sp)

    print("\n=== Dashboard pages in a released folder")
    dashboards.run(root, write)

    print("\n=== Released files the DMS does not know")
    known = _register_of(sp)
    marked = noworkflow.marked(root)
    unknown, locked = [], []
    for folder, _dirs, names in os.walk(root):
        if os.path.basename(folder).lower() not in RELEASED:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if name.lower().endswith(SKIP) or name.startswith("~$"):
                continue
            if not file_service.is_read_only(path):
                locked.append(path)
            if os.path.basename(folder).lower() != "current_readonly":
                continue
            if os.path.normcase(os.path.normpath(path)) in known or noworkflow.is_marked(root, path, marked):
                continue
            unknown.append(path)
            print(f"{'registering' if (write and register) else 'not known '}  {path}")
            if write and register:
                try:
                    noworkflow.mark(root, path)
                    noworkflow.release(sp, s, path, s.first_load_approver or s.dev_user or "dms",
                                       "Found in Current_ReadOnly by the alignment pass")
                except Exception as e:  # noqa: BLE001 - one file never stops the pass
                    print(f"FAILED       {path}: {e}")
    if unknown and not register:
        print("  (--register registers these as released without workflow, with their audit row)")

    print("\n=== Released files that are not read only")
    for path in locked:
        print(f"{'making read only' if write else 'not read only  '}  {path}")
        if write:
            try:
                file_service._set_read_only(path, True)
            except OSError as e:
                print(f"FAILED       {path}: {e}")
    folders = {os.path.dirname(p) for p in locked}
    if write and folders:
        for f in sorted(folders):
            try:
                file_service._protect(f)
            except Exception as e:  # noqa: BLE001
                log.info("%s was not hardened: %s", f, e)

    print("\n=== Markdown")
    backfill.run(root, write)

    print(f"\nDone. {len(unknown)} released file(s) the DMS did not know, {len(locked)} that were not read only."
          + ("" if write else "  (nothing changed: add --write)"))
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(message)s")
    s = Settings.from_env()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--write", action="store_true", help="make the changes (without it, only says what it would do)")
    p.add_argument("--register", action="store_true",
                   help="also register a file found in Current_ReadOnly that the DMS does not know")
    a = p.parse_args()
    if not s.repository_root or not os.path.isdir(s.repository_root):
        print(f"The repository root was not found: {s.repository_root!r}", file=sys.stderr)
        return 2
    print(f"{'Aligning' if a.write else 'Checking'} the DMS against {s.repository_root}\n")
    return run(s, a.write, a.register)


if __name__ == "__main__":
    raise SystemExit(main())
