"""The customer skeleton: one customer folder kept as the shape every new customer is cut from.

A customer's tree is in the blueprint, so the DMS can always make the folders. What the blueprint cannot
carry is the file server's own side of it - the AD groups on each folder, the inheritance that was broken
where a department's folder had to be closed. Those live on the folders themselves, and the only honest way
to give a new customer the same ones is to copy them from a customer that already has them.

So one folder under 02_Customers is the skeleton (DMS_CUSTOMER_SKELETON, Customer_Skeleton by default; a
folder named Customer_Skelton answers to it too). A new customer is its folder tree and its permissions,
copied - and no documents.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading

from .config import WORKFLOW_FOLDERS

log = logging.getLogger("dms_api.skeleton")
LOOKS_LIKE = re.compile(r"^customer[ _-]?skel(e)?ton$", re.I)
# The same shape, for the employee files under HR: a folder named Employee_Skelton answers too, as a
# misspelled customer skeleton does - the name on the file server is whatever somebody typed that day.
EMPLOYEE_LOOKS_LIKE = re.compile(r"^employees?[ _-]?skel(e)?ton$", re.I)


def find(root: str, folder: str, named: str = "", looks_like: re.Pattern | None = None) -> str | None:
    """The skeleton folder inside that folder, by the name it was given or by the look of its name."""
    base = os.path.join(root, *folder.replace("\\", "/").split("/"))
    pattern = looks_like or LOOKS_LIKE
    if not os.path.isdir(base):
        return None
    if named:
        here = os.path.join(base, named)
        if os.path.isdir(here):
            return here
    try:
        with os.scandir(base) as it:
            for e in it:
                if e.is_dir() and pattern.match(e.name):
                    return e.path
    except OSError:
        return None
    return None


def folders_of(path: str) -> list[tuple[str, ...]]:
    """Every folder under the skeleton, as name tuples, parents first. Its files are not part of the shape.

    Working / Submitted / Current_ReadOnly / Obsolete_ReadOnly are not part of the shape either: they are
    not blueprint folders anywhere, the DMS makes them beside a document when it goes through the workflow.
    A skeleton should hold none; if somebody made one there by hand, it is skipped rather than copied.
    """
    out: list[tuple[str, ...]] = []
    for folder, dirs, _names in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in WORKFLOW_FOLDERS)
        rel = os.path.relpath(folder, path)
        if rel != ".":
            out.append(tuple(rel.replace("\\", "/").split("/")))
    return sorted(out, key=len)


def copy(skeleton: str, target: str, wait: bool = False) -> tuple[int, str]:
    """The skeleton's folders - and on Windows the permissions on them - as a new customer. No documents.

    The folders are made here and now: that is what the person is waiting for. The permissions are copied
    after the answer, unless wait, because robocopy on a large tree takes as long as it takes and nobody
    should watch a dialog for it. Returns (how many folders, what is happening to the permissions)."""
    made = folders_of(skeleton)
    os.makedirs(target, exist_ok=True)
    for rel in made:
        os.makedirs(os.path.join(target, *rel), exist_ok=True)
    if os.name != "nt":
        return len(made), "folders only (not Windows)"
    if wait:
        return len(made), permissions(skeleton, target)
    threading.Thread(target=permissions, args=(skeleton, target), daemon=True, name="dms-skeleton").start()
    return len(made), "folders made; their permissions are being copied"


def permissions(skeleton: str, target: str) -> str:
    """The permissions each folder carries, copied onto the same folder of the new customer.

    robocopy is the one thing that copies a folder's own security with it: /E every folder, /XF * nothing of
    what is in them, /XD never a workflow folder (the DMS makes those, not the skeleton), /COPYALL the permissions, the owner and the auditing beside the dates."""
    try:
        r = subprocess.run(["robocopy", skeleton, target, "/E", "/XF", "*", "/XD", *WORKFLOW_FOLDERS,
                            "/COPYALL", "/DCOPY:DAT",
                            "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
                           capture_output=True, text=True, timeout=600)
        # robocopy says 0-7 for "did something, or nothing to do"; 8 and up is a failure.
        if r.returncode >= 8:
            log.warning("the permissions were not copied to %s: robocopy %s %s", target, r.returncode,
                        (r.stdout or r.stderr or "").strip()[:300])
            return f"the permissions were not copied (robocopy {r.returncode})"
        log.info("%s: folders and permissions copied from %s", target, os.path.basename(skeleton))
        return "folders and their permissions"
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("robocopy could not be run for %s: %s", target, e)
        return f"the permissions were not copied ({e})"
