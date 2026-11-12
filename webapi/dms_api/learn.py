"""Learn the structure this company really has, and keep it beside the blueprint.

The blueprint in `blueprint.py` is the shape the DMS was written with. A company adds departments of its
own and folders inside them, and those are just as much "the structure": they should be grey in the page,
not renamed or deleted from a row, and each department should have its KPIs folder. This reads the file
server and writes what it finds to `04_Workflow_System\\Blueprint.json`, which the DMS merges at startup.

    py -m dms_api.learn                 # says what it would add
    py -m dms_api.learn --write         # writes it
    py -m dms_api.learn --write --depth 3     # fewer levels

What it never learns: the workflow folders, a KPI's own folder, the customers themselves (any folder under
the customers folder is a customer already), and anything hidden or starting with a dot.
"""
from __future__ import annotations

import json
import os

from . import blueprint
from .config import WORKFLOW_FOLDERS, Settings

SKIP = {*WORKFLOW_FOLDERS, "Recycle"}


def _tree(folder: str, depth: int, known: dict | None = None) -> dict:
    """Every folder under here, to `depth` levels. A Hebrew name already written for a folder is kept as
    it is: somebody corrected it, and learning again must not undo that."""
    out: dict = {}
    if depth <= 0:
        return out
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
    except OSError:
        return out
    for e in entries:
        if not e.is_dir() or e.name.startswith(".") or e.name in SKIP:
            continue
        was = (known or {}).get(e.name) or {}
        out[e.name] = {"en": was.get("en") or e.name.replace("_", " "),
                       "he": was.get("he") or blueprint.hebrew_of(e.name) or "",
                       "folders": _tree(e.path, depth - 1, was.get("folders"))}
    return out


def read(root: str, *, depth: int = 6, skeleton: str = "") -> dict:
    """What the file server has: the departments under General with their folders, all the way down, and
    the shape shared by the customers (taken from the skeleton, which is what a new customer is cut from).

    What was learned before is read first, so a Hebrew name somebody corrected in Blueprint.json survives."""
    was = {}
    try:
        with open(os.path.join(root, blueprint.LEARNED), encoding="utf-8") as f:
            was = json.load(f)
    except (OSError, ValueError):
        was = {}
    general = _tree(os.path.join(root, "01_General"), depth, was.get("general"))
    customer = {}
    shape = os.path.join(root, "02_Customers", skeleton or "Customer_Skeleton")
    if os.path.isdir(shape):
        customer = _tree(shape, depth, was.get("customer"))
    return {"general": general, "customer": customer}


def what_is_new(found: dict) -> list[str]:
    """The folders that are not in the blueprint already - what learning them would add."""
    out: list[str] = []

    def walk(tree: dict, names: dict, where: str) -> None:
        for name, kids in sorted(names.items()):
            node = tree.get(name) or next((v for k, v in tree.items() if k.lower() == name.lower()), None)
            if node is None:
                out.append(f"{where}\\{name}")
            walk((node[2] if node else {}) or {}, kids.get("folders") or {}, f"{where}\\{name}")

    walk(blueprint.MANAGEMENT, found.get("general") or {}, "01_General")
    walk(blueprint.CUSTOMER, found.get("customer") or {}, "02_Customers\\<customer>")
    return out


def write(root: str, found: dict) -> str:
    path = os.path.join(root, blueprint.LEARNED)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(found, f, ensure_ascii=False, indent=1)
    return path


def main(argv: list[str]) -> int:   # pragma: no cover - the command
    s = Settings.from_env()
    root = next((a for a in argv[1:] if not a.startswith("--")), "") or s.repository_root
    depth = 6
    if "--depth" in argv:
        try:
            depth = int(argv[argv.index("--depth") + 1])
        except (IndexError, ValueError):
            pass
    if not root or not os.path.isdir(root):
        print(f"The repository root was not found: {root or '(DMS_REPOSITORY_ROOT is not set)'}")
        return 2
    found = read(root, depth=depth, skeleton=s.customer_skeleton)
    new = what_is_new(found)
    print(f"Repository: {root}\n")
    print(f"{len(found.get('general') or {})} department(s) under General, "
          f"{len(found.get('customer') or {})} folder(s) in a customer\n")
    for line in new:
        print(f"  new to the blueprint   {line}")
    if not new:
        print("  (nothing the blueprint does not already know)")
    if "--write" not in argv:
        print("\nNothing was written. Add --write to keep this.")
        return 0
    print(f"\nWritten: {write(root, found)}")
    print("Restart the DMS for it to take effect (.\\scripts\\Restart-Dms.ps1).")
    return 0


if __name__ == "__main__":   # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv))
