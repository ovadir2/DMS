"""File server access. Every path is checked to be inside the repository root."""
from __future__ import annotations

import ntpath
import os
from datetime import datetime, timezone

from .config import WORKFLOW_FOLDERS


class PathNotAllowed(Exception):
    pass


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def resolve(root: str, path: str | None) -> str:
    """Return the absolute path for `path` (absolute, or relative to root) if it is inside root."""
    if not root:
        raise PathNotAllowed("DMS_REPOSITORY_ROOT is not set")
    if path and ".." in path.replace("\\", "/").split("/"):
        raise PathNotAllowed(path)
    if not path:
        full = root
    elif os.path.isabs(path) or path.startswith("\\\\"):
        full = path
    else:
        full = os.path.join(root, path)
    full = os.path.normpath(full)
    r, f = _norm(root), _norm(full)
    if f != r and not f.startswith(r.rstrip("\\/") + os.sep):
        raise PathNotAllowed(path)
    return full


def same_path(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and _norm(a) == _norm(b)


def office_uri(path: str) -> str | None:
    """ms-word/ms-excel/ms-powerpoint link that opens the file from the server in the desktop app."""
    app = {".doc": "ms-word", ".docx": "ms-word", ".docm": "ms-word",
           ".xls": "ms-excel", ".xlsx": "ms-excel", ".xlsm": "ms-excel",
           ".ppt": "ms-powerpoint", ".pptx": "ms-powerpoint"}.get(os.path.splitext(path)[1].lower())
    if not app:
        return None
    url = "file:" + path.replace("\\", "/") if path.startswith("\\\\") else "file:///" + path.replace("\\", "/").lstrip("/")
    return f"{app}:ofv|u|{url}"


def list_folder(root: str, path: str | None) -> dict:
    folder = resolve(root, path)
    if not os.path.isdir(folder):
        raise FileNotFoundError(folder)
    folders, files = [], []
    with os.scandir(folder) as it:
        for entry in sorted(it, key=lambda x: x.name.lower()):
            if entry.name.startswith(("~$", ".")):
                continue
            st = entry.stat()
            item = {"name": entry.name, "path": entry.path,
                    "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()}
            if entry.is_dir():
                item["workflowFolder"] = entry.name in WORKFLOW_FOLDERS
                folders.append(item)
            else:
                item.update(size=st.st_size, readOnly=not os.access(entry.path, os.W_OK),
                            officeUri=office_uri(entry.path))
                files.append(item)
    parent = None if _norm(folder) == _norm(root) else os.path.dirname(folder)
    return {"path": folder, "parent": parent, "folders": folders, "files": files}


def candidate_register_paths(path: str) -> list[str]:
    """Register paths a file can belong to: itself, and for a file the Workflow Service moved into
    Submitted, the place it came from (WorkingUncPath stays the user's original path)."""
    out = [path]
    sep = "\\" if "\\" in path else os.sep
    parent, name = path.rsplit(sep, 1) if sep in path else ("", path)
    if parent and ntpath.basename(parent.replace("/", "\\")) == "Submitted":
        base = parent.rsplit(sep, 1)[0]
        out.append(f"{base}{sep}{name}")
        out.append(f"{base}{sep}Working{sep}{name}")
    return out
