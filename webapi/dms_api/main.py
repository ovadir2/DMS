"""DMS Web API: browse the repository by customer (what AD allows), save files into it, register
a file and submit it for approval, and see each file's status.

Run:  uvicorn dms_api.main:app --host 0.0.0.0 --port 8080
Docs: /docs (OpenAPI). Page: /dms/dms-page?lang=EN&path=<UNC>&name=<file>
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import blueprint, files, finder
from .ai import AiError, OpenWebUI
from .rag import RagError, RagTools
from .auth import current_user
from .config import WORKFLOW_FOLDERS, Settings
from .security import User
from .sharepoint import SharePoint, SharePointError

STATIC = Path(__file__).resolve().parent / "static"
logger = logging.getLogger("dms_api")


class NewFolderRequest(BaseModel):
    parent: str
    name: str


class RenameRequest(BaseModel):
    path: str
    newName: str


class SubmitRequest(BaseModel):
    approvers: list[str] | None = Field(None, description="Chosen approvers (emails); all must approve. [] = the Approver Matrix; "
                                                          "omitted = the approvers chosen at the last submission (if any)")


class DocRenameRequest(BaseModel):
    newName: str = Field(min_length=1, max_length=200)


class DeleteRequest(BaseModel):
    path: str


class RegisterRequest(BaseModel):
    path: str = Field(description="UNC path of the file, inside the repository root")
    title: str | None = Field(None, description="Defaults to the file name without the extension")
    documentType: str | None = Field(None, description="Defaults to the type of the blueprint folder")
    documentArea: str | None = Field(None, description="Defaults to the area of the blueprint folder")
    controlMode: str | None = None
    documentId: str | None = Field(None, description="Defaults to <prefix>-<item id>, e.g. DMS-00012")
    submit: bool = Field(False, description="Also submit it for approval")
    approvers: list[str] | None = Field(None, description="Chosen approvers (emails); all must approve. Empty: the Approver Matrix")


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    path: str | None = Field(None, description="A repository file to ask about; without it the knowledge bases are used")
    lang: str = "EN"


class RagRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    tool: str = "qms"
    lang: str = "EN"
    new: bool = False                    # start a new conversation


class DecisionRequest(BaseModel):
    approve: bool
    comment: str = Field("", max_length=1000)


class DelegateRequest(BaseModel):
    to: str = Field(description="The person who approves instead (email)")
    on_behalf: str | None = Field(None, alias="from", description="Super users: the waiting approver being replaced")
    comment: str = Field("", max_length=1000)


class ReleaseRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=200)   # files released without workflow (check boxes)


class ShareRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    message: str = Field("", max_length=2000)
    customer: str | None = Field(None, max_length=200)  # only when the file is not under a customer folder
    documentIds: list[int] = Field(default_factory=list, max_length=50)  # more approved documents, same customer folder


class FirstLoadRequest(BaseModel):
    source: str = Field(description="The old repository folder (any path the service can read)")
    target: str = Field(description="The folder under the repository root")
    documentType: str | None = Field(None, description="Empty: each file gets the type of its blueprint folder")
    documentArea: str | None = Field(None, description="Empty: each file gets the area of its blueprint folder")
    controlMode: str | None = None
    dryRun: bool = True
    copyMissing: bool = True
    updateLinks: bool = True
    mode: str = Field("approve", pattern="^(approve|save)$",
                      description="approve: DMS approval simulated, into Current_ReadOnly; save: the files only, no workflow")
    approver: str | None = Field(None, description="approve: recorded as the approver (default DMS_FIRST_LOAD_APPROVER)")


class FindRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    lang: str = "EN"


from contextvars import ContextVar

PAGE_LANG: ContextVar[str] = ContextVar("PAGE_LANG", default="EN")   # the language the user chose on the page

NOTIFY_TEXT = {
    "EN": {"waiting": ("{id} {title} - waiting for your approval", "approvals", '{id} "{title}" is waiting for your approval.'),
           "approved": ("{id} {title} - approved", "workflows", '{id} "{title}" was approved.'),
           "rejected": ("{id} {title} - rejected", "workflows", '{id} "{title}" was rejected: {comment}'),
           "withdrawn": ("{id} {title} - withdrawn", "approvals", '{id} "{title}" was withdrawn and no longer needs your approval.'),
           "test": ("DMS test notification", "", "This is a test of the DMS notifications (DMS Notifications list + DC-P2 flow)."),
           "open": "Open in the DMS"},
    "HE": {"waiting": ("{id} {title} - ממתין לאישורך", "approvals", 'המסמך {id} "{title}" ממתין לאישורך.'),
           "approved": ("{id} {title} - אושר", "workflows", 'המסמך {id} "{title}" אושר.'),
           "rejected": ("{id} {title} - נדחה", "workflows", 'המסמך {id} "{title}" נדחה: {comment}'),
           "withdrawn": ("{id} {title} - נמשך", "approvals", 'המסמך {id} "{title}" נמשך ואינו ממתין עוד לאישורך.'),
           "test": ("הודעת בדיקה מה-DMS", "", "זוהי הודעת בדיקה של התראות ה-DMS (רשימת DMS Notifications וזרימת DC-P2)."),
           "open": "פתיחה ב-DMS"},
}


def answer_lang(question: str, page_lang: str) -> str:
    """Answer in the language of the question (a Hebrew question gets a Hebrew answer on the English page too)."""
    if any("\u0590" <= ch <= "\u05ff" for ch in question):
        return "HE"
    return "HE" if page_lang.upper() == "HE" and not any(ch.isascii() and ch.isalpha() for ch in question) else "EN"


def create_app(settings: Settings | None = None, sharepoint: SharePoint | None = None, ai: OpenWebUI | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    app = FastAPI(title="RH DMS Web API", version="1.1")
    app.state.settings = s
    files.set_short_paths(s.repository_root, s.short_paths)
    own_register = sharepoint is None                            # False in the tests (they pass their own)
    if sharepoint is None and s.sharepoint == "memory":
        from .memory import MemorySharePoint
        sharepoint = MemorySharePoint(s)
    if sharepoint is None and s.sharepoint != "memory" and s.sp_auth == "interactive":
        sharepoint = SharePoint(s)
        account = sharepoint.sign_in()                          # pilot on a PC: opens the browser the first time
        logger.info("SharePoint: signed in as %s", account)
        if s.auth_mode == "dev" and not s.dev_user and account:
            s.dev_user = account                                # you are the DMS user too
    app.state.sp = sharepoint or SharePoint(s)
    if s.file_service_seconds > 0:
        from . import file_service
        file_service.start(app.state.sp, s)
    if own_register:
        from . import exchange_expiry
        exchange_expiry.start(app.state.sp, s)
    app.state.ai = ai or OpenWebUI(s)
    app.state.rag = RagTools(s)
    from .filelinker import FileLinker
    app.state.linker = FileLinker(s)
    @app.middleware("http")
    async def office_dav_discovery(request: Request, call_next):
        """Office asks the server and the folders above a file whether they speak WebDAV (OPTIONS / PROPFIND)
        before it opens a DMS link for editing; without these answers Word opens it read only."""
        from fastapi.responses import Response
        path = request.url.path
        office = path.startswith(("/api/o", "/_vti")) or request.method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD")
        if office:                                              # what Word / Excel ask: logs\office.log (support)
            response = await _office(request, call_next, path)
            try:
                os.makedirs(os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs"), exist_ok=True)
                with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "office.log"), "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {request.method} {path} -> {response.status_code}"
                            f" | {request.headers.get('user-agent', '')[:80]}\n")
            except OSError:
                pass
            return response
        return await call_next(request)

    async def _office(request: Request, call_next, path: str):
        from urllib.parse import quote, unquote
        from fastapi.responses import Response
        dav = {"DAV": "1,2", "MS-Author-Via": "DAV", "Allow": "OPTIONS, GET, HEAD, PROPFIND, LOCK, UNLOCK, PUT"}
        is_file = path.startswith("/api/o/") and path.count("/") >= 4 and not path.endswith("/")
        if request.method == "OPTIONS" and not is_file and "access-control-request-method" not in request.headers:   # not a CORS preflight
            return Response(status_code=200, headers=dav)
        if request.method == "PROPFIND" and not is_file:
            body = ('<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:"><D:response>'
                    f"<D:href>{quote(unquote(path), safe='/')}</D:href><D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype>"
                    "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response></D:multistatus>")
            return Response(body, status_code=207, media_type='text/xml; charset="utf-8"', headers=dav)
        return await call_next(request)

    @app.middleware("http")
    async def page_language(request: Request, call_next):
        """The page sends its language (X-DMS-Lang); notifications are written in it."""
        token = PAGE_LANG.set("HE" if (request.headers.get("x-dms-lang") or "").upper() == "HE" else "EN")
        from .config import _short_paths
        local = (request.client.host if request.client else "") in ("127.0.0.1", "::1", "localhost", "testclient")
        drives = files.user_drives(_short_paths(request.headers.get("x-dms-drives") or ""), local)   # the user's drive letters
        base = files.BASE_URL.set(str(request.base_url))
        opener = files.OPENER.set(request.headers.get("x-dms-opener") == "1")
        try:
            return await call_next(request)
        finally:
            files.OPENER.reset(opener)
            files.BASE_URL.reset(base)
            files.USER_SHORT.reset(drives)
            PAGE_LANG.reset(token)

    @app.middleware("http")
    async def remote_signin(request: Request, call_next):
        """Pilot on a PC (dev mode): another PC signs in with its own Windows account (ntlm.py)."""
        from fastapi.responses import Response
        from starlette.concurrency import run_in_threadpool
        from . import ntlm
        if (s.auth_mode != "dev" or s.remote_signin != "ntlm" or ntlm.is_local(request)
                or request.method == "OPTIONS" or request.url.path == "/api/health"):
            return await call_next(request)
        ask = Response("Sign in with your Windows account (RH\\name).", status_code=401,
                       headers={"WWW-Authenticate": "NTLM"}, media_type="text/plain")
        conn = ntlm.connection(request)
        who = ntlm.from_cookie(request.cookies.get(ntlm.COOKIE, "")) or ntlm.signed_in(conn)
        fresh = False
        scheme, _, data = request.headers.get("authorization", "").partition(" ")
        if not who and scheme.lower() == "ntlm" and data:
            import base64
            try:
                challenge, account = await run_in_threadpool(ntlm.accept, conn, base64.b64decode(data))
            except Exception as e:  # noqa: BLE001 - wrong password, unknown account: ask again
                logging.getLogger("dms_api").warning("Windows sign-in from %s refused: %s", conn[0], e)
                return ask
            if challenge:
                return Response(status_code=401, headers={"WWW-Authenticate": "NTLM " + base64.b64encode(challenge).decode("ascii")})
            from .security import upn_of
            who, fresh = ((upn_of(account) or account).lower(), account), True
            ntlm.remember(conn, *who)
            logging.getLogger("dms_api").info("Windows sign-in from %s: %s (%s)", conn[0], who[0], account)
        if not who:
            return ask
        request.state.remote_user = who
        response = await call_next(request)
        if fresh:
            response.set_cookie(ntlm.COOKIE, ntlm.cookie_for(*who), max_age=ntlm.HOURS * 3600, httponly=True, samesite="lax")
        return response

    if s.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=s.allowed_origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

    status_key = {v: k for k, v in s.choices.items() if k in ("Working", "Submitted", "Approved_ReadOnly")}

    def sp() -> SharePoint:
        return app.state.sp

    def with_key(d: dict) -> dict:
        return {**d, "statusKey": status_key.get(d.get("lifecycleStatus") or "", "Other"),
                "noWorkflow": bool(d.get("controlMode")) and d.get("controlMode") == blueprint.choice("Collaboration", sp().choices("ControlMode"))}

    def register_index() -> dict[str, dict]:
        idx: dict[str, dict] = {}
        for d in sp().documents():
            for p in (d.get("workingUncPath"), d.get("currentUncPath")):
                if p:
                    idx[os.path.normcase(os.path.normpath(p))] = d
        return idx

    def find_registered(path: str, idx: dict[str, dict]) -> dict | None:
        for c in files.candidate_register_paths(path):
            d = idx.get(os.path.normcase(os.path.normpath(c)))
            if d:
                return d
        return None

    @app.exception_handler(files.PathNotAllowed)
    async def _path(_: Request, e: files.PathNotAllowed):
        return JSONResponse({"detail": f"Path is outside the controlled repository: {e}"}, status_code=403)

    from collections import deque
    app.state.sp_errors = deque(maxlen=30)               # the last SharePoint errors, for the SharePoint check
    app.state.notify_log = deque(maxlen=20)              # the last notifications (written, skipped, failed)

    def sp_error(what: str, e: Exception) -> None:
        app.state.sp_errors.appendleft({"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "what": what, "error": str(e)[:400]})

    @app.exception_handler(SharePointError)
    async def _sp(request: Request, e: SharePointError):
        sp_error(f"{request.method} {request.url.path}", e)
        return JSONResponse({"detail": f"SharePoint: {e}"}, status_code=502)

    # ------------------------------------------------------------------ public
    def _version() -> str:
        """The git commit this DMS runs (to check that a pull + restart took effect)."""
        import subprocess
        try:
            return subprocess.run(["git", "-C", os.path.dirname(os.path.abspath(__file__)), "rev-parse", "--short", "HEAD"],
                                  capture_output=True, text=True, timeout=5).stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            return "unknown"
    version = _version()
    logger.info("DMS version %s", version)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": version, "repositoryRoot": s.repository_root,
                "rootReachable": os.path.isdir(s.repository_root)}

    @app.get("/api/client-config")
    def client_config():
        return {"authMode": s.auth_mode, "playground": s.sharepoint == "memory", "notify": s.approvals == "page" and s.notify, "fileService": s.file_service_seconds > 0, "firstLoadApprover": s.first_load_approver, "shareDays": s.ex_days, "customersFolder": s.customers_folder, "root": s.repository_root, "shortPaths": [[os.path.join(s.repository_root, k), v] for k, v in s.short_paths.items()],
                "approvals": s.approvals, "fileLinker": bool(s.fl_check_url and s.fl_update_url),
                "site": s.site_url if s.sharepoint != "memory" else "", "tenantId": s.tenant_id, "clientId": s.spa_client_id,
                "scope": s.api_scope,
                "repositoryRoot": s.repository_root, "delegationDays": s.delegation_days}

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/dms/dms-page?lang=EN")

    @app.get("/dms/logo.png", include_in_schema=False)
    def logo():
        """The company logo: put logo.png in dms_api/static (a drawn "rh" is shown without it)."""
        f = STATIC / "logo.png"
        if not f.exists():
            raise HTTPException(404)
        return FileResponse(f)

    @app.get("/dms/dms-page", include_in_schema=False)
    def page():
        return FileResponse(STATIC / "dms-page.html", media_type="text/html; charset=utf-8")

    # ------------------------------------------------------------------ signed in
    def customers_root() -> str:
        return os.path.join(s.repository_root, s.customers_folder)

    def search_roots() -> list[str]:
        """The user areas of the repository (01_General, 02_Customers, ...), without the system folders."""
        try:
            return [e.path for e in sorted(os.scandir(s.repository_root), key=lambda e: e.name)
                    if e.is_dir() and e.name not in blueprint.HIDDEN_AT_ROOT and not files.is_hidden(e)]
        except OSError:
            return [customers_root()]

    def doc_path(d: dict) -> str | None:
        return d.get("currentUncPath") or d.get("workingUncPath")

    def visible(d: dict, user: User) -> bool:
        p = doc_path(d)
        try:
            return bool(p) and user.can(files.resolve(s.repository_root, p))
        except files.PathNotAllowed:
            return False

    def is_admin(user: User) -> bool:
        return user.email in s.admins or pilot_owner(user.email)

    def pilot_owner(email: str) -> bool:
        """The live pilot on a PC (dev mode, real SharePoint): the person who runs the DMS is always a super user."""
        return s.auth_mode == "dev" and s.sp_auth == "interactive" and email == (s.dev_user or "").lower()

    @app.get("/api/diagnostics/sharepoint")
    def sp_check(user: User = Depends(current_user)):
        """Super users: the DMS lists in SharePoint (exists, items, may this account add), and the last errors."""
        if not is_admin(user):
            raise HTTPException(403, "Only a DMS super user can run the SharePoint check")
        from .sharepoint import AUDIT, DECISIONS, DELEGATIONS, MATRIX, NOTIFY, REGISTER
        lists = [sp().list_info(rel) for rel in (REGISTER, AUDIT, MATRIX, NOTIFY, DECISIONS, DELEGATIONS)]
        return {"site": s.site_url if s.sharepoint != "memory" else "memory (playground)", "account": user.email,
                "auth": s.sp_auth, "lists": lists, "errors": list(app.state.sp_errors),
                "notifications": {"on": s.approvals == "page" and s.notify, "approvals": s.approvals, "notify": s.notify,
                                  "pageUrl": s.page_url, "last": list(app.state.notify_log)}}

    @app.post("/api/diagnostics/clear-errors")
    def clear_errors(user: User = Depends(current_user)):
        """Super users: empty the list of last SharePoint errors (it also empties at every restart)."""
        if not is_admin(user):
            raise HTTPException(403, "Only a DMS super user can clear the errors")
        app.state.sp_errors.clear()
        return {"errors": 0}

    @app.post("/api/diagnostics/notify-test")
    def notify_test(user: User = Depends(current_user)):
        """Super users: write one test row to DMS Notifications, addressed to themselves (the DC-P2 flow sends it)."""
        if not is_admin(user):
            raise HTTPException(403, "Only a DMS super user can send a test notification")
        subject, body, link = notify_text("test", "TEST", "")
        sp().notify(to=[user.email], subject=subject, body=body, link=link, ref="TEST")
        app.state.notify_log.appendleft({"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "test",
                                         "doc": "TEST", "to": [user.email], "result": "written to DMS Notifications"})
        return {"to": user.email}

    @app.get("/api/people")
    def people(q: str = Query(..., min_length=2), _: User = Depends(current_user)):
        """People in the company directory, for choosing approvers (SharePoint people picker)."""
        return sp().people(q)

    @app.get("/api/people/list")
    def people_list(_: User = Depends(current_user)):
        """The list to choose approvers from: all RH Microsoft 365 users (people search); if the directory
        cannot be read, the people of the DocumentControl site. The DMS super users are always in it."""
        try:
            people = sp().directory_people()
        except Exception as e:  # noqa: BLE001 - fall back to the site's people
            logger.warning("directory people not read: %s", e)
            sp_error("Company directory (people search)", e)
            people = []
        if not people:
            people = sp().site_people()
        out = {p["email"]: p for p in people}
        for a in s.admins:
            out.setdefault(a, {"email": a, "name": a.split("@")[0], "title": ""})
        return sorted(out.values(), key=lambda p: p["name"].lower())

    @app.get("/api/approver-rule")
    def approver_rule_view(documentType: str, _: User = Depends(current_user)):
        """Who the Approver Matrix sends this document type to (the default when nobody is chosen)."""
        r = rule_for(documentType)
        return {"mandatory": (r or {}).get("mandatory", []), "final": (r or {}).get("final"), "fallback": bool((r or {}).get("fallback"))}

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        out = {"email": user.email, "name": user.name, "admin": is_admin(user), "actingFrom": user.acting_from}
        if is_admin(user) or user.acting_from:                  # super users: "Acting as" in the ⋮ menu
            real = user.acting_from or user.email
            out["actingUsers"] = [real, *[u for u in s.dev_users if u != real]]
        return out

    @app.get("/api/options")
    def options(_: User = Depends(current_user)):
        return {f: sp().choices(f) for f in ("DocumentType", "DocumentArea", "ControlMode")}

    def classify(folder: str) -> dict:
        """Document type, area and control mode inherited from the blueprint folder, as the site's choice values."""
        bp = blueprint.classify(rel_parts(folder))
        typ = blueprint.choice(bp["type"], sp().choices("DocumentType"))
        mode = blueprint.choice("Workflow Required", sp().choices("ControlMode")) if typ else None
        return {"documentType": typ, "documentArea": blueprint.choice(bp["area"], sp().choices("DocumentArea")), "controlMode": mode}

    @app.get("/api/classify")
    def classify_folder(path: str, _: User = Depends(current_user)):
        """What a file saved in this folder (or this file) inherits from the blueprint."""
        full = files.resolve(s.repository_root, path)
        return classify(full if os.path.isdir(full) else os.path.dirname(full))

    @app.get("/api/customers")
    def customers(q: str = "", user: User = Depends(current_user)):
        """Customer folders the user may open (AD), optionally filtered by name."""
        try:
            listing = files.list_folder(s.repository_root, customers_root(), user.can)
        except (FileNotFoundError, PermissionError):
            return []
        return [{"name": f["name"], "path": f["path"]} for f in listing["folders"] if q.lower() in f["name"].lower()]

    def rel_parts(path: str) -> list[str]:
        rel = os.path.relpath(path, s.repository_root)
        return [] if rel == "." else [x for x in rel.replace("\\", "/").split("/") if x]

    def context_of(parts: list[str]) -> dict:
        """The customer and project folders a path is in (blueprint: 02_Customers\\<c>\\Projects\\<p>)."""
        ctx = {"customer": None, "project": None}
        if len(parts) >= 2 and parts[0].lower() == s.customers_folder.lower():
            ctx["customer"] = {"name": parts[1], "path": os.path.join(s.repository_root, *parts[:2])}
            k = blueprint.product_index(parts)
            if k is not None:
                ctx["project"] = {"name": parts[k], "path": os.path.join(s.repository_root, *parts[:k + 1])}
        return ctx

    def child_folders(parts: list[str], user: User) -> list[dict]:
        """Subfolders of a folder for the cascading selectors: AD-filtered, in blueprint order,
        without system and workflow folders."""
        folder = os.path.join(s.repository_root, *parts)
        try:
            entries = [e for e in os.scandir(folder) if e.is_dir() and not files.is_hidden(e)]
        except OSError:
            return []
        rank = {n.lower(): i for i, n in enumerate(blueprint.order(parts))}
        out = [{"name": e.name, "path": e.path, "label": blueprint.describe(parts + [e.name])} for e in entries
               if e.name not in WORKFLOW_FOLDERS and not (not parts and e.name in blueprint.HIDDEN_AT_ROOT) and user.can(e.path)]
        return sorted(out, key=lambda f: (rank.get(f["name"].lower(), len(rank)), f["name"].lower()))

    # ------------------------------------------------------------------ path finder (blueprint, including missing folders)
    def _node_missing(parts: list[str]) -> bool:
        """True when a path that does not exist is not a blueprint path either."""
        return blueprint.describe(parts) is None and not all(
            p.lower() in [n.lower() for n in blueprint.order(parts[:i])] for i, p in enumerate(parts) if i)
    @app.get("/api/pathfinder")
    def pathfinder(path: str | None = None, user: User = Depends(current_user)):
        """The options for the next level under `path`: the folders that exist (AD-filtered) plus the
        blueprint folders that do not exist yet ("exists": false). Customers and projects (the "*"
        levels of the blueprint) are offered only when they exist."""
        parts = rel_parts(files.resolve(s.repository_root, path)) if path else []
        folder = os.path.join(s.repository_root, *parts)
        exists = not parts or os.path.isdir(folder)
        if not exists and _node_missing(parts):
            raise HTTPException(404, "Not a blueprint folder")
        existing = {f["name"].lower(): f for f in child_folders(parts, user)} if exists else {}
        out = list(existing.values())
        for name in blueprint.order(parts):
            if name.lower() not in existing and not (not parts and name in blueprint.HIDDEN_AT_ROOT):
                out.append({"name": name, "path": os.path.join(folder, name), "label": blueprint.describe(parts + [name]), "exists": False})
        for f in out:
            f.setdefault("exists", True)
        rank = {n.lower(): i for i, n in enumerate(blueprint.order(parts))}
        out.sort(key=lambda f: (rank.get(f["name"].lower(), len(rank)), f["name"].lower()))
        node = blueprint.describe(parts) if parts else None
        return {"path": folder, "relative": os.path.relpath(folder, s.repository_root) if parts else "", "node": node,
                "exists": exists, "canWrite": exists and user.can(folder, "write"), "options": out}

    @app.post("/api/pathfinder/create", status_code=201)
    def pathfinder_create(path: str, user: User = Depends(current_user)):
        """Create the missing folders of a blueprint path. Every new folder must be one the blueprint
        expects at its level, and the user needs write permission on the deepest folder that exists."""
        full = files.resolve(s.repository_root, path)
        parts = rel_parts(full)
        existing = s.repository_root
        for i, p in enumerate(parts):
            nxt = os.path.join(existing, p)
            if os.path.isdir(nxt):
                existing = nxt
                continue
            for j in range(i, len(parts)):
                if parts[j].lower() not in [n.lower() for n in blueprint.order(parts[:j])]:
                    raise HTTPException(400, f"'{parts[j]}' is not a blueprint folder at this level")
            break
        if not user.can(existing, "write"):
            raise HTTPException(403, "You do not have permission to create folders here")
        os.makedirs(full, exist_ok=True)
        log(user, "new-folder", full)
        return {"path": full, "canWrite": user.can(full, "write")}

    @app.get("/api/levels")
    def levels(path: str | None = None, user: User = Depends(current_user)):
        """One selector per level of the tree, from the root down to `path`, plus the next level:
        [{selected, options}]. Choosing an option in one level gives the options of the next."""
        parts = rel_parts(files.resolve(s.repository_root, path)) if path else []
        out = []
        for i in range(len(parts) + 1):
            options = child_folders(parts[:i], user)
            if not options:
                break
            out.append({"selected": parts[i] if i < len(parts) else None, "options": options})
        return out

    def holds_share_log(full: str) -> bool:
        """The customer's share log (02_Customers\\<c>\\Shared\\DMS-Shared-Log.csv), or a folder holding it:
        kept by the DMS, read only for everyone (no rename, delete, overwrite or workflow)."""
        if not s.shared_log:
            return False
        parts = s.shared_log.replace("\\", "/").split("/")
        if os.path.basename(full).lower() == parts[-1].lower():
            p = rel_parts(full)
            return len(p) == 2 + len(parts) and p[0].lower() == s.customers_folder.lower()
        return os.path.isdir(full) and any(os.path.isfile(os.path.join(full, *parts[i:])) for i in range(len(parts)))

    def in_shared_folder(full: str) -> bool:
        """Inside a customer's Shared folder (02_Customers\\<c>\\Shared): copies already sent, not workflowed."""
        if not s.shared_log or "/" not in s.shared_log.replace("\\", "/"):
            return False
        shared = s.shared_log.replace("\\", "/").split("/")[0].lower()
        p = rel_parts(full)
        return len(p) >= 3 and p[0].lower() == s.customers_folder.lower() and p[2].lower() == shared

    @app.get("/api/browse")
    def browse(path: str | None = None, user: User = Depends(current_user)):
        try:
            result = files.list_folder(s.repository_root, path, user.can)
        except FileNotFoundError:
            raise HTTPException(404, "Folder not found") from None
        except PermissionError:
            raise HTTPException(403, "You do not have access to this folder") from None
        parts = rel_parts(result["path"])
        if not parts:
            result["folders"] = [f for f in result["folders"] if f["name"] not in blueprint.HIDDEN_AT_ROOT]
        rank = {n.lower(): i for i, n in enumerate(blueprint.order(parts))}
        for f in result["folders"]:
            f["label"] = blueprint.describe(parts + [f["name"]])
        result["folders"].sort(key=lambda f: (rank.get(f["name"].lower(), len(rank)), f["name"].lower()))
        result["node"] = blueprint.describe(parts)
        result["trail"] = [{"name": p, "path": os.path.join(s.repository_root, *parts[: i + 1]),
                            "label": blueprint.describe(parts[: i + 1])} for i, p in enumerate(parts)]
        result["context"] = context_of(parts)
        idx = register_index()
        from . import noworkflow
        nw = noworkflow.marked(s.repository_root)
        for f in result["files"]:
            d = find_registered(f["path"], idx)
            f["document"] = with_key(d) if d else None
            if noworkflow.is_marked(s.repository_root, f["path"], nw):
                f["noWorkflow"] = True
            if holds_share_log(f["path"]) or in_shared_folder(f["path"]):
                f.update(readOnly=True, system=True, noWorkflow=True)   # open (view), download, copy path only
            elif (f.get("officeUri") and not f.get("readOnly") and not files.in_workflow_folder(s.repository_root, f["path"])
                  and (not d or d.get("lifecycleStatus") == s.choices["Working"]) and user.can(f["path"], "write")):
                # not yet registered (or still in Working): opens in Word / Excel / PowerPoint for editing
                f.update(officeUri=files.office_uri(f["path"], edit=True), editable=True)
        if in_shared_folder(os.path.join(result["path"], "x")):
            result.update(noWorkflow=True, canWrite=False, sharedNote=True)
        return result

    @app.get("/api/areas")
    def areas(user: User = Depends(current_user)):
        """The top of the tree the user may open: Customers and Management."""
        out = []
        for key in blueprint.ROOT:
            path = os.path.join(s.repository_root, key)
            if os.path.isdir(path) and user.can(path):
                out.append({"name": key, "path": path, "label": blueprint.describe([key])})
        return out

    @app.get("/api/projects")
    def projects(customer: str, user: User = Depends(current_user)):
        """Project folders of one customer that the user may open."""
        folder = os.path.join(files.resolve(s.repository_root, customer), *blueprint.PRODUCTS)
        try:
            listing = files.list_folder(s.repository_root, folder, user.can)
        except (FileNotFoundError, PermissionError):
            return []
        return [{"name": f["name"], "path": f["path"]} for f in listing["folders"]]

    @app.get("/api/guide")
    def guide(_: User = Depends(current_user)):
        """"What are you saving?" - the document kinds and where each belongs in the blueprint tree."""
        return [{"key": k, "en": en, "he": he, "needsProject": t.startswith("{p}")} for k, en, he, t in blueprint.SAVE_GUIDE]

    @app.get("/api/guide/target")
    def guide_target(key: str, customer: str, project: str | None = None, user: User = Depends(current_user)):
        """The folder for one kind of document, for a customer (and project). It may not exist yet."""
        entry = next((g for g in blueprint.SAVE_GUIDE if g[0] == key), None)
        if not entry:
            raise HTTPException(404, "Unknown document kind")
        template = entry[3]
        if template.startswith("{p}") and not project:
            raise HTTPException(400, "Choose a project first")
        base = files.resolve(s.repository_root, project if template.startswith("{p}") else customer)
        target = files.resolve(s.repository_root, os.path.join(base, *template[4:].split("/")))
        exists = os.path.isdir(target)
        return {"path": target, "exists": exists, "canWrite": exists and user.can(target, "write")}

    @app.get("/api/search")
    def search(q: str = Query(..., min_length=2), scope: str = Query("all", description="all | customer | project | document | file | quick (customers, folders, documents)"),
               customer: str | None = Query(None, description="Customer folder path, to search inside one customer"),
               limit: int | None = Query(None, ge=1, le=500, description="At most this many results (suggestions while typing)"),
               user: User = Depends(current_user)):
        """Customers, folders, registered documents (Document ID, title, type, file name) and file names the
        user may see, in the whole repository. Several words match in any order. An exact Document ID comes first."""
        out: list[dict] = []
        cap = min(limit or s.search_limit, s.search_limit)
        words = q.lower().split()
        seen: set[str] = set()
        if scope in ("all", "customer", "quick"):
            out += [{"kind": "customer", **c} for c in customers(q, user)]
        if scope in ("all", "document", "quick"):
            docs = []
            for d in sp().documents():
                if d.get("lifecycleStatus") == s.choices["Archived"]:
                    continue
                path = doc_path(d) or ""
                hay = " ".join([d.get("documentId") or "", d.get("title") or "", d.get("documentType") or "",
                                os.path.basename(path.replace("\\", "/"))]).lower()
                if all(w in hay for w in words) and visible(d, user):
                    exact = (d.get("documentId") or "").lower() == q.strip().lower()
                    docs.append((not exact, {"kind": "document", "name": d.get("title"), "path": path, "document": with_key(d)}))
                    seen.add(os.path.normcase(path))
            out += [x for _, x in sorted(docs, key=lambda t: t[0])]
        starts = [files.resolve(s.repository_root, customer)] if customer else search_roots()
        if scope in ("all", "project", "file", "quick"):
            idx = register_index()
            left = cap - len(out)
            for start in [p for p in starts if os.path.isdir(p)]:
                for hit in files.walk_search(start, q, user.can, left, folders_only=scope == "project"):
                    left -= 1
                    if hit["isFolder"]:
                        out.append({"kind": "folder", **hit})
                    elif os.path.normcase(hit["path"]) not in seen:
                        d = find_registered(hit["path"], idx)
                        out.append({"kind": "file", **hit, "document": with_key(d) if d else None})
                if left <= 0:
                    break
        return out[:cap]

    @app.post("/api/guide/create", status_code=201)
    def guide_create(key: str, customer: str, project: str | None = None, user: User = Depends(current_user)):
        """Create the blueprint folder for a document kind when it is missing (the user needs write
        permission on the deepest folder that exists)."""
        t = guide_target(key, customer, project, user)
        if t["exists"]:
            return t
        existing = t["path"]
        while not os.path.isdir(existing):
            existing = os.path.dirname(existing)
        if not user.can(existing, "write"):
            raise HTTPException(403, "You do not have permission to create this folder")
        os.makedirs(t["path"], exist_ok=True)
        log(user, "new-folder", t["path"])
        return {"path": t["path"], "exists": True, "canWrite": user.can(t["path"], "write")}

    @app.post("/api/files/upload", status_code=201)
    def upload(folder: str = Form(...), file: UploadFile = File(...), overwrite: bool = Form(False),
               noWorkflow: bool = Form(False), user: User = Depends(current_user)):
        """Save a file from the user's PC into a folder of the repository (the user needs write access there)."""
        target_dir = files.resolve(s.repository_root, folder)
        if not os.path.isdir(target_dir):
            raise HTTPException(404, "Folder not found")
        if files.in_workflow_folder(s.repository_root, target_dir):
            raise HTTPException(403, "Workflow folders are managed by the DMS")
        if not user.can(target_dir, "write"):
            raise HTTPException(403, "You do not have permission to save files in this folder")
        if in_shared_folder(os.path.join(target_dir, "x")):
            raise HTTPException(403, "The customer's Shared folder is kept by the DMS (read only)")
        from . import noworkflow
        if noWorkflow:                                             # straight to Current_ReadOnly: never over a controlled document
            there = os.path.join(target_dir, "Current_ReadOnly", os.path.basename((file.filename or "").replace("\\", "/")))
            if os.path.exists(there) and find_registered(there, register_index()) and not noworkflow.is_marked(s.repository_root, there):
                raise HTTPException(409, "A controlled document with this name is in Current_ReadOnly: use New revision")
        try:
            path = files.save_upload(s.repository_root, target_dir, file.filename or "", file.file,
                                     s.max_upload_mb * 1024 * 1024, overwrite, released=noWorkflow)
        except FileExistsError:
            raise HTTPException(409, "A file with this name already exists in the folder") from None
        except (ValueError, PermissionError) as e:
            raise HTTPException(400, str(e)) from None
        traced = None
        if noWorkflow:
            noworkflow.mark(s.repository_root, path)               # released as is, read only: no Start workflow for it
            try:                                                   # traced in SharePoint: Document Register + Control Audit
                noworkflow.release(sp(), s, path, user.email, "Save file (no workflow) on the DMS page", classify)
            except Exception as e:  # noqa: BLE001 - the file is saved; the trace error is reported
                traced = str(e)
                logger.warning("no-workflow trace failed for %s: %r", path, e)
        log(user, "upload", path + (" (no workflow)" if noWorkflow else ""))
        d = find_registered(path, register_index())
        return {"name": os.path.basename(path), "path": path, "document": with_key(d) if d else None,
                **({"traceError": traced} if traced else {})}

    def registered_inside(path: str) -> dict | None:
        """A registered document at this path or below it (a folder holding controlled files)."""
        base = os.path.normcase(os.path.normpath(path))
        for d in sp().documents():
            for p in (d.get("workingUncPath"), d.get("currentUncPath")):
                n = os.path.normcase(os.path.normpath(p)) if p else ""
                if n and (n == base or n.startswith(base + os.sep)):
                    return d
        return None

    FILE_OPS = {"upload", "new-folder", "rename", "delete"}
    AI_OPS = {"ai-ask", "ai-find", "ai-chat", "ai-rag"}      # AI Insights questions, CorrelationId AI

    def log(user: User, action: str, detail: str) -> None:
        """Service log; repository changes (upload, new folder, rename, delete) also go to Control Audit
        in SharePoint (CorrelationId FS), so every change is kept there with who and when."""
        logger.info("%s %s %s", user.email, action, detail)
        if action in FILE_OPS or action in AI_OPS:
            root = s.repository_root.rstrip("\\/")
            short = detail.replace(root + os.sep, "").replace(root + "/", "").replace(root + "\\", "")
            try:
                sp().audit(document_id="AI" if action in AI_OPS else "FS", event=s.choices["FileDone"], from_status="",
                           to_status="", actor=user.email, details=f"{action}: {short}")
            except Exception as e:  # noqa: BLE001 - the change itself is done; do not fail the request
                logger.warning("audit row not written for %s: %s", action, e)
                sp_error(f"Control Audit row ({action})", e)

    @app.post("/api/files/release")
    def release_files(req: ReleaseRequest, user: User = Depends(current_user)):
        """Selected files released without workflow, like Save file (no workflow): each goes to Current_ReadOnly in
        its folder, read only, registered in SharePoint (approved by DMS, Collaboration, SHA-256); can be shared."""
        from . import noworkflow
        from .file_service import _move, _set_read_only
        idx = register_index()
        out = []
        for p in req.paths:
            full = files.resolve(s.repository_root, p)
            folder, name = os.path.dirname(full), os.path.basename(full)
            try:
                if not os.path.isfile(full):
                    raise ValueError("file not found")
                if os.path.basename(folder) in WORKFLOW_FOLDERS or files.in_workflow_folder(s.repository_root, folder):
                    raise ValueError("already in a DMS workflow folder")
                if find_registered(full, idx):
                    raise ValueError("already registered (use its workflow)")
                if not (user.can(full, "write") and user.can(folder, "write")):
                    raise ValueError("no permission")
                target = os.path.join(folder, "Current_ReadOnly", name)
                if os.path.exists(target):
                    raise ValueError("a file with this name is already in Current_ReadOnly")
                target = _move(full, target)
                _set_read_only(target, True)
                noworkflow.mark(s.repository_root, target)
                doc = noworkflow.release(sp(), s, target, user.email, "Released without workflow on the DMS page", classify)
                log(user, "release", target)
                out.append({"path": p, "ok": True, "documentId": doc.get("documentId"), "target": target})
            except (ValueError, OSError, SharePointError) as e:
                out.append({"path": p, "ok": False, "error": str(e)})
        return {"results": out}

    @app.post("/api/folders", status_code=201)
    def new_folder(req: NewFolderRequest, user: User = Depends(current_user)):
        parent = files.resolve(s.repository_root, req.parent)
        if files.in_workflow_folder(s.repository_root, parent):
            raise HTTPException(403, "Workflow folders are managed by the DMS")
        if in_shared_folder(os.path.join(parent, "x")):
            raise HTTPException(403, "The customer's Shared folder is kept by the DMS (read only)")
        if not user.can(parent, "write"):
            raise HTTPException(403, "You do not have permission to create folders here")
        try:
            path = files.make_folder(s.repository_root, parent, req.name)
        except FileExistsError:
            raise HTTPException(409, "A folder with this name already exists") from None
        except FileNotFoundError:
            raise HTTPException(404, "Folder not found") from None
        # a new customer or a new project gets its blueprint folders at once (Appendix A)
        parts, sub = rel_parts(path), []
        if len(parts) == 2 and parts[0].lower() == s.customers_folder.lower():
            sub = blueprint.leaves(blueprint.CUSTOMER)
        elif blueprint.product_index(parts) == len(parts) - 1:
            sub = blueprint.leaves(blueprint.PROJECT)
        for rel in sub:
            os.makedirs(os.path.join(path, *rel), exist_ok=True)
        log(user, "new-folder", f"{path}" + (f" (+{len(sub)} blueprint folders)" if sub else ""))
        return {"name": os.path.basename(path), "path": path, "blueprintFolders": len(sub)}

    @app.post("/api/items/rename")
    def rename(req: RenameRequest, user: User = Depends(current_user)):
        full = files.resolve(s.repository_root, req.path)
        if not (user.can(full, "write") and user.can(os.path.dirname(full), "write")):
            raise HTTPException(403, "You do not have permission to rename this item")
        if os.path.exists(full):
            files.check_editable(s.repository_root, full, s.protected_depth)   # workflow folders first: clearest reason
        if holds_share_log(full) or in_shared_folder(full):
            raise HTTPException(403, "The customer's Shared folder is kept by the DMS (read only) and cannot be renamed")
        if (blueprint.describe(rel_parts(full)) or {}).get("kind") not in (None, "project"):   # a project folder is the user's
            raise HTTPException(403, "This folder is part of the company skeleton (blueprint) and cannot be renamed. Its content can.")
        d = registered_inside(full)
        if d:
            raise HTTPException(409, f"It holds a controlled document ({d.get('documentId')}) and cannot be renamed")
        try:
            path = files.rename_item(s.repository_root, full, req.newName, s.protected_depth)
            from . import noworkflow
            noworkflow.moved(s.repository_root, full, path)
        except FileExistsError:
            raise HTTPException(409, "An item with this name already exists") from None
        except FileNotFoundError:
            raise HTTPException(404, "Not found") from None
        except PermissionError as e:
            raise HTTPException(409, str(e)) from None
        log(user, "rename", f"{full} -> {path}")
        return {"name": os.path.basename(path), "path": path}

    @app.post("/api/items/delete")
    def delete(req: DeleteRequest, user: User = Depends(current_user)):
        """Moves the file or folder to the recycle folder (04_Workflow_System\\Recycle), never erases it."""
        full = files.resolve(s.repository_root, req.path)
        if not (user.can(full, "write") and user.can(os.path.dirname(full), "write")):
            raise HTTPException(403, "You do not have permission to delete this item")
        if os.path.exists(full):
            files.check_editable(s.repository_root, full, s.protected_depth)
        if holds_share_log(full) or in_shared_folder(full):
            raise HTTPException(403, "The customer's Shared folder is kept by the DMS (read only) and cannot be deleted")
        if (blueprint.describe(rel_parts(full)) or {}).get("kind") not in (None, "project"):   # a project folder is the user's
            raise HTTPException(403, "This folder is part of the company skeleton (blueprint) and cannot be deleted. Its content can.")
        d = registered_inside(full)
        if d:
            raise HTTPException(409, f"It holds a controlled document ({d.get('documentId')}) and cannot be deleted")
        try:
            moved = files.delete_item(s.repository_root, full, s.protected_depth, user.email)
            from . import noworkflow
            noworkflow.moved(s.repository_root, full, None)
        except FileNotFoundError:
            raise HTTPException(404, "Not found") from None
        except PermissionError as e:
            raise HTTPException(409, str(e)) from None
        log(user, "delete", f"{full} -> {moved}")
        return {"deleted": full, "recycledTo": moved}

    # ------------------------------------------------------------------ approvals on the page (DMS_APPROVALS=page)
    def events_by_doc() -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for e in sp().audit_events():
            out.setdefault(e["documentId"] or "", []).append(e)
        return out

    def file_back(d: dict, status: str) -> None:
        """Withdrawn or rejected: the file returns to its place now (not at the next file service run),
        so it can be edited and submitted again under the same name."""
        from .file_service import return_to_working
        try:
            details = return_to_working(s.repository_root, d.get("workingUncPath"))
        except OSError as e:
            logger.warning("file not returned to Working for %s: %s", d.get("documentId"), e)
            return
        if details:
            sp().audit(document_id=d.get("documentId") or f"ID {d.get('id')}", event=s.choices["FileDone"], from_status=status,
                       to_status=status, actor="RH-DMS-Workflow-Service", details=details, source=s.choices["WorkflowService"])

    DELEGATED = "Delegated: "

    def valid_to(start: date) -> date:
        """The last day of a delegation: start + DMS_DELEGATION_DAYS working days (the weekend not counted)."""
        d, left = start, s.delegation_days
        while left > 0:
            d += timedelta(days=1)
            if d.weekday() not in s.weekend:
                left -= 1
        return d

    def delegations(cycle: list[dict]) -> dict[str, str]:
        """'who -> instead of whom' from the Control Audit rows of the current cycle (oldest first). A delegation
        past its last day no longer counts: the approval returns to the original approver."""
        out: dict[str, str] = {}
        today = datetime.now().date()
        for e in reversed(cycle):
            details = e.get("details") or ""
            try:
                started = datetime.fromisoformat((e.get("utc") or "").replace("Z", "+00:00")).astimezone().date()
            except ValueError:
                started = today
            if valid_to(started) < today:
                continue
            if e["event"] == s.choices["PermissionChanged"] and details.startswith(DELEGATED):
                pair = details[len(DELEGATED):].split(":")[0]
                if " -> " in pair:
                    a, b = (x.strip().lower() for x in pair.split(" -> ", 1))
                    if a and b:
                        out[a] = b.split()[0]                   # "(by …)" after the address is a note
        return out

    def _follow(delegated: dict[str, str], person: str) -> str:
        seen = set()
        while person in delegated and person not in seen:     # a delegate may delegate again
            seen.add(person)
            person = delegated[person]
        return person

    CHOSEN = "Approvers (chosen): "

    def chosen_approvers(submitted: dict | None) -> list[str]:
        """The approvers chosen at submission, kept in the Control Audit 'submitted' row."""
        details = (submitted or {}).get("details") or ""
        if CHOSEN not in details:
            return []
        part = details.split(CHOSEN, 1)[1].split("\n")[0]
        return [x.strip().lower() for x in part.split(";") if "@" in x]

    def clean_approvers(emails: list[str] | None) -> list[str]:
        out = []
        for e in emails or []:
            e = (e or "").strip().lower()
            if not re.fullmatch(r"[^@\s;]+@[^@\s;]+\.[^@\s;]+", e):
                raise HTTPException(400, f"Not an email address: {e!r}")
            if e not in out:
                out.append(e)
        return out[:20]

    def rule_for(document_type: str) -> dict | None:
        """The Approver Matrix rule; a type without an active rule is approved by the super users (pilot)."""
        rule = sp().approver_rule(document_type)
        if not rule and s.admins:
            rule = {"mandatory": [], "final": s.admins[0], "fallback": True}
        return rule

    RETURNED = "Stage 1 returned with remarks: "

    def approval_state(d: dict, events: list[dict], rules: dict) -> dict:
        """Where a submitted document stands, by the DC-P1 rules: stage 1 = every mandatory approver,
        stage 2 = the final approver. Decisions of the current cycle are the audit rows after the last submission."""
        c = s.choices
        cycle, submitted = [], None
        for e in events:                                        # newest first
            if e["event"] in (c["SubmittedEvent"], c["RejectedEvent"], c["Cancelled"]):
                submitted = e if e["event"] == c["SubmittedEvent"] else None
                break
            cycle.append(e)
        chosen = chosen_approvers(submitted)
        t = d.get("documentType") or ""
        if chosen:                                              # chosen at submission: all of them, one stage
            rule = {"mandatory": chosen, "final": None, "chosen": True}
        else:
            if t not in rules:
                rules[t] = rule_for(t)
            rule = rules[t]
        if not rule:
            return {"stage": None, "pending": [], "approved": [], "rule": False}
        delegated = delegations(cycle)
        if delegated:                                           # a delegate approves instead, in this cycle
            sub = lambda p: _follow(delegated, p)  # noqa: E731
            rule = {**rule, "mandatory": list(dict.fromkeys(sub(m) for m in rule["mandatory"])),
                    "final": sub(rule["final"]) if rule.get("final") else rule.get("final")}
        approvals = [e for e in cycle if e["event"] == c["ApprovedEvent"]]
        stage1 = {e["actor"] for e in approvals if (e.get("details") or "").startswith("Stage 1")}
        su = any((e.get("details") or "").startswith("Stage 1 (super user)") for e in approvals)
        returned = [{"by": e["actor"], "comment": (e.get("details") or "")[len(RETURNED):].split(" [file SHA-256")[0]}
                    for e in reversed(cycle) if e["event"] == c["StatusChanged"] and (e.get("details") or "").startswith(RETURNED)]
        answered = stage1 | {r["by"] for r in returned}
        pending1 = [] if su else [m for m in rule["mandatory"] if m not in answered]
        extra = {"chosen": bool(rule.get("chosen")), "final": rule.get("final"), "returned": returned,
                 "delegated": [{"from": a, "to": b} for a, b in delegated.items()]}
        if pending1:
            return {"stage": 1, "pending": pending1, "approved": sorted(stage1), "rule": True, **extra}
        return {"stage": 2, "pending": [rule["final"]] if rule["final"] else [], "approved": sorted(stage1), "rule": True, **extra}

    def decision_row(d: dict, approver: str, stage: int, decision: str, comment: str, delegated_from: str | None = None,
                     final: bool = False) -> None:
        """Approval Decisions: one row per decision on the page (the production flow DC-P1 writes the same list)."""
        doc_id = d.get("documentId") or f"ID {d.get('id')}"
        submitted = next((e for e in events_by_doc().get(doc_id, []) if e["event"] == s.choices["SubmittedEvent"]), None)
        stamp = re.sub(r"[^0-9T]", "", (submitted or {}).get("utc") or "")[:13]
        try:
            sp().log_decision(workflow_id=f"{doc_id}-{stamp}" if stamp else doc_id, document_id=doc_id,
                              revision=d.get("draftRevision") or d.get("currentRevision") or "01", approver=approver,
                              role="Final" if final else "Mandatory", stage=stage, decision=decision, comment=comment,
                              delegated_from=delegated_from)
        except Exception as e:  # noqa: BLE001 - the decision itself is done (Control Audit)
            logger.warning("decision not logged in Approval Decisions: %s", e)
            sp_error("Approval Decisions row", e)

    def notify_text(kind: str, doc_id: str, title: str, comment: str = "") -> tuple[str, str, str]:
        """Subject, body and link of a notification, in the language the user chose on the page."""
        lang = PAGE_LANG.get()
        subject, view, body = NOTIFY_TEXT[lang][kind]
        fill = {"id": doc_id, "title": title, "comment": comment}
        base = re.sub(r"([?&])lang=[A-Za-z]+&?", r"\1", s.page_url or "/dms/dms-page").rstrip("?&")
        link = base + ("&" if "?" in base else "?") + f"lang={lang}" + (f"&view={view}" if view else "")
        body = body.format(**fill)
        if lang == "HE":                                        # right to left in Outlook and Teams
            body = f'<div dir="rtl" style="text-align:right">{body}</div>'
        return subject.format(**fill), body, link

    def notify(kind: str, d: dict, to: list[str], comment: str = "") -> None:
        """Pilot (page approvals): tell people by email and Teams through DMS Notifications + DC-P2."""
        to = sorted({t for t in to if t})
        doc_id, title = d.get("documentId") or "", d.get("title") or ""
        entry = {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, "doc": doc_id, "to": to}
        app.state.notify_log.appendleft(entry)
        if s.approvals != "page" or not s.notify or not to:
            entry["result"] = ("skipped - approvals are in Teams (DMS_APPROVALS=flow)" if s.approvals != "page" else
                               "skipped - notifications are off (DMS_NOTIFY=0)" if not s.notify else "skipped - nobody to notify")
            return
        subject, body, link = notify_text(kind, doc_id, title, comment)
        try:
            sp().notify(to=to, subject=subject, body=body, link=link, ref=doc_id)
            entry["result"] = "written to DMS Notifications"
        except Exception as e:  # noqa: BLE001 - a notification must never block the workflow
            logger.warning("notification not written (%s): %s", kind, e)
            sp_error(f"DMS Notifications row ({kind})", e)
            entry["result"] = f"failed - {str(e)[:200]}"

    def notify_stage(d: dict) -> None:
        """Tell the approvers of the current stage of a submitted document."""
        st = approval_state(d, events_by_doc().get(d.get("documentId") or "", []), {})
        notify("waiting", d, st["pending"])

    @app.get("/api/approvals")
    def approvals(everyone: bool = Query(False, description="Super users: every pending approval"), user: User = Depends(current_user)):
        """Documents waiting for this user's approval (DMS_APPROVALS=page)."""
        if s.approvals != "page":
            return []
        by_doc, rules, out = events_by_doc(), {}, []
        for d in sp().documents():
            if d.get("lifecycleStatus") != s.choices["Submitted"]:
                continue
            events = by_doc.get(d.get("documentId") or "", [])
            st = approval_state(d, events, rules)
            if user.email in st["pending"] or (everyone and is_admin(user)):
                submitted = next((e for e in events if e["event"] == s.choices["SubmittedEvent"]), None)
                file = submitted_file(d)
                out.append({**with_key(d), **st, "submittedUtc": submitted["utc"] if submitted else None,
                            "submittedBy": submitted["actor"] if submitted else None, "file": file,
                            "officeUri": files.office_uri(file, edit=s.submitted_editable) if file else None,
                            "editable": s.submitted_editable, "mine": user.email in st["pending"]})
        return sorted(out, key=lambda x: x.get("submittedUtc") or "")

    def submitted_file(d: dict) -> str | None:
        """Where the file of a submitted document is now (its Submitted folder, else its working path)."""
        path = d.get("workingUncPath") or ""
        if not path:
            return None
        folder = os.path.dirname(path)
        in_sub = os.path.join(folder if os.path.basename(folder) != "Submitted" else os.path.dirname(folder), "Submitted", os.path.basename(path))
        return in_sub if os.path.isfile(in_sub) else path

    def file_sha(path: str | None) -> str:
        import hashlib
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest().upper()
        except (OSError, TypeError):
            return "?"

    @app.post("/api/approvals/{item_id}")
    def decide(item_id: int, req: DecisionRequest, user: User = Depends(current_user)):
        """Approve or reject on the page (DMS_APPROVALS=page). A super user may decide any stage."""
        c = s.choices
        if s.approvals != "page":
            raise HTTPException(409, "Approvals are done in Teams (DC-P1)")
        d = sp().document(item_id)
        if d.get("lifecycleStatus") != c["Submitted"]:
            raise HTTPException(409, "The document is not waiting for approval")
        st = approval_state(d, events_by_doc().get(d.get("documentId") or "", []), {})
        if not st["rule"]:
            raise HTTPException(409, "No active Approver Matrix rule for this document type")
        su = user.email not in st["pending"]
        if su and not is_admin(user):
            raise HTTPException(403, "You are not an approver of this stage")
        if not req.approve and not req.comment.strip():
            raise HTTPException(400, "Please write why the document is rejected")
        tag = f"Stage {st['stage']}" + (" (super user)" if su else "")
        sha = f" [file SHA-256 {file_sha(submitted_file(d))}]"    # the exact content this decision was made on
        doc_id = d.get("documentId") or f"ID {item_id}"
        left = [] if su else [p for p in st["pending"] if p != user.email]
        remarks = st.get("returned") or []
        back_to_owner = None                                    # the remarks of the whole review, when it ends returned
        if not req.approve and st["stage"] == 1 and not su and left:
            # stage 1: the review goes on - the others still add their remarks; the owner gets them all at the end
            sp().audit(document_id=doc_id, event=c["StatusChanged"], from_status=c["Submitted"], to_status=c["Submitted"],
                       actor=user.email, details=f"{RETURNED}{req.comment.strip()}{sha}")
        elif not req.approve:
            remarks = remarks + [{"by": user.email, "comment": req.comment.strip()}]
            back_to_owner = remarks
        else:
            if st["stage"] == 2:
                final = True
            else:                                               # stage 1 ends when nobody is left; then the final approver
                final = not left and not st.get("final")
            if not left and remarks and st["stage"] == 1 and not su:
                final = False                                   # someone returned it: back to the owner, not on
                back_to_owner = remarks
            if final:
                sp().update(item_id, {"LifecycleStatus": c["Approved_ReadOnly"], "LastApprovedUtc": datetime.now(timezone.utc).isoformat()})
            sp().audit(document_id=doc_id, event=c["ApprovedEvent"], from_status=c["Submitted"],
                       to_status=c["Approved_ReadOnly"] if final else c["Submitted"], actor=user.email,
                       details=tag + (f": {req.comment.strip()}" if req.comment.strip() else "") + sha)
        if back_to_owner is not None:                           # the owner reviews all the remarks and submits again
            summary = "; ".join(f"{r['by'].split('@')[0]}: {r['comment']}" for r in back_to_owner)
            one = len(back_to_owner) == 1 and back_to_owner[0]["by"] == user.email
            sp().update(item_id, {"LifecycleStatus": c["Working"]})
            sp().audit(document_id=doc_id, event=c["RejectedEvent"], from_status=c["Submitted"], to_status=c["Working"],
                       actor=user.email, details=(f"{tag}: {back_to_owner[0]['comment']}" if one
                                                  else f"{tag}: returned to the owner with remarks - {summary}") + sha)
            file_back(d, c["Working"])
        log(user, "approve" if req.approve else "reject", f"{doc_id} {tag}")
        original = next((x["from"] for x in st.get("delegated") or [] if x["to"] == user.email), None)
        decision_row(d, user.email, st["stage"] or 1, "Approved" if req.approve else "Rejected", req.comment.strip(),
                     delegated_from=original, final=st["stage"] == 2)
        after = sp().document(item_id)
        if back_to_owner is not None:
            notify("rejected", after, [after.get("ownerEmail") or ""],
                   "; ".join(f"{r['by'].split('@')[0]}: {r['comment']}" for r in back_to_owner))
        elif not req.approve:
            pass                                                # remarks kept; the owner is told when the review ends
        elif after.get("lifecycleStatus") == c["Approved_ReadOnly"]:
            notify("approved", after, [after.get("ownerEmail") or ""])
        elif st["stage"] == 1 and approval_state(after, events_by_doc().get(after.get("documentId") or "", []), {})["stage"] == 2:
            notify_stage(after)                                 # stage 1 complete: the final approver
        d = with_key(sp().document(item_id))
        if d["statusKey"] == "Submitted":
            d.update(approval_state(d, events_by_doc().get(d.get("documentId") or "", []), {}))
        return d

    @app.post("/api/approvals/{item_id}/delegate")
    def delegate(item_id: int, req: DelegateRequest, user: User = Depends(current_user)):
        """Pass a waiting approval to someone else for this cycle (the approver, or a super user for any waiting approver)."""
        c = s.choices
        if s.approvals != "page":
            raise HTTPException(409, "Approvals are done in Teams (DC-P1)")
        d = sp().document(item_id)
        if d.get("lifecycleStatus") != c["Submitted"]:
            raise HTTPException(409, "The document is not waiting for approval")
        st = approval_state(d, events_by_doc().get(d.get("documentId") or "", []), {})
        frm = (req.on_behalf or user.email).strip().lower()
        if frm != user.email and not is_admin(user):
            raise HTTPException(403, "You can only delegate your own approval")
        if frm not in st["pending"]:
            raise HTTPException(409, f"{frm} is not waiting to approve this document")
        to = clean_approvers([req.to])[0] if req.to else ""
        if not to or to == frm:
            raise HTTPException(400, "Choose another person")
        if to in st["pending"]:
            raise HTTPException(409, f"{to} is already an approver of this stage")
        doc_id = d.get("documentId") or f"ID {item_id}"
        until = valid_to(datetime.now().date())
        details = f"{DELEGATED}{frm} -> {to}" + f" (until {until:%d/%m/%Y})" \
            + (f": {req.comment.strip()}" if req.comment.strip() else "") \
            + (f" (by {user.email})" if user.email != frm else "")
        sp().audit(document_id=doc_id, event=c["PermissionChanged"], from_status=c["Submitted"], to_status=c["Submitted"],
                   actor=user.email, details=details)
        log(user, "delegate", f"{doc_id}: {frm} -> {to}")
        decision_row(d, frm, st["stage"] or 1, "Delegated", f"-> {to}" + (f": {req.comment.strip()}" if req.comment.strip() else ""),
                     final=st["stage"] == 2)
        try:                                                    # the Delegations list keeps the log too
            today = datetime.now().date()
            sp().log_delegation(title=f"{doc_id}: {frm} -> {to}", delegator=frm, delegate=to, approved_by=user.email,
                                reason=f"{doc_id} {d.get('title') or ''}" + (f": {req.comment.strip()}" if req.comment.strip() else ""),
                                valid_from=today.isoformat(), valid_to=valid_to(today).isoformat())
        except Exception as e:  # noqa: BLE001 - the delegation itself is done (Control Audit)
            logger.warning("delegation not logged in the Delegations list: %s", e)
            sp_error("Delegations row", e)
        notify("waiting", d, [to])
        d = with_key(sp().document(item_id))
        d.update(approval_state(d, events_by_doc().get(d.get("documentId") or "", []), {}))
        return d

    @app.get("/api/my-workflows")
    def my_workflows(everyone: bool = Query(False, description="Super users: everyone's workflows"),
                     user: User = Depends(current_user)):
        """Every document the user owns or registered/submitted, with its workflow status, the last
        decision and the full history from Control Audit."""
        c = s.choices
        rules: dict = {}
        by_doc: dict[str, list[dict]] = {}
        for e in sp().audit_events():
            by_doc.setdefault(e["documentId"] or "", []).append(e)
        items = []
        for d in sp().documents():
            if d.get("lifecycleStatus") == c["Archived"]:               # deleted in Working (kept for the audit)
                continue
            events = by_doc.get(d.get("documentId") or "", [])          # newest first
            asked = any(e["actor"] == user.email and e["event"] in (c["Created"], c["SubmittedEvent"]) for e in events)
            if not (everyone and is_admin(user)) and (d.get("ownerEmail") or "").lower() != user.email and not asked:
                continue
            doc = with_key(d)
            decision = next((e for e in events if e["event"] in (c["ApprovedEvent"], c["RejectedEvent"])), None)
            submitted = next((e for e in events if e["event"] == c["SubmittedEvent"]), None)
            if doc["statusKey"] == "Working" and decision and decision["event"] == c["RejectedEvent"]:
                doc["statusKey"] = "Rejected"                           # returned to the owner after a rejection
            if s.approvals == "page" and doc["statusKey"] == "Submitted":
                doc.update(approval_state(d, events, rules))
            if doc["statusKey"] == "Submitted" and s.submitted_editable:
                f = submitted_file(d)
                doc["editUri"] = files.office_uri(f, edit=True) if f else None
            elif doc["statusKey"] in ("Working", "Rejected") and d.get("workingUncPath"):   # the owner edits (remarks)
                doc["editUri"] = files.office_uri(d["workingUncPath"], edit=True)
            elif doc["statusKey"] == "Approved_ReadOnly" and d.get("currentUncPath"):
                doc["viewUri"] = files.office_uri(d["currentUncPath"])
            doc.update(submittedUtc=submitted["utc"] if submitted else None, decision=decision,
                       lastEvent=events[0] if events else None, history=list(reversed(events)))
            items.append(doc)
        items.sort(key=lambda x: (x["lastEvent"] or {}).get("utc") or x.get("modified") or "", reverse=True)
        summary = {k: sum(1 for i in items if i["statusKey"] == k) for k in ("Working", "Submitted", "Approved_ReadOnly", "Rejected")}
        return {"summary": summary, "items": items}

    @app.post("/api/file-service/run")
    def file_service_run(user: User = Depends(current_user)):
        """Run the file moves now (pilot, when the file service runs inside the web service)."""
        if s.file_service_seconds <= 0:
            raise HTTPException(404, "The file service does not run inside this web service")
        from . import file_service
        r = file_service.run_once(sp(), s)
        log(user, "file-service-run", str(r))
        return r

    @app.post("/api/playground/decide/{item_id}", include_in_schema=False)
    def playground_decide(item_id: int, approve: bool = True, comment: str = "", user: User = Depends(current_user)):
        """Playground only (DMS_SHAREPOINT=memory): approve or reject as the approvers would in Teams."""
        if s.sharepoint != "memory":
            raise HTTPException(404)
        try:
            return with_key(sp().decide(item_id, approve, "approver@rh.co.il", comment))
        except (KeyError, ValueError) as e:
            raise HTTPException(409, str(e)) from None

    @app.get("/api/ai/status")
    def ai_status(_: User = Depends(current_user)):
        return {"enabled": app.state.ai.enabled, "model": s.ai_model, "knowledge": bool(s.ai_knowledge_ids), "url": s.ai_url.rstrip("/"),
                "rag": [{"tool": t, "page": app.state.rag.page(t)} for t in s.rag_tools] if app.state.rag.enabled else []}

    @app.post("/api/ai/find")
    def ai_find(req: FindRequest, user: User = Depends(current_user)):
        """Find files from a free-text request, only among what the user may see. With AI Insights
        configured, the AI makes the search plan and ranks the matches with a reason; without it,
        the request's keywords are used."""
        ai: OpenWebUI = app.state.ai
        lang = answer_lang(req.question, req.lang)
        cust_list = customers("", user)
        plan, used_ai = None, False
        if ai.enabled:
            try:
                plan = ai.plan_search(req.question, [c["name"] for c in cust_list], [(k, en) for k, en, _he, _t in blueprint.SAVE_GUIDE])
                used_ai = True
            except (AiError, requests.RequestException, ValueError):
                plan = None
        plan = plan or {}
        terms = [str(t) for t in (plan.get("terms") or []) if str(t).strip()][:8] or finder.keywords(req.question)
        q_low = req.question.lower()
        cust = next((c for c in cust_list if str(plan.get("customer") or "").lower() == c["name"].lower()), None) \
            or next((c for c in cust_list if c["name"].lower() in q_low), None)
        start, project = cust["path"] if cust else s.repository_root, None
        if cust and plan.get("project"):
            want = str(plan["project"]).lower()
            project = next((p for p in projects(cust["path"], user) if want in p["name"].lower()), None)
            if project:
                start = project["path"]
        kind = next((g for g in blueprint.SAVE_GUIDE if g[0] == plan.get("kind")), None)
        kind_folder = kind[3][4:] if kind else None
        if cust:
            terms = [t for t in terms if t.lower() != cust["name"].lower()] or terms
        idx = register_index()
        found: list[tuple[float, str, float]] = []
        walk = (e for root in ([start] if start != s.repository_root else search_roots())
                for e in finder.walk_files(root, lambda p: user.can(p)))
        for e in walk:
            rel = os.path.relpath(e.path, s.repository_root)
            sc = finder.score(rel, e.name, terms, kind_folder, plan.get("extensions") or [])
            if sc <= 0:
                continue
            mtime = e.stat().st_mtime
            sc += finder.age_bonus(mtime) * (3 if plan.get("latest") else 1)
            d = find_registered(e.path, idx)
            if d and with_key(d)["statusKey"] == "Approved_ReadOnly":
                sc += 0.5
            found.append((sc, e.path, mtime))
        found.sort(reverse=True)
        cands = []
        for sc, path, mtime in found[:60]:
            if not user.can(path):
                continue
            d = find_registered(path, idx)
            cands.append({"name": os.path.basename(path), "path": path, "relative": os.path.relpath(path, s.repository_root),
                          "modified": datetime.fromtimestamp(mtime, timezone.utc).isoformat(), "score": round(sc, 2),
                          "officeUri": files.office_uri(path), "document": with_key(d) if d else None,
                          "documentId": d.get("documentId") if d else None, "status": d.get("lifecycleStatus") if d else None,
                          "folder": os.path.dirname(path), "reason": ""})
            if len(cands) >= 30:
                break
        suggestions = cands[:10]
        if used_ai and cands:
            try:
                picks = ai.rank(req.question, cands, lang)
                if picks:
                    suggestions = [{**cands[p["i"]], "reason": p["reason"]} for p in picks]
            except (AiError, requests.RequestException, ValueError):
                pass
        log(user, "ai-find", f"{req.question[:1000]!r} -> {len(suggestions)} suggestions" + (": " + ", ".join(x["name"] for x in suggestions[:10]) if suggestions else ""))
        for x in suggestions:
            x.pop("documentId", None)
            x.pop("status", None)
        return {"usedAi": used_ai, "plan": {"terms": terms, "customer": cust["name"] if cust else None,
                                            "project": project["name"] if project else None, "kind": kind[0] if kind else None},
                "suggestions": suggestions}

    @app.post("/api/ai/ask")
    def ai_ask(req: AskRequest, user: User = Depends(current_user)):
        """AI Insights: ask about one file (after the AD read check) or the company knowledge bases."""
        ai: OpenWebUI = app.state.ai
        if not ai.enabled:
            raise HTTPException(503, "AI Insights is not configured (DMS_AI_URL)")
        path, context = None, ""
        if req.path:
            path = files.resolve(s.repository_root, req.path)
            if not os.path.isfile(path):
                raise HTTPException(404, "File not found")
            if not user.can(path):
                raise HTTPException(403, "You do not have access to this file")
            d = find_registered(path, register_index())
            context = f"Document: {os.path.basename(path)}" + (
                f". DMS record {d.get('documentId')}, type {d.get('documentType')}, status {d.get('lifecycleStatus')},"
                f" revision {d.get('currentRevision') or '-'}, owner {d.get('ownerName') or d.get('ownerEmail')}" if d else ". Not registered in the DMS")
        try:
            result = ai.ask(req.question, lang=answer_lang(req.question, req.lang), file_path=path, context=context)
        except AiError as e:
            raise HTTPException(502, str(e)) from None
        except requests.RequestException as e:
            raise HTTPException(502, f"The AI service did not answer: {type(e).__name__}") from None
        log(user, "ai-ask", f"{path or 'knowledge'}: {req.question[:1000]!r} (model {result.get('model')}) -> {result['answer'][:2000]!r}")
        return result

    @app.post("/api/ai/rag")
    def ai_rag(req: RagRequest, user: User = Depends(current_user)):
        """AI Insights: a question to an RH RAG tool on the AI portal (e.g. QMS)."""
        rag: RagTools = app.state.rag
        if not rag.enabled:
            raise HTTPException(503, "The RAG tools are not configured (DMS_RAG_URL, DMS_RAG_TOOLS)")
        try:
            result = rag.ask(req.tool, req.question, user=user.email, new=req.new)
        except RagError as e:
            raise HTTPException(502, str(e)) from None
        except requests.RequestException as e:
            raise HTTPException(502, f"The RAG tool did not answer: {type(e).__name__}") from None
        log(user, "ai-rag", f"{req.tool}: {req.question[:1000]!r} -> {result['answer'][:2000]!r}"
            + (". Sources: " + ", ".join(x["name"] + (f" | {x['section']}" if x["section"] else "") for x in result["sources"][:10]) if result["sources"] else ""))
        return result

    @app.post("/api/ai/chat-log", status_code=204)
    def ai_chat_log(req: AskRequest, user: User = Depends(current_user)):
        """A question the page opened in the RH AI chat (when the page is not connected to its API)."""
        log(user, "ai-chat", f"{req.path or 'knowledge'}: {req.question[:1000]!r} (opened in {s.ai_url})")

    @app.get("/api/documents")
    def documents(mine: bool = False, status: str | None = Query(None, description="Working | Submitted | Approved_ReadOnly"),
                  user: User = Depends(current_user)):
        docs = [with_key(d) for d in sp().documents()]
        if mine:
            docs = [d for d in docs if (d.get("ownerEmail") or "").lower() == user.email]
        else:
            docs = [d for d in docs if visible(d, user)]
        if status:
            docs = [d for d in docs if d["statusKey"] == status]
        return sorted(docs, key=lambda d: d.get("modified") or "", reverse=True)

    @app.get("/api/documents/{item_id}")
    def document(item_id: int, user: User = Depends(current_user)):
        d = sp().document(item_id)
        if (d.get("ownerEmail") or "").lower() != user.email and not visible(d, user):
            raise HTTPException(403, "You do not have access to this document")
        return with_key(d)

    @app.post("/api/documents", status_code=201)
    def register(req: RegisterRequest, user: User = Depends(current_user)):
        clean_approvers(req.approvers)                          # a wrong address stops it before anything is created
        path = files.resolve(s.repository_root, req.path)
        if not os.path.isfile(path):
            raise HTTPException(404, "File not found")
        if not user.can(path):
            raise HTTPException(403, "You do not have access to this file")
        if os.path.basename(os.path.dirname(path)) in WORKFLOW_FOLDERS[1:]:
            raise HTTPException(409, "The file is already in a workflow folder")
        if holds_share_log(path):
            raise HTTPException(403, "The customer's share log is kept by the DMS and is not a controlled document")
        from . import noworkflow
        if noworkflow.is_marked(s.repository_root, path):
            raise HTTPException(409, "This file was saved without workflow (Save file (no workflow))")
        if in_shared_folder(path):
            raise HTTPException(403, "Files in the customer's Shared folder are not workflowed (they are copies already sent)")
        existing = find_registered(path, register_index())
        if existing:
            raise HTTPException(409, {"message": "The file is already registered", "document": with_key(existing)})
        title = req.title or os.path.splitext(os.path.basename(path))[0]
        bp = classify(os.path.dirname(path))
        document_type, document_area = req.documentType or bp["documentType"], req.documentArea or bp["documentArea"]
        if not document_type or not document_area:
            raise HTTPException(400, "Choose the document type and area (this folder does not set them)")
        doc = sp().create_document(title=title, path=path, document_type=document_type,
                                   document_area=document_area, owner_email=user.email,
                                   control_mode=req.controlMode or bp["controlMode"], document_id=req.documentId)
        rev = files.parse_revision(os.path.basename(path))[1]
        sp().update(doc["id"], {"DraftRevision": f"{rev or 1:02d}"})
        sp().audit(document_id=doc["documentId"], event=s.choices["Created"], from_status="",
                   to_status=s.choices["Working"], actor=user.email,
                   details=f"Registered from the DMS page: {os.path.relpath(path, s.repository_root)}")
        if req.submit:
            return submit(doc["id"], SubmitRequest(approvers=req.approvers), user)
        return with_key(doc)

    def last_chosen(doc_id: str) -> list[str]:
        """The approvers chosen at the document's last submission (empty: it went by the Approver Matrix)."""
        last = next((e for e in events_by_doc().get(doc_id or "", []) if e["event"] == s.choices["SubmittedEvent"]), None)
        return chosen_approvers(last)

    @app.get("/api/documents/{item_id}/approvers")
    def doc_approvers(item_id: int, _: User = Depends(current_user)):
        """For a new submission: the approvers chosen last time, and the document type (for the Matrix)."""
        d = sp().document(item_id)
        return {"chosen": last_chosen(d.get("documentId") or ""), "documentType": d.get("documentType") or ""}

    @app.post("/api/documents/{item_id}/submit")
    def submit(item_id: int, req: SubmitRequest | None = None, user: User = Depends(current_user)):
        doc = sp().document(item_id)
        if req is None or req.approvers is None:                # not said: the same approvers as last time
            approvers = last_chosen(doc.get("documentId") or "")
        else:
            approvers = clean_approvers(req.approvers)
        if (doc.get("ownerEmail") or "").lower() != user.email and not is_admin(user):
            raise HTTPException(403, "Only the document owner (or a DMS super user) can submit it")
        if doc.get("lifecycleStatus") != s.choices["Working"]:
            raise HTTPException(409, f"Only a document in {s.choices['Working']} can be submitted")
        file_back(doc, s.choices["Working"])                    # still in Submitted from an earlier cycle
        if not doc.get("workingUncPath") or not os.path.isfile(files.resolve(s.repository_root, doc["workingUncPath"])):
            raise HTTPException(409, "The working file was not found on the file server")
        sp().update(item_id, {"LifecycleStatus": s.choices["Submitted"]})
        sp().audit(document_id=doc["documentId"], event=s.choices["SubmittedEvent"], from_status=s.choices["Working"],
                   to_status=s.choices["Submitted"], actor=user.email,
                   details="Submitted from the DMS page" + (f". {CHOSEN}{'; '.join(approvers)}" if approvers else ""))
        after = sp().document(item_id)
        if s.approvals == "page":
            notify_stage(after)
        return with_key(after)

    @app.post("/api/documents/{item_id}/revise")
    def revise(item_id: int, file: UploadFile | None = File(None), submit: bool = Form(False),
               user: User = Depends(current_user)):
        """Start the next revision of an approved document, on the same record: from a copy of the
        approved version, or from a file uploaded from the user's PC. The draft is saved next to the
        document as <name>_RevNN_DRAFT.<ext>; on approval the file service makes it the current version
        and moves the previous one to Obsolete_ReadOnly."""
        from .file_service import to_root
        c = s.choices
        d = sp().document(item_id)
        if d.get("lifecycleStatus") != c["Approved_ReadOnly"]:
            raise HTTPException(409, "Only an approved document can get a new revision")
        current = approved_file(d)
        if not current:
            raise HTTPException(409, f"The approved file was not found on the file server ({d.get('currentUncPath') or 'no path in the record'})")
        if not user.can(current):
            raise HTTPException(403, "You do not have access to this document")
        cur_dir = os.path.dirname(current)
        place = os.path.dirname(cur_dir) if os.path.basename(cur_dir) in WORKFLOW_FOLDERS else cur_dir
        if not user.can(place, "write"):
            raise HTTPException(403, "You do not have permission to save files in this folder")
        base, rev, ext = files.parse_revision(os.path.basename(current))
        cur_rev = int(d["currentRevision"]) if str(d.get("currentRevision") or "").isdigit() else (rev or 1)
        new_rev = cur_rev + 1
        if file is not None and file.filename:
            ext = os.path.splitext(file.filename)[1] or ext
        name = files.revision_name(base, new_rev, ext)
        target = os.path.join(place, name)
        if os.path.exists(target):
            raise HTTPException(409, f"{name} already exists in the folder")
        try:
            if file is not None and file.filename:
                target = files.save_upload(s.repository_root, place, name, file.file, s.max_upload_mb * 1024 * 1024)
                how = f"uploaded {os.path.basename(file.filename)}"
            else:
                files.copy_writable(current, target)
                how = f"a copy of revision {cur_rev:02d}"
        except (ValueError, PermissionError) as e:
            raise HTTPException(400, str(e)) from None
        sp().update(item_id, {"WorkingUncPath": target, "DraftRevision": f"{new_rev:02d}", "LifecycleStatus": c["Working"]})
        sp().audit(document_id=d.get("documentId") or f"ID {item_id}", event=c["StatusChanged"], from_status=c["Approved_ReadOnly"],
                   to_status=c["Working"], actor=user.email,
                   details=f"New revision {new_rev:02d} from {how}: {os.path.relpath(target, s.repository_root)}")
        if with_key(d)["noWorkflow"]:                            # saved without workflow: from now on it goes through workflow
            from . import noworkflow
            sp().update(item_id, {"ControlMode": classify(os.path.dirname(target))["controlMode"]
                                  or blueprint.choice("Workflow Required", sp().choices("ControlMode"))})
            noworkflow.moved(s.repository_root, to_root(s.repository_root, d.get("currentUncPath")) or "", None)
        log(user, "revise", f"{d.get('documentId')} -> {target}")
        if submit:
            return {**submit_doc(item_id, None, user), "draft": target, "officeUri": files.office_uri(target, edit=True)}
        return {**with_key(sp().document(item_id)), "draft": target, "officeUri": files.office_uri(target, edit=True)}

    def approved_file(d: dict) -> str | None:
        """The approved file of a record: CurrentUncPath, else where the file service puts it (Current_ReadOnly next to
        the working file) - then the record is corrected (it was not updated when the file moved)."""
        import re as _re
        from .file_service import _sha256, to_root
        current = to_root(s.repository_root, d.get("currentUncPath"))
        if current and os.path.isfile(current):
            return current
        working = to_root(s.repository_root, d.get("workingUncPath"))
        if not working:
            return None
        parent = os.path.dirname(working)
        folder = os.path.dirname(parent) if os.path.basename(parent) in WORKFLOW_FOLDERS else parent
        landed = os.path.join(folder, "Current_ReadOnly", _re.sub(r"_DRAFT(?=\.[^.]+$|$)", "", os.path.basename(working), flags=_re.I))
        if not os.path.isfile(landed):
            return None
        sp().update(d["id"], {"CurrentUncPath": landed, "CurrentSHA256": _sha256(landed), "WorkingUncPath": ""})
        logger.info("%s: CurrentUncPath corrected to %s", d.get("documentId"), landed)
        return landed

    def shareable(item_id: int, user: User) -> tuple[dict, str, str]:
        """An approved document the user may share: (record, approved file, revision), else HTTP error."""
        from .file_service import to_root
        d = sp().document(item_id)
        if d.get("lifecycleStatus") != s.choices["Approved_ReadOnly"]:
            raise HTTPException(409, f"{d.get('documentId') or item_id}: only an approved document can be shared with a customer")
        if (d.get("ownerEmail") or "").lower() != user.email and not is_admin(user):
            raise HTTPException(403, f"{d.get('documentId')}: only the document owner (or a DMS super user) can share it")
        current = approved_file(d)
        if not current:
            raise HTTPException(409, f"{d.get('documentId')}: the approved file was not found on the file server "
                                     f"({d.get('currentUncPath') or d.get('workingUncPath') or 'no path in the record'})")
        if not user.can(current):
            raise HTTPException(403, f"{d.get('documentId')}: you do not have access to this document")
        rev = str(d.get("currentRevision") or files.parse_revision(os.path.basename(current))[1] or 1).zfill(2)
        return d, current, rev

    def customer_names(user: User) -> list[str]:
        try:
            return [f["name"] for f in files.list_folder(s.repository_root, customers_root(), user.can)["folders"]]
        except (FileNotFoundError, PermissionError):
            return []

    def customer_of_path(path: str) -> str | None:
        from .file_service import _under_root, to_root
        full = to_root(s.repository_root, path)
        c = context_of(rel_parts(full))["customer"] if full and _under_root(s.repository_root, full) else None
        return c["name"] if c else None

    @app.get("/api/documents/{item_id}/share-info")
    def share_info(item_id: int, user: User = Depends(current_user)):
        """For the Share dialog: the customer from the file's folder (02_Customers\\<name>, preselected), the
        customer folders to choose from (any of them), and the other approved documents the user may add."""
        d, current, rev = shareable(item_id, user)
        mine = [x for x in sp().documents() if x.get("lifecycleStatus") == s.choices["Approved_ReadOnly"] and x["id"] != item_id
                and ((x.get("ownerEmail") or "").lower() == user.email or is_admin(user))]
        others = [{"id": x["id"], "documentId": x.get("documentId"), "title": x.get("title"), "revision": x.get("currentRevision"),
                   "customer": customer_of_path(x.get("currentUncPath") or "")} for x in mine]
        return {"customer": customer_of_path(current), "customers": customer_names(user), "revision": rev,
                "folder": s.ex_folder, "shortcut": s.ex_shortcut, "days": s.ex_days, "others": others}

    @app.post("/api/documents/{item_id}/share")
    def share(item_id: int, req: ShareRequest, user: User = Depends(current_user)):
        """Share approved revisions with a customer: the files are copied straight into the customer folder on the
        Large File Exchange site (<library>/Outbound/<Customer>/, the name of the folder under 02_Customers) and
        SharePoint invites the person to that folder (view only, B2B guest). More documents can go in the same
        share; every later share adds to the same folder. A OneDrive shortcut DMS_<Customer> is added for the
        user. Only approved documents, by the owner or a DMS super user; one Control Audit row per document."""
        c = s.choices
        if s.sharepoint != "memory" and not s.ex_site_url:
            raise HTTPException(409, "Sharing with customers is not configured (DMS_EX_SITE_URL)")
        docs = [shareable(i, user) for i in dict.fromkeys([item_id, *req.documentIds])]
        names = {n.lower(): n for n in customer_names(user)}
        if (req.customer or "").strip():                       # chosen in the dialog (default: the file's customer folder)
            customer = names.get(req.customer.strip().lower())
        else:
            customer = customer_of_path(docs[0][1])
        if not customer:
            raise HTTPException(400, "Choose the customer (a folder under " + s.customers_folder + ")")
        names = [os.path.basename(p) for _, p, _ in docs]
        if len({n.lower() for n in names}) != len(names):
            raise HTTPException(409, "Two of the files have the same name; share them separately")
        email = req.email.strip().lower()
        titles = ", ".join(f"{d.get('title')} (Rev {rev})" for d, _, rev in docs)
        message = req.message.strip() or (f"RH shares with you: {titles}. The link is personal and opens the "
                                          f"{customer} folder for viewing.")
        r = sp().share_with_guest(local_paths=[p for _, p, _ in docs], folder=f"{s.ex_folder}/{customer}", email=email,
                                  subject=f"RH - {customer}: {titles}"[:250], message=message,
                                  shortcut_for=user.email, shortcut_name=f"DMS_{customer}" if s.ex_shortcut else None)
        for (d, _, rev), url in zip(docs, r["urls"]):
            doc_id = d.get("documentId") or f"ID {d['id']}"
            sp().audit(document_id=doc_id, event=c["PermissionChanged"], from_status=c["Approved_ReadOnly"],
                       to_status=c["Approved_ReadOnly"], actor=user.email,
                       details=f"Shared revision {rev} with {email} (customer {customer}, view only, Large File Exchange): {url}")
            log(user, "share", f"{doc_id} Rev{rev} -> {email} ({customer})")
        from . import shared_log
        until = (datetime.now(timezone.utc) + timedelta(days=s.ex_days)).strftime("%Y-%m-%d") if s.ex_days > 0 else ""
        log_error = None
        try:
            shared_log.append(s, customer, [{"Action": "Shared", "Shared by": user.email, "Shared with": email,
                                             "Document ID": d.get("documentId"), "Title": d.get("title"), "Revision": rev,
                                             "File": os.path.basename(p), "Exchange link": url, "Available until": until}
                                            for (d, p, rev), url in zip(docs, r["urls"])])
        except OSError as e:
            log_error = str(e)
            logger.warning("Share log of %s: %s", customer, e)
        if r.get("shortcutError"):
            logger.warning("OneDrive shortcut DMS_%s: %s", customer, r["shortcutError"])
        return {"url": r["folderUrl"], "urls": r["urls"], "email": email, "customer": customer, "revision": docs[0][2],
                "documents": [{"documentId": d.get("documentId"), "revision": rev} for d, _, rev in docs],
                "shortcut": r.get("shortcut"), "shortcutError": r.get("shortcutError"), "days": s.ex_days,
                "log": os.path.relpath(shared_log.path_for(s, customer), s.repository_root) if s.shared_log and not log_error else None,
                "logError": log_error}

    # ------------------------------------------------------------------ DMS First loading (super users)
    @app.post("/api/first-load", status_code=202)
    def first_load_start(req: FirstLoadRequest, user: User = Depends(current_user)):
        """Load documents approved in the old repository: into Current_ReadOnly, registered as Approved,
        File Linker links moved. Runs in the background; follow it with GET /api/first-load/{id}."""
        from . import first_load
        if not is_admin(user):
            raise HTTPException(403, "Only a DMS super user can run the First loading")
        target = files.resolve(s.repository_root, req.target)
        if not os.path.isdir(target):
            raise HTTPException(404, "The target folder was not found")
        if files.in_workflow_folder(s.repository_root, target):
            raise HTTPException(403, "The target cannot be a workflow folder")
        if not req.dryRun and not user.can(target, "write"):
            raise HTTPException(403, "You do not have permission to write in the target folder")
        source = os.path.normpath(req.source.strip())
        if not os.path.isdir(source) and not os.listdir(target):
            raise HTTPException(404, "The source folder was not found and the target folder is empty")
        if os.path.normcase(source) == os.path.normcase(target):
            raise HTTPException(400, "The source and the target must be different folders")
        job = first_load.start(sp(), s, app.state.linker, user.email, source=source, target=target,
                               document_type=req.documentType or None, document_area=req.documentArea or None,
                               control_mode=req.controlMode or None, classify=classify,
                               dry_run=req.dryRun, copy_missing=req.copyMissing, update_links=req.updateLinks,
                               mode=req.mode, approver=(req.approver or s.first_load_approver).strip().lower())
        log(user, "first-load", f"{'dry run ' if req.dryRun else ''}{req.mode} {source} -> {target}")
        return {k: job[k] for k in ("id", "state", "dryRun")}

    @app.get("/api/first-load/{job_id}")
    def first_load_status(job_id: str, user: User = Depends(current_user)):
        from . import first_load
        job = first_load.JOBS.get(job_id)
        if not job or (job["actor"] != user.email and not is_admin(user)):
            raise HTTPException(404, "Unknown run")
        return job

    @app.post("/api/documents/{item_id}/withdraw")
    def withdraw(item_id: int, user: User = Depends(current_user)):
        """Take a submitted document back to Working (owner or super user). The approval cycle ends,
        the file service returns the file to its place, and it can be submitted again."""
        c = s.choices
        doc = sp().document(item_id)
        if (doc.get("ownerEmail") or "").lower() != user.email and not is_admin(user):
            raise HTTPException(403, "Only the document owner (or a DMS super user) can withdraw it")
        if doc.get("lifecycleStatus") != c["Submitted"]:
            raise HTTPException(409, "Only a submitted document can be withdrawn")
        waiting = approval_state(doc, events_by_doc().get(doc.get("documentId") or "", []), {})["pending"] if s.approvals == "page" else []
        sp().update(item_id, {"LifecycleStatus": c["Working"]})
        notify("withdrawn", doc, waiting)
        sp().audit(document_id=doc.get("documentId") or f"ID {item_id}", event=c["Cancelled"], from_status=c["Submitted"],
                   to_status=c["Working"], actor=user.email, details="Withdrawn from the DMS page")
        file_back(doc, c["Working"])
        log(user, "withdraw", doc.get("documentId") or str(item_id))
        return with_key(sp().document(item_id))

    @app.post("/api/documents/{item_id}/delete")
    def delete_document(item_id: int, user: User = Depends(current_user)):
        """Delete a document in Working (owner or super user). The file goes to the recycle folder and the
        record stays for the audit trail: Archived, or for a new revision draft, back to its approved revision."""
        from .file_service import to_root
        c = s.choices
        d = sp().document(item_id)
        if (d.get("ownerEmail") or "").lower() != user.email and not is_admin(user):
            raise HTTPException(403, "Only the document owner (or a DMS super user) can delete it")
        if d.get("lifecycleStatus") != c["Working"]:
            raise HTTPException(409, "Only a document in Working can be deleted (withdraw it first)")
        file_back(d, c["Working"])                              # a copy left in Submitted comes back first
        working = to_root(s.repository_root, d.get("workingUncPath"))
        recycled = None
        if working and os.path.isfile(working):
            if not user.can(working, "write"):
                raise HTTPException(403, "You do not have permission to delete this file")
            try:
                recycled = files.delete_item(s.repository_root, working, 0, user.email)
            except PermissionError as e:
                raise HTTPException(409, str(e)) from None
        doc_id = d.get("documentId") or f"ID {item_id}"
        where = f"; file -> {os.path.relpath(recycled, s.repository_root)}" if recycled else "; the file was not found"
        if d.get("currentUncPath"):                             # a new revision draft: the approved one stays
            sp().update(item_id, {"LifecycleStatus": c["Approved_ReadOnly"], "WorkingUncPath": "", "DraftRevision": ""})
            to, details = c["Approved_ReadOnly"], f"Draft revision {d.get('draftRevision') or ''} deleted{where}. The approved revision stays current"
        else:
            sp().update(item_id, {"LifecycleStatus": c["Archived"], "WorkingUncPath": ""})
            to, details = c["Archived"], f"Working document deleted{where}"
        sp().audit(document_id=doc_id, event=c["Cancelled"], from_status=c["Working"], to_status=to, actor=user.email, details=details)
        log(user, "delete-document", f"{doc_id}: {details}")
        return with_key(sp().document(item_id))

    @app.post("/api/documents/{item_id}/rename")
    def rename_document(item_id: int, req: DocRenameRequest, user: User = Depends(current_user)):
        """Rename the file of a document in Working (owner or super user). The register follows: working path,
        title (when it was the file name) and draft revision (from a _RevNN in the new name)."""
        from .file_service import to_root
        c = s.choices
        d = sp().document(item_id)
        if (d.get("ownerEmail") or "").lower() != user.email and not is_admin(user):
            raise HTTPException(403, "Only the document owner (or a DMS super user) can rename it")
        if d.get("lifecycleStatus") != c["Working"]:
            raise HTTPException(409, "Only a document in Working can be renamed (withdraw it first)")
        file_back(d, c["Working"])                              # a copy left in Submitted comes back first
        working = to_root(s.repository_root, d.get("workingUncPath"))
        if not working or not os.path.isfile(working):
            raise HTTPException(409, "The working file was not found on the file server")
        if not (user.can(working, "write") and user.can(os.path.dirname(working), "write")):
            raise HTTPException(403, "You do not have permission to rename this file")
        old_base, ext = os.path.splitext(os.path.basename(working))
        name = req.newName.strip()
        if not os.path.splitext(name)[1]:
            name += ext                                         # keep the file type
        try:
            path = files.rename_item(s.repository_root, working, name, 0)
        except FileExistsError:
            raise HTTPException(409, "A file with this name already exists in the folder") from None
        except (PermissionError, ValueError) as e:
            raise HTTPException(409, str(e)) from None
        values = {"WorkingUncPath": path}
        if (d.get("title") or "") == old_base:
            values["Title"] = os.path.splitext(os.path.basename(path))[0]
        rev = files.parse_revision(os.path.basename(path))[1]
        if rev:
            values["DraftRevision"] = f"{rev:02d}"
        sp().update(item_id, values)
        doc_id = d.get("documentId") or f"ID {item_id}"
        details = f"Renamed: {os.path.basename(working)} -> {os.path.basename(path)}"
        sp().audit(document_id=doc_id, event=c["StatusChanged"], from_status=c["Working"], to_status=c["Working"],
                   actor=user.email, details=details)
        log(user, "rename-document", f"{doc_id}: {details}")
        return with_key(sp().document(item_id))

    submit_doc = submit                                         # used where a parameter is called "submit"

    # The DMS link for Office (paths too long for Word): a small WebDAV resource, as Office uses with SharePoint.
    # Word opens it with the original file name and Save writes back to the same file on the server.
    DAV_METHODS = ["GET", "HEAD", "OPTIONS", "PROPFIND", "LOCK", "UNLOCK", "PUT"]

    def dav_writable(full: str, user: User) -> bool:
        return (not files.is_read_only(full) and user.can(full, "write")
                and os.path.basename(os.path.dirname(full)) not in WORKFLOW_FOLDERS[2:])

    DAV_LOCKS: dict[str, dict] = {}                             # file -> {token, owner, until}: Office checks its lock

    def dav_lock(full: str) -> dict | None:
        lk = DAV_LOCKS.get(full)
        if lk and lk["until"] < datetime.now().timestamp():
            DAV_LOCKS.pop(full, None)
            return None
        return lk

    def active_lock(lk: dict, href: str) -> str:
        from xml.sax.saxutils import escape
        left = max(1, int(lk["until"] - datetime.now().timestamp()))
        return ("<d:activelock><d:locktype><d:write/></d:locktype><d:lockscope><d:exclusive/></d:lockscope>"
                f"<d:depth>0</d:depth>{lk['owner']}<d:timeout>Second-{left}</d:timeout>"
                f"<d:locktoken><d:href>{lk['token']}</d:href></d:locktoken>"
                f"<d:lockroot><d:href>{escape(href)}</d:href></d:lockroot></d:activelock>")

    def dav_href(request: Request) -> str:
        """The address as Office sent it, percent-encoded (spaces, Hebrew): with a raw name Word cannot match the
        answer to the file it locked and opens it read only."""
        from urllib.parse import quote, unquote
        return quote(unquote(request.url.path), safe="/")

    def dav_props(full: str, href: str, user: User) -> str:
        from email.utils import formatdate
        from xml.sax.saxutils import escape
        st = os.stat(full)
        etag = f'"{int(st.st_mtime)}-{st.st_size}"'
        return (f"<d:response><d:href>{escape(href)}</d:href><d:propstat><d:prop>"
                f"<d:displayname>{escape(os.path.basename(full))}</d:displayname><d:resourcetype/>"
                f"<d:getcontentlength>{st.st_size}</d:getcontentlength>"
                f"<d:getcontenttype>{mimetypes.guess_type(full)[0] or 'application/octet-stream'}</d:getcontenttype>"
                f"<d:getlastmodified>{formatdate(st.st_mtime, usegmt=True)}</d:getlastmodified>"
                f"<d:creationdate>{datetime.fromtimestamp(st.st_ctime, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}</d:creationdate>"
                f"<d:getetag>{etag}</d:getetag>"
                "<d:supportedlock><d:lockentry><d:lockscope><d:exclusive/></d:lockscope><d:locktype><d:write/></d:locktype>"
                "</d:lockentry></d:supportedlock>"
                + (f"<d:lockdiscovery>{active_lock(dav_lock(full), href)}</d:lockdiscovery>" if dav_lock(full) else "<d:lockdiscovery/>") +
                f"<d:isreadonly>{'f' if dav_writable(full, user) else 't'}</d:isreadonly>"
                f"</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")

    @app.api_route("/api/o/{token}/", methods=["OPTIONS", "PROPFIND"])
    def open_link_folder(token: str, request: Request, _: User = Depends(current_user)):
        """Office asks about the "folder" of the DMS link too."""
        from fastapi.responses import Response
        dav = {"DAV": "1,2", "MS-Author-Via": "DAV", "Allow": ", ".join(DAV_METHODS)}
        if request.method == "OPTIONS":
            return Response(status_code=200, headers=dav)
        body = ('<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:"><d:response>'
                f"<d:href>{dav_href(request)}</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop>"
                "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>")
        return Response(body, status_code=207, media_type="application/xml; charset=utf-8", headers=dav)

    @app.api_route("/api/o/{token}/{name}", methods=DAV_METHODS)
    async def open_link(token: str, name: str, request: Request, user: User = Depends(current_user)):
        """Open for a path too long for Office (Hebrew names): Word / Excel / PowerPoint open and save the file here."""
        from fastapi.responses import Response
        full = files.open_path(token)
        if not full or not os.path.isfile(full):
            raise HTTPException(404, "The link expired: open the file again from the DMS page")
        if name != os.path.basename(full):                     # only this file (not Office's temporary ~$ files)
            raise HTTPException(404 if request.method in ("GET", "HEAD", "PROPFIND") else 403, "Not this file")
        if not user.can(full):
            raise HTTPException(403, "You do not have access to this file")
        m = request.method
        dav = {"DAV": "1,2", "MS-Author-Via": "DAV", "Allow": ", ".join(DAV_METHODS)}
        if m == "OPTIONS":
            return Response(status_code=200, headers=dav)
        if m == "PROPFIND":
            body = ('<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:">'
                    + dav_props(full, dav_href(request), user) + "</d:multistatus>")
            return Response(body, status_code=207, media_type='text/xml; charset="utf-8"', headers=dav)
        if m == "LOCK":
            if not dav_writable(full, user):
                raise HTTPException(423, "Read only")
            import re as _re
            import uuid as _uuid
            body_in = (await request.body()).decode("utf-8", "replace")
            lk = dav_lock(full)
            if lk and body_in.strip():                          # a new lock while another is active
                raise HTTPException(423, "The file is open for editing by someone else")
            secs = 3600
            t = _re.search(r"Second-(\d+)", request.headers.get("timeout", ""))
            if t:
                secs = min(int(t.group(1)), 86400)
            if not lk:
                o = _re.search(r"<(?:\w+:)?owner\b[^>]*>.*?</(?:\w+:)?owner>", body_in, _re.S)
                owner = (_re.sub(r"<(/?)\w+:", r"<\1d:", o.group(0)) if o else f"<d:owner>{user.email}</d:owner>")
                lk = {"token": f"opaquelocktoken:{_uuid.uuid4()}", "owner": owner}
            lk["until"] = datetime.now().timestamp() + secs     # new lock, or a refresh (no body)
            DAV_LOCKS[full] = lk
            body = ('<?xml version="1.0" encoding="utf-8"?><d:prop xmlns:d="DAV:"><d:lockdiscovery>'
                    + active_lock(lk, dav_href(request)) + "</d:lockdiscovery></d:prop>")
            return Response(body, status_code=200, media_type='text/xml; charset="utf-8"',
                            headers={**dav, "Lock-Token": f"<{lk['token']}>", "Timeout": f"Second-{secs}"})
        if m == "UNLOCK":
            DAV_LOCKS.pop(full, None)
            return Response(status_code=204, headers=dav)
        if m == "PUT":
            if not dav_writable(full, user):
                raise HTTPException(403, "This file is read only in the DMS")
            data = await request.body()
            tmp = full + ".dms-save"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, full)
            log(user, "upload", full + " (saved from Office)")
            return Response(status_code=204, headers=dav)
        if m == "HEAD":
            return Response(status_code=200, headers={**dav, "Content-Length": str(os.path.getsize(full))})
        return FileResponse(full, filename=os.path.basename(full), headers=dav,
                            content_disposition_type="inline")

    @app.get("/api/files/download")
    def download(path: str, user: User = Depends(current_user)):
        full = files.resolve(s.repository_root, path)
        if not os.path.isfile(full):
            raise HTTPException(404, "File not found")
        if not user.can(full):
            raise HTTPException(403, "You do not have access to this file")
        return FileResponse(full, filename=os.path.basename(full))

    return app


app = create_app()
