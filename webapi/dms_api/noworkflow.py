"""Files saved "without workflow" (Save file (no workflow), First loading "Save only"): they stay as they are
and the page does not offer Start workflow for them. Kept in 04_Workflow_System\\NoWorkflow.json as paths
relative to the repository root; renames and deletes on the page keep it up to date."""
from __future__ import annotations

import json
import os
import threading

_lock = threading.Lock()
FILE = os.path.join("04_Workflow_System", "NoWorkflow.json")


def _key(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/").lower()


def _load(root: str) -> set[str]:
    try:
        with open(os.path.join(root, FILE), encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def _save(root: str, keys: set[str]) -> None:
    p = os.path.join(root, FILE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, ensure_ascii=False, indent=0)
    os.replace(tmp, p)


def mark(root: str, path: str) -> None:
    with _lock:
        keys = _load(root)
        keys.add(_key(root, path))
        _save(root, keys)


def marked(root: str) -> set[str]:
    return _load(root)


def is_marked(root: str, path: str, keys: set[str] | None = None) -> bool:
    return _key(root, path) in (keys if keys is not None else _load(root))


def moved(root: str, old: str, new: str | None) -> None:
    """A file or folder was renamed (new) or deleted (None): its entries follow."""
    o = _key(root, old)
    with _lock:
        keys = _load(root)
        hit = {k for k in keys if k == o or k.startswith(o + "/")}
        if not hit:
            return
        keys -= hit
        if new:
            n = _key(root, new)
            keys |= {n + k[len(o):] for k in hit}
        _save(root, keys)


DMS_APPROVER = "DMS"


def release(sp, s, path: str, owner: str, how: str, classify=None) -> dict:
    """Trace a file saved without workflow in SharePoint: a Document Register record, Approved by DMS, control mode
    Collaboration (no workflow), current = the file in Current_ReadOnly, with a Control Audit row (SHA-256).
    The same file saved again updates its record. The owner can share it with a customer like any approved document."""
    import hashlib
    from datetime import datetime, timezone

    from . import blueprint, files
    c = s.choices
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    sha, now = h.hexdigest(), datetime.now(timezone.utc).isoformat()
    rel = os.path.relpath(path, s.repository_root)
    rev = f"{files.parse_revision(os.path.basename(path))[1] or 1:02d}"
    here = os.path.normcase(os.path.normpath(path))
    doc = next((d for d in sp.documents(refresh=True)
                if d.get("currentUncPath") and os.path.normcase(os.path.normpath(d["currentUncPath"])) == here), None)
    if doc:
        sp.update(doc["id"], {"CurrentSHA256": sha, "LastApprovedUtc": now})
        what = "saved again"
    else:
        folder = os.path.dirname(path)
        if os.path.basename(folder) == "Current_ReadOnly":
            folder = os.path.dirname(folder)
        bp = classify(folder) if classify else {}
        doc = sp.create_document(title=os.path.splitext(os.path.basename(path))[0], path="",
                                 document_type=bp.get("documentType"), document_area=bp.get("documentArea"),
                                 owner_email=owner, control_mode=blueprint.choice("Collaboration", sp.choices("ControlMode")),
                                 document_id=None)
        sp.update(doc["id"], {"LifecycleStatus": c["Approved_ReadOnly"], "CurrentUncPath": path, "WorkingUncPath": "",
                              "CurrentSHA256": sha, "CurrentRevision": rev, "LastApprovedUtc": now})
        what = "registered"
    sp.audit(document_id=doc["documentId"], event=c["ApprovedEvent"], from_status="", to_status=c["Approved_ReadOnly"],
             actor=DMS_APPROVER, details=f"Approved by DMS - {how}, no workflow ({what}, owner {owner}): {rel} [file SHA-256 {sha}]",
             source=c["WorkflowService"])
    return sp.document(doc["id"])
