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
