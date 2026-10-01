"""Find files from a free-text request: a search plan (from the AI, or plain keywords without it)
is matched against the repository the user may see, and the matches are scored."""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from datetime import datetime, timezone

from .config import WORKFLOW_FOLDERS

STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "file", "files", "document", "find", "show", "me",
        "latest", "last", "new", "newest", "please", "where", "is", "my", "our", "את", "של", "על", "עם", "קובץ", "מסמך",
        "תמצא", "מצא", "הראה", "לי", "האחרון", "האחרונה", "החדש", "איפה", "בבקשה"}


def keywords(text: str) -> list[str]:
    words = re.findall(r"[\w\-\.+]+", text.lower())
    return [w for w in words if len(w) > 1 and w not in STOP][:8]


def walk_files(start: str, can_dir: Callable[[str], bool], max_files: int = 20000) -> Iterator[os.DirEntry]:
    """Files under `start`. Folders the user may not read are skipped with everything inside them.
    Superseded revisions (Obsolete_ReadOnly) and the workflow queue (Submitted) are not offered."""
    stack, seen = [start], 0
    while stack and seen < max_files:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for e in entries:
            if e.name.startswith(("~$", ".")):
                continue
            if e.is_dir():
                if e.name not in (WORKFLOW_FOLDERS[1], WORKFLOW_FOLDERS[3]) and can_dir(e.path):
                    stack.append(e.path)
            else:
                seen += 1
                yield e


def score(rel: str, name: str, terms: list[str], kind_folder: str | None, extensions: list[str]) -> float:
    n, r = name.lower(), rel.lower().replace("\\", "/")
    s = 0.0
    for t in terms:
        t = t.lower()
        if t in n:
            s += 3
        elif t in r:
            s += 1.5
        elif t.replace(" ", "_") in r or t.replace(" ", "") in n.replace("_", "").replace(" ", ""):
            s += 1
    if kind_folder and kind_folder.lower().replace("\\", "/") in r:
        s += 3
    if extensions and os.path.splitext(n)[1] in [x.lower() if x.startswith(".") else "." + x.lower() for x in extensions]:
        s += 1
    return s


def age_bonus(mtime: float) -> float:
    days = (datetime.now(timezone.utc).timestamp() - mtime) / 86400
    return 1.0 if days < 30 else 0.5 if days < 180 else 0.0
