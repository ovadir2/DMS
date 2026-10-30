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
OBSOLETE = ("obsolete_readonly", "submitted")   # a Markdown has no business there
# A PDF is read too - it is a document, and what it says is what the AI should answer from. Only what has
# no text to take (a picture, an archive) and the Markdown itself are passed over.
SKIP = (".md", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico", ".zip", ".7z", ".rar", ".exe", ".dll")


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


def run(root: str, write: bool, report: str = "") -> int:
    from . import markdown
    s = Settings.from_env()
    docs = _register(s) if write else {}                       # a dry run asks SharePoint nothing
    if write and not markdown.PDF_OF[0]:
        # The web application sets this at startup; this pass runs on its own. Without it a legacy .doc or
        # .ppt - which nothing here and no markitdown can read - would simply be counted as a failure.
        from .sharepoint import pdf_bytes
        markdown.PDF_OF[0] = lambda path: pdf_bytes(path, s)
    done = skipped = failed = 0
    rows: list[tuple] = []
    for folder, dirs, names in os.walk(root):
        if os.path.basename(folder).lower() in OBSOLETE:
            # The Markdown is what the AI reads, and it answers from the revision in force: a copy left in
            # Obsolete_ReadOnly by an older DMS would have it quoting a revision that was replaced.
            for name in names:
                if not name.lower().endswith(".md"):
                    continue
                stale = os.path.join(folder, name)
                print(f"{'removing' if write else 'would remove'}   {stale}")
                if write:
                    try:
                        os.chmod(stale, os.stat(stale).st_mode | 0o200)
                        os.remove(stale)
                        rows.append(("removed", stale, "Markdown lives in Current_ReadOnly only"))
                    except OSError as e:
                        print(f"FAILED       {stale}: {e}")
                        rows.append(("failed", stale, str(e)))
                        failed += 1
            continue
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
                    rows.append(("written", target, ""))
                    done += 1
                else:
                    print(f"nothing to read in {path}")
                    rows.append(("nothing to read", path, "neither the file itself nor its PDF gave any text"))
                    failed += 1
            except Exception as e:  # noqa: BLE001 - one file never stops the pass
                print(f"FAILED       {path}: {e}")
                rows.append(("failed", path, str(e)))
                failed += 1
    print(f"\n{done} {'to write' if not write else 'written'}, {skipped} already there or not a document, {failed} failed")
    if report:
        # Written as a file, in UTF-8: a Hebrew path does not survive every console, and the reason a
        # document has no Markdown is the one thing worth keeping from the run.
        with open(report, "w", encoding="utf-8-sig", newline="") as out:
            out.write("result,path,reason\n")
            for row in rows:
                out.write(",".join('"' + str(x).replace('"', '""') + '"' for x in row) + "\n")
        print(f"report: {report}")
    return 1 if failed else 0


def main() -> int:
    # A Hebrew path printed into a pipe would otherwise stop the whole pass: the console's own codepage
    # (cp1252) cannot write those letters, and the exception comes from the print, not from the document.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = Settings.from_env()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=s.repository_root, help="the repository root (DMS_REPOSITORY_ROOT)")
    p.add_argument("--write", action="store_true", help="write the files (without it, only says what it would do)")
    p.add_argument("--report", default="", help="write what happened to this CSV (UTF-8), one row per file")
    a = p.parse_args()
    if not a.root or not os.path.isdir(a.root):
        print(f"The repository root was not found: {a.root!r}. Give it with --root.", file=sys.stderr)
        return 2
    print(f"{'Writing' if a.write else 'Looking for'} Markdown under {a.root}\n")
    return run(a.root, a.write, a.report)


if __name__ == "__main__":
    raise SystemExit(main())
