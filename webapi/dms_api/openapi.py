"""The OpenAPI (Swagger) description of the DMS.

FastAPI knows the routes; this says what they are - who may call each one, in which group it belongs, and
how a caller signs in. Swagger UI is served at /dms/api-docs, ReDoc at /dms/api-redoc, and the document
itself at /api/openapi.json (and in the repository, as docs\\dms-openapi.json, so the Builder and the RAG
can generate a client without reaching the server).
"""
from __future__ import annotations

import re

from fastapi.openapi.utils import get_openapi

from .apidocs import GROUPS, HIDE

DESCRIPTION = """
The DMS answers three kinds of caller, and never more than the caller's own rights allow.

* **A person on the page** - Windows authentication (IIS). The DMS asks AD what that person may see, folder
  by folder, and answers nothing else. Most endpoints are these.
* **A page of the repository** - a dashboard or a KPI page runs sandboxed, with an origin of its own, so it
  cannot sign in. It is given a page key when it is opened (`?t=`), good for the folder it was opened from
  and for a few hours. Reading only.
* **An application** - a key of its own (`X-DMS-Api-Key`, or `Authorization: Bearer`). The key names what it
  may read and the AD account it acts as: the DMS answers it exactly what that account may see. One
  endpoint writes (the KPI Builder's), the rest read.

The DMS writes on the file server with its own account, so an approver needs no rights there at all - but it
never stands in for a right the person does not have. See `docs/13-Machine-API.md` for applications,
`docs/15-KPI-Builder-Contract.md` for the KPI Builder and `docs/14-API-Reference.md` for the whole list.
""".strip()

SECURITY = {
    "windows": {"type": "http", "scheme": "negotiate",
                "description": "Windows authentication, done by IIS: the browser's own sign-in. The DMS "
                               "answers as that person, by their AD groups."},
    "apiKey": {"type": "apiKey", "in": "header", "name": "X-DMS-Api-Key",
               "description": "An application's key. It names the scopes it may read and the AD account it "
                              "acts as (scripts\\New-DmsApiKey.ps1)."},
    "bearer": {"type": "http", "scheme": "bearer",
               "description": "The same application key, sent as Authorization: Bearer."},
    "pageKey": {"type": "apiKey", "in": "query", "name": "t",
                "description": "The page key the DMS mints when it opens a page of the repository. Reading "
                               "only, inside that page's own folder, for DMS_PAGE_KEY_HOURS."},
}


def _group_of(path: str) -> str:
    for title, pattern, _blurb in GROUPS:
        if re.search(pattern, path):
            return title
    return "The rest"


def spec(app, version: str = "") -> dict:
    """The whole document, as /api/openapi.json serves it."""
    doc = get_openapi(title="RH DMS Web API", version=version or app.version,
                      description=DESCRIPTION, routes=app.routes)
    doc.setdefault("components", {})["securitySchemes"] = SECURITY
    doc["tags"] = [{"name": title, "description": blurb} for title, _p, blurb in GROUPS] + \
                  [{"name": "The rest", "description": "Answers that are not JSON: a page, an image, a file."}]
    for path, ops in list(doc["paths"].items()):
        if path in HIDE:
            doc["paths"].pop(path)
            continue
        group = _group_of(path)
        for verb, op in ops.items():
            if not isinstance(op, dict):
                continue
            op["tags"] = [group]
            # One name per verb and path, written here: a route that answers several methods with the same
            # function (the WebDAV one Office uses) was given the same name for all of them, and which one
            # it was changed from run to run - a client generated from the document could not be trusted.
            op["operationId"] = (verb + "_" + re.sub(r"[^A-Za-z0-9]+", "_", path)).strip("_").lower()
            if path.startswith("/api/v1/"):
                op["security"] = [{"apiKey": []}, {"bearer": []}]
            elif path.startswith("/api/kpi/"):
                op["security"] = [] if path.endswith("/ping") else [{"pageKey": []}]
            else:
                op["security"] = [{"windows": []}]
    return doc
