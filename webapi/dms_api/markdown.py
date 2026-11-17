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


T_SLIDE, T_NOTES = "Slide", "Notes"      # the two words the DMS adds to a deck, so a section can be cited
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PML = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


def _slide_para(p) -> tuple[int, str]:
    """A paragraph of a slide: how deep it is bulleted, and what it says."""
    pr = p.find(f"{A}pPr")
    try:
        level = int((pr.get("lvl") if pr is not None else "0") or 0)
    except ValueError:
        level = 0
    return level, re.sub(r"[ \t]+", " ", "".join(t.text or "" for t in p.iter(f"{A}t"))).strip()


def _slide_table(tbl) -> list[str]:
    rows = [[" ".join(x for _, x in (_slide_para(p) for p in c.iter(f"{A}p")) if x).strip()
             for c in tr.iter(f"{A}tc")] for tr in tbl.iter(f"{A}tr")]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head, *body = rows
    return ["| " + " | ".join(c or " " for c in head) + " |", "|" + "---|" * width] + \
           ["| " + " | ".join(c or " " for c in r) + " |" for r in body]


def _pptx(path: str) -> str:
    """A deck, slide by slide. Each slide is a section under its own title - a reader (and the AI) can then
    say which slide an answer came from - with the bullets as a list, the tables as tables and the speaker
    notes after them, which is often where the sentence behind a bullet actually is."""
    out: list[str] = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.findall(r"\d+", n)[-1]))
        for i, n in enumerate(slides, 1):
            root = ElementTree.fromstring(z.read(n))
            title, lines = "", []
            for sp in root.iter(f"{PML}sp"):
                ph = next(iter(sp.iter(f"{PML}ph")), None)
                said = [x for x in (_slide_para(p) for p in sp.iter(f"{A}p")) if x[1]]
                if not said:
                    continue
                if not title and ph is not None and (ph.get("type") or "") in ("title", "ctrTitle"):
                    title = " ".join(t for _, t in said)
                else:
                    lines += said
            body = [("  " * min(level, 4)) + "- " + text for level, text in lines]
            for tbl in root.iter(f"{A}tbl"):
                rows = _slide_table(tbl)
                if rows:
                    body += [""] + rows
            notes = ""
            rel = f"ppt/slides/_rels/{os.path.basename(n)}.rels"
            if rel in names:
                for r in ElementTree.fromstring(z.read(rel)):
                    if (r.get("Type") or "").endswith("/notesSlide"):
                        t = (r.get("Target") or "").replace("\\", "/").replace("../", "ppt/").lstrip("/")
                        if t in names:
                            said = [x for _, x in (_slide_para(p) for p in ElementTree.fromstring(z.read(t)).iter(f"{A}p")) if x]
                            notes = " ".join(x for x in said if not x.isdigit())    # the slide number is not a note
            head = f"## {T_SLIDE} {i}" + (f" - {title}" if title else "")
            if body or notes:
                out.append("\n\n".join(x for x in [head, "\n".join(body).strip(), f"*{T_NOTES}:* {notes}" if notes else ""] if x))
            else:
                out.append(head)
    return "\n\n".join(out)



def _plain(path: str) -> str:
    """The text of a file that holds text (a note, a CSV, a PDF with a text layer). A file that is damaged,
    truncated or not what its name says reads as nothing: a release is never failed over it."""
    from .doc_text import extract
    try:
        return extract(path)
    except Exception as e:  # noqa: BLE001 - every reader has its own errors; none is worth a failed release
        log.info("%s could not be read as text: %s", path, e)
        return ""


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


# What the DMS can turn into text, by the file's kind. The answer for one file is only certain once it has
# been tried - a scanned PDF has a convertible name and no text in it at all - but the kind is known before
# anything is approved, which is what a person wants to be told when they upload.
TEXT_KINDS = (".docx", ".docm", ".doc", ".xlsx", ".xlsm", ".xls", ".pptx", ".pptm", ".pdf",
              ".txt", ".csv", ".md", ".json", ".xml", ".htm", ".html", ".log", ".ini", ".cfg",
              ".yml", ".yaml", ".rtf")
PICTURE_KINDS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg", ".ico", ".webp")


def _was_ocr(path: str, body: str) -> bool:
    """Was this text read by OCR? A file with no text layer of its own, that has one now."""
    ext = os.path.splitext(path)[1].lower()
    return ext in PICTURE_KINDS or (ext == ".pdf" and body.startswith("## Page "))


def can_read(path: str) -> dict:
    """Before anything is approved: can this kind of file become text, and what to say if it cannot.

    `sure` is true where the kind decides it on its own - a picture has no text, a .txt is nothing but.
    A PDF or an old Word file is the uncertain case: it depends on what is inside, and the DMS only knows
    once it has tried, which is when the card is written instead."""
    ext = os.path.splitext(path)[1].lower()
    if ext in PICTURE_KINDS:
        if OCR.get("on"):
            return {"ext": ext, "readable": True, "sure": False,
                    "why": "a picture: OCR will be tried, and a card written if it reads nothing"}
        return {"ext": ext, "readable": False, "sure": True,
                "why": "a picture has no text in it: the AI will know the document exists and point at it"}
    if ext in (".pdf", ".doc", ".ppt"):
        return {"ext": ext, "readable": True, "sure": False,
                "why": ("depends on what is inside: a scanned one has no text of its own, and is read by "
                        "OCR here" if OCR.get("on") else
                        "depends on what is inside: a scanned one has no text, and gets a card instead")}
    if ext in TEXT_KINDS:
        return {"ext": ext, "readable": True, "sure": True, "why": "this kind becomes Markdown"}
    return {"ext": ext or "(no extension)", "readable": False, "sure": False,
            "why": "the DMS does not know this kind: it will try, and write a card if nothing comes back"}


