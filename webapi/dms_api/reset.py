"""Back to the blueprint: take the pilot's files off the file server and leave the shape.

What was played with during the pilot - documents, drafts, the KPI folders a build made, whatever somebody
dropped to see what would happen - is not what production starts from. This removes all of it and leaves
exactly the folders the blueprint defines, the KPIs folders among them, with every customer keeping its own
tree.

    py -m dms_api.reset                 # says what it would remove, removes nothing
    py -m dms_api.reset --write         # does it
    py -m dms_api.reset --write --customers    # ...and the customer folders too (the skeleton stays)

It never touches anything outside DMS_REPOSITORY_ROOT, and it is written to be read before it is run: the
plan is printed either way.
"""
from __future__ import annotations

import os
import shutil
import stat

from . import blueprint
from .config import WORKFLOW_FOLDERS, Settings

STATE = ("CheckedOut.json", "OpenLinks.json", "NoWorkflow.json")   # 04_Workflow_System: emptied, not kept
SYSTEM = "04_Workflow_System"


def _parts(root: str, path: str) -> list[str]:
    rel = os.path.relpath(path, root)
    return [] if rel == "." else [p for p in rel.replace("\\", "/").split("/") if p]


def _of_blueprint(parts: list[str]) -> bool:
    """A folder the blueprint defines: a department, a customer (by its own name), a project, a KPIs folder,
    and the system folders at the root that the page does not show. Everything else - a KPI's own folder, a
    workflow folder, something somebody made to see what would happen - is not."""
    if not parts:
        return True
    if len(parts) == 1 and parts[0] in blueprint.HIDDEN_AT_ROOT:
        return True                     # 03_Operations_Staging, 04_Workflow_System, 05_Exchange_Quarantine
    if parts[-1] in WORKFLOW_FOLDERS:
        return False
    return blueprint.describe(parts) is not None


def plan(root: str, *, customers: bool = False) -> dict:
    """What would be removed, and what the blueprint is missing. Nothing is changed."""
    root = os.path.abspath(root)
    files: list[str] = []
    folders: list[str] = []
    skeleton = (os.environ.get("DMS_CUSTOMER_SKELETON", "") or "Customer_Skeleton").strip().lower()
    for here, dirs, names in os.walk(root, topdown=True):
        parts = _parts(root, here)
        if parts and parts[0] in blueprint.HIDDEN_AT_ROOT:
            # the system folders keep their shape, whatever is in them; what is written in them goes
            for inside, _d, written in os.walk(here):
                files += [os.path.join(inside, n) for n in sorted(written)]
            dirs[:] = []
            continue
        gone = []
        for d in sorted(dirs):
            kid = parts + [d]
            customer = len(kid) == 2 and kid[0].lower() == "02_customers"
            if customer:
                # A customer is a customer, not something the pilot made - it is kept and cleared, unless
                # the whole list of them is asked for. The shape new customers are cut from always stays.
                if not customers or d.lower() == skeleton:
                    continue
                folders.append(os.path.join(here, d))
                gone.append(d)
                continue
            if not _of_blueprint(kid):
                folders.append(os.path.join(here, d))
                gone.append(d)
        dirs[:] = [d for d in sorted(dirs) if d not in gone]
        files += [os.path.join(here, n) for n in sorted(names)]
    missing = [os.path.join(root, *p) for p in blueprint.leaves(blueprint.ROOT)
               if not os.path.isdir(os.path.join(root, *p))]
    for customer in _customers(root):
        missing += [os.path.join(customer, *p) for p in blueprint.leaves(blueprint.CUSTOMER)
                    if not os.path.isdir(os.path.join(customer, *p))]
    return {"root": root, "files": files, "folders": folders, "missing": missing}


def _customers(root: str) -> list[str]:
    base = os.path.join(root, "02_Customers")
    try:
        return sorted(e.path for e in os.scandir(base) if e.is_dir() and not e.name.startswith("."))
    except OSError:
        return []


def _writable(path: str) -> None:
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)    # released files are read only, by design
    except OSError:
        pass


def apply(what: dict) -> dict:
    """Remove what the plan names and make the folders it says are missing. Returns what happened."""
    removed_files = removed_folders = made = 0
    failed: list[str] = []
    for f in what["files"]:
        try:
            _writable(f)
            os.remove(f)
            removed_files += 1
        except OSError as e:
            failed.append(f"{f}: {e}")
    for d in what["folders"]:
        try:
            shutil.rmtree(d, onerror=lambda fn, p, _e: (_writable(p), fn(p)))
            removed_folders += 1
        except OSError as e:
            failed.append(f"{d}: {e}")
    for d in what["missing"]:
        try:
            os.makedirs(d, exist_ok=True)
            made += 1
        except OSError as e:
            failed.append(f"{d}: {e}")
    return {"files": removed_files, "folders": removed_folders, "made": made, "failed": failed}


def main(argv: list[str]) -> int:   # pragma: no cover - the command
    write = "--write" in argv
    customers = "--customers" in argv
    s = Settings.from_env()
    root = next((a for a in argv[1:] if not a.startswith("--")), "") or s.repository_root
    if not root or not os.path.isdir(root):
        print(f"The repository root was not found: {root or '(DMS_REPOSITORY_ROOT is not set)'}")
        return 2
    what = plan(root, customers=customers)
    print(f"Repository: {what['root']}\n")
    for d in what["folders"]:
        print(f"  folder   {d}")
    for f in what["files"][:200]:
        print(f"  file     {f}")
    if len(what["files"]) > 200:
        print(f"  ... and {len(what['files']) - 200} more files")
    print(f"\n{len(what['folders'])} folder(s) and {len(what['files'])} file(s) to remove, "
          f"{len(what['missing'])} blueprint folder(s) to make.")
    if not write:
        print("\nNothing was changed. Add --write to do it.")
        return 0
    done = apply(what)
    print(f"\nRemoved {done['files']} file(s) and {done['folders']} folder(s); made {done['made']}.")
    for line in done["failed"][:50]:
        print(f"FAILED {line}")
    return 1 if done["failed"] else 0


if __name__ == "__main__":   # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv))
