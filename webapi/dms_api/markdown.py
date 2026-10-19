"""An approved document as Markdown, for the company's AI to read.

A PDF of a procedure answers questions badly: its headings, lists and tables arrive as lines on a page and
nothing says which is which. Markdown keeps them, so an answer can quote a clause and name where it came from.

The file is written beside the approved document in Current_ReadOnly - not in a tree of its own - so it is seen
by exactly the people who may see the document itself: the AD rights of the folder, with nothing to maintain.

Microsoft's markitdown is used when it is installed on the server; otherwise the DMS converts the document
itself, from the same parts doc_text already reads. Nothing has to be installed for this to work.
"""
from __future__ import annotations

import logging
import os
import re
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree

log = logging.getLogger("dms_api.markdown")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _runs(el) -> str:
    out = []
    for node in el.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "t" and node.text:
            out.append(node.text)
        elif tag in ("tab", "br"):
            out.append(" ")
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def _paragraph(p) -> str:
    """One Word paragraph as Markdown: a heading, a list item, or a line of its own."""
    text = _runs(p)
    if not text:
        return ""
    style = p.find(f"{W}pPr/{W}pStyle")
    name = (style.get(f"{W}val") if style is not None else "") or ""
    level = re.search(r"(\d+)$", name)
    if name.lower().startswith("heading") and level:
        return "#" * min(6, int(level.group(1))) + " " + text
    if p.find(f"{W}pPr/{W}numPr") is not None:
        return "- " + text
    return text


def _table(tbl) -> str:
    rows = []
    for tr in tbl.findall(f"{W}tr"):
        rows.append([_runs(tc) or " " for tc in tr.findall(f"{W}tc")])
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [" "] * (width - len(r)) for r in rows]
    head, *body = rows
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(out)


def _docx(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    out: list[str] = []
    for el in list(body or []):
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            line = _paragraph(el)
            if line:
                out.append(line)
        elif tag == "tbl":
            table = _table(el)
            if table:
                out.append(table)
    return "\n\n".join(out)


def _xlsx(path: str) -> str:
    from .doc_text import extract                     # the cells, sheet by sheet, tab separated
    out = []
    for block in extract(path).split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        sheet, rows = lines[0].strip("[]"), [ln.split("\t") for ln in lines[1:]]
        if not rows:
            continue
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        head, *body = rows
        md = ["| " + " | ".join(c or " " for c in head) + " |", "|" + "---|" * width]
        md += ["| " + " | ".join(c or " " for c in r) + " |" for r in body]
        out.append(f"## {sheet}\n\n" + "\n".join(md))
    return "\n\n".join(out)


def _plain(path: str) -> str:
    from .doc_text import extract
    return extract(path)


def body_of(path: str) -> str:
    """The document as Markdown, or an empty string when this kind of file has nothing to read."""
    ext = os.path.splitext(path)[1].lower()
    try:
        from markitdown import MarkItDown               # on the server, when IT installed it
        return (MarkItDown().convert(path).text_content or "").strip()
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001 - its answer is not worth failing a release for
        log.info("markitdown did not convert %s: %s", path, e)
    try:
        if ext in (".docx", ".docm"):
            return _docx(path).strip()
        if ext in (".xlsx", ".xlsm"):
            return _xlsx(path).strip()
        return _plain(path).strip()
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, ValueError) as e:
        log.info("%s was not turned into Markdown: %s", path, e)
        return ""


def write_beside(path: str, doc: dict | None = None) -> str | None:
    """Write <document>.md beside the approved document. It opens with what the document is - the DMS id, the
    revision, when it was approved and where it lives - so an answer can say which document it came from and
    not only what it said. Returns where it was written, or None when there was nothing to write."""
    body = body_of(path)
    if not body:
        return None
    d = doc or {}
    head = [f"# {d.get('title') or os.path.splitext(os.path.basename(path))[0]}", ""]
    for label, value in (("Document ID", d.get("documentId")), ("Revision", d.get("currentRevision")),
                         ("Type", d.get("documentType")), ("Area", d.get("documentArea")),
                         ("Approved", (d.get("lastApprovedUtc") or "")[:10]), ("Owner", d.get("ownerEmail"))):
        if value:
            head.append(f"- {label}: {value}")
    head += [f"- File: {path}",
             f"- Written by the DMS: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC", "", "---", ""]
    target = os.path.splitext(path)[0] + ".md"
    try:
        if os.path.exists(target):
            os.chmod(target, os.stat(target).st_mode | 0o200)
        with open(target, "w", encoding="utf-8") as f:
            f.write("\n".join(head) + body + "\n")
        os.chmod(target, os.stat(target).st_mode & ~0o222)     # read only, like the document beside it
    except OSError as e:
        log.warning("%s was not written: %s", target, e)
        return None
    return target
