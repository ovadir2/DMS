"""A file taken out for editing in SharePoint, and brought back.

Nobody but the DMS has rights on the file server, so a person who wants to look at a document or change it
before sending it does so in SharePoint, with their own Microsoft account. The DMS puts a copy there, gives
that one person edit on it, and the file on the file server waits, marked as taken out, so a second person
cannot edit a second copy. "Done editing" brings it back; a file forgotten there comes back by itself after
DMS_CHECKOUT_HOURS, so nothing stays locked for ever.

The list of what is out lives in 04_Workflow_System\\CheckedOut.json, so a restart of the DMS changes nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

FILE = os.path.join("04_Workflow_System", "CheckedOut.json")


def _path(root: str) -> str:
    return os.path.join(root, FILE)


def read(root: str) -> dict:
    try:
        with open(_path(root), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write(root: str, data: dict) -> None:
    f = _path(root)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    tmp = f + ".tmp"
    with open(tmp, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=1)
    os.replace(tmp, f)


def key_of(root: str, path: str, by: str = "") -> str:
    """A short, stable name for the folder in SharePoint. Without a person it names the file itself: that is the
    one copy open for editing, and only one may exist. With a person it names a copy that person is only reading,
    so several people can look at the same document at once."""
    rel = os.path.normcase(os.path.relpath(path, root))
    if by:
        return "view-" + hashlib.sha1((rel + "|" + by.lower()).encode("utf-8")).hexdigest()[:12]
    return "edit-" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]


def of(root: str, path: str, by: str = "") -> dict | None:
    return read(root).get(key_of(root, path, by))


def add(root: str, path: str, *, by: str, name: str, url: str, edit: bool) -> dict:
    data = read(root)
    key = key_of(root, path, "" if edit else by)
    entry = {"key": key, "path": path, "by": by, "name": name, "url": url, "edit": edit,
             "utc": datetime.now(timezone.utc).isoformat()}
    data[key] = entry
    write(root, data)
    return entry


def remove(root: str, path: str, by: str = "") -> dict | None:
    data = read(root)
    entry = data.pop(key_of(root, path, by), None)
    if entry is not None:
        write(root, data)
    return entry


def drop(root: str, key: str) -> None:
    data = read(root)
    if data.pop(key, None) is not None:
        write(root, data)


def due(root: str, hours: int) -> list[dict]:
    """What has been out longer than that: the DMS brings these back by itself."""
    limit = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for entry in read(root).values():
        try:
            when = datetime.fromisoformat(entry.get("utc") or "")
        except ValueError:
            continue
        if when < limit:
            out.append(entry)
    return out
