"""Software qualification against SRS-001: every requirement, and whether what proves it passed.

A green test run says 252 tests passed. It does not say the system meets its specification. This reads
the run (pytest's JUnit XML) and answers the question the validation actually asks - requirement by
requirement, which tests stand behind it, and did they pass - so the SQA report can be signed against
SRS-001 rather than against a number.

    py -m dms_api.qualification <junit.xml>            # the report, as Markdown
    py -m dms_api.qualification --check                # only: is the map sound?
"""
from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAP = os.path.join(ROOT, "docs", "validation", "srs-tests.json")
TESTS = os.path.join(ROOT, "webapi", "tests")


def mapping() -> dict[str, list[str]]:
    with open(MAP, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if k.startswith("SRS-")}


def test_names() -> set[str]:
    """Every test the suite actually has."""
    names: set[str] = set()
    for name in os.listdir(TESTS):
        if name.startswith("test_") and name.endswith(".py"):
            with open(os.path.join(TESTS, name), encoding="utf-8") as f:
                names |= set(re.findall(r"^def (test_[A-Za-z0-9_]+)", f.read(), re.M))
    return names


def check() -> dict[str, list[str]]:
    """What would make the qualification a lie: a requirement that says it is tested and is not, and a
    map that names a test which no longer exists."""
    from . import traceability
    reqs = {r["id"]: r for r in traceability.requirements()}
    m, have = mapping(), test_names()
    return {
        "requirements verified by test with no test named":
            sorted(i for i, r in reqs.items() if "T" in r["verify"].split(", ") and not m.get(i)),
        "mapped tests that do not exist":
            sorted({t for tests in m.values() for t in tests} - have),
        "mapped requirements that are not in the SRS":
            sorted(set(m) - set(reqs)),
    }


def results(junit: str) -> dict[str, str]:
    """test name -> passed / failed / skipped, from a pytest run."""
    out: dict[str, str] = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        name = (case.get("name") or "").split("[")[0]
        state = "passed"
        if case.find("failure") is not None or case.find("error") is not None:
            state = "failed"
        elif case.find("skipped") is not None:
            state = "skipped"
        if out.get(name) != "failed":
            out[name] = state
    return out


def report(junit: str = "") -> str:
    from . import traceability
    reqs = traceability.requirements()
    m = mapping()
    ran = results(junit) if junit and os.path.isfile(junit) else {}
    rows, qualified, pending, failed = [], 0, 0, 0
    for r in reqs:
        tests = m.get(r["id"], [])
        methods = [x.strip() for x in r["verify"].split(",")]
        if tests and ran:
            states = {t: ran.get(t, "not run") for t in tests}
            if any(v == "failed" for v in states.values()):
                verdict, failed = "**FAIL**", failed + 1
            elif all(v == "passed" for v in states.values()):
                verdict, qualified = "**PASS**", qualified + 1
            else:
                verdict, pending = "incomplete", pending + 1
            said = ", ".join(f"{t} ({v})" if v != "passed" else t for t, v in states.items())
        elif tests:
            verdict, said, pending = "not run", ", ".join(tests), pending + 1
        else:
            where = "OQ" if "D" in methods or "W" in methods else "inspection"
            verdict = f"at {where}"
            said = ", ".join(r["steps"]) or where
            pending += 1
        rows.append(f"| {r['id']} | {r['text']} | {r['risk']} | {r['verify']} | {said} | {verdict} |")
    nl = "\n"
    problems = {k: v for k, v in check().items() if v}
    return f"""## Qualification against SRS-001

{len(reqs)} requirement(s): {qualified} qualified by this run, {failed} failed,
{pending} verified at IQ, OQ, PQ or by inspection.

| Requirement | What it states | Risk | Verify | What proves it | Result |
|---|---|---|---|---|---|
{nl.join(rows)}

### The map itself

{"No problem found: every requirement that says it is tested names tests, and every test named exists."
 if not problems else nl.join(f"- **{k}**: {', '.join(v)}" for k, v in problems.items())}
"""


if __name__ == "__main__":   # pragma: no cover - the writer
    if "--check" in sys.argv:
        for what, which in check().items():
            print(f"{what}: {', '.join(which) if which else 'none'}")
        sys.exit(1 if any(check().values()) else 0)
    sys.stdout.write(report(sys.argv[1] if len(sys.argv) > 1 else ""))
