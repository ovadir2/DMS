"""The text of a document, for AI Insights questions about a file (the RH AI chat has no file upload)."""
from __future__ import annotations

import os
import re
import zipfile
from xml.etree import ElementTree

TEXT_EXT = {".txt", ".csv", ".md", ".log", ".json", ".xml", ".html", ".htm"}


def _xml_text(data: bytes, para_tag: str) -> str:
    """The text of an Office XML part; a new line after each paragraph / row."""
    root = ElementTree.fromstring(data)
    out: list[str] = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("t", "v") and el.text:
            out.append(el.text)
        elif tag in ("tab",):
            out.append("\t")
        if tag == para_tag:
            out.append("\n")
    return "".join(out).strip()


def _office(path: str, ext: str) -> str:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if ext == ".docx":
            parts = ["word/document.xml"] + sorted(n for n in names if re.match(r"word/(header|footer)\d*\.xml", n))
            return "\n".join(_xml_text(z.read(n), "p") for n in parts if n in names)
        if ext == ".pptx":
            slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                            key=lambda n: int(re.findall(r"\d+", n)[-1]))
            return "\n\n".join(f"[Slide {i}]\n" + _xml_text(z.read(n), "p") for i, n in enumerate(slides, 1))
        if ext == ".xlsx":
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
                for si in root:
                    shared.append("".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")))
            # The sheets by the names people gave them. The part name (sheet1.xml) is not one: a workbook of
            # several sheets came out as "sheet1.xml", "sheet2.xml", and an answer could not say which sheet
            # it had read. workbook.xml lists them in order, and the relationships say which part each is.
            titles: dict[str, str] = {}
            try:
                rels = {}
                if "xl/_rels/workbook.xml.rels" in names:
                    for r in ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels")):
                        t = (r.get("Target") or "").replace("\\", "/")
                        rels[r.get("Id")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
                rid = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                for sh in ElementTree.fromstring(z.read("xl/workbook.xml")).iter():
                    if sh.tag.endswith("}sheet") and sh.get("name"):
                        part = rels.get(sh.get(rid), "")
                        if part in names:
                            titles[part] = sh.get("name")
            except (KeyError, ElementTree.ParseError, OSError):
                titles = {}                      # no names to be had: the part name says which sheet it was

            # Which styles mean a date: a date is kept as a number (45678), and written as one it is not the
            # date anybody wrote. The style of the cell is the only thing that says otherwise.
            dates = _date_styles(z, names)

            out = []
            for n in sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)):
                rows = []
                for row in ElementTree.fromstring(z.read(n)).iter():
                    if not row.tag.endswith("}row"):
                        continue
                    cells: list[str] = []
                    for c in row:
                        if not c.tag.endswith("}c"):
                            continue
                        # The cell says which column it is in (A1, D1). Taking the cells in the order they
                        # come puts the value of D under the heading of B as soon as a cell is empty, and a
                        # number under the wrong heading is worse than no number at all.
                        at = _column_of(c.get("r"))
                        if at is not None:
                            while len(cells) < at:
                                cells.append("")
                        cells.append(_cell_text(c, shared, dates))
                    if any(x.strip() for x in cells):
                        rows.append("\t".join(cells).rstrip("\t"))
                out.append(f"[{titles.get(n) or os.path.splitext(os.path.basename(n))[0]}]\n" + "\n".join(rows))
            return "\n\n".join(out)
    return ""


def _column_of(ref: str | None) -> int | None:
    """A1 -> 0, D7 -> 3: where in the row this cell sits."""
    if not ref:
        return None
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    if not letters:
        return None
    at = 0
    for ch in letters:
        at = at * 26 + (ord(ch) - 64)
    return at - 1


def _date_styles(z, names: set | list) -> set:
    """The style numbers that mean a date or a time, from the workbook's own formats."""
    builtin = set(range(14, 23)) | set(range(45, 48))         # Excel's own date and time formats
    out: set = set()
    if "xl/styles.xml" not in names:
        return out
    try:
        root = ElementTree.fromstring(z.read("xl/styles.xml"))
    except ElementTree.ParseError:
        return out
    custom = {f.get("numFmtId"): (f.get("formatCode") or "") for f in root.iter() if f.tag.endswith("}numFmt")}
    dated = {i for i, code in custom.items()
             if re.search(r"[yY]|[dD]{1,4}|mmm|hh|ss", re.sub(r"\[[^\]]*\]|\"[^\"]*\"", "", code))}
    xfs = next((e for e in root.iter() if e.tag.endswith("}cellXfs")), None)
    for i, xf in enumerate(list(xfs) if xfs is not None else []):
        fmt = xf.get("numFmtId") or "0"
        if fmt in dated or (fmt.isdigit() and int(fmt) in builtin):
            out.add(str(i))
    return out


def _serial_date(value: str) -> str:
    """Excel keeps a date as the days since 1900 (and counts a 29 February 1900 that never was)."""
    from datetime import datetime, timedelta
    try:
        days = float(value)
    except ValueError:
        return value
    if days < 1:                                              # a time of day on no particular date
        seconds = round(days * 86400)
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"
    when = datetime(1899, 12, 30) + timedelta(days=days)      # 30 December 1899: the leap-year bug included
    return when.strftime("%Y-%m-%d") if days == int(days) else when.strftime("%Y-%m-%d %H:%M")


def _cell_text(c, shared: list, dates: set) -> str:
    """What the cell says. A formula contributes the value Excel last worked out for it; when the workbook
    was written without one, the formula itself is the only thing the cell has to say, and saying nothing
    would quietly drop a number from the table."""
    kind = c.get("t") or "n"
    if kind == "inlineStr":
        return "".join(t.text or "" for t in c.iter() if t.tag.endswith("}t")).strip()
    v = next((x.text for x in c.iter() if x.tag.endswith("}v")), None)
    if v is None:
        f = next((x.text for x in c.iter() if x.tag.endswith("}f")), None)
        return ("=" + f.strip()) if f else ""
    if kind == "s" and v.isdigit() and int(v) < len(shared):
        return shared[int(v)]
    if kind == "b":
        return "TRUE" if v.strip() == "1" else "FALSE"
    if kind in ("str", "e"):
        return (v or "").strip()
    if (c.get("s") or "") in dates:
        return _serial_date(v)
    return (v or "").strip()


def extract(path: str, max_chars: int = 60000) -> str:
    ext = os.path.splitext(path)[1].lower()
    text = ""
    try:
        if ext in (".docx", ".docm", ".pptx", ".xlsx", ".xlsm"):
            text = _office(path, {".docm": ".docx", ".xlsm": ".xlsx"}.get(ext, ext))
        elif ext == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return ""
            text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
        elif ext in TEXT_EXT:
            with open(path, "rb") as f:
                raw = f.read(max_chars * 4)
            for enc in ("utf-8-sig", "cp1255", "latin-1"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, ValueError):
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars] + ("\n[... the document continues ...]" if len(text) > max_chars else "")
