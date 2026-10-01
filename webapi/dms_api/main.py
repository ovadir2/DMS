"""DMS Web API: browse the repository by customer (what AD allows), save files into it, register
a file and submit it for approval, and see each file's status.

Run:  uvicorn dms_api.main:app --host 0.0.0.0 --port 8080
Docs: /docs (OpenAPI). Page: /dms/dms-page?lang=EN&path=<UNC>&name=<file>
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import blueprint, files
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


def create_app(settings: Settings | None = None, sharepoint: SharePoint | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    app = FastAPI(title="RH DMS Web API", version="1.1")
    app.state.settings = s
    app.state.sp = sharepoint or SharePoint(s)
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
        return {"authMode": s.auth_mode, "tenantId": s.tenant_id, "clientId": s.spa_client_id,
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

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return {"email": user.email, "name": user.name}

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
            entries = [e for e in os.scandir(folder) if e.is_dir() and not e.name.startswith((".", "~$"))]
        except OSError:
            return []
        rank = {n.lower(): i for i, n in enumerate(blueprint.order(parts))}
        out = [{"name": e.name, "path": e.path, "label": blueprint.describe(parts + [e.name])} for e in entries
               if e.name not in WORKFLOW_FOLDERS and not (not parts and e.name in blueprint.HIDDEN_AT_ROOT) and user.can(e.path)]
        return sorted(out, key=lambda f: (rank.get(f["name"].lower(), len(rank)), f["name"].lower()))

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
        if not user.can(target_dir, "write"):
            raise HTTPException(403, "You do not have permission to save files in this folder")
        try:
            path = files.save_upload(s.repository_root, target_dir, file.filename or "", file.file,
                                     s.max_upload_mb * 1024 * 1024, overwrite)
        except FileExistsError:
            raise HTTPException(409, "A file with this name already exists in the folder") from None
        except (ValueError, PermissionError) as e:
            raise HTTPException(400, str(e)) from None
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

    def log(user: User, action: str, detail: str) -> None:
        logger.info("%s %s %s", user.email, action, detail)

    @app.post("/api/folders", status_code=201)
    def new_folder(req: NewFolderRequest, user: User = Depends(current_user)):
        parent = files.resolve(s.repository_root, req.parent)
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
        sp().audit(document_id=doc["documentId"], event=s.choices["Created"], from_status="",
                   to_status=s.choices["Working"], actor=user.email, details=f"Registered from the DMS page: {path}")
        if req.submit:
            return submit(doc["id"], user)
        return with_key(doc)

    @app.post("/api/documents/{item_id}/submit")
    def submit(item_id: int, user: User = Depends(current_user)):
        doc = sp().document(item_id)
        if (doc.get("ownerEmail") or "").lower() != user.email:
            raise HTTPException(403, "Only the document owner can submit it")
        if doc.get("lifecycleStatus") != s.choices["Working"]:
            raise HTTPException(409, f"Only a document in {s.choices['Working']} can be submitted")
        if not doc.get("workingUncPath") or not os.path.isfile(files.resolve(s.repository_root, doc["workingUncPath"])):
            raise HTTPException(409, "The working file was not found on the file server")
        sp().update(item_id, {"LifecycleStatus": s.choices["Submitted"]})
        sp().audit(document_id=doc["documentId"], event=s.choices["SubmittedEvent"], from_status=s.choices["Working"],
                   to_status=s.choices["Submitted"], actor=user.email, details="Submitted from the DMS page")
        return with_key(sp().document(item_id))

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
