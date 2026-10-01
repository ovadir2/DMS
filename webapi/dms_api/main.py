"""DMS Web API: browse the controlled repository, register a file and submit it for approval.

Run:  uvicorn dms_api.main:app --host 0.0.0.0 --port 8080
Docs: /docs (OpenAPI). Page: /dms/dms-page?lang=EN&path=<UNC>&name=<file>
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import files
from .auth import current_user
from .config import WORKFLOW_FOLDERS, Settings
from .sharepoint import SharePoint, SharePointError

STATIC = Path(__file__).resolve().parent / "static"


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
    app = FastAPI(title="RH DMS Web API", version="1.0")
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

    @app.get("/dms/dms-page", include_in_schema=False)
    def page():
        return FileResponse(STATIC / "dms-page.html", media_type="text/html; charset=utf-8")

    # ------------------------------------------------------------------ signed in
    @app.get("/api/me")
    def me(user: str = Depends(current_user)):
        return {"email": user}

    @app.get("/api/options")
    def options(_: str = Depends(current_user)):
        return {f: sp().choices(f) for f in ("DocumentType", "DocumentArea", "ControlMode")}

    @app.get("/api/browse")
    def browse(path: str | None = None, _: str = Depends(current_user)):
        try:
            result = files.list_folder(s.repository_root, path)
        except FileNotFoundError:
            raise HTTPException(404, "Folder not found") from None
        idx = register_index()
        for f in result["files"]:
            d = find_registered(f["path"], idx)
            f["document"] = with_key(d) if d else None
        return result

    @app.get("/api/documents")
    def documents(mine: bool = False, status: str | None = Query(None, description="Working | Submitted | Approved_ReadOnly"),
                  user: str = Depends(current_user)):
        docs = [with_key(d) for d in sp().documents()]
        if mine:
            docs = [d for d in docs if (d.get("ownerEmail") or "").lower() == user]
        if status:
            docs = [d for d in docs if d["statusKey"] == status]
        return sorted(docs, key=lambda d: d.get("modified") or "", reverse=True)

    @app.get("/api/documents/{item_id}")
    def document(item_id: int, _: str = Depends(current_user)):
        return with_key(sp().document(item_id))

    @app.post("/api/documents", status_code=201)
    def register(req: RegisterRequest, user: str = Depends(current_user)):
        path = files.resolve(s.repository_root, req.path)
        if not os.path.isfile(path):
            raise HTTPException(404, "File not found")
        if os.path.basename(os.path.dirname(path)) in WORKFLOW_FOLDERS[1:]:
            raise HTTPException(409, "The file is already in a workflow folder")
        existing = find_registered(path, register_index())
        if existing:
            raise HTTPException(409, {"message": "The file is already registered", "document": with_key(existing)})
        title = req.title or os.path.splitext(os.path.basename(path))[0]
        doc = sp().create_document(title=title, path=path, document_type=req.documentType,
                                   document_area=req.documentArea, owner_email=user,
                                   control_mode=req.controlMode, document_id=req.documentId)
        sp().audit(document_id=doc["documentId"], event=s.choices["Created"], from_status="",
                   to_status=s.choices["Working"], actor=user, details=f"Registered from the DMS page: {path}")
        if req.submit:
            return submit(doc["id"], user)
        return with_key(doc)

    @app.post("/api/documents/{item_id}/submit")
    def submit(item_id: int, user: str = Depends(current_user)):
        doc = sp().document(item_id)
        if (doc.get("ownerEmail") or "").lower() != user:
            raise HTTPException(403, "Only the document owner can submit it")
        if doc.get("lifecycleStatus") != s.choices["Working"]:
            raise HTTPException(409, f"Only a document in {s.choices['Working']} can be submitted")
        if not doc.get("workingUncPath") or not os.path.isfile(files.resolve(s.repository_root, doc["workingUncPath"])):
            raise HTTPException(409, "The working file was not found on the file server")
        sp().update(item_id, {"LifecycleStatus": s.choices["Submitted"]})
        sp().audit(document_id=doc["documentId"], event=s.choices["SubmittedEvent"], from_status=s.choices["Working"],
                   to_status=s.choices["Submitted"], actor=user, details="Submitted from the DMS page")
        return with_key(sp().document(item_id))

    @app.get("/api/files/download")
    def download(path: str, _: str = Depends(current_user)):
        full = files.resolve(s.repository_root, path)
        if not os.path.isfile(full):
            raise HTTPException(404, "File not found")
        return FileResponse(full, filename=os.path.basename(full))

    return app


app = create_app()
