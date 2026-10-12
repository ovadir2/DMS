"""Builds scripts\\dms-access-template.xlsx: every blueprint folder of 01_General and 02_Customers, by levels,
with the columns IT fills in (Modify groups / Read groups / Users / Inherit) before the automation script runs.

    py scripts\\new_access_workbook.py [<customer> ...]

Without a customer name the customer rows stay the template <Customer> (one set for every customer). With names
(py scripts\\new_access_workbook.py Customer_A Customer_B) each one gets its own rows.
The folder list is scripts\\blueprint-folders.txt, so the workbook follows the DMS blueprint.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HERE = Path(__file__).resolve().parent
LEVELS = 6                                     # 02_Customers\<Customer>\Develop\Products\<Product>\06_Implementation
FILL_IN = ("Modify groups", "Read groups", "Users", "Inherit", "Notes")
BUILT_IN = ("domain users", "authenticated users", "everyone", "users", "domain admins")   # already in AD / Windows
HEAD = PatternFill("solid", fgColor="1F3864")
FILL_IN_HEAD = PatternFill("solid", fgColor="2E7D32")
BAND = PatternFill("solid", fgColor="F2F6FC")


def folders(customers: list[str]) -> list[list[str]]:
    lines = [ln.strip() for ln in (HERE / "blueprint-folders.txt").read_text("utf-8-sig").splitlines() if ln.strip()]
    out = []
    for line in lines:
        parts = line.split("\\")
        if parts[0] not in ("01_General", "02_Customers"):
            continue
        for p in ([[c if x == "<Customer>" else x for x in parts] for c in customers]
                  if customers and "<Customer>" in parts else [parts]):
            out.append(p)
    return out


def rules() -> list[dict]:
    """dms-access.csv: what the pilot gives today (a suggestion to check, not a decision)."""
    with (HERE / "dms-access.csv").open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("Department") or "").strip()]


def split(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(";") if x.strip() and not x.strip().startswith("<")]


def suggest(parts: list[str], rows: list[dict], customers: list[str]) -> tuple[str, str, str]:
    """(Modify groups, Read groups, Inherit) for one folder, from dms-access.csv."""
    rel, mod, read, inherit = "\\".join(parts), [], [], ""
    for r in rows:
        dep = (r["Department"] or "").strip().strip("\\")
        hit = False
        if "\\" in dep or dep in ("01_General", "02_Customers"):
            hit = dep.lower() == rel.lower() or (
                "<Customer>" in parts and dep.lower() == rel.lower().replace("<customer>", parts[1].lower()))
            if not hit and customers:                        # a row for one customer, rows expanded per customer
                hit = dep.lower() == rel.lower()
        elif len(parts) == 2 and parts[0] == "01_General":
            hit = dep.lower() == parts[1].lower()
        elif len(parts) == 3 and parts[0] == "02_Customers":
            hit = parts[2].lower() in [x.lower() for x in split(r.get("CustomerFolders"))]
        if not hit:
            continue
        mod += split(r.get("Groups"))
        read += split(r.get("ReadGroups"))
        if (r.get("Inherit") or "").strip().lower() in ("no", "n", "false", "0"):
            inherit = "No"
    return ("; ".join(dict.fromkeys(mod)), "; ".join(dict.fromkeys(read)), inherit or ("Yes" if mod or read else ""))


def members() -> list[dict]:
    """dms-ad-groups.csv: the groups and people IT creates in AD."""
    f = HERE / "dms-ad-groups.csv"
    if not f.exists():
        return []
    with f.open(encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("Group") or "").strip()]


def main(customers: list[str]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Folders"
    head = ["#", "Depth", "Path from the root"] + [f"Level {i + 1}" for i in range(LEVELS)] + list(FILL_IN)
    ws.append(head)
    for i, cell in enumerate(ws[1], start=1):
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = FILL_IN_HEAD if cell.value in FILL_IN else HEAD
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    rows, rules_ = folders(customers), rules()
    covered = {"\\".join(p).lower() for p in rows}
    for r in rules_:                                          # a row for one customer only: its own folder row
        dep = (r["Department"] or "").strip().strip("\\")
        if "\\" in dep and dep.lower() not in covered and split(r.get("Groups")):
            rows.append(dep.split("\\"))
            covered.add(dep.lower())
    for n, parts in enumerate(rows, start=1):
        path = "\\".join(parts)
        mod, read, inherit = suggest(parts, rules_, customers)
        line = [n, len(parts), path] + parts + [""] * (LEVELS - len(parts)) + [mod, read, "", inherit, ""]
        ws.append(line)
        if len(parts) <= 2:                                   # the levels IT decides first: 01_General, its departments
            for cell in ws[ws.max_row]:
                cell.fill = BAND
                if cell.column <= 3 + LEVELS:
                    cell.font = Font(bold=True)

    last = ws.max_row
    yes_no = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
    yes_no.error = "Yes (keeps what the folder above gives) or No (only what this row gives)"
    ws.add_data_validation(yes_no)
    inherit_col = get_column_letter(head.index("Inherit") + 1)
    yes_no.add(f"{inherit_col}2:{inherit_col}{last}")

    widths = {"A": 5, "B": 7, "C": 58}
    for i in range(LEVELS):
        widths[get_column_letter(4 + i)] = 26
    for i, name in enumerate(FILL_IN):
        widths[get_column_letter(4 + LEVELS + i)] = 30 if name != "Inherit" else 9
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(head))}{last}"

    # the groups and people IT creates in AD (outside the DMS): one row per group
    gs = wb.create_sheet("Groups to create in AD")
    gs.append(["Group", "Scope", "Description (which folders)", "Members (users / groups)", "Done in AD"])
    for cell in gs[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD
    used = {g for r in ws.iter_rows(min_row=2, values_only=True) for c in (r[-5], r[-4]) for g in split(c)}
    known = {(m["Group"] or "").strip(): m for m in members()}
    for g in sorted(used, key=str.lower):
        m = known.get(g, {})
        if g.lower() in BUILT_IN:
            gs.append([g, "built-in", "Already in AD / Windows: nothing to create", "everyone in the company", "-"])
            continue
        gs.append([g, "Global", m.get("Description", ""), (m.get("Members") or "").replace(";", "; "), ""])
    for cell in gs[1]:
        cell.alignment = Alignment(vertical="center")
    for w, col in zip((34, 14, 58, 40, 12), "ABCDE"):
        gs.column_dimensions[col].width = w
    gs.freeze_panes = "A2"

    nt = wb.create_sheet("How to fill in")
    for line in [
        ["Sheet", "What to write"],
        ["Folders", "One row per blueprint folder. The Level columns are the same path split by level, so you can "
                    "filter or sort by level (Level 1 = 01_General / 02_Customers)."],
        ["Folders: Modify groups", "The AD groups that may open and edit there. Several groups: \";\" between them. "
                                   "Empty = nobody but the admins and the DMS account."],
        ["Folders: Read groups", "The AD groups that may only open and copy there."],
        ["Folders: Users", "People who should be in those groups (IT puts them in AD, not on the folder)."],
        ["Folders: Inherit", "Yes = the folder keeps what the folder above gives (the usual). "
                             "No = only what this row gives (HR, for example)."],
        ["Groups to create in AD", "Every group named in the Folders sheet, for IT: the group, its scope "
                                   "(Global / Domain Local), what it opens and its members. The DMS creates "
                                   "nothing in AD."],
        ["Filled in already", "What the pilot gives today (scripts\\dms-access.csv): a suggestion to check and "
                              "change, not a decision."],
        ["", ""],
        ["Rows with <Customer>", "One set for every customer: the same groups in each customer folder. "
                                 "Regenerate with the customer names for one row each: "
                                 "py scripts\\new_access_workbook.py Customer_A Customer_B"],
        ["Rows with <Product>", "A project folder a user creates under Develop\\Products. It inherits from the "
                                "customer's Develop folder, so it needs no row of its own."],
        ["After it is filled in", "The automation script reads this workbook (or dms-access.csv with the same "
                                  "columns) and sets the folders. AD itself is done by IT, on the file server "
                                  "and in AD, outside the DMS."],
    ]:
        nt.append(line)
    for cell in nt[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD
    nt.column_dimensions["A"].width = 26
    nt.column_dimensions["B"].width = 112
    for row in nt.iter_rows(min_row=2):
        row[0].font = Font(bold=True)
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    out = HERE / "dms-access-template.xlsx"
    wb.save(out)
    print(f"{out}  ({last - 1} folders, {LEVELS} levels)")
    return out


if __name__ == "__main__":
    main(sys.argv[1:])
