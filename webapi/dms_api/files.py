"""File server access. Every path is checked to be inside the repository root."""
from __future__ import annotations

import ntpath
import os
import re
import shutil
import stat
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from contextvars import ContextVar
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


LONG_PATH = 200          # Office cannot open longer paths (about 218 characters, as URL): use the short (8.3) path


def url_len(path: str) -> int:
    """The length Office sees: the path as a URL (a space is %20, a Hebrew letter is %D7%xx = 6 characters)."""
    from urllib.parse import quote
    return len(quote(path.replace("\\", "/"), safe="/:"))


def short_path(path: str, force: bool = False) -> str:
    """The Windows short (8.3) form of a long path, e.g. \\\\srv\\Shares\\QUALIT~1\\..., so Office can open it
    (8.3 names are ASCII: Hebrew names become short too). The same path when it is short enough (unless force),
    when not on Windows, or when the volume has no 8.3 names."""
    if os.name != "nt" or (not force and url_len(path) <= LONG_PATH):
        return path
    try:
        import ctypes
        ext = "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(ext, buf, 32768)
        if not n or n >= 32768:
            return path
        short = buf.value
        if short.startswith("\\\\?\\UNC\\"):
            short = "\\\\" + short[8:]
        elif short.startswith("\\\\?\\"):
            short = short[4:]
        return short if len(short) < len(path) else path
    except (OSError, AttributeError, ValueError):
        return path


SHORT: list[tuple[str, str]] = []          # (long prefix, short prefix), set by the app from DMS_SHORT_PATHS
ROOT = [""]
# this user's own drive letters (the page sends them, X-DMS-Drives), when they differ from DMS_SHORT_PATHS
USER_SHORT: ContextVar[list | None] = ContextVar("USER_SHORT", default=None)


def _pairs(root: str, mapping: dict) -> list[tuple[str, str]]:
    return sorted(((os.path.join(root, folder), short) for folder, short in mapping.items()), key=lambda x: -len(x[0]))


def set_short_paths(root: str, mapping: dict) -> None:
    ROOT[0] = root
    SHORT[:] = _pairs(root, mapping)


def user_drives(mapping: dict):
    """For one request: this user's drive letters first, then DMS_SHORT_PATHS. Returns the token to reset."""
    return USER_SHORT.set(_pairs(ROOT[0], mapping) + SHORT if mapping else None)


def user_path(path: str) -> str:
    """The path users open and copy: $Root\\02_Customers\\... -> the short path of that folder (DMS_SHORT_PATHS)."""
    if not path:
        return path
    n = os.path.normcase(os.path.normpath(path))
    for long, short in (USER_SHORT.get() or SHORT):
        for lg in (long, _short_prefix(long)):                 # the folder, or its 8.3 form in a short path
            lp = os.path.normcase(os.path.normpath(lg))
            if n == lp or n.startswith(lp + os.sep):
                rest = os.path.normpath(path)[len(os.path.normpath(lg)):].lstrip("\\/")
                return short + ("\\" + rest.replace("/", "\\") if rest else "")
    return path


_SHORT_PREFIX: dict[str, str] = {}


def _short_prefix(long: str) -> str:
    if long not in _SHORT_PREFIX:
        _SHORT_PREFIX[long] = short_path(long, force=True)
    return _SHORT_PREFIX[long]


def office_uri(path: str, edit: bool = False) -> str | None:
    """ms-word/ms-excel/ms-powerpoint link that opens the file from the server in the desktop app
    (a long path is given in its short 8.3 form). View only, unless edit."""
    app = {".doc": "ms-word", ".docx": "ms-word", ".docm": "ms-word",
           ".xls": "ms-excel", ".xlsx": "ms-excel", ".xlsm": "ms-excel",
           ".ppt": "ms-powerpoint", ".pptx": "ms-powerpoint"}.get(os.path.splitext(path)[1].lower())
    if not app:
        return None
    full, path = path, user_path(path)
    if url_len(path) > LONG_PATH and BASE_URL.get():
        # too long for Office as a file path (Hebrew names count 6 characters each): the DMS link (WebDAV, like
        # SharePoint) - the original file name, and Save writes back to the same file on the server
        from urllib.parse import quote
        return (f"{app}:{'ofe' if edit else 'ofv'}|u|{BASE_URL.get().rstrip('/')}/api/o/{open_token(full)}/"
                f"{quote(os.path.basename(full))}")
    if url_len(path) > LONG_PATH:                              # no DMS address: the 8.3 names, if the volume has them
        short = user_path(short_path(full, force=True))
        path = short if url_len(short) < url_len(path) else short_path(path)
    url = "file:" + path.replace("\\", "/") if path.startswith("\\\\") else "file:///" + path.replace("\\", "/").lstrip("/")
    return f"{app}:{'ofe' if edit else 'ofv'}|u|{url}"


BASE_URL: ContextVar[str] = ContextVar("BASE_URL", default="")   # this request's DMS address, for the short Open link
OPEN_TOKENS: dict[str, str] = {}


def _tokens_file() -> str:
    return os.path.join(ROOT[0], "04_Workflow_System", "OpenLinks.json") if ROOT[0] else ""