# Optical character recognition, for the documents that have no text to read: a scan, a drawing with a
# title block, a photographed form. It is off unless the server has it (DMS_OCR=1) because it needs
# Tesseract installed beside the DMS - and it is tried only when everything else came back empty, so a
# document with a text layer is never put through it.
OCR = {"on": False, "languages": "heb+eng", "max_pages": 20}


def _ocr(path: str) -> str:
    """The text of a scan, read by Tesseract. Empty when OCR is off, not installed, or finds nothing."""
    if not OCR.get("on"):
        return ""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        log.info("OCR is on but Tesseract (pytesseract, Pillow) is not installed beside the DMS")
        return ""
    ext = os.path.splitext(path)[1].lower()
    langs = OCR.get("languages") or "eng"
    try:
        if ext in PICTURE_KINDS:
            return (pytesseract.image_to_string(Image.open(path), lang=langs) or "").strip()
        if ext != ".pdf":
            return ""
        import io
        import fitz                                   # PyMuPDF: renders a page without Poppler
        out = []
        with fitz.open(path) as book:
            for page in list(book)[:int(OCR.get("max_pages") or 20)]:
                png = page.get_pixmap(dpi=200).tobytes("png")
                text = (pytesseract.image_to_string(Image.open(io.BytesIO(png)), lang=langs) or "").strip()
                if text:
                    out.append(f"## Page {page.number + 1}\n\n{text}")
        return "\n\n".join(out).strip()
    except Exception as e:  # noqa: BLE001 - a scan that will not read is a card, not a failed release
        log.info("OCR did not read %s: %s", path, e)
        return ""


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
        elif ext in (".pptx", ".pptm"):
            body = _pptx(path).strip()
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
    body = _via_pdf(path)
    if body:
        return body
    # Still nothing: a scan, a photographed form, a drawing with a title block. Tesseract, where the
    # server has it - this is the only way to the content of a document that has no text in it at all.
    return _ocr(path)


def heading_of(path: str) -> dict:
    """What the DMS wrote at the top of a Markdown file: its title and the facts under it (Document ID,
    Revision, Type, Area, Approved, Owner, File). Empty for a file that has no such head."""
    out: dict = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("# ") and "title" not in out:
                    out["title"] = line[2:].strip()
                    continue
                if line.startswith("- "):
                    label, _, value = line[2:].partition(":")
                    if value.strip():
                        out[label.strip()] = value.strip()
                    continue
                if line.startswith("---"):
                    break
    except OSError:
        return {}
    return out


def _written_for(md: str) -> str:
    """The document a Markdown file was written for, from the "- File:" line the DMS puts at its top."""
    try:
        with open(md, encoding="utf-8", errors="ignore") as f:
            for line in f.read(4096).splitlines():
                if line.startswith("- File: "):
                    return line[len("- File: "):].strip()
    except OSError:
        return ""
    return ""


def path_for(path: str, *, existing: bool = False) -> str | None:
    """Where the Markdown of this document file belongs.

    Normally it is the document's name with .md instead of its extension - Procedure.docx -> Procedure.md.
    But two documents can share a folder and a base name (a procedure and its workbook, Procedure.docx and
    Procedure.xlsx): one Procedure.md cannot serve both, and whichever was approved second used to overwrite
    the other's Markdown. So the first one there keeps the short name and the next carries its extension
    too - Procedure.xlsx.md. With existing=True this returns the Markdown that is already beside the
    document, or None when it has none.
    """
    stem, _ext = os.path.splitext(path)
    plain, full = stem + ".md", path + ".md"
    if os.path.isfile(full):
        return full
    if os.path.isfile(plain):
        owner = _written_for(plain)
        if owner and os.path.normcase(owner) != os.path.normcase(path) and os.path.isfile(owner):
            return full if not existing else (full if os.path.isfile(full) else None)
        return plain
    return None if existing else plain


def write_beside(path: str, doc: dict | None = None) -> str | None:
    """Write <document>.md beside the approved document. It opens with what the document is - the DMS id, the
    revision, when it was approved and where it lives - so an answer can say which document it came from and
    not only what it said. Returns where it was written, or None when there was nothing to write."""
    body, readable = body_of(path), True
    d = doc or {}
    by_ocr = bool(body) and OCR.get("on") and _was_ocr(path, body)
    if not body:
        readable = False
        # A drawing, a scan, a picture, a CAD file: nothing to read, and until now nothing was written -
        # so the document was invisible to the AI, which could not even say it exists. A card is written
        # instead: what it is, which revision, where it lives, and plainly that its content cannot be
        # read. The AI can then name it and point a person at it, and never quotes from it.
        kind = (os.path.splitext(path)[1].lstrip(".") or "file").upper()
        body = (f"No text could be read from this {kind} file: it is a drawing, a scan, a picture or "
                f"another format the DMS cannot turn into text. It is the revision in force all the same - "
                f"open the file itself to read it.")
    head = [f"# {d.get('title') or os.path.splitext(os.path.basename(path))[0]}", ""]
    for label, value in (("Document ID", d.get("documentId")), ("Revision", d.get("currentRevision")),
                         ("Type", d.get("documentType")), ("Area", d.get("documentArea")),
                         ("Approved", (d.get("lastApprovedUtc") or "")[:10]), ("Owner", d.get("ownerEmail"))):
        if value:
            head.append(f"- {label}: {value}")
    if not readable:
        head.append("- Content: not readable (no text in this format)")
    elif by_ocr:
        head.append("- Content: read by OCR from a scan (the words may be imperfect)")
    head += [f"- File: {path}",
             f"- Written by the DMS: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC", "", "---", ""]
    target = path_for(path)
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
