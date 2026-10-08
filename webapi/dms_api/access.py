"""Department access on the file server: DMS_DEPARTMENT_GROUPS=Engineering=RH\\GG_Eng;HR=RH\\GG_HR.

Each department folder of the blueprint (01_General\\HR, 01_General\\Enginnering, every 02_Customers\\<Customer>\\Engineering,
...) gives its group Modify on the folder and everything below it, and nothing above it: a department sees only its own
folders and opens them by their path (Windows "bypass traverse checking"). The key is a folder name, or the end of a
path (02_Customers\\<Customer>\\Engineering); a value can hold several groups (","). Applied at start (folders made in
Explorer too) and when the DMS creates a customer. Run by the account of the DMS (it must be allowed to change permissions).
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading

from . import blueprint

logger = logging.getLogger("dms_api")


def _matches(rel: list[str], key: str) -> bool:
    kp = [p for p in key.replace("/", "\\").split("\\") if p]
    if not kp or len(kp) > len(rel):
        return False
    return all(k == "<Customer>" or k.lower() == r.lower() for k, r in zip(kp, rel[-len(kp):]))


def groups_for(rel: list[str], mapping: dict) -> list[str]:
    return [g.strip() for key, v in mapping.items() if _matches(rel, key) for g in v.split(",") if g.strip()]


def folders(root: str, customers_folder: str = "02_Customers") -> list[list[str]]:
    """The blueprint folders that exist under the root, <Customer> = every customer folder (not the projects)."""
    try:
        customers = [e.name for e in os.scandir(os.path.join(root, customers_folder)) if e.is_dir()]
    except OSError:
        customers = []
    out = []
    for line in blueprint.folder_list():
        if "<Product>" in line:
            continue
        rel = line.replace("02_Customers", customers_folder, 1).split("\\")
        for r in ([[c if p == "<Customer>" else p for p in rel] for c in customers] if "<Customer>" in rel else [rel]):
            if os.path.isdir(os.path.join(root, *r)):
                out.append(r)
    return out


def _has(path: str, rule: str) -> bool:
    return rule.lower() in subprocess.run(["icacls", path], capture_output=True, text=True).stdout.lower()


def _grant(path: str, group: str, modify: bool) -> None:
    """modify: Modify on the folder, its subfolders and files. Always: Deny Delete on the folder itself only, so the
    blueprint folder cannot be renamed or deleted in Explorer (its content can, like in the DMS)."""
    for rule, arg in (([(f"{group}:(oi)(ci)(m)", ["/grant", f"{group}:(OI)(CI)M"])] if modify else [])
                      + [(f"{group}:(deny)(d)", ["/deny", f"{group}:(D)"])]):
        if _has(path, rule):
            continue
        r = subprocess.run(["icacls", path, *arg], capture_output=True, text=True)
        if r.returncode:
            raise OSError((r.stdout + r.stderr).strip())
        logger.info("Access: %s %s %s", group, "may modify" if "/grant" in arg else "may not rename / delete", path)


GRANT = [_grant]                     # the tests replace it


def apply(root: str, mapping: dict, rels: list[list[str]]) -> int:
    """Grants the department groups on these blueprint folders (relative to the root): Modify on the department
    folder, and no rename / delete on it and the blueprint folders below it. Returns how many grants failed."""
    failed = 0
    for rel in rels:
        own = groups_for(rel, mapping)
        below = [g for i in range(1, len(rel)) for g in groups_for(rel[:i], mapping) if g not in own]
        for g, modify in [(g, True) for g in own] + [(g, False) for g in dict.fromkeys(below)]:
            try:
                GRANT[0](os.path.join(root, *rel), g, modify)
            except OSError as e:
                failed += 1
                logger.warning("Access: %s not set on %s: %s", g, os.path.join(root, *rel), e)
    return failed


def start(root: str, mapping: dict, customers_folder: str) -> None:
    if mapping and os.name == "nt":
        threading.Thread(target=lambda: apply(root, mapping, folders(root, customers_folder)), daemon=True,
                         name="dms-access").start()