def open_token(path: str) -> str:
    """A short hash for a path, kept in 04_Workflow_System\\OpenLinks.json (the links work after a restart)."""
    import hashlib
    import json
    t = hashlib.sha1(os.path.normcase(path).encode("utf-8")).hexdigest()[:16]
    if OPEN_TOKENS.get(t) != path:
        OPEN_TOKENS[t] = path
        f = _tokens_file()
        if f:
            try:
                os.makedirs(os.path.dirname(f), exist_ok=True)
                with open(f + ".tmp", "w", encoding="utf-8") as out:
                    json.dump(OPEN_TOKENS, out, ensure_ascii=False)
                os.replace(f + ".tmp", f)
            except OSError:
                pass
    return t


def open_path(token: str) -> str | None:
    if token not in OPEN_TOKENS and _tokens_file():
        import json
        try:
            with open(_tokens_file(), encoding="utf-8") as f:
                OPEN_TOKENS.update({k: v for k, v in json.load(f).items() if k not in OPEN_TOKENS})
        except (OSError, ValueError):
            pass
    return OPEN_TOKENS.get(token)


def _ascii_name(path: str) -> str:
    """A short ASCII file name for the link (Word shows it as the title): the ASCII part of the name, else "document"."""
    base, ext = os.path.splitext(os.path.basename(path))
    a = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9._-]+", "_", base)).strip("_.")[:60]
    return (a or "document") + ext.lower()


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
    managed = any(p in WORKFLOW_FOLDERS[1:] for p in ([] if rel == "." else rel.replace("\\", "/").split("/")))
    return {"path": folder, "relative": "" if rel == "." else rel, "parent": parent, "managed": managed,
            "canWrite": not managed and can(folder, "write"),
            "folders": folders, "files": files}


def save_upload(root: str, folder: str, filename: str, stream: BinaryIO, max_bytes: int, overwrite: bool = False,
                released: bool = False) -> str:
    """Write an uploaded file into `folder` (inside root): to a temporary name first, then renamed,
    so a broken upload never leaves half a file. Workflow folders are refused, except with `released`:
    the file goes straight into the folder's Current_ReadOnly, read only (saved without workflow)."""
    target_dir = resolve(root, folder)
    if released:
        target_dir = os.path.join(target_dir, WORKFLOW_FOLDERS[2])
        os.makedirs(target_dir, exist_ok=True)
    if not os.path.isdir(target_dir):
        raise FileNotFoundError(target_dir)
    if not released and os.path.basename(target_dir) in WORKFLOW_FOLDERS[1:]:
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
            if not released:
                raise PermissionError("the existing file is read-only (controlled)")
            os.chmod(target, os.stat(target).st_mode | stat.S_IWRITE)
        os.replace(tmp, target)
        if released:
            os.chmod(target, os.stat(target).st_mode & ~stat.S_IWRITE & ~stat.S_IWGRP & ~stat.S_IWOTH)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return target


def walk_search(start: str, text: str, can: Can = _allow_all, limit: int = 200,
                folders_only: bool = False) -> Iterator[dict]:
    """Files and folders under `start` whose name contains every word of `text` (any order, case-insensitive),
    skipping what the user may not read. Stops after `limit` results."""
    words, found, stack = text.lower().split(), 0, [start]
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
            name = entry.name.lower()
            if words and all(w in name for w in words) and (is_dir or not folders_only):
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
    if os.path.isdir(full) and contains_workflow_folder(full):
        raise PathNotAllowed("this folder holds DMS workflow folders (Submitted / Current_ReadOnly / Obsolete_ReadOnly)")
    return full


def in_workflow_folder(root: str, path: str) -> bool:
    """True for Submitted / Current_ReadOnly / Obsolete_ReadOnly and anything inside them."""
    rel = os.path.relpath(path, root).replace("\\", "/").split("/")
    return any(p in WORKFLOW_FOLDERS[1:] for p in rel)


def contains_workflow_folder(folder: str) -> bool:
    for _dirpath, dirs, _files in os.walk(folder):
        if any(d in WORKFLOW_FOLDERS for d in dirs):
            return True
    return False


_REV = re.compile(r"^(?P<base>.*?)[ _\-]*rev\.?\s*(?P<rev>\d+)(?:_draft)?$", re.I)


def parse_revision(filename: str) -> tuple[str, int | None, str]:
    """'CRU 4 FCT Quote_Rev1.xlsx' -> ('CRU 4 FCT Quote', 1, '.xlsx'); without a revision -> (stem, None, ext)."""
    stem, ext = os.path.splitext(filename)
    stem = re.sub(r"_DRAFT$", "", stem, flags=re.I)
    m = _REV.match(stem)
    return (m.group("base").rstrip(" _-"), int(m.group("rev")), ext) if m else (stem, None, ext)


def copy_writable(source: str, target: str) -> str:
    """Copy a (read-only) approved file to a new writable draft."""
    if os.path.exists(target):
        raise FileExistsError(target)
    shutil.copy2(source, target)
    os.chmod(target, os.stat(target).st_mode | stat.S_IWRITE)
    return target


def revision_name(base: str, rev: int, ext: str) -> str:
    return f"{base}_Rev{rev:02d}_DRAFT{ext}"


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
