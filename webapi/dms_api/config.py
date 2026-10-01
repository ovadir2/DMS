"""Settings, read from environment variables (or a .env file next to the service)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


# Choice values as stored in the lists. The DocumentControl site is provisioned in Hebrew.
CHOICES = {
    "he": {"Working": "בעבודה", "Submitted": "הוגש לאישור", "Approved_ReadOnly": "מאושר - קריאה בלבד",
           "Created": "נוצר", "SubmittedEvent": "הוגש", "Manual": "ידני",
           "ApprovedEvent": "אושר", "RejectedEvent": "נדחה", "FileDone": "פעולת קובץ הושלמה",
           "FileFailed": "פעולת קובץ נכשלה", "WorkflowService": "שירות תהליכים", "Cancelled": "בוטל",
           "StatusChanged": "שינוי סטטוס", "PermissionChanged": "שינוי הרשאות"},
    "en": {"Working": "Working", "Submitted": "Submitted", "Approved_ReadOnly": "Approved_ReadOnly",
           "Created": "Created", "SubmittedEvent": "Submitted", "Manual": "Manual",
           "ApprovedEvent": "Approved", "RejectedEvent": "Rejected", "FileDone": "FileActionCompleted",
           "FileFailed": "FileActionFailed", "WorkflowService": "WorkflowService", "Cancelled": "Cancelled",
           "StatusChanged": "StatusChanged", "PermissionChanged": "PermissionChanged"},
}

# Folders the Workflow Service manages next to each controlled file.
WORKFLOW_FOLDERS = ("Working", "Submitted", "Current_ReadOnly", "Obsolete_ReadOnly")


@dataclass
class Settings:
    repository_root: str = ""
    site_url: str = ""                      # https://rhisrael.sharepoint.com/sites/DocumentControl-TEST
    tenant_id: str = ""
    client_id: str = ""                     # app-only access to SharePoint (certificate)
    cert_path: str = ""                     # PEM with the private key
    cert_thumbprint: str = ""
    choice_language: str = "he"
    auth_mode: str = "windows"              # windows | entra | header | dev (see auth.py)
    api_audience: str = ""                  # entra: the app (client) id of the DMS app registration
    spa_client_id: str = ""                 # entra: app id the built-in page signs in with
    user_header: str = "X-MS-CLIENT-PRINCIPAL-NAME"   # header: set by the trusted reverse proxy
    dev_user: str = ""                      # dev: fixed user email, never in production
    allowed_origins: list[str] = field(default_factory=list)
    document_id_prefix: str = "DMS"
    register_cache_seconds: int = 30
    customers_folder: str = "02_Customers"  # under the root: one folder per customer
    max_upload_mb: int = 500
    search_limit: int = 200
    approvals: str = "flow"                 # flow (DC-P1 in Teams) | page (approve on the DMS page; turn DC-P1 off)
    ex_site_url: str = ""                   # Large File Exchange site, for sharing approved files with customers
    ex_library: str = "TemporaryUploads"
    ex_folder: str = "Outbound"
    fl_check_url: str = ""                  # File Linker WebAPI#1 (is a path registered?), {path} in the URL
    fl_update_url: str = ""                 # File Linker WebAPI#2 (replace a registered path)
    fl_update_method: str = "POST"
    fl_update_body: str = ""                # JSON template with {old} and {new}
    fl_registered_field: str = ""
    fl_auth: str = "windows"                # windows | bearer | none
    fl_token: str = ""
    notify: bool = True                     # page approvals: write DMS Notifications (email + Teams by DC-P2)
    page_url: str = ""                      # the DMS page address used in notification links
    admins: list[str] = field(default_factory=list)   # DMS super users: submit any document, see all workflows
    sp_auth: str = "certificate"            # certificate (server) | interactive (pilot on a PC, your own sign-in)
    file_service_seconds: int = 0           # >0: run the Workflow Service file moves inside the web service
    sharepoint: str = "online"              # online | memory (try the page on a PC without SharePoint)
    ai_url: str = ""                        # AI Insights: Open WebUI, e.g. https://chat.ai.rh-global.com
    ai_token: str = ""                      # service account token / API key of Open WebUI
    ai_model: str = ""                      # model id as listed in Open WebUI (empty: the first model offered)
    ai_knowledge_ids: list[str] = field(default_factory=list)   # knowledge bases for general questions
    ai_max_file_mb: int = 25
    rag_url: str = ""                       # AI Insights RAG tools (n8n webhook), e.g. https://aiportal.ai.rh-global.com/webhook/tools
    rag_tools: list[str] = field(default_factory=list)          # tools offered on the page, e.g. qms
    rag_token: str = ""                     # optional bearer token of the webhook
    rag_body: str = '{"tool": "{tool}", "chatInput": "{question}", "question": "{question}", "sessionId": "{session}", "lang": "{lang}", "user": "{user}"}'
    protected_depth: int = 2                # 02_Customers\Customer_A and above cannot be renamed or deleted

    @property
    def api_scope(self) -> str:
        if not self.api_audience:
            return ""
        base = self.api_audience if "://" in self.api_audience else f"api://{self.api_audience}"
        return f"{base}/access_as_user"

    @property
    def choices(self) -> dict[str, str]:
        return CHOICES[self.choice_language]

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        e = os.environ.get
        return cls(
            repository_root=e("DMS_REPOSITORY_ROOT", ""),
            site_url=e("DMS_SITE_URL", "").rstrip("/"),
            tenant_id=e("DMS_TENANT_ID", ""),
            client_id=e("DMS_CLIENT_ID", ""),
            cert_path=e("DMS_CERT_PATH", ""),
            cert_thumbprint=e("DMS_CERT_THUMBPRINT", ""),
            choice_language=e("DMS_CHOICE_LANGUAGE", "he"),
            auth_mode=e("DMS_AUTH_MODE", "windows"),
            api_audience=e("DMS_API_AUDIENCE", ""),
            spa_client_id=e("DMS_SPA_CLIENT_ID", ""),
            user_header=e("DMS_USER_HEADER", "X-MS-CLIENT-PRINCIPAL-NAME"),
            dev_user=e("DMS_DEV_USER", ""),
            allowed_origins=[o.strip() for o in e("DMS_ALLOWED_ORIGINS", "").split(",") if o.strip()],
            document_id_prefix=e("DMS_DOCUMENT_ID_PREFIX", "DMS"),
            register_cache_seconds=int(e("DMS_REGISTER_CACHE_SECONDS", "30")),
            customers_folder=e("DMS_CUSTOMERS_FOLDER", "02_Customers"),
            max_upload_mb=int(e("DMS_MAX_UPLOAD_MB", "500")),
            search_limit=int(e("DMS_SEARCH_LIMIT", "200")),
            protected_depth=int(e("DMS_PROTECTED_DEPTH", "2")),
            sharepoint=e("DMS_SHAREPOINT", "online"),
            sp_auth=e("DMS_SP_AUTH", "certificate"),
            approvals=e("DMS_APPROVALS", "flow"),
            ex_site_url=e("DMS_EX_SITE_URL", "").rstrip("/"),
            ex_library=e("DMS_EX_LIBRARY", "TemporaryUploads"),
            ex_folder=e("DMS_EX_FOLDER", "Outbound"),
            fl_check_url=e("DMS_FL_CHECK_URL", ""),
            fl_update_url=e("DMS_FL_UPDATE_URL", ""),
            fl_update_method=e("DMS_FL_UPDATE_METHOD", "POST"),
            fl_update_body=e("DMS_FL_UPDATE_BODY", ""),
            fl_registered_field=e("DMS_FL_REGISTERED_FIELD", ""),
            fl_auth=e("DMS_FL_AUTH", "windows"),
            fl_token=e("DMS_FL_TOKEN", ""),
            notify=e("DMS_NOTIFY", "1") not in ("0", "false", "no"),
            page_url=e("DMS_PAGE_URL", ""),
            admins=[a.strip().lower() for a in e("DMS_ADMINS", "").split(",") if a.strip()],
            file_service_seconds=int(e("DMS_FILE_SERVICE_SECONDS", "0")),
            ai_url=e("DMS_AI_URL", "https://chat.ai.rh-global.com"),
            ai_token=e("DMS_AI_TOKEN", ""),
            ai_model=e("DMS_AI_MODEL", ""),
            ai_knowledge_ids=[k.strip() for k in e("DMS_AI_KNOWLEDGE_IDS", "").split(",") if k.strip()],
            ai_max_file_mb=int(e("DMS_AI_MAX_FILE_MB", "25")),
            rag_url=e("DMS_RAG_URL", "https://aiportal.ai.rh-global.com/webhook/tools"),
            rag_tools=[k.strip() for k in e("DMS_RAG_TOOLS", "qms").split(",") if k.strip()],
            rag_token=e("DMS_RAG_TOKEN", ""),
            rag_body=e("DMS_RAG_BODY", Settings.rag_body),
        )
