"""Document Register and Control Audit through the SharePoint REST API.

DMS_SP_AUTH=certificate (server): app-only, the Entra app needs Sites.Selected with write on the
DocumentControl site (the same grant as RH-DMS-Workflow-Service, docs/02). No user credentials.
DMS_SP_AUTH=interactive (pilot on a PC): you sign in once in the browser with the Entra app you use
for PnP ($C); the token is cached in %LOCALAPPDATA%\\DMS and refreshed silently.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests

from .config import Settings

REGISTER = "Lists/DocumentRegister"
AUDIT = "Lists/ControlAudit"
REGISTER_FIELDS = ("Id", "Title", "DocumentId", "DocumentType", "DocumentArea", "ControlMode", "LifecycleStatus",
                   "WorkingUncPath", "CurrentUncPath", "CurrentSHA256", "CurrentRevision", "LastApprovedUtc",
                   "DraftRevision", "Modified", "Created")


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
        self.account_email: str | None = None
        self._public = None

    # ------------------------------------------------------------------ plumbing
    def _interactive_token(self) -> str:
        import msal  # imported here so the tests run without network access

        if self._public is None:
            folder = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "DMS")
            os.makedirs(folder, exist_ok=True)
            self._cache_file = os.path.join(folder, "sharepoint-token.bin")
            self._msal_cache = msal.SerializableTokenCache()
            if os.path.exists(self._cache_file):
                with open(self._cache_file, encoding="utf-8") as f:
                    self._msal_cache.deserialize(f.read())
            self._public = msal.PublicClientApplication(
                self.s.client_id, authority=f"https://login.microsoftonline.com/{self.s.tenant_id}", token_cache=self._msal_cache)
        scopes = [f"{self.host}/.default"]
        accounts = self._public.get_accounts()
        r = self._public.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
        if not r or "access_token" not in r:
            r = self._public.acquire_token_interactive(scopes, prompt="select_account")
        if "access_token" not in r:
            raise SharePointError(f"Sign-in failed: {r.get('error_description') or r.get('error')}")
        if self._msal_cache.has_state_changed:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                f.write(self._msal_cache.serialize())
        claims = r.get("id_token_claims") or {}
        acc = self._public.get_accounts()
        self.account_email = (claims.get("preferred_username") or (acc[0]["username"] if acc else "") or "").lower() or None
        self._token = (r["access_token"], time.time() + int(r.get("expires_in", 3600)))
        return self._token[0]

    def sign_in(self) -> str | None:
        """Interactive mode: sign in now (opens the browser the first time) and return the account."""
        self._access_token()
        return self.account_email

    def _access_token(self) -> str:
        if self._token and self._token[1] > time.time() + 60:
            return self._token[0]
        if self.s.sp_auth == "interactive":
            return self._interactive_token()
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
    def audit_events(self, refresh: bool = False) -> list[dict]:
        """Control Audit rows, newest first (pilot: the latest 5000)."""
        if not refresh and getattr(self, "_audit_cache", None) and self._audit_cache[1] > time.time():
            return self._audit_cache[0]
        url = (f"{self._list(AUDIT)}/items?$select=Id,CorrelationId,AuditEventType,FromStatus,ToStatus,ActorEmail,EventUtc,"
               f"EventSource,EventDetails&$orderby=EventUtc desc&$top=5000")
        rows = self._call("GET", url).get("value", [])
        events = [{"documentId": r.get("CorrelationId"), "event": r.get("AuditEventType"), "fromStatus": r.get("FromStatus"),
                   "toStatus": r.get("ToStatus"), "actor": (r.get("ActorEmail") or "").lower(), "utc": r.get("EventUtc"),
                   "source": r.get("EventSource"), "details": r.get("EventDetails")} for r in rows]
        self._audit_cache = (events, time.time() + self.s.register_cache_seconds)
        return events

    def audit(self, *, document_id: str, event: str, from_status: str, to_status: str, actor: str, details: str,
              source: str | None = None) -> None:
        self._call("POST", f"{self._list(AUDIT)}/items", json={
            "Title": f"{event} {document_id}", "CorrelationId": document_id, "AuditEventType": event,
            "FromStatus": from_status, "ToStatus": to_status, "ActorEmail": actor,
            "EventUtc": datetime.now(timezone.utc).isoformat(), "EventSource": source or self.s.choices["Manual"],
            "EventDetails": details})
        self._audit_cache = None
