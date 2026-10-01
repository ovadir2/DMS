"""DMS Web API: browse the repository by customer (what AD allows), save files into it, register
a file and submit it for approval, and see each file's status.

Run:  uvicorn dms_api.main:app --host 0.0.0.0 --port 8080
Docs: /docs (OpenAPI). Page: /dms/dms-page?lang=EN&path=<UNC>&name=<file>
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import blueprint, files, finder
from .ai import AiError, OpenWebUI
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


class DeleteRequest(BaseModel):
    path: str


class RegisterRequest(BaseModel):
    path: str = Field(description="UNC path of the file, inside the repository root")
    title: str | None = Field(None, description="Defaults to the file name without the extension")
    documentType: str
    documentArea: str
    controlMode: str | None = None
    documentId: str | None = Field(None, description="Defaults to <prefix>-<item id>, e.g. DMS-00012")
    submit: bool = Field(False, description="Also submit it for approval")


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    path: str | None = Field(None, description="A repository file to ask about; without it the knowledge bases are used")
    lang: str = "EN"


class DecisionRequest(BaseModel):
    approve: bool
    comment: str = Field("", max_length=1000)


class FindRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    lang: str = "EN"


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

    @app.exception_handler(SharePointError)
    async def _sp(_: Request, e: SharePointError):
        return JSONResponse({"detail": f"SharePoint: {e}"}, status_code=502)

    # ------------------------------------------------------------------ public
    @app.get("/api/health")
    def health():
        return {"status": "ok", "repositoryRoot": s.repository_root, "rootReachable": os.path.isdir(s.repository_root)}

    @app.get("/api/client-config")
    def client_config():
        return {"authMode": s.auth_mode, "playground": s.sharepoint == "memory", "fileService": s.file_service_seconds > 0,
                "approvals": s.approvals,
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

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return {"email": user.email, "name": user.name, "admin": is_admin(user)}

    @app.get("/api/options")
    def options(_: User = Depends(current_user)):
        return {f: sp().choices(f) for f in ("DocumentType", "DocumentArea", "ControlMode")}

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
    def search(q: str = Query(..., min_length=2), scope: str = Query("all", description="all | customer | project | document | file"),
               customer: str | None = Query(None, description="Customer folder path, to search inside one customer"),
               user: User = Depends(current_user)):
        """Customers, project folders, registered documents and file names the user may see."""
        out: list[dict] = []
        ql = q.lower()
        if scope in ("all", "customer"):
            out += [{"kind": "customer", **c} for c in customers(q, user)]
        if scope in ("all", "document"):
            for d in sp().documents():
                if (ql in (d.get("documentId") or "").lower() or ql in (d.get("title") or "").lower()) and visible(d, user):
                    out.append({"kind": "document", "name": d.get("title"), "path": doc_path(d), "document": with_key(d)})
        start = files.resolve(s.repository_root, customer) if customer else customers_root()
        if os.path.isdir(start) and scope in ("all", "project", "file"):
            idx = register_index()
            for hit in files.walk_search(start, q, user.can, s.search_limit, folders_only=scope == "project"):
                if hit["isFolder"]:
                    out.append({"kind": "folder", **hit})
                elif scope in ("all", "file"):
                    d = find_registered(hit["path"], idx)
                    out.append({"kind": "file", **hit, "document": with_key(d) if d else None})
        return out[: s.search_limit]

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

    def log(user: User, action: str, detail: str) -> None:
        """Service log; repository changes (upload, new folder, rename, delete) also go to Control Audit
        in SharePoint (CorrelationId FS), so every change is kept there with who and when."""
        logger.info("%s %s %s", user.email, action, detail)
        if action in FILE_OPS:
            root = s.repository_root.rstrip("\\/")
            short = detail.replace(root + os.sep, "").replace(root + "/", "").replace(root + "\\", "")
            try:
                sp().audit(document_id="FS", event=s.choices["FileDone"], from_status="", to_status="",
                           actor=user.email, details=f"{action}: {short}")
            except Exception as e:  # noqa: BLE001 - the change itself is done; do not fail the request
                logger.warning("audit row not written for %s: %s", action, e)

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

    def approval_state(d: dict, events: list[dict], rules: dict) -> dict:
        """Where a submitted document stands, by the DC-P1 rules: stage 1 = every mandatory approver,
        stage 2 = the final approver. Decisions of the current cycle are the audit rows after the last submission."""
        c = s.choices
        cycle = []
        for e in events:                                        # newest first
            if e["event"] in (c["SubmittedEvent"], c["RejectedEvent"], c["Cancelled"]):
                break
            cycle.append(e)
        t = d.get("documentType") or ""
        if t not in rules:
            rules[t] = sp().approver_rule(t)
        rule = rules[t]
        if not rule:
            return {"stage": None, "pending": [], "approved": [], "rule": False}
        approvals = [e for e in cycle if e["event"] == c["ApprovedEvent"]]
        stage1 = {e["actor"] for e in approvals if (e.get("details") or "").startswith("Stage 1")}
        su = any((e.get("details") or "").startswith("Stage 1 (super user)") for e in approvals)
        pending1 = [] if su else [m for m in rule["mandatory"] if m not in stage1]
        if pending1:
            return {"stage": 1, "pending": pending1, "approved": sorted(stage1), "rule": True}
        return {"stage": 2, "pending": [rule["final"]] if rule["final"] else [], "approved": sorted(stage1), "rule": True}

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
        else:
            if st["stage"] == 2:
                final = True
            else:                                               # stage 1 ends when nobody is left; then the final approver
                left = [] if su else [p for p in st["pending"] if p != user.email]
                final = not left and not sp().approver_rule(d.get("documentType") or "")["final"]
            if final:
                sp().update(item_id, {"LifecycleStatus": c["Approved_ReadOnly"], "LastApprovedUtc": datetime.now(timezone.utc).isoformat()})
            sp().audit(document_id=doc_id, event=c["ApprovedEvent"], from_status=c["Submitted"],
                       to_status=c["Approved_ReadOnly"] if final else c["Submitted"], actor=user.email,
                       details=tag + (f": {req.comment.strip()}" if req.comment.strip() else ""))
        log(user, "approve" if req.approve else "reject", f"{doc_id} {tag}")
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
        return {"enabled": app.state.ai.enabled, "model": s.ai_model, "knowledge": bool(s.ai_knowledge_ids)}

    @app.post("/api/ai/find")
    def ai_find(req: FindRequest, user: User = Depends(current_user)):
        """Find files from a free-text request, only among what the user may see. With AI Insights
        configured, the AI makes the search plan and ranks the matches with a reason; without it,
        the request's keywords are used."""
        ai: OpenWebUI = app.state.ai
        lang = "HE" if req.lang.upper() == "HE" else "EN"
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
        start, project = cust["path"] if cust else customers_root(), None
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
        for e in finder.walk_files(start, lambda p: user.can(p)):
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
        log(user, "ai-find", f"{req.question[:120]!r} -> {len(suggestions)}")
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
            raise HTTPException(503, "AI Insights is not configured (DMS_AI_URL, DMS_AI_TOKEN, DMS_AI_MODEL)")
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
            result = ai.ask(req.question, lang="HE" if req.lang.upper() == "HE" else "EN", file_path=path, context=context)
        except AiError as e:
            raise HTTPException(502, str(e)) from None
        except requests.RequestException as e:
            raise HTTPException(502, f"The AI service did not answer: {type(e).__name__}") from None
        log(user, "ai-ask", f"{path or 'knowledge'}: {req.question[:120]!r}")
        return result

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
        doc = sp().create_document(title=title, path=path, document_type=req.documentType,
                                   document_area=req.documentArea, owner_email=user.email,
                                   control_mode=req.controlMode, document_id=req.documentId)
        rev = files.parse_revision(os.path.basename(path))[1]
        sp().update(doc["id"], {"DraftRevision": f"{rev or 1:02d}"})
        sp().audit(document_id=doc["documentId"], event=s.choices["Created"], from_status="",
                   to_status=s.choices["Working"], actor=user.email,
                   details=f"Registered from the DMS page: {os.path.relpath(path, s.repository_root)}")
        if req.submit:
            return submit(doc["id"], user)
        return with_key(doc)

    @app.post("/api/documents/{item_id}/submit")
    def submit(item_id: int, user: User = Depends(current_user)):
        doc = sp().document(item_id)
        if (doc.get("ownerEmail") or "").lower() != user.email and not is_admin(user):
            raise HTTPException(403, "Only the document owner (or a DMS super user) can submit it")
        if doc.get("lifecycleStatus") != s.choices["Working"]:
            raise HTTPException(409, f"Only a document in {s.choices['Working']} can be submitted")
        if not doc.get("workingUncPath") or not os.path.isfile(files.resolve(s.repository_root, doc["workingUncPath"])):
            raise HTTPException(409, "The working file was not found on the file server")
        sp().update(item_id, {"LifecycleStatus": s.choices["Submitted"]})
        sp().audit(document_id=doc["documentId"], event=s.choices["SubmittedEvent"], from_status=s.choices["Working"],
                   to_status=s.choices["Submitted"], actor=user.email, details="Submitted from the DMS page")
        return with_key(sp().document(item_id))

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
            return {**submit_doc(item_id, user), "draft": target, "officeUri": files.office_uri(target)}
        return {**with_key(sp().document(item_id)), "draft": target, "officeUri": files.office_uri(target)}

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
        sp().update(item_id, {"LifecycleStatus": c["Working"]})
        sp().audit(document_id=doc.get("documentId") or f"ID {item_id}", event=c["Cancelled"], from_status=c["Submitted"],
                   to_status=c["Working"], actor=user.email, details="Withdrawn from the DMS page")
        log(user, "withdraw", doc.get("documentId") or str(item_id))
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
