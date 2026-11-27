"""The software revision of the DMS, and whether the build running is the one that was validated.

A validated system has to be able to say which revision it is, and a change to it is not a deployment but
a revision: the validation documents are revised with it, the impact of the change is assessed, and the
new revision is released in the DMS like any other controlled document.

The one source of truth is docs/validation/validation.json, which travels with the code - so the revision
cannot drift from the build - and the DMS answers with it on /api/health and shows it on the page.
"""
from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger("dms_api.validation")

FILE = os.path.join("docs", "validation", "validation.json")


def _path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))        # webapi\dms_api
    return os.path.join(os.path.dirname(os.path.dirname(here)), *FILE.split(os.sep))


def state() -> dict:
    """What revision this build is, and whether it is the validated one. Never raises: a DMS that cannot
    read the file still answers, and says it does not know rather than claiming to be validated."""
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        log.info("the validation revision could not be read: %s", e)
        return {"softwareRevision": "", "status": "unknown", "validatedCommit": "", "validatedOn": "",
                "documents": []}
    return {"softwareRevision": str(data.get("softwareRevision") or ""),
            "status": str(data.get("status") or ""),
            "validatedCommit": str(data.get("validatedCommit") or ""),
            "validatedOn": str(data.get("validatedOn") or ""),
            "standard": str(data.get("standard") or ""),
            "documents": data.get("documents") or []}


def health(version: str) -> dict:
    """The revision, for /api/health: and whether the build running is the one the revision was validated
    on. A build that is ahead of the validated commit is not a fault - it is a change that has not been
    through its validation step yet - so the answer says so plainly instead of hiding it."""
    st = state()
    validated = bool(st["validatedCommit"]) and version.startswith(st["validatedCommit"][:len(version)])
    return {"softwareRevision": st["softwareRevision"], "validationStatus": st["status"],
            "validatedCommit": st["validatedCommit"], "validatedOn": st["validatedOn"],
            "runningValidatedBuild": validated}


def folder() -> str:
    return os.path.dirname(_path())


def consistency() -> dict[str, list[str]]:
    """One version for the whole validation, or none of it is evidence.

    Every document of the set carries the software revision of validation.json, every document listed has
    a file, and every document file is listed. A report produced against another version is a deviation,
    which is why the executors record the revision they ran against.
    """
    st = state()
    rev, here = st["softwareRevision"], folder()
    listed = {d["id"]: d for d in st["documents"]}
    files = {}
    for name in sorted(os.listdir(here)):
        if not name.endswith(".md") or name == "README.md":
            continue
        doc_id = name.split("-")[0] + "-" + name.split("-")[1]
        files[doc_id] = os.path.join(here, name)
    wrong = []
    for doc_id, path in files.items():
        with open(path, encoding="utf-8") as f:
            said = re.search(r"^\| Software revision \| (\S+)", f.read(), re.M)
        if not said:
            wrong.append(f"{doc_id} does not say which revision it is")
        elif said.group(1) != rev:
            wrong.append(f"{doc_id} says revision {said.group(1)}, the set is {rev}")
    return {"documents with the wrong version": wrong,
            "listed with no document": sorted(set(listed) - set(files)),
            "documents not listed": sorted(set(files) - set(listed))}


def bump(revision: str) -> list[str]:
    """Raise the whole set to a new revision at once: validation.json and the version line of every
    document. The one way the version is ever changed, so the set cannot be half-revised."""
    if not re.fullmatch(r"\d{2}", revision):
        raise ValueError("A revision is two digits, as everywhere else in the DMS: 01, 02, 03")
    with open(_path(), encoding="utf-8") as f:
        data = json.load(f)
    data["softwareRevision"] = revision
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    changed = []
    here = folder()
    for name in sorted(os.listdir(here)):
        if not name.endswith(".md") or name == "README.md":
            continue
        path = os.path.join(here, name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        new = re.sub(r"^(\| Software revision \| )\S+", r"\g<1>" + revision, text, count=1, flags=re.M)
        if new != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            changed.append(name)
    return changed


if __name__ == "__main__":   # pragma: no cover - the command
    import sys
    if "--bump" in sys.argv:
        where = sys.argv[sys.argv.index("--bump") + 1]
        for name in bump(where):
            print(f"{name} -> revision {where}")
    else:
        print(json.dumps({**state(), "consistency": consistency()}, indent=2, ensure_ascii=False))
