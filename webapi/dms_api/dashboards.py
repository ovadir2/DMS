"""Dashboard pages that were released before the DMS knew what they are.

A dashboard page (dashboard_DB.html) is a tool: it is opened and it runs, and it belongs in the folder
somebody put it in, writable, so a newer one replaces it. Dropping one used to release it like any other
file - into Current_ReadOnly, read only, with a Markdown beside it - and out of there it cannot be moved by
hand, because the DMS keeps that folder read only. This puts them back.

    cd C:\\DMS-Pilot\\app\\webapi
    .venv\\Scripts\\python.exe -m dms_api.dashboards            # what it would move
    .venv\\Scripts\\python.exe -m dms_api.dashboards --write    # move it
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from . import files, noworkflow
from .config import Settings

log = logging.getLogger("dms_api.dashboards")


def run(root: str, write: bool) -> int:
    from .file_service import _move, _set_read_only
    moved = failed = 0
    seen: list[str] = []
    looked = 0

    def unreachable(e: OSError) -> None:
        # os.walk says nothing when a folder cannot be read, and the pass then reports "0 to move" for a
        # repository it never actually looked at - a share it may not read, or a path that is not there.
        nonlocal failed
        failed += 1
        print(f"NOT READ     {getattr(e, 'filename', '')}: {e}")

    for folder, _dirs, names in os.walk(root, onerror=unreachable):
        if os.path.basename(folder).lower() != "current_readonly":
            continue
        looked += 1
        for name in names:
            if not files.is_dashboard(name):
                # Every page in there is named, matching or not: when nothing is moved, the answer is almost
                # always the name itself (a space or a hyphen where the rule wants dashboard_).
                if name.lower().endswith((".html", ".htm")):
                    print(f"not a dashboard  {os.path.join(folder, name)}")
                    seen.append(name)
                continue
            here, there = os.path.join(folder, name), os.path.join(os.path.dirname(folder), name)
            if not write:
                print(f"would move   {here}\n          -> {there}")
                moved += 1
                continue
            try:
                _set_read_only(here, False)
                target = _move(here, there)
                _set_read_only(target, False)              # a tool is replaced by a newer one, not approved
                md = os.path.splitext(here)[0] + ".md"
                if os.path.isfile(md):                     # it is not a document: nothing of it belongs to the AI
                    os.chmod(md, os.stat(md).st_mode | 0o200)
                    os.remove(md)
                noworkflow.moved(root, here, target)
                print(f"moved        {here}\n          -> {target}")
                moved += 1
            except OSError as e:
                print(f"FAILED       {here}: {e}")
                failed += 1
    print(f"\n{moved} {'to move' if not write else 'moved'}, {failed} failed"
          f" ({looked} Current_ReadOnly folder{'' if looked == 1 else 's'} looked at under {root})")
    if not moved and seen:
        print("\nHTML pages that are not named as dashboards (dashboard_<name>.html, <name>_dashboard.html):")
        for name in sorted(set(seen)):
            print(f"  {name}")
    return 1 if failed else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = Settings.from_env()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=s.repository_root, help="the repository root (DMS_REPOSITORY_ROOT)")
    p.add_argument("--write", action="store_true", help="move them (without it, only says what it would do)")
    a = p.parse_args()
    if not a.root or not os.path.isdir(a.root):
        print(f"The repository root was not found: {a.root!r}. Give it with --root.", file=sys.stderr)
        return 2
    print(f"{'Moving' if a.write else 'Looking for'} dashboard pages released under {a.root}\n")
    return run(a.root, a.write)


if __name__ == "__main__":
    raise SystemExit(main())
