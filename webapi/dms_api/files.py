"""File server access. Every path is checked to be inside the repository root."""
from __future__ import annotations

import ntpath
import os
import stat
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from typing import BinaryIO

from .config import WORKFLOW_FOLDERS


class PathNotAllowed(Exception):
    pass


SYSTEM_FILES = {"thumbs.db", "desktop.ini", ".ds_store", "ehthumbs.db"}


def is_hidden(entry: os.DirEntry) -> bool:
    """Office lock files, Windows/Mac system files (Thumbs.db, desktop.ini) and hidden or system items."""
    if entry.name.startswith(("~$", ".")) or entry.name.lower() in SYSTEM_FILES:
        return True
    try:
        return bool(getattr(entry.stat(), "st_file_attributes", 0) & 0x6)   # FILE_ATTRIBUTE_HIDDEN | SYSTEM
    except OSError:
        return True


def is_read_only(path: str) -> bool:
    """The read-only attribute (Windows) / no write bit, whoever runs the service."""
    return not os.stat(path).st_mode & stat.S_IWRITE


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


Can = Callable[[str, str], bool]          # (path, "read" | "write") -> allowed


def _allow_all(_path: str, _access: str) -> bool:
    return True


def list_folder(root: str, path: str | None, can: Can = _allow_all) -> dict:
    """One folder, showing only what the user may read. Raises PermissionError when the user may
    not read the folder itself."""
    folder = resolve(root, path)
    if not os.path.isdir(folder):
        raise FileNotFoundError(folder)
    if not can(folder, "read"):
        raise PermissionError(folder)
    folders, files = [], []
    with os.scandir(folder) as it:
        for entry in sorted(it, key=lambda x: x.name.lower()):
            if is_hidden(entry) or not can(entry.path, "read"):
                continue
            st = entry.stat()
            item = {"name": entry.name, "path": entry.path,
                    "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()}
            if entry.is_dir():
                item["workflowFolder"] = entry.name in WORKFLOW_FOLDERS
                folders.append(item)
            else:
                item.update(size=st.st_size, readOnly=is_read_only(entry.path),
                            officeUri=office_uri(entry.path))
                files.append(item)
    parent = None if _norm(folder) == _norm(root) else os.path.dirname(folder)
    rel = os.path.relpath(folder, root)
    return {"path": folder, "relative": "" if rel == "." else rel, "parent": parent, "canWrite": can(folder, "write"),
            "folders": folders, "files": files}


def save_upload(root: str, folder: str, filename: str, stream: BinaryIO, max_bytes: int, overwrite: bool = False) -> str:
    """Write an uploaded file into `folder` (inside root): to a temporary name first, then renamed,
    so a broken upload never leaves half a file. Workflow folders are refused."""
    target_dir = resolve(root, folder)
    if not os.path.isdir(target_dir):
        raise FileNotFoundError(target_dir)
    if os.path.basename(target_dir) in WORKFLOW_FOLDERS[1:]:
        raise PathNotAllowed("files cannot be saved into a workflow folder")
    name = os.path.basename(filename.replace("\\", "/"))
    if not name or name in (".", "..") or any(c in name for c in '<>:"|?*'):
        raise PathNotAllowed(f"invalid file name {filename!r}")
    target = os.path.join(target_dir, name)
    if os.path.exists(target) and not overwrite:
        raise FileExistsError(target)
    tmp = os.path.join(target_dir, f".upload-{uuid.uuid4().hex}.partial")
    size = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"the file is larger than {max_bytes // (1024 * 1024)} MB")
                out.write(chunk)
        if os.path.exists(target) and is_read_only(target):
            raise PermissionError("the existing file is read-only (controlled)")
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return target


def walk_search(start: str, text: str, can: Can = _allow_all, limit: int = 200,
                folders_only: bool = False) -> Iterator[dict]:
    """Files and folders under `start` whose name contains `text` (case-insensitive), skipping
    what the user may not read. Stops after `limit` results."""
    text, found, stack = text.lower(), 0, [start]
    while stack and found < limit:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda x: x.name.lower())
        except OSError:
            continue
        for entry in entries:
            if is_hidden(entry) or not can(entry.path, "read"):
                continue
            is_dir = entry.is_dir()
            if is_dir:
                stack.append(entry.path)
            if text in entry.name.lower() and (is_dir or not folders_only):
                found += 1
                yield {"name": entry.name, "path": entry.path, "isFolder": is_dir,
                       "officeUri": None if is_dir else office_uri(entry.path)}
                if found >= limit:
                    return


RECYCLE = os.path.join("04_Workflow_System", "Recycle")


def valid_name(name: str) -> str:
    name = (name or "").strip().rstrip(".")
    if not name or name in (".", "..") or any(c in name for c in '<>:"/\\|?*') or name in WORKFLOW_FOLDERS:
        raise PathNotAllowed(f"invalid name {name!r}")
    return name


def check_editable(root: str, path: str, protected_depth: int) -> str:
    """An item the user may rename or delete: inside root, deeper than the structure folders
    (e.g. 02_Customers\\Customer_A) and not a workflow folder or something inside one."""
    full = resolve(root, path)
    rel = os.path.relpath(full, root)
    parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
    if len(parts) <= protected_depth:
        raise PathNotAllowed("the company folder structure cannot be changed here")
    if any(p in WORKFLOW_FOLDERS[1:] for p in parts) or parts[-1] == "Working":
        raise PathNotAllowed("workflow folders are managed by the DMS")
    if not os.path.exists(full):
        raise FileNotFoundError(full)
    return full


def make_folder(root: str, parent: str, name: str) -> str:
    parent_dir = resolve(root, parent)
    if not os.path.isdir(parent_dir):
        raise FileNotFoundError(parent_dir)
    if os.path.basename(parent_dir) in WORKFLOW_FOLDERS[1:]:
        raise PathNotAllowed("workflow folders are managed by the DMS")
    target = os.path.join(parent_dir, valid_name(name))
    os.mkdir(target)                     # FileExistsError when it exists
    return target


def rename_item(root: str, path: str, new_name: str, protected_depth: int) -> str:
    full = check_editable(root, path, protected_depth)
    target = os.path.join(os.path.dirname(full), valid_name(new_name))
    if os.path.exists(target) and os.path.normcase(target) != os.path.normcase(full):
        raise FileExistsError(target)
    if os.path.isfile(full) and is_read_only(full):
        raise PermissionError("the file is read-only (controlled)")
    os.rename(full, target)
    return target


def delete_item(root: str, path: str, protected_depth: int, user: str) -> str:
    """Move the item to 04_Workflow_System\\Recycle\\<date>\\<user>\\<its path>, so a deletion can be undone."""
    full = check_editable(root, path, protected_depth)
    for dirpath, _dirs, names in os.walk(full) if os.path.isdir(full) else [(os.path.dirname(full), [], [os.path.basename(full)])]:
        for n in names:
            if is_read_only(os.path.join(dirpath, n)):
                raise PermissionError(f"{n} is read-only (controlled) and cannot be deleted")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    target = os.path.join(root, RECYCLE, stamp, user.split("@")[0], os.path.relpath(full, root))
    if os.path.exists(target):
        target += datetime.now(timezone.utc).strftime("_%H%M%S")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.replace(full, target)
    return target


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
