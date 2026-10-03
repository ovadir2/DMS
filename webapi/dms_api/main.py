"""DMS Web API: browse the repository by customer (what AD allows), save files into it, register
a file and submit it for approval, and see each file's status.

Run:  uvicorn dms_api.main:app --host 0.0.0.0 --port 8080
Docs: /docs (OpenAPI). Page: /dms/dms-page?lang=EN&path=<UNC>&name=<file>
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
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


class ShareRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    message: str = Field("", max_length=2000)


class FirstLoadRequest(BaseModel):
    source: str = Field(description="The old repository folder (any path the service can read)")
    target: str = Field(description="The folder under the repository root")
    documentType: str | None = Field(None, description="Empty: each file gets the type of its blueprint folder")
    documentArea: str | None = Field(None, description="Empty: each file gets the area of its blueprint folder")
    controlMode: str | None = None
    dryRun: bool = True
    copyMissing: bool = True
    updateLinks: bool = True


class FindRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    lang: str = "EN"


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
    app.state.ai = ai or OpenWebUI(s)
    app.state.rag = RagTools(s)
    from .filelinker import FileLinker
    app.state.linker = FileLinker(s)
    if s.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=s.allowed_origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

    status_key = {v: k for k, v in s.choices.items() if k in ("Working", "Submitted", "Approved_ReadOnly")}

    def sp() -> SharePoint:
        return app.state.sp

    def with_key(d: dict) -> dict:
        return {**d, "statusKey": status_key.get(d.get("lifecycleStatus") or "", "Other")}

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
    @app.get("/api/health")
    def health():
        return {"status": "ok", "repositoryRoot": s.repository_root, "rootReachable": os.path.isdir(s.repository_root)}

    @app.get("/api/client-config")
    def client_config():
        return {"authMode": s.auth_mode, "playground": s.sharepoint == "memory", "notify": s.approvals == "page" and s.notify, "fileService": s.file_service_seconds > 0,
                "approvals": s.approvals, "fileLinker": bool(s.fl_check_url and s.fl_update_url),
                "site": s.site_url if s.sharepoint != "memory" else "", "tenantId": s.tenant_id, "clientId": s.spa_client_id,
                "scope": s.api_scope,
                "repositoryRoot": s.repository_root}

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
        """The user areas of the repository (01_Management, 02_Customers, ...), without the system folders."""
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
        return user.email in s.admins

    @app.get("/api/diagnostics/sharepoint")
    def sp_check(user: User = Depends(current_user)):
        """Super users: the DMS lists in SharePoint (exists, items, may this account add), and the last errors."""
        if not is_admin(user):
            raise HTTPException(403, "Only a DMS super user can run the SharePoint check")
        from .sharepoint import AUDIT, MATRIX, NOTIFY, REGISTER
        lists = [sp().list_info(rel) for rel in (REGISTER, AUDIT, MATRIX, NOTIFY)]
        return {"site": s.site_url if s.sharepoint != "memory" else "memory (playground)", "account": user.email,
                "auth": s.sp_auth, "lists": lists, "errors": list(app.state.sp_errors),
                "notifications": {"on": s.approvals == "page" and s.notify, "approvals": s.approvals, "notify": s.notify,
                                  "pageUrl": s.page_url, "last": list(app.state.notify_log)}}

    @app.post("/api/diagnostics/notify-test")
    def notify_test(user: User = Depends(current_user)):
        """Super users: write one test row to DMS Notifications, addressed to themselves (the DC-P2 flow sends it)."""
        if not is_admin(user):
            raise HTTPException(403, "Only a DMS super user can send a test notification")
        base = s.page_url or "/dms/dms-page?lang=EN"
        sp().notify(to=[user.email], subject="DMS test notification / הודעת בדיקה",
                    body="This is a test of the DMS notifications (DMS Notifications list + DC-P2 flow). זוהי הודעת בדיקה.",
                    link=base, ref="TEST")
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
        return {"email": user.email, "name": user.name, "admin": is_admin(user)}

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
            if len(parts) >= 4 and parts[2].lower() == "projects":
                ctx["project"] = {"name": parts[3], "path": os.path.join(s.repository_root, *parts[:4])}
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
        for f in result["files"]:
            d = find_registered(f["path"], idx)
            f["document"] = with_key(d) if d else None
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
        folder = os.path.join(files.resolve(s.repository_root, customer), "Projects")
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
               user: User = Depends(current_user)):
        """Save a file from the user's PC into a folder of the repository (the user needs write access there)."""
        target_dir = files.resolve(s.repository_root, folder)
        if not os.path.isdir(target_dir):
            raise HTTPException(404, "Folder not found")
        if files.in_workflow_folder(s.repository_root, target_dir):
            raise HTTPException(403, "Workflow folders are managed by the DMS")
        if not user.can(target_dir, "write"):
            raise HTTPException(403, "You do not have permission to save files in this folder")
        try:
            path = files.save_upload(s.repository_root, target_dir, file.filename or "", file.file,
                                     s.max_upload_mb * 1024 * 1024, overwrite)
        except FileExistsError:
            raise HTTPException(409, "A file with this name already exists in the folder") from None
        except (ValueError, PermissionError) as e:
            raise HTTPException(400, str(e)) from None
        log(user, "upload", path)
        d = find_registered(path, register_index())
        return {"name": os.path.basename(path), "path": path, "document": with_key(d) if d else None}

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

    @app.post("/api/folders", status_code=201)
    def new_folder(req: NewFolderRequest, user: User = Depends(current_user)):
        parent = files.resolve(s.repository_root, req.parent)
        if files.in_workflow_folder(s.repository_root, parent):
            raise HTTPException(403, "Workflow folders are managed by the DMS")
        if not user.can(parent, "write"):
            raise HTTPException(403, "You do not have permission to create folders here")
        try:
            path = files.make_folder(s.repository_root, parent, req.name)
        except FileExistsError:
            raise HTTPException(409, "A folder with this name already exists") from None
        except FileNotFoundError:
            raise HTTPException(404, "Folder not found") from None
        log(user, "new-folder", path)
        return {"name": os.path.basename(path), "path": path}

    @app.post("/api/items/rename")
    def rename(req: RenameRequest, user: User = Depends(current_user)):
        full = files.resolve(s.repository_root, req.path)
        if not (user.can(full, "write") and user.can(os.path.dirname(full), "write")):
            raise HTTPException(403, "You do not have permission to rename this item")
        if os.path.exists(full):
            files.check_editable(s.repository_root, full, s.protected_depth)   # workflow folders first: clearest reason
        if blueprint.describe(rel_parts(full)) is not None:
            raise HTTPException(403, "This folder is part of the company skeleton (blueprint) and cannot be renamed. Its content can.")
        d = registered_inside(full)
        if d:
            raise HTTPException(409, f"It holds a controlled document ({d.get('documentId')}) and cannot be renamed")
        try:
            path = files.rename_item(s.repository_root, full, req.newName, s.protected_depth)
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
        if blueprint.describe(rel_parts(full)) is not None:
            raise HTTPException(403, "This folder is part of the company skeleton (blueprint) and cannot be deleted. Its content can.")
        d = registered_inside(full)
        if d:
            raise HTTPException(409, f"It holds a controlled document ({d.get('documentId')}) and cannot be deleted")
        try:
            moved = files.delete_item(s.repository_root, full, s.protected_depth, user.email)
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
        approvals = [e for e in cycle if e["event"] == c["ApprovedEvent"]]
        stage1 = {e["actor"] for e in approvals if (e.get("details") or "").startswith("Stage 1")}
        su = any((e.get("details") or "").startswith("Stage 1 (super user)") for e in approvals)
        pending1 = [] if su else [m for m in rule["mandatory"] if m not in stage1]
        extra = {"chosen": bool(rule.get("chosen")), "final": rule.get("final")}
        if pending1:
            return {"stage": 1, "pending": pending1, "approved": sorted(stage1), "rule": True, **extra}
        return {"stage": 2, "pending": [rule["final"]] if rule["final"] else [], "approved": sorted(stage1), "rule": True, **extra}

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
        texts = {
            "waiting": (f"{doc_id} {title} - waiting for your approval / ממתין לאישורך",
                        "approvals", f"{doc_id} \"{title}\" is waiting for your approval. מסמך {doc_id} ממתין לאישורך."),
            "approved": (f"{doc_id} {title} - approved / אושר", "workflows",
                         f"{doc_id} \"{title}\" was approved. המסמך {doc_id} אושר."),
            "rejected": (f"{doc_id} {title} - rejected / נדחה", "workflows",
                         f"{doc_id} \"{title}\" was rejected: {comment}. המסמך {doc_id} נדחה: {comment}"),
            "withdrawn": (f"{doc_id} {title} - withdrawn / נמשך", "approvals",
                          f"{doc_id} \"{title}\" was withdrawn and no longer needs your approval. המסמך {doc_id} נמשך ואינו ממתין עוד לאישורך."),
        }
        subject, view, body = texts[kind]
        base = s.page_url or "/dms/dms-page?lang=EN"
        link = base + ("&" if "?" in base else "?") + f"view={view}"
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
                path = d.get("workingUncPath") or ""
                folder = os.path.dirname(path)
                in_sub = os.path.join(folder if os.path.basename(folder) != "Submitted" else os.path.dirname(folder), "Submitted", os.path.basename(path))
                file = in_sub if path and os.path.isfile(in_sub) else path
                out.append({**with_key(d), **st, "submittedUtc": submitted["utc"] if submitted else None,
                            "submittedBy": submitted["actor"] if submitted else None, "file": file,
                            "officeUri": files.office_uri(file) if file else None, "mine": user.email in st["pending"]})
        return sorted(out, key=lambda x: x.get("submittedUtc") or "")

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
        doc_id = d.get("documentId") or f"ID {item_id}"
        if not req.approve:
            sp().update(item_id, {"LifecycleStatus": c["Working"]})
            sp().audit(document_id=doc_id, event=c["RejectedEvent"], from_status=c["Submitted"], to_status=c["Working"],
                       actor=user.email, details=f"{tag}: {req.comment.strip()}")
            file_back(d, c["Working"])
        else:
            if st["stage"] == 2:
                final = True
            else:                                               # stage 1 ends when nobody is left; then the final approver
                left = [] if su else [p for p in st["pending"] if p != user.email]
                final = not left and not st.get("final")
            if final:
                sp().update(item_id, {"LifecycleStatus": c["Approved_ReadOnly"], "LastApprovedUtc": datetime.now(timezone.utc).isoformat()})
            sp().audit(document_id=doc_id, event=c["ApprovedEvent"], from_status=c["Submitted"],
                       to_status=c["Approved_ReadOnly"] if final else c["Submitted"], actor=user.email,
                       details=tag + (f": {req.comment.strip()}" if req.comment.strip() else ""))
        log(user, "approve" if req.approve else "reject", f"{doc_id} {tag}")
        after = sp().document(item_id)
        if not req.approve:
            notify("rejected", after, [after.get("ownerEmail") or ""], req.comment.strip())
        elif after.get("lifecycleStatus") == c["Approved_ReadOnly"]:
            notify("approved", after, [after.get("ownerEmail") or ""])
        elif st["stage"] == 1 and approval_state(after, events_by_doc().get(after.get("documentId") or "", []), {})["stage"] == 2:
            notify_stage(after)                                 # stage 1 complete: the final approver
        d = with_key(sp().document(item_id))
        if d["statusKey"] == "Submitted":
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
        current = to_root(s.repository_root, d.get("currentUncPath"))
        if not current or not os.path.isfile(current):
            raise HTTPException(409, "The approved file was not found on the file server")
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
        log(user, "revise", f"{d.get('documentId')} -> {target}")
        if submit:
            return {**submit_doc(item_id, None, user), "draft": target, "officeUri": files.office_uri(target)}
        return {**with_key(sp().document(item_id)), "draft": target, "officeUri": files.office_uri(target)}

    @app.post("/api/documents/{item_id}/share")
    def share(item_id: int, req: ShareRequest, user: User = Depends(current_user)):
        """Share the approved revision with a customer: a copy goes to the Large File Exchange site
        (<library>/Outbound/<DocumentId>_RevNN/) and SharePoint invites the person (view only, B2B guest).
        Only approved documents, by the owner or a DMS super user; written to Control Audit."""
        from .file_service import to_root
        c = s.choices
        if s.sharepoint != "memory" and not s.ex_site_url:
            raise HTTPException(409, "Sharing with customers is not configured (DMS_EX_SITE_URL)")
        d = sp().document(item_id)
        if d.get("lifecycleStatus") != c["Approved_ReadOnly"]:
            raise HTTPException(409, "Only an approved document can be shared with a customer")
        if (d.get("ownerEmail") or "").lower() != user.email and not is_admin(user):
            raise HTTPException(403, "Only the document owner (or a DMS super user) can share it")
        current = to_root(s.repository_root, d.get("currentUncPath"))
        if not current or not os.path.isfile(current):
            raise HTTPException(409, "The approved file was not found on the file server")
        if not user.can(current):
            raise HTTPException(403, "You do not have access to this document")
        rev = str(d.get("currentRevision") or files.parse_revision(os.path.basename(current))[1] or 1).zfill(2)
        doc_id = d.get("documentId") or f"ID {item_id}"
        email = req.email.strip().lower()
        message = req.message.strip() or (f"RH shares with you {d.get('title')} (revision {rev}). "
                                          f"The link is personal and opens the file for viewing.")
        r = sp().share_with_guest(local_path=current, folder=f"{s.ex_folder}/{doc_id}_Rev{rev}", email=email,
                                  subject=f"RH - {d.get('title')} (Rev {rev})", message=message)
        sp().audit(document_id=doc_id, event=c["PermissionChanged"], from_status=c["Approved_ReadOnly"],
                   to_status=c["Approved_ReadOnly"], actor=user.email,
                   details=f"Shared revision {rev} with {email} (view only, Large File Exchange): {r['url']}")
        log(user, "share", f"{doc_id} Rev{rev} -> {email}")
        return {"url": r["url"], "email": email, "revision": rev, "documentId": doc_id}

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
                               dry_run=req.dryRun, copy_missing=req.copyMissing, update_links=req.updateLinks)
        log(user, "first-load", f"{'dry run ' if req.dryRun else ''}{source} -> {target}")
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
