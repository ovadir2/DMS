"""Settings, read from environment variables (or a .env file next to the service)."""
from __future__ import annotations

import os
import re
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
            value = re.sub(r"\s+#.*$", "", value).strip()       # a comment after the value (" # ...")
            os.environ.setdefault(key.strip(), value.strip("'\""))


def _short_paths(value: str) -> dict:
    """DMS_SHORT_PATHS=02_Customers=\\\\fs\\Customers;01_General=\\\\fs\\General -> {folder: short path}."""
    out = {}
    for part in value.split(";"):
        if "=" in part:
            folder, short = part.split("=", 1)
            if folder.strip() and short.strip():
                out[folder.strip().strip("\\/")] = short.strip().rstrip("\\/")
    return out


# Choice values as stored in the lists. The DocumentControl site is provisioned in Hebrew.
CHOICES = {
    "he": {"Working": "בעבודה", "Submitted": "הוגש לאישור", "Approved_ReadOnly": "מאושר - קריאה בלבד",
           "Created": "נוצר", "SubmittedEvent": "הוגש", "Manual": "ידני",
           "ApprovedEvent": "אושר", "RejectedEvent": "נדחה", "FileDone": "פעולת קובץ הושלמה",
           "FileFailed": "פעולת קובץ נכשלה", "WorkflowService": "שירות תהליכים", "Cancelled": "בוטל",
           "StatusChanged": "שינוי סטטוס", "PermissionChanged": "שינוי הרשאות", "Archived": "בארכיון"},
    "en": {"Working": "Working", "Submitted": "Submitted", "Approved_ReadOnly": "Approved_ReadOnly",
           "Created": "Created", "SubmittedEvent": "Submitted", "Manual": "Manual",
           "ApprovedEvent": "Approved", "RejectedEvent": "Rejected", "FileDone": "FileActionCompleted",
           "FileFailed": "FileActionFailed", "WorkflowService": "WorkflowService", "Cancelled": "Cancelled",
           "StatusChanged": "StatusChanged", "PermissionChanged": "PermissionChanged", "Archived": "Archived"},
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
    dev_users: list[str] = field(default_factory=list)  # dev: other users to act as (page: "Acting as"), testing only
    dev_ad_check: bool = False              # dev: check AD / NTFS for each user (not the DMS_ADMINS), domain PC only
    remote_signin: str = ""                 # dev: ntlm = other PCs sign in with their own Windows account (ntlm.py); off
    allowed_origins: list[str] = field(default_factory=list)
    document_id_prefix: str = "DMS"
    register_cache_seconds: int = 30
    customers_folder: str = "02_Customers"  # under the root: one folder per customer
    client_root: str = ""                            # the root as other PCs open it (\\server\Shares, not e$)
    short_paths: dict = field(default_factory=dict)  # folder under the root -> shorter path users open and copy
    max_upload_mb: int = 500
    search_limit: int = 200
    approvals: str = "flow"                 # flow (DC-P1 in Teams) | page (approve on the DMS page; turn DC-P1 off)
    ex_site_url: str = ""                   # Large File Exchange site, for sharing approved files with customers
    ex_library: str = "TemporaryUploads"
    ex_folder: str = "Outbound"
    shared_log: str = "Shared/DMS-Shared-Log.csv"  # per customer folder: every share appended (empty: off)
    first_load_approver: str = "dms_approval@rh.co.il"  # First loading "DMS approval": recorded as the approver
    submitted_editable: bool = True        # during approval the owner and the approvers may edit (remarks) the submitted file
    ex_days: int = 3                        # shared files are removed from the Exchange site N days after their last share (0: never)
    ex_shortcut: bool = True                # add a OneDrive shortcut DMS_<Customer> to the customer folder
    ex_shortcut_folder: str = "DMS Shortcuts"  # the OneDrive folder that holds the shortcuts (created if missing)
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
    ai_model: str = "org-chat"              # the model the RH AI chat page uses
    ai_path: str = "/stream"                # the chat endpoint under DMS_AI_URL
    ai_upload_path: str = "/upload"         # file upload (📎) under DMS_AI_URL; empty: send the file's text
    ai_max_tokens: int = 4096
    ai_max_chars: int = 60000               # document text sent with a question about a file
    ai_knowledge_ids: list[str] = field(default_factory=list)   # knowledge bases for general questions
    ai_max_file_mb: int = 25
    delegation_days: int = 3                # a delegation is valid this many working days after today
    weekend: list[int] = field(default_factory=lambda: [4, 5])   # Friday, Saturday (Python weekday numbers)
    rag_url: str = ""                       # AI Insights RAG tools (n8n), e.g. https://aiportal.ai.rh-global.com/webhook
    rag_tools: list[str] = field(default_factory=list)          # tools offered on the page, e.g. qms
    rag_token: str = ""                     # optional bearer token of the webhook
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
            dev_users=[a.strip().lower() for a in e("DMS_DEV_USERS", "").split(",") if a.strip()],
            dev_ad_check=e("DMS_DEV_AD_CHECK", "").strip().lower() in ("1", "true", "yes", "on"),
            remote_signin=e("DMS_REMOTE_SIGNIN", "ntlm" if os.name == "nt" else "off").strip().lower(),
            allowed_origins=[o.strip() for o in e("DMS_ALLOWED_ORIGINS", "").split(",") if o.strip()],
            document_id_prefix=e("DMS_DOCUMENT_ID_PREFIX", "DMS"),
            register_cache_seconds=int(e("DMS_REGISTER_CACHE_SECONDS", "30")),
            customers_folder=e("DMS_CUSTOMERS_FOLDER", "02_Customers"),
            client_root=e("DMS_CLIENT_ROOT", ""),
            short_paths=_short_paths(e("DMS_SHORT_PATHS", "")),
            max_upload_mb=int(e("DMS_MAX_UPLOAD_MB", "500")),
            search_limit=int(e("DMS_SEARCH_LIMIT", "200")),
            protected_depth=int(e("DMS_PROTECTED_DEPTH", "2")),
            sharepoint=e("DMS_SHAREPOINT", "online"),
            sp_auth=e("DMS_SP_AUTH", "certificate"),
            approvals=e("DMS_APPROVALS", "flow"),
            ex_site_url=e("DMS_EX_SITE_URL", "").rstrip("/"),
            ex_library=e("DMS_EX_LIBRARY", "TemporaryUploads"),
            ex_folder=e("DMS_EX_FOLDER", "Outbound"),
            ex_days=int(e("DMS_EX_DAYS", "3")),
            first_load_approver=e("DMS_FIRST_LOAD_APPROVER", "dms_approval@rh.co.il").strip().lower(),
            submitted_editable=e("DMS_SUBMITTED_EDITABLE", "true").lower() not in ("0", "false", "no", "off"),
            shared_log=e("DMS_SHARED_LOG", "Shared/DMS-Shared-Log.csv").strip("/\\ "),
            ex_shortcut=e("DMS_EX_SHORTCUT", "true").lower() not in ("0", "false", "no", "off"),
            ex_shortcut_folder=e("DMS_EX_SHORTCUT_FOLDER", "DMS Shortcuts").strip("/\\ "),
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
            ai_model=e("DMS_AI_MODEL", "org-chat"),
            ai_path=e("DMS_AI_PATH", "/stream"),
            ai_upload_path=e("DMS_AI_UPLOAD_PATH", "/upload"),
            ai_max_tokens=int(e("DMS_AI_MAX_TOKENS", "4096")),
            ai_max_chars=int(e("DMS_AI_MAX_CHARS", "60000")),
            ai_knowledge_ids=[k.strip() for k in e("DMS_AI_KNOWLEDGE_IDS", "").split(",") if k.strip()],
            ai_max_file_mb=int(e("DMS_AI_MAX_FILE_MB", "25")),
            delegation_days=int(e("DMS_DELEGATION_DAYS", "3")),
            weekend=[["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(d.strip().lower()[:3])
                     for d in e("DMS_WEEKEND", "fri,sat").split(",") if d.strip()],
            rag_url=e("DMS_RAG_URL", "https://aiportal.ai.rh-global.com/webhook"),
            rag_tools=[k.strip() for k in e("DMS_RAG_TOOLS", "qms").split(",") if k.strip()],
            rag_token=e("DMS_RAG_TOKEN", ""),
        )
