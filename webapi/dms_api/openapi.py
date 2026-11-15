"""The OpenAPI (Swagger) description of the DMS.

FastAPI knows the routes; this says what they are - who may call each one, in which group it belongs, and
how a caller signs in. Swagger UI is served at /dms/api-docs, ReDoc at /dms/api-redoc, and the document
itself at /api/openapi.json (and in the repository, as docs\\dms-swagger.json, so the Builder and the RAG
can generate a client without reaching the server).
"""
from __future__ import annotations

import re

from fastapi.openapi.utils import get_openapi

from .apidocs import GROUPS, HIDE

# What another system talks to: the machine API, the ticket the company's AI indexes with, and the page key
# a dashboard runs on. Everything else is how the DMS page works with itself - a caller outside has no use
# for it, and a document that lists 90 endpoints is read by nobody. /api/openapi-all.json has them all.
INTEGRATION = (r"^/api/v1/", r"^/api/ai/index-ticket$", r"^/api/kpi/")

DESCRIPTION = """
What another system needs from the DMS, and nothing else. Three ways in:

* **An application** - its own key (`X-DMS-Api-Key`, or `Authorization: Bearer`). The key names what it may
  read and **the AD account it acts as**: the DMS answers exactly what that account may see.
* **The company's AI** - a ticket minted for the person who asked (`/api/ai/index-ticket`). The answer is
  then what *that person* may read, file by file. The ticket does not say whose it is and cannot be pointed
  at somebody else.
* **A page of the repository** - a dashboard or a KPI page runs sandboxed and cannot sign in, so it is given
  a page key when it is opened (`?t=`), good for its own folder and for a few hours. Reading only.

Nothing here stands in for a right the person or the account does not have. One endpoint writes (the KPI
Builder's); the rest read.

Guides: `docs/09-Machine-API.md` (applications and the AI), `docs/08-KPI-Builder-Contract.md` (the KPI
Builder), `docs/07-KPI-Integration.md` (the page key). The DMS page's own endpoints are not here: they are
in `docs/10-Swagger.md`, and in `/api/openapi-all.json` for a client that really wants them.
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
    "indexTicket": {"type": "apiKey", "in": "query", "name": "ticket",
                    "description": "An indexing ticket the DMS mints for a person (/api/ai/index-ticket). "
                                   "The answer is then what that person's AD rights allow, file by file - "
                                   "which is how the company's AI indexes just what the person asking may "
                                   "read. Good for DMS_PAGE_KEY_HOURS; may also be sent as the header "
                                   "X-DMS-Index-Ticket."},
    "pageKey": {"type": "apiKey", "in": "query", "name": "t",
                "description": "The page key the DMS mints when it opens a page of the repository. Reading "
                               "only, inside that page's own folder, for DMS_PAGE_KEY_HOURS."},
}


def _group_of(path: str) -> str:
    for title, pattern, _blurb in GROUPS:
        if re.search(pattern, path):
            return title
    return "The rest"


def spec(app, version: str = "", full: bool = False) -> dict:
    """The document /api/openapi.json serves: what another system talks to. full=True keeps every endpoint
    of the page as well (/api/openapi-all.json), for whoever is working on the DMS itself."""
    doc = get_openapi(title="RH DMS Web API", version=version or app.version,
                      description=DESCRIPTION, routes=app.routes)
    doc.setdefault("components", {})["securitySchemes"] = SECURITY
    doc["tags"] = [{"name": title, "description": blurb} for title, _p, blurb in GROUPS] + \
                  [{"name": "The rest", "description": "Answers that are not JSON: a page, an image, a file."}]
    if not full:
        doc["info"]["title"] = "RH DMS - the API other systems use"
    for path, ops in list(doc["paths"].items()):
        if path in HIDE or (not full and not any(re.search(p, path) for p in INTEGRATION)):
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
                op["security"] = [{"apiKey": []}, {"bearer": []}, {"indexTicket": []}]
            elif path.startswith("/api/kpi/"):
                op["security"] = [] if path.endswith("/ping") else [{"pageKey": []}]
            else:
                op["security"] = [{"windows": []}]
    used = {op["tags"][0] for ops in doc["paths"].values() for op in ops.values()
            if isinstance(op, dict) and op.get("tags")}
    doc["tags"] = [t for t in doc["tags"] if t["name"] in used]
    return doc
