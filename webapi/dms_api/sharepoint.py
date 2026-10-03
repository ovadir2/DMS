"""Document Register and Control Audit through the SharePoint REST API.

DMS_SP_AUTH=certificate (server): app-only, the Entra app needs Sites.Selected with write on the
DocumentControl site (the same grant as RH-DMS-Workflow-Service, docs/02). No user credentials.
DMS_SP_AUTH=interactive (pilot on a PC): you sign in once in the browser with the Entra app you use
for PnP ($C); the token is cached in %LOCALAPPDATA%\\DMS and refreshed silently.
"""
from __future__ import annotations

import os
import time
from json import dumps as json_dumps, loads as json_loads
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests

from .config import Settings

REGISTER = "Lists/DocumentRegister"
AUDIT = "Lists/ControlAudit"
MATRIX = "Lists/ApproverMatrix"
NOTIFY = "Lists/DmsNotifications"
DELEGATIONS = "Lists/Delegations"
DECISIONS = "Lists/ApprovalDecisions"
DECISION_HE = {"Approved": "אושר", "Rejected": "נדחה", "Delegated": "הואצל", "Mandatory": "חובה", "Final": "מאשר סופי"}
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

    def _call(self, method: str, url: str, json: dict | None = None, headers: dict | None = None,
              data: bytes | None = None) -> dict:
        h = {"Authorization": f"Bearer {self._access_token()}", "Accept": "application/json;odata=nometadata",
             "Content-Type": "application/octet-stream" if data is not None else "application/json;odata=nometadata"}
        h.update(headers or {})
        r = self.http.request(method, url, json=json, data=data, headers=h, timeout=300 if data is not None else 30)
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

    def approver_rule(self, document_type: str) -> dict | None:
        """The active Approver Matrix rule for a document type: {mandatory: [emails], final: email}."""
        t = document_type.replace("'", "''")
        url = (f"{self._list(MATRIX)}/items?$select=Id,DocumentType,IsActive,MandatoryApprovers/EMail,FinalApprover/EMail"
               f"&$expand=MandatoryApprovers,FinalApprover&$filter=DocumentType eq '{t}' and IsActive eq 1&$top=1")
        rows = self._call("GET", url).get("value", [])
        if not rows:
            return None
        r = rows[0]
        mandatory = [(u.get("EMail") or "").lower() for u in (r.get("MandatoryApprovers") or []) if u.get("EMail")]
        final = ((r.get("FinalApprover") or {}).get("EMail") or "").lower() or None
        return {"mandatory": mandatory, "final": final}

    def people(self, q: str) -> list[dict]:
        """Users in the directory matching q (SharePoint people picker): [{email, name}]."""
        r = self._call("POST", f"{self.s.site_url}/_api/SP.UI.ApplicationPages.ClientPeoplePickerWebServiceInterface.clientPeoplePickerSearchUser",
                       json={"queryParams": {"QueryString": q, "MaximumEntitySuggestions": 12, "AllowEmailAddresses": False,
                                             "AllowMultipleEntities": True, "PrincipalSource": 15, "PrincipalType": 1}})
        raw = r.get("value") if isinstance(r, dict) else None
        raw = raw if raw is not None else ((r.get("d") or {}).get("ClientPeoplePickerSearchUser") if isinstance(r, dict) else "[]")
        out = []
        for e in json_loads(raw or "[]"):
            data = e.get("EntityData") or {}
            email = (data.get("Email") or "").lower()
            if email and all(o["email"] != email for o in out):
                out.append({"email": email, "name": e.get("DisplayText") or email, "title": data.get("Title") or data.get("Department") or ""})
        return out

    PEOPLE_SOURCE = "b09a7990-05ea-4af9-81ef-edfab16c4e31"     # SharePoint search: Local People Results

    def directory_people(self, max_people: int = 5000) -> list[dict]:
        """All RH Microsoft 365 users with a mailbox (the company directory, through SharePoint people search).
        Cached for an hour."""
        cached = getattr(self, "_people_cache", None)
        if cached and cached[1] > time.time():
            return cached[0]
        out: dict[str, dict] = {}
        start = 0
        while start < max_people:
            url = (f"{self.s.site_url}/_api/search/query?querytext='*'&sourceid='{self.PEOPLE_SOURCE}'"
                   f"&selectproperties='PreferredName,WorkEmail,JobTitle,Department'&rowlimit=500&startrow={start}&trimduplicates=false")
            res = (self._call("GET", url).get("PrimaryQueryResult") or {}).get("RelevantResults") or {}
            rows = ((res.get("Table") or {}).get("Rows")) or []
            for row in rows:
                cells = {c.get("Key"): c.get("Value") for c in row.get("Cells") or []}
                email = (cells.get("WorkEmail") or "").lower()
                if email and email not in out:
                    out[email] = {"email": email, "name": cells.get("PreferredName") or email,
                                  "title": " · ".join(x for x in (cells.get("JobTitle"), cells.get("Department")) if x)}
            start += len(rows)
            if not rows or start >= int(res.get("TotalRows") or 0):
                break
        people = sorted(out.values(), key=lambda p: p["name"].lower())
        self._people_cache = (people, time.time() + 3600)
        return people

    def site_people(self) -> list[dict]:
        """The people (with an email) of the DocumentControl site: the default list to choose approvers from."""
        url = f"{self.s.site_url}/_api/web/siteusers?$select=Email,Title,PrincipalType,IsHiddenInUI&$filter=PrincipalType eq 1&$top=1000"
        out = []
        for u in self._call("GET", url).get("value", []):
            email = (u.get("Email") or "").lower()
            if email and not u.get("IsHiddenInUI") and all(o["email"] != email for o in out):
                out.append({"email": email, "name": u.get("Title") or email, "title": ""})
        return sorted(out, key=lambda p: p["name"].lower())

    def log_delegation(self, *, title: str, delegator: str, delegate: str, approved_by: str, reason: str,
                       valid_from: str, valid_to: str) -> None:
        """One row in the Delegations list (provisioned by Provision-DMS.ps1): who passed an approval to whom."""
        r = self._call("GET", f"{self._list(DELEGATIONS)}/fields/getbyinternalnameortitle('DelegationStatus')?$select=Choices")
        active = next((v for v in (r.get("Choices") or []) if v in ("Active", "פעיל")), "Active")
        day = lambda d: f"{d}T12:00:00Z"  # noqa: E731 - noon UTC keeps the same date in any site time zone
        self._call("POST", f"{self._list(DELEGATIONS)}/items", json={
            "Title": title[:255], "DelegatorId": self._user_id(delegator), "DelegateToId": self._user_id(delegate),
            "ValidFrom": day(valid_from), "ValidTo": day(valid_to), "DelegationReason": reason, "DelegationStatus": active,
            "DelegationApprovedById": self._user_id(approved_by)})

    def _list_choice(self, rel: str, field: str, key: str) -> str:
        """The value of a choice as the list stores it (English key or Hebrew label)."""
        cache = self.__dict__.setdefault("_choice_cache", {})
        if (rel, field) not in cache:
            r = self._call("GET", f"{self._list(rel)}/fields/getbyinternalnameortitle('{field}')?$select=Choices")
            cache[(rel, field)] = list(r.get("Choices") or [])
        values = cache[(rel, field)]
        return next((v for v in (key, DECISION_HE.get(key)) if v in values), key)

    def log_decision(self, *, workflow_id: str, document_id: str, revision: str, approver: str, role: str, stage: int,
                     decision: str, comment: str, delegated_from: str | None = None) -> None:
        """One row in Approval Decisions (provisioned by Provision-DMS.ps1) for each decision on the page."""
        values = {"Title": f"{document_id} {decision} {approver}"[:255], "WorkflowId": workflow_id[:40], "DocumentId": document_id[:40],
                  "Revision": (revision or "01")[:20], "ApproverId": self._user_id(approver),
                  "ApproverRole": self._list_choice(DECISIONS, "ApproverRole", role), "ApprovalStage": stage,
                  "Decision": self._list_choice(DECISIONS, "Decision", decision), "DecisionComment": comment,
                  "DecisionUtc": datetime.now(timezone.utc).isoformat(), "ApprovalRef": "DMS page"}
        if delegated_from:
            values["DelegatedFromId"] = self._user_id(delegated_from)
        self._call("POST", f"{self._list(DECISIONS)}/items", json=values)

    def list_info(self, rel: str) -> dict:
        """Does the list exist, how many items, and may the signed-in account add items (read only, writes nothing)."""
        try:
            r = self._call("GET", f"{self._list(rel)}?$select=Title,ItemCount,EffectiveBasePermissions")
        except SharePointError as e:
            return {"list": rel, "exists": False, "error": str(e)[:300]}
        low = int((r.get("EffectiveBasePermissions") or {}).get("Low") or 0)
        return {"list": rel, "exists": True, "title": r.get("Title"), "items": r.get("ItemCount"),
                "canRead": bool(low & 0x1), "canAdd": bool(low & 0x2), "canEdit": bool(low & 0x4)}

    def notify(self, *, to: list[str], subject: str, body: str, link: str, ref: str) -> None:
        """A row in DMS Notifications; the DC-P2 flow sends it by email and Teams."""
        self._call("POST", f"{self._list(NOTIFY)}/items", json={
            "Title": subject[:255], "NotifyTo": "; ".join(to), "MessageBody": body, "LinkUrl": link[:255], "RefId": ref})

    # ------------------------------------------------------------------ share with a customer (Large File Exchange site)
    def share_with_guest(self, *, local_path: str, folder: str, email: str, subject: str, message: str) -> dict:
        """Copy the file to the Exchange site library (<library>/<folder>/) and share it with one external
        person: view only, a specific-people invitation sent by SharePoint (B2B guest, no anonymous link)."""
        ex = self.s.ex_site_url.rstrip("/")
        ex_path = urlparse(ex).path.rstrip("/")
        q = lambda p: quote(p.replace("'", "''"), safe="/")  # noqa: E731
        current = f"{ex_path}/{self.s.ex_library}"
        for part in [p for p in folder.split("/") if p]:
            current = f"{current}/{part}"
            try:
                self._call("POST", f"{ex}/_api/web/folders/AddUsingPath(DecodedUrl='{q(current)}')")
            except SharePointError as e:
                if "exist" not in str(e).lower():
                    raise
        name = os.path.basename(local_path)
        with open(local_path, "rb") as f:
            up = self._call("POST", f"{ex}/_api/web/GetFolderByServerRelativePath(DecodedUrl='{q(current)}')"
                                    f"/Files/AddUsingPath(DecodedUrl='{q(name)}',Overwrite=true)", data=f.read())
        url = self.host + (up.get("ServerRelativeUrl") or f"{current}/{name}")
        person = {"Key": email, "DisplayText": email, "IsResolved": True, "Description": email, "EntityType": "",
                  "EntityData": {"SPUserID": email, "Email": email, "IsBlocked": "False", "PrincipalType": "UNVALIDATED_EMAIL_ADDRESS",
                                 "AccountName": email, "SIPAddress": email},
                  "MultipleMatches": [], "ProviderName": "", "ProviderDisplayName": ""}
        r = self._call("POST", f"{ex}/_api/SP.Web.ShareObject", json={
            "url": url, "peoplePickerInput": json_dumps([person]), "roleValue": "role:1073741826", "groupId": 0,
            "propagateAcl": False, "sendEmail": True, "includeAnonymousLinkInEmail": False,
            "emailSubject": subject, "emailBody": message, "useSimplifiedRoles": True})
        if r.get("StatusCode") not in (None, 0) or r.get("ErrorMessage"):
            raise SharePointError(f"Sharing refused: {r.get('ErrorMessage') or r.get('StatusCode')} "
                                  "(check external sharing on the Exchange site and its allowed guest domains)")
        return {"url": url}

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
              source: str | None = None) -> int | None:
        r = self._call("POST", f"{self._list(AUDIT)}/items", json={
            "Title": f"{event} {document_id}", "CorrelationId": document_id, "AuditEventType": event,
            "FromStatus": from_status, "ToStatus": to_status, "ActorEmail": actor,
            "EventUtc": datetime.now(timezone.utc).isoformat(), "EventSource": source or self.s.choices["Manual"],
            "EventDetails": details[:60000]})
        self._audit_cache = None
        return r.get("Id")

    def attach(self, audit_id: int, name: str, path: str) -> None:
        """Attach a file (e.g. the First loading trace log and CSV) to a Control Audit row."""
        with open(path, "rb") as f:
            self._call("POST", f"{self._list(AUDIT)}/items({audit_id})/AttachmentFiles/add(FileName='{quote(name)}')",
                       data=f.read())
