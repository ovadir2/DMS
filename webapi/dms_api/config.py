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
           "Created": "נוצר", "SubmittedEvent": "הוגש", "Manual": "ידני"},
    "en": {"Working": "Working", "Submitted": "Submitted", "Approved_ReadOnly": "Approved_ReadOnly",
           "Created": "Created", "SubmittedEvent": "Submitted", "Manual": "Manual"},
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
    auth_mode: str = "entra"                # entra | header | dev
    api_audience: str = ""                  # entra: the app (client) id of the DMS app registration
    spa_client_id: str = ""                 # entra: app id the built-in page signs in with
    user_header: str = "X-MS-CLIENT-PRINCIPAL-NAME"   # header: set by the trusted reverse proxy
    dev_user: str = ""                      # dev: fixed user email, never in production
    allowed_origins: list[str] = field(default_factory=list)
    document_id_prefix: str = "DMS"
    register_cache_seconds: int = 30

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
            auth_mode=e("DMS_AUTH_MODE", "entra"),
            api_audience=e("DMS_API_AUDIENCE", ""),
            spa_client_id=e("DMS_SPA_CLIENT_ID", ""),
            user_header=e("DMS_USER_HEADER", "X-MS-CLIENT-PRINCIPAL-NAME"),
            dev_user=e("DMS_DEV_USER", ""),
            allowed_origins=[o.strip() for o in e("DMS_ALLOWED_ORIGINS", "").split(",") if o.strip()],
            document_id_prefix=e("DMS_DOCUMENT_ID_PREFIX", "DMS"),
            register_cache_seconds=int(e("DMS_REGISTER_CACHE_SECONDS", "30")),
        )
