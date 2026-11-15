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

# What an OEM talks to, and nothing else: who is asking, what there is, the file itself, and where it all
# lives. Four. The DMS has eighty more for its own page and they are nobody's business outside it:
# /api/openapi-all.json and docs\\10-Swagger.md have them, and docs\\09-Machine-API.md has the rest of the
# machine API (search, the KPI Builder's publish call, the page key a dashboard runs on).
INTEGRATION = (r"^/api/ai/index-ticket$", r"^/api/v1/approved-documents$", r"^/api/v1/file$",
               r"^/api/v1/structure$")

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

Guides: `docs/09-Machine-API.md` (applications and the AI), `docs/08-WidgetBuilder-Contract.md` (the KPI
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



# What each call answers, so the page shows a real example beside the parameters instead of "string".
EXAMPLES: dict[str, dict] = {
    "/api/ai/index-ticket": {
        "ticket": "Qm9iLXRpY2tldC0yMDI2", "hours": 8,
        "documents": "https://dms.rh.tech/api/v1/approved-documents?ticket=Qm9iLXRpY2tldC0yMDI2",
        "search": "https://dms.rh.tech/api/v1/search?ticket=Qm9iLXRpY2tldC0yMDI2&q=",
        "header": "X-DMS-Index-Ticket"},
    "/api/v1/approved-documents": {
        "documents": [{
            "DocID": "QP-16.1", "DocName": "Control of documents", "DocRev": "03",
            "DocFile": "E:\\Shares\\01_General\\Quality\\Current_ReadOnly\\QP-16.1 Rev03.docx",
            "DocFileName": "QP-16.1 Rev03.docx",
            "DocDMSpath": "E:\\Shares\\01_General\\Quality\\Current_ReadOnly\\QP-16.1 Rev03.md",
            "url": "https://dms.rh.tech/api/v1/file?path=E%3A%5CShares%5C...%5CQP-16.1%20Rev03.docx&ticket=Qm9i",
            "markdownUrl": "https://dms.rh.tech/api/v1/file?path=E%3A%5CShares%5C...%5CQP-16.1%20Rev03.md&ticket=Qm9i",
            "markdown": "# Control of documents\n\n- Document ID: QP-16.1\n- Revision: 03\n\n---\n\n## 1. Purpose ...",
            "etag": "\"9f2c41a7be03d5f1\"", "modifiedUtc": "2026-11-15T07:12:04Z", "size": 7431,
            "folder": "E:\\Shares\\01_General\\Quality\\Current_ReadOnly", "customer": "",
            "hasMarkdown": True,
            "files": [{"name": "QP-16.1 Rev03.docx", "path": "E:\\Shares\\...", "size": 182144},
                      {"name": "QP-16.1 Rev03.md", "path": "E:\\Shares\\...", "size": 7431}]}],
        "count": 1},
    "/api/v1/structure": {
        "departments": [{"name": "Quality", "label": "Quality", "path": "E:\\Shares\\01_General\\Quality",
                         "kpis": "E:\\Shares\\01_General\\Quality\\KPIs", "kpisExists": True}],
        "customers": [{"name": "Elbit", "path": "E:\\Shares\\02_Customers\\Elbit",
                       "kpis": "E:\\Shares\\02_Customers\\Elbit\\KPIs", "kpisExists": False}],
        "counts": {"departments": 14, "customers": 23}},
}

def _group_of(path: str) -> str:
    for title, pattern, _blurb in GROUPS:
        if re.search(pattern, path):
            return title
    return "The rest"


def spec(app, version: str = "", full: bool = False, base: str = "") -> dict:
    """The document /api/openapi.json serves: what another system talks to. full=True keeps every endpoint
    of the page as well (/api/openapi-all.json), for whoever is working on the DMS itself."""
    doc = get_openapi(title="RH DMS Web API", version=version or app.version,
                      description=DESCRIPTION, routes=app.routes)
    doc.setdefault("components", {})["securitySchemes"] = SECURITY
    if base:
        # Where this DMS answers, so "Try it out" calls the server the reader is reading from and a
        # generated client needs no address written by hand.
        doc["servers"] = [{"url": base.rstrip("/"), "description": "This DMS"}]
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
    for path, example in EXAMPLES.items():
        op = (doc["paths"].get(path) or {}).get("get")
        if not op:
            continue
        ok = op.setdefault("responses", {}).setdefault("200", {"description": "The answer"})
        ok.setdefault("content", {}).setdefault("application/json", {})["example"] = example
    body = (doc["paths"].get("/api/v1/file") or {}).get("get")
    if body:
        ok = body.setdefault("responses", {}).setdefault("200", {"description": "The file itself"})
        ok["description"] = ("The file itself - the Markdown as text/markdown, the document as bytes. With "
                             "If-None-Match the answer is 304 and nothing is sent.")
    used = {op["tags"][0] for ops in doc["paths"].values() for op in ops.values()
            if isinstance(op, dict) and op.get("tags")}
    doc["tags"] = [t for t in doc["tags"] if t["name"] in used]
    if not full:
        named = {k for ops in doc["paths"].values() for op in ops.values() if isinstance(op, dict)
                 for one in (op.get("security") or []) for k in one}
        doc["components"]["securitySchemes"] = {k: v for k, v in SECURITY.items() if k in named}
    return doc
