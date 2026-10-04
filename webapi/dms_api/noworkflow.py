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
