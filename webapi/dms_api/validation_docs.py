"""The validation documents as Word files, with the company's logo, for the DMS to control like any other.

The source of each one is its Markdown in docs/validation: that is what is edited and reviewed in git.
This turns them into .docx so they can be released in the DMS, signed, and read by anyone - carrying the
rh logo, the document number, the software revision they belong to, and a page footer that says which
revision a printed page came from.

    py -m dms_api.validation_docs <out folder> [--revision 02]
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE = os.path.join(ROOT, "docs", "validation")
LOGO = os.path.join(ROOT, "assets", "logo.png")


def _docs() -> list[tuple[str, str, str]]:
    """(id, title, file) for every validation document, in order."""
    from . import validation
    out = []
    for d in validation.state()["documents"]:
        for name in sorted(os.listdir(SOURCE)):
            if name.startswith(d["id"]) and name.endswith(".md"):
                out.append((d["id"], d["title"], os.path.join(SOURCE, name)))
                break
    return out


def _heading(doc, text: str, level: int) -> None:
    doc.add_heading(re.sub(r"^#+\s*", "", text).strip(), level=min(level, 4))


def _table(doc, rows: list[list[str]]) -> None:
    head, body = rows[0], [r for r in rows[1:] if not all(set(c) <= set("-: ") for c in r)]
    t = doc.add_table(rows=1, cols=len(head))
    t.style = "Table Grid"
    for i, cell in enumerate(head):
        run = t.rows[0].cells[i].paragraphs[0].add_run(cell)
        run.bold = True
    for row in body:
        cells = t.add_row().cells
        for i, cell in enumerate(row[:len(head)]):
            cells[i].text = re.sub(r"[*`]", "", cell)


def _inline(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return re.sub(r"\*\*([^*]*)\*\*", r"\1", text)


def write_one(doc_id: str, title: str, source: str, out_folder: str, revision: str) -> str:
    """One Markdown file as a .docx, with the logo, the revision and the signature page it already carries."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Cm

    doc = Document()
    for section in doc.sections:
        header = section.header
        p = header.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        if os.path.isfile(LOGO):
            p.add_run().add_picture(LOGO, height=Cm(1.0))
        tab = p.add_run(f"\t{doc_id} {title}\tRevision {revision}")
        tab.font.size = Pt(9)
        foot = section.footer.paragraphs[0]
        foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = foot.add_run(f"RH Electronics · {doc_id} rev {revision} · released by the DMS · "
                           f"a printed page is uncontrolled")
        run.font.size = Pt(8)

    lines = open(source, encoding="utf-8").read().splitlines()
    table: list[list[str]] = []
    for line in lines:
        if line.startswith("|"):
            table.append([c.strip() for c in line.strip().strip("|").split("|")])
            continue
        if table:
            _table(doc, table)
            table = []
        if not line.strip():
            continue
        if line.startswith("#"):
            _heading(doc, line, line.count("#", 0, 6))
        elif line.startswith(("- ", "* ")):
            doc.add_paragraph(_inline(line[2:]), style="List Bullet")
        elif re.match(r"^\d+\.\s", line):
            doc.add_paragraph(_inline(re.sub(r"^\d+\.\s", "", line)), style="List Number")
        else:
            doc.add_paragraph(_inline(line))
    if table:
        _table(doc, table)

    name = f"{doc_id}_{title.replace(' ', '_')}_Rev{revision}.docx"
    path = os.path.join(out_folder, name)
    doc.save(path)
    return path


def write_all(out_folder: str, revision: str = "") -> list[str]:
    from . import validation
    st = validation.state()
    revision = revision or st["softwareRevision"] or "01"
    os.makedirs(out_folder, exist_ok=True)
    made = []
    for doc_id, title, source in _docs():
        made.append(write_one(doc_id, title, source, out_folder, revision))
    index = os.path.join(out_folder, f"VAL-000_Validation_Index_Rev{revision}.md")
    with open(index, "w", encoding="utf-8") as f:
        f.write(f"# RH DMS validation, software revision {revision}\n\n")
        f.write(f"Issued {date.today():%Y-%m-%d}. Status: {st['status']}. "
                f"Standard: {st.get('standard', '')}\n\n| Document | Title | Revision |\n|---|---|---|\n")
        for d in st["documents"]:
            f.write(f"| {d['id']} | {d['title']} | {d.get('revision', revision)} |\n")
    made.append(index)
    return made


if __name__ == "__main__":   # pragma: no cover - the writer, run by the script
    where = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SOURCE, "out")
    rev = ""
    if "--revision" in sys.argv:
        rev = sys.argv[sys.argv.index("--revision") + 1]
    for made in write_all(where, rev):
        print(made)
