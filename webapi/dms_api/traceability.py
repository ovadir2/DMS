"""The traceability matrix (VAL-005), built from the specification and the OQ protocol.

A matrix kept by hand is wrong within a month, and a validation stands on it: it is what says every
requirement is tested and every test has a reason. So it is generated from SRS-001 and VAL-003, and a test
in the suite rebuilds it and fails if the file on disk is behind, if a requirement has no step, or if a
step cites no requirement.

    py -m dms_api.traceability          # print it
    py -m dms_api.traceability --write  # write docs/validation/VAL-005-Traceability-Matrix.md
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRS = os.path.join(ROOT, "docs", "validation", "SRS-001-Software-Requirements-Specification.md")
OQ = os.path.join(ROOT, "docs", "validation", "VAL-003-OQ-Protocol.md")
WALK = os.path.join(ROOT, "scripts", "Test-DmsSmoke.ps1")
MATRIX = os.path.join(ROOT, "docs", "validation", "VAL-005-Traceability-Matrix.md")


def requirements() -> list[dict]:
    """Every requirement of SRS-001, with the steps that verify it."""
    out = []
    for line in open(SRS, encoding="utf-8"):
        if not re.match(r"^\|\s*SRS-\d+\s*\|", line):
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        out.append({"id": c[0], "text": c[1], "risk": c[2], "verify": c[3],
                    "steps": re.findall(r"(?:OQ|IQ|PQ)-\d+", c[4])})
    return out


def steps() -> list[dict]:
    """Every step of the OQ protocol, with the requirements it cites."""
    out = []
    for line in open(OQ, encoding="utf-8"):
        if not line.startswith("| OQ-"):
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        out.append({"id": c[0], "srs": c[1], "what": c[2], "expected": c[3], "evidence": c[4]})
    return out


def walk_ids() -> dict[str, str]:
    """What the end-to-end walk proves, line by line."""
    out = {}
    for line in open(WALK, encoding="utf-8-sig"):
        m = re.search(r"(?:Check|Skip) '(REQ-P\d+)' \"(.*?)\"", line)
        if m:
            out.setdefault(m.group(1), m.group(2))
    return out


def gaps() -> dict[str, list[str]]:
    """What a validation cannot have: a requirement nothing proves, or a step with no reason to exist."""
    return {"requirements with no step": [r["id"] for r in requirements() if not r["steps"]],
            "steps with no requirement": [s["id"] for s in steps() if s["srs"] in ("", "-")]}


def matrix() -> str:
    reqs, sts, walk = requirements(), steps(), walk_ids()
    evidence = {s["id"]: s["evidence"] for s in sts}
    rows = []
    for r in reqs:
        where = ", ".join(r["steps"]) or "-"
        said = "; ".join(f"{s}: {evidence[s]}" if s in evidence else s for s in r["steps"]) or "-"
        rows.append(f"| {r['id']} | {r['text']} | {r['risk']} | {r['verify']} | {where} | {said} |")
    nl = "\n"
    from . import validation
    rev = validation.state()["softwareRevision"]
    return f"""# VAL-005 Requirements Traceability Matrix

| | |
|---|---|
| Software revision | {rev} - the whole validation set carries one version (`validation.json`) |

Generated from SRS-001 and VAL-003 by `webapi\\dms_api\\traceability.py` - never written by hand, so it
cannot drift from them. A test in the suite fails if it is out of date, if a requirement has no step, or
if a step has no requirement.

Verification: T = automated test, W = the end-to-end walk, D = demonstration witnessed on the page,
I = inspection. Risk: H / M / L.

## 1. Every requirement to the step that proves it

| Requirement | What it states | Risk | Verify | Step | Evidence |
|---|---|---|---|---|---|
{nl.join(rows)}

## 2. Every OQ step to the requirements behind it

| Step | Function | Requirements |
|---|---|---|
{nl.join(f"| {s['id']} | {s['what']} | {s['srs']} |" for s in sts)}

## 3. The walk's own requirement ids

The end-to-end walk prints one of these on every line it proves, so a line of its report is the evidence
for the step that cites it.

| Walk id | What the line proves |
|---|---|
{nl.join(f"| {k} | {v} |" for k, v in sorted(walk.items(), key=lambda x: int(x[0][5:])))}

## 4. Coverage

| | |
|---|---|
| Requirements in SRS-001 | {len(reqs)} |
| Requirements with at least one step | {sum(1 for r in reqs if r['steps'])} |
| OQ steps | {len(sts)} |
| OQ steps with at least one requirement | {sum(1 for s in sts if s['srs'] != '-')} |
| Walk requirement ids | {len(walk)} |
"""


if __name__ == "__main__":   # pragma: no cover - the writer
    text = matrix()
    if "--write" in sys.argv:
        with open(MATRIX, "w", encoding="utf-8") as f:
            f.write(text)
        print(MATRIX)
        for what, which in gaps().items():
            if which:
                print(f"  {what}: {', '.join(which)}")
    else:
        sys.stdout.write(text)
