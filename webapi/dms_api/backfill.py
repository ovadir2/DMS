"""One pass over the file server: a Markdown copy beside every file in Current_ReadOnly.

The DMS writes <document>.md beside a document when it is approved, and the upkeep pass fills in what is
missing for the documents it knows. This writes one for everything that is in a Current_ReadOnly folder,
whether or not it carries a record - a file released by hand, or approved before the DMS wrote Markdown at
all, is otherwise invisible to the AI.

    cd C:\\DMS-Pilot\\app\\webapi
    .venv\\Scripts\\python.exe -m dms_api.backfill            # what it would write
    .venv\\Scripts\\python.exe -m dms_api.backfill --write    # write it
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import Settings

log = logging.getLogger("dms_api.backfill")
FOLDER = "current_readonly"
SKIP = (".md", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".zip", ".7z", ".rar", ".msg", ".eml")


def _register(s: Settings) -> dict:
    """documentId by file path, for the header of each Markdown (revision, type, area, owner). An empty
    register is no reason to stop: the Markdown is then written with what the file itself says."""
    try:
        from .sharepoint import SharePoint
        docs = SharePoint(s).documents()
    except Exception as e:  # noqa: BLE001 - the pass is about the files, not the register
        log.warning("The register was not read (%s): the Markdown is written without the document's details", e)
        return {}
    out = {}
    for d in docs:
        for key in ("currentUncPath", "workingUncPath"):
            p = d.get(key)
            if p:
                out[os.path.normcase(os.path.normpath(p))] = d
    return out


def run(root: str, write: bool) -> int:
    from . import markdown
    docs = _register(Settings()) if write else {}     # a dry run asks SharePoint nothing
    done = skipped = failed = 0
    for folder, dirs, names in os.walk(root):
        if os.path.basename(folder).lower() != FOLDER:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if name.lower().endswith(SKIP) or name.startswith("~$"):
                skipped += 1
                continue
            target = os.path.splitext(path)[0] + ".md"
            if os.path.isfile(target):
                skipped += 1
                continue
            if not write:
                print(f"would write  {target}")
                done += 1
                continue
            try:
                d = docs.get(os.path.normcase(os.path.normpath(path)))
                if markdown.write_beside(path, d):
                    print(f"written      {target}")
                    done += 1
                else:
                    print(f"nothing to read in {path}")
                    failed += 1
            except Exception as e:  # noqa: BLE001 - one file never stops the pass
                print(f"FAILED       {path}: {e}")
                failed += 1
    print(f"\n{done} {'to write' if not write else 'written'}, {skipped} already there or not a document, {failed} failed")
    return 1 if failed else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = Settings()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=s.repository_root, help="the repository root (DMS_REPOSITORY_ROOT)")
    p.add_argument("--write", action="store_true", help="write the files (without it, only says what it would do)")
    a = p.parse_args()
    if not a.root or not os.path.isdir(a.root):
        print(f"The repository root was not found: {a.root!r}. Give it with --root.", file=sys.stderr)
        return 2
    print(f"{'Writing' if a.write else 'Looking for'} Markdown under {a.root}\n")
    return run(a.root, a.write)


if __name__ == "__main__":
    raise SystemExit(main())
