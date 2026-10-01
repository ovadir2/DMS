"""Document Register and Control Audit through the SharePoint REST API, app-only (certificate).

The Entra app needs Sites.Selected with write on the DocumentControl site (the same grant as
RH-DMS-Workflow-Service, docs/02). No user credentials are stored.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests

from .config import Settings

REGISTER = "Lists/DocumentRegister"
AUDIT = "Lists/ControlAudit"
REGISTER_FIELDS = ("Id", "Title", "DocumentId", "DocumentType", "DocumentArea", "ControlMode", "LifecycleStatus",
                   "WorkingUncPath", "CurrentUncPath", "CurrentSHA256", "CurrentRevision", "LastApprovedUtc",
                   "Modified", "Created")


class SharePointError(Exception):
    pass


class SharePoint:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.s = settings
        u = urlparse(settings.site_url)
        self.host = f"{u.scheme}://{u.netloc}"
        self.site_path = u.path.rstrip("/")
        self.http = session or requests.Session()
        self._token: tuple[str, float] | None = None
        self._cache: tuple[list[dict], float] | None = None

    # ------------------------------------------------------------------ plumbing
    def _access_token(self) -> str:
        if self._token and self._token[1] > time.time() + 60:
            return self._token[0]
        import msal  # imported here so the tests run without network access

        with open(self.s.cert_path, encoding="utf-8") as f:
            key = f.read()
        app = msal.ConfidentialClientApplication(
            self.s.client_id, authority=f"https://login.microsoftonline.com/{self.s.tenant_id}",
            client_credential={"private_key": key, "thumbprint": self.s.cert_thumbprint})
        r = app.acquire_token_for_client(scopes=[f"{self.host}/.default"])
        if "access_token" not in r:
            raise SharePointError(f"Token request failed: {r.get('error_description') or r.get('error')}")
        self._token = (r["access_token"], time.time() + int(r.get("expires_in", 3600)))
        return self._token[0]

    def _call(self, method: str, url: str, json: dict | None = None, headers: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self._access_token()}", "Accept": "application/json;odata=nometadata",
             "Content-Type": "application/json;odata=nometadata"}
        h.update(headers or {})
        r = self.http.request(method, url, json=json, headers=h, timeout=30)
        if r.status_code >= 400:
            raise SharePointError(f"{method} {url.split('?')[0]} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def _list(self, rel: str) -> str:
        return f"{self.s.site_url}/_api/web/GetList('{quote(self.site_path + '/' + rel)}')"

    # ------------------------------------------------------------------ register
    def documents(self, refresh: bool = False) -> list[dict]:
        if not refresh and self._cache and self._cache[1] > time.time():
            return self._cache[0]
        select = ",".join(REGISTER_FIELDS) + ",DocumentOwner/EMail,DocumentOwner/Title"
        url = f"{self._list(REGISTER)}/items?$select={select}&$expand=DocumentOwner&$top=2000"
        items: list[dict] = []
        while url:
            page = self._call("GET", url)
            items.extend(page.get("value", []))
            url = page.get("odata.nextLink")
        docs = [self._doc(i) for i in items]
        self._cache = (docs, time.time() + self.s.register_cache_seconds)
        return docs

    def document(self, item_id: int) -> dict:
        select = ",".join(REGISTER_FIELDS) + ",DocumentOwner/EMail,DocumentOwner/Title"
        return self._doc(self._call("GET", f"{self._list(REGISTER)}/items({item_id})?$select={select}&$expand=DocumentOwner"))

    @staticmethod
    def _doc(i: dict) -> dict:
        owner = i.get("DocumentOwner") or {}
        d = {k[0].lower() + k[1:]: i.get(k) for k in REGISTER_FIELDS}
        d["id"] = i.get("Id")
        d["ownerEmail"] = owner.get("EMail")
        d["ownerName"] = owner.get("Title")
        return d

    def _user_id(self, email: str) -> int:
        r = self._call("POST", f"{self.s.site_url}/_api/web/ensureuser",
                       json={"logonName": f"i:0#.f|membership|{email}"})
        return r["Id"]

    def create_document(self, *, title: str, path: str, document_type: str, document_area: str,
                        owner_email: str, control_mode: str | None, document_id: str | None) -> dict:
        values = {"Title": title, "DocumentId": document_id or "NEW", "DocumentType": document_type,
                  "DocumentArea": document_area, "LifecycleStatus": self.s.choices["Working"],
                  "WorkingUncPath": path, "DocumentOwnerId": self._user_id(owner_email)}
        if control_mode:
            values["ControlMode"] = control_mode
        item = self._call("POST", f"{self._list(REGISTER)}/items", json=values)
        item_id = item["Id"]
        if not document_id:
            self.update(item_id, {"DocumentId": f"{self.s.document_id_prefix}-{item_id:05d}"})
        self._cache = None
        return self.document(item_id)

    def update(self, item_id: int, values: dict) -> None:
        self._call("POST", f"{self._list(REGISTER)}/items({item_id})", json=values,
                   headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "*"})
        self._cache = None

    def choices(self, field: str) -> list[str]:
        r = self._call("GET", f"{self._list(REGISTER)}/fields/getbyinternalnameortitle('{field}')?$select=Choices")
        return list(r.get("Choices") or [])

    # ------------------------------------------------------------------ audit
    def audit(self, *, document_id: str, event: str, from_status: str, to_status: str, actor: str, details: str) -> None:
        self._call("POST", f"{self._list(AUDIT)}/items", json={
            "Title": f"{event} {document_id}", "CorrelationId": document_id, "AuditEventType": event,
            "FromStatus": from_status, "ToStatus": to_status, "ActorEmail": actor,
            "EventUtc": datetime.now(timezone.utc).isoformat(), "EventSource": self.s.choices["Manual"],
            "EventDetails": details})
