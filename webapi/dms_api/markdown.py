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


SKIP = (f"{W}del", f"{W}instrText", f"{W}fldChar", f"{W}proofErr")   # removed by tracked changes, or field code


def _runs(el) -> str:
    """The words of a paragraph or a cell. Text struck out by tracked changes and the inside of field codes
    are not words of the document: left in, they arrive as letters with no sentence around them."""
    out: list[str] = []

    def walk(node) -> None:
        for child in node:
            if child.tag in SKIP:                      # the whole subtree, not only this element
                continue
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "t" and child.text:
                out.append(child.text)
            elif tag in ("tab", "br"):
                out.append(" ")
            walk(child)

    walk(el)
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?[\s\u00a0]+(\S.*)$")


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
    # A procedure numbers its sections by hand as often as it styles them ("3. שיטה"). A short line that opens
    # with a number and does not end as a sentence is that section's title, and the depth of the number is its
    # level - otherwise half the document's headings are headings and half are ordinary lines.
    m = NUMBERED.match(text)
    if m and len(text) <= 80 and not text.endswith((".", ":", "،", "؛")) and p.find(f"{W}pPr/{W}numPr") is None:
        return "#" * min(6, 1 + m.group(1).count(".") + 1) + " " + text
    if p.find(f"{W}pPr/{W}numPr") is not None:
        return "- " + text
    return text


def _cells(tr) -> list[str]:
    """One row. A cell merged across columns fills the columns it covers, so the row keeps its shape; a cell
    merged with the one above it carries no text of its own and is left empty."""
    out: list[str] = []
    for tc in tr.findall(f"{W}tc"):
        span = tc.find(f"{W}tcPr/{W}gridSpan")
        wide = int(span.get(f"{W}val", "1")) if span is not None else 1
        out.append(_runs(tc))
        out += [""] * (wide - 1)
    return out


def _table(tbl) -> str:
    """A Word table as Markdown. The block at the head of a procedure - document number, revision, date, each
    on its own line - is a table in Word but a list of facts to a reader, so it is written as one: a six column
    grid of merged cells says nothing to anybody, least of all to the AI this file is for."""
    rows = [_cells(tr) for tr in tbl.findall(f"{W}tr")]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [i for i in range(width) if any(r[i].strip() for r in rows)]   # a column nobody wrote in is not one
    rows = [[r[i] for i in keep] for r in rows]
    width = len(keep)
    if width == 0:
        return ""
    if width == 1:
        return "\n".join(r[0] for r in rows if r[0].strip())
    if width == 2:
        return "\n".join(f"- **{a.strip()}**: {b.strip()}" for a, b in rows if (a + b).strip())
    head, *body = rows
    out = ["| " + " | ".join(c.strip() or " " for c in head) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(c.strip() or " " for c in r) + " |" for r in body]
    return "\n".join(out)


def tidy(text: str) -> str:
    """One blank line between blocks, none at the edges: Word leaves empty paragraphs everywhere, and each one
    arrives here as a gap the reader has to climb over."""
    text = re.sub(r"[ \t]+\n", "\n", text.replace("\r\n", "\n").replace("\u00a0", " "))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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


def _xls(path: str) -> str:
    """The old Excel format (.xls), read with xlrd. markitdown does not open one at all, and a company's
    older procedures and forms are full of them - without this they are invisible to the AI."""
    import xlrd                                        # installed on the server; absent, the caller falls back
    book = xlrd.open_workbook(path)
    out = []
    for sheet in book.sheets():
        rows = []
        for r in range(sheet.nrows):
            cells = []
            for c in range(sheet.ncols):
                v = sheet.cell_value(r, c)
                if isinstance(v, float) and v == int(v):
                    v = int(v)                         # 3.0 is 3 in a document, not in a spreadsheet
                cells.append(str(v).strip())
            if any(cells):
                rows.append(cells)
        if not rows:
            continue
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        head, *body = rows
        md = ["| " + " | ".join(c or " " for c in head) + " |", "|" + "---|" * width]
        md += ["| " + " | ".join(c or " " for c in r) + " |" for r in body]
        out.append(f"## {sheet.name}\n\n" + "\n".join(md))
    return "\n\n".join(out)


def _plain(path: str) -> str:
    from .doc_text import extract
    return extract(path)


# Set by the app at startup: a function that turns a document into PDF bytes through SharePoint. It is how
# a format nothing here can read - a legacy .doc, a .ppt - still reaches the company's AI: SharePoint lays it
# out as pages, and the text is taken from those. Without it, such a document has no Markdown.
PDF_OF: list = [None]


def _via_pdf(path: str) -> str:
    """The document as text, by way of the PDF SharePoint makes of it."""
    make = PDF_OF[0]
    if not make:
        return ""
    data = make(path)
    if not data:
        return ""
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), f"dms-{abs(hash(path))}.pdf")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        body = _plain(tmp).strip()                 # the pages read here (pypdf), with nothing to install
        if body:
            return body
        from markitdown import MarkItDown
        return (MarkItDown().convert(tmp).text_content or "").strip()
    except Exception as e:  # noqa: BLE001 - a last resort: say why and leave the document without Markdown
        log.info("%s was not read through its PDF: %s", path, e)
        return ""
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def body_of(path: str) -> str:
    """The document as Markdown, or an empty string when this kind of file has nothing to read.

    A procedure is converted here and not by a general purpose tool: those read a Word table as a grid, so the
    block at the head of every procedure arrives as six columns of merged cells, and they call a section a
    heading only where Word styled it - half the headings of a hand numbered procedure are then ordinary lines.
    markitdown is asked only for what this cannot read at all."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".docx", ".docm"):
            body = _docx(path).strip()
        elif ext in (".xlsx", ".xlsm"):
            body = _xlsx(path).strip()
        elif ext == ".xls":
            body = _xls(path).strip()
        else:
            body = _plain(path).strip()
        if body:
            return body
    except (OSError, ImportError, zipfile.BadZipFile, ElementTree.ParseError, ValueError) as e:
        log.info("%s was not turned into Markdown here: %s", path, e)
    try:
        from markitdown import MarkItDown               # on the server, when IT installed it
        body = (MarkItDown().convert(path).text_content or "").strip()
        if body.lower() == "none":
            body = ""                                   # what it says about a file it could not read
        if body:
            return body
    except ImportError:
        pass                                            # not installed: the PDF is the only way left
    except Exception as e:  # noqa: BLE001 - its answer is not worth failing a release for
        log.info("markitdown did not convert %s: %s", path, e)
    # Nothing here could read it, and markitdown had nothing to say either (a legacy .doc gives an empty
    # answer rather than an error): let SharePoint lay it out as pages and read those.
    return _via_pdf(path)


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
            f.write("\n".join(head) + tidy(body) + "\n")
        os.chmod(target, os.stat(target).st_mode & ~0o222)     # read only, like the document beside it
    except OSError as e:
        log.warning("%s was not written: %s", target, e)
        return None
    return target
