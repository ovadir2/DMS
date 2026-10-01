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
            out = []
            for n in sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)):
                rows = []
                for row in ElementTree.fromstring(z.read(n)).iter():
                    if not row.tag.endswith("}row"):
                        continue
                    cells = []
                    for c in row:
                        v = next((x.text for x in c.iter() if x.tag.endswith("}v") or x.tag.endswith("}t")), None)
                        if v is None:
                            continue
                        cells.append(shared[int(v)] if c.get("t") == "s" and v.isdigit() and int(v) < len(shared) else v)
                    if cells:
                        rows.append("\t".join(cells))
                out.append(f"[{os.path.basename(n)}]\n" + "\n".join(rows))
            return "\n\n".join(out)
    return ""


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
