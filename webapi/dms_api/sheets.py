"""A workbook as rows, for a page that has to draw it.

A dashboard in a browser cannot open an .xlsx by itself without a library of its own, and the server may have
no way out to fetch one. The DMS already reads workbooks - it writes the Markdown the AI reads from them - so
it answers with the cells instead: sheet by sheet, row by row, as text.
"""
from __future__ import annotations

import csv
import os

MAX_ROWS = 5000                     # a dashboard draws a report, not a database


def rows_of(path: str) -> dict[str, list[list[str]]]:
    """{sheet name: rows of cells}. An empty answer means this is not a workbook."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        from .doc_text import _office
        out: dict[str, list[list[str]]] = {}
        for block in (_office(path, ".xlsx") or "").split("\n\n"):
            lines = [ln for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue
            out[lines[0].strip("[]")] = [ln.split("\t") for ln in lines[1:MAX_ROWS + 1]]
        return out
    if ext == ".xls":
        import xlrd
        book = xlrd.open_workbook(path)
        out = {}
        for sheet in book.sheets():
            rows = []
            for r in range(min(sheet.nrows, MAX_ROWS)):
                cells = []
                for c in range(sheet.ncols):
                    v = sheet.cell_value(r, c)
                    if isinstance(v, float) and v == int(v):
                        v = int(v)
                    cells.append(str(v).strip())
                if any(cells):
                    rows.append(cells)
            out[sheet.name] = rows
        return out
    if ext == ".csv":
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            return {os.path.basename(path): [r for _, r in zip(range(MAX_ROWS), csv.reader(f))]}
    return {}
