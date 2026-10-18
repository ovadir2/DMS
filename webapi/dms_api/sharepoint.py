"""Document Register and Control Audit through the SharePoint REST API.

DMS_SP_AUTH=certificate (server): app-only, the Entra app needs Sites.Selected with write on the
DocumentControl site (the same grant as RH-DMS-Workflow-Service, docs/02). No user credentials.
DMS_SP_AUTH=interactive (pilot on a PC): you sign in once in the browser with the Entra app you use
for PnP ($C); the token is cached in %LOCALAPPDATA%\\DMS and refreshed silently.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from json import dumps as json_dumps, loads as json_loads
from urllib.parse import quote, urlparse

import requests

from .config import Settings

logger = logging.getLogger("dms_api")

# what Word, Excel and PowerPoint for the web open in the browser; anything else is the file itself
OFFICE_WEB = (".docx", ".docm", ".doc", ".dotx", ".xlsx", ".xlsm", ".xls", ".csv",
              ".pptx", ".pptm", ".ppt", ".ppsx")

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

    def cert_days_left(self) -> int | None:
        """Days until the sign-in certificate expires (None: not certificate mode, or it cannot be read).
        Nobody remembers a date two years out, so the DMS says it: at start, and in the SharePoint check."""
        if self.s.sp_auth != "certificate" or not self.s.cert_path:
            return None
        try:
            from cryptography import x509
            with open(self.s.cert_path, "rb") as f:
                cert = x509.load_pem_x509_certificate(f.read())
            end = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=timezone.utc)
            return (end - datetime.now(timezone.utc)).days
        except Exception:  # noqa: BLE001 - a missing or odd file must not stop the DMS
            return None

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
              data: bytes | None = None, raw: bool = False):
        h = {"Authorization": f"Bearer {self._access_token()}", "Accept": "application/json;odata=nometadata",
             "Content-Type": "application/octet-stream" if data is not None else "application/json;odata=nometadata"}
        h.update(headers or {})
        for attempt in range(3):                               # SharePoint drops idle connections / throttles:
            try:                                                # the first call after a pause could fail, so try again
                r = self.http.request(method, url, json=json, data=data, headers=h, timeout=300 if data is not None else 30)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
                continue
            if r.status_code in (429, 503, 504) and attempt < 2:
                time.sleep(min(int(r.headers.get("Retry-After", "2") or 2), 10))
                continue
            break
        if r.status_code >= 400:
            raise SharePointError(f"{method} {url.split('?')[0]} -> {r.status_code}: {r.text[:300]}")
        if raw:                                                 # a file's content, not a JSON answer
            return r.content
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
        if "@" not in email:                                    # a domain account with no email (UPN) in AD
            raise SharePointError(f"{email} has no email (Microsoft 365 account): SharePoint knows people by email. "
                                  "Act as a user with an email for workflow actions (submit, approve, share).")
        r = self._call("POST", f"{self.s.site_url}/_api/web/ensureuser",
                       json={"logonName": f"i:0#.f|membership|{email}"})
        return r["Id"]

    def create_document(self, *, title: str, path: str, document_type: str, document_area: str,
                        owner_email: str, control_mode: str | None, document_id: str | None) -> dict:
        values = {"Title": title, "DocumentId": document_id or "NEW", "LifecycleStatus": self.s.choices["Working"],
                  "WorkingUncPath": path, "DocumentOwnerId": self._user_id(owner_email)}
        if document_type:
            values["DocumentType"] = document_type
        if document_area:
            values["DocumentArea"] = document_area
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
        """All RH Microsoft 365 users with a mailbox (the company directory). Cached for an hour.
        Signed in with a certificate (app-only) the SharePoint search API refuses the call ("No User or App
        Context found"), so the directory comes from Microsoft Graph; without that permission either, the
        people of the DMS site are offered instead."""
        cached = getattr(self, "_people_cache", None)
        if cached and cached[1] > time.time():
            return cached[0]
        if self.s.sp_auth != "interactive":
            try:
                people = self._graph_people(max_people)
            except SharePointError as e:
                logger.info("Company directory from Graph: %s. The people of the site are offered instead.", e)
                people = self.site_people()
            self._people_cache = (people, time.time() + 3600)
            return people
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

    def _graph_people(self, max_people: int = 5000) -> list[dict]:
        """The company directory through Microsoft Graph (the Entra app needs User.Read.All, Application)."""
        out: dict[str, dict] = {}
        path = "users?$select=displayName,mail,jobTitle,department&$top=999"
        while path and len(out) < max_people:
            r = self._graph("GET", path)
            for u in r.get("value") or []:
                email = (u.get("mail") or "").lower()
                if email and email not in out:
                    out[email] = {"email": email, "name": u.get("displayName") or email,
                                  "title": " · ".join(x for x in (u.get("jobTitle"), u.get("department")) if x)}
            nxt = r.get("@odata.nextLink") or ""
            path = nxt.split("/v1.0/", 1)[1] if "/v1.0/" in nxt else ""
        if not out:
            raise SharePointError("Microsoft Graph returned no users with a mailbox")
        return sorted(out.values(), key=lambda p: p["name"].lower())

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
    def share_with_guest(self, *, local_paths: list[str], folder: str, email: str, subject: str, message: str,
                         shortcut_for: str | None = None, shortcut_name: str | None = None,
                         request_ids: dict[str, str] | None = None) -> dict:
        """Copy the files straight into the customer folder on the Exchange site (<library>/<folder>/, e.g.
        Outbound/Customer_A) and share that folder with one external person: view only, a specific-people
        invitation sent by SharePoint (B2B guest, no anonymous link). The customer sees every file ever shared
        into the folder. Then, if asked, a OneDrive shortcut (shortcut_name) to the folder is added to the
        sharing user's OneDrive (Microsoft Graph; a failure there does not undo the share)."""
        ex = self.s.ex_site_url.rstrip("/")
        ex_path = urlparse(ex).path.rstrip("/")
        q = lambda p: quote(p.replace("'", "''"), safe="/")  # noqa: E731
        current = f"{ex_path}/{self.s.ex_library}"
        for part in [p for p in folder.split("/") if p]:
            current = f"{current}/{part}"
            try:
                self._call("POST", f"{ex}/_api/web/folders/AddUsingPath(DecodedUrl='{q(current)}')")
            except SharePointError:
                # already there (the message is in the site's language, e.g. Hebrew): check, do not parse it
                if not self._folder_exists(ex, current):
                    raise
        urls = []
        for local_path in local_paths:
            name = os.path.basename(local_path)
            with open(local_path, "rb") as f:
                up = self._call("POST", f"{ex}/_api/web/GetFolderByServerRelativePath(DecodedUrl='{q(current)}')"
                                        f"/Files/AddUsingPath(DecodedUrl='{q(name)}',Overwrite=true)", data=f.read())
            landed = up.get("ServerRelativeUrl") or f"{current}/{name}"
            urls.append(self.host + landed)
            # the Exchange library asks every file which request it belongs to: for the DMS that is the document
            request = (request_ids or {}).get(name)
            if request:
                try:
                    self._call("POST", f"{ex}/_api/web/GetFileByServerRelativePath(DecodedUrl='{q(landed)}')/ListItemAllFields",
                               json={"RequestId": request[:255]}, headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "*"})
                except SharePointError as e:   # the column is the library's business, not the share's
                    logger.info("The request of %s could not be written: %s", name, e)
        folder_url = self.host + quote(current, safe="/")
        person = {"Key": email, "DisplayText": email, "IsResolved": True, "Description": email, "EntityType": "",
                  "EntityData": {"SPUserID": email, "Email": email, "IsBlocked": "False", "PrincipalType": "UNVALIDATED_EMAIL_ADDRESS",
                                 "AccountName": email, "SIPAddress": email},
                  "MultipleMatches": [], "ProviderName": "", "ProviderDisplayName": ""}
        emailed = True
        try:
            emailed = self._graph_invite(folder=folder, email=email, message=message)   # the DMS account's own way
        except Exception as e:  # noqa: BLE001 - whatever Graph could not do, SharePoint is asked next
            graph_said = str(e)
            logger.info("No guest invitation through Graph for %s: %s", email, graph_said)
            r = self._call("POST", f"{ex}/_api/SP.Web.ShareObject", json={
                "url": folder_url, "peoplePickerInput": json_dumps([person]), "roleValue": "role:1073741826", "groupId": 0,
                "propagateAcl": False, "sendEmail": True, "includeAnonymousLinkInEmail": False,
                "emailSubject": subject, "emailBody": message, "useSimplifiedRoles": True})
            if r.get("StatusCode") not in (None, 0) or r.get("ErrorMessage"):
                raise SharePointError(f"Sharing refused: {r.get('ErrorMessage') or r.get('StatusCode')} "
                                      f"(check external sharing on the Exchange site and its allowed guest domains) "
                                      f"| Graph: {graph_said}") from None
        out = {"urls": urls, "url": urls[0] if urls else folder_url, "folderUrl": folder_url, "shortcut": None,
               "shortcutError": None, "emailed": emailed}
        if shortcut_name:
            try:
                out["shortcut"] = self.onedrive_shortcut(folder, shortcut_name, shortcut_for)
            except Exception as e:  # noqa: BLE001 - the share itself succeeded
                out["shortcutError"] = str(e)[:300]
        return out

    # ------------------------------------------------------------------ the review bridge (approvers work in SharePoint)
    def review_site(self) -> str:
        """Where approvers open the document: DMS_REVIEW_SITE_URL, else the Document Control site."""
        return (self.s.review_site_url or self.s.site_url).rstrip("/")

    def _library_of(self, key: str) -> str:
        """Which library that copy belongs in. A copy somebody is only reading goes to the view library, where
        nobody has standing rights: a person with Edit on the approvals library would otherwise be able to
        change a released document through the copy made for them to read. The key says which it is: the DMS
        names a reading copy "view-..." and an editing one "edit-..." (an approval goes by its document id)."""
        return self.s.view_library if (self.s.view_library and key.startswith("view-")) else self.s.review_library

    def _review_folder(self, key: str) -> str:
        """A folder of its own per document under approval, or per file taken out for editing or reading."""
        site = urlparse(self.review_site()).path.rstrip("/")
        return f"{site}/{self._library_of(key)}/{key}"

    def ensure_review_library(self, title: str = "") -> None:
        """Make the library on the review site if it is not there yet: nothing has to be created by hand."""
        ready = getattr(self, "_review_ready", set())
        site, title = self.review_site(), title or self.s.review_library
        if title in ready:
            return
        q = title.replace("'", "''")
        try:
            self._call("GET", f"{site}/_api/web/lists/GetByTitle('{quote(q)}')?$select=Id")
        except SharePointError:
            # the DMS talks OData nometadata, which refuses __metadata: the type comes from the url
            self._call("POST", f"{site}/_api/web/lists", json={
                "Title": title, "BaseTemplate": 101,                                     # 101 = document library
                "Description": "Documents the DMS puts here for people to open and edit; the DMS removes them again."})
            logger.info("The review library %s was created on %s", title, site)
        self._review_ready = ready | {title}

    def review_put(self, *, local_path: str, document_id: str, edit: bool = True) -> dict:
        """Copy the file to the review library, under a folder of its own. Returns the address to open it with:
        Word, Excel or PowerPoint for the web, for editing, or read only for a released document."""
        lib = self._library_of(document_id)
        self.ensure_review_library(lib)
        site, q = self.review_site(), lambda p: quote(p.replace("'", "''"), safe="/")
        current = f"{urlparse(site).path.rstrip('/')}/{lib}"
        for part in [document_id]:
            current = f"{current}/{part}"
            try:
                self._call("POST", f"{site}/_api/web/folders/AddUsingPath(DecodedUrl='{q(current)}')")
            except SharePointError:
                if not self._folder_exists(site, current):
                    raise
        name = os.path.basename(local_path)
        with open(local_path, "rb") as f:
            up = self._call("POST", f"{site}/_api/web/GetFolderByServerRelativePath(DecodedUrl='{q(current)}')"
                                    f"/Files/AddUsingPath(DecodedUrl='{q(name)}',Overwrite=true)", data=f.read())
        server_relative = up.get("ServerRelativeUrl") or f"{current}/{name}"
        return {"name": name, "serverRelative": server_relative, "url": self.office_url(server_relative, edit=edit)}

    def office_url(self, server_relative: str, *, edit: bool = True) -> str:
        """The address that opens the document in Word / Excel / PowerPoint for the web. The file's own address
        makes the browser ask whether to download it; this one opens it in the browser, in the right program."""
        name = server_relative.rsplit("/", 1)[-1]
        if not name.lower().endswith(OFFICE_WEB):              # a PDF, an image, anything else: the file itself
            return self.host + quote(server_relative, safe="/")
        site = self.review_site()
        return (f"{site}/_layouts/15/WopiFrame.aspx?sourcedoc={quote(server_relative, safe='')}"
                f"&action={'edit' if edit else 'view'}")

    def review_info(self, *, document_id: str, name: str) -> dict | None:
        """When that copy was last written in SharePoint, and how large it is: the DMS brings it back as soon
        as someone has changed it there. None when it is not there."""
        site, q = self.review_site(), lambda p: quote(p.replace("'", "''"), safe="/")
        path = f"{self._review_folder(document_id)}/{name}"
        try:
            r = self._call("GET", f"{site}/_api/web/GetFileByServerRelativePath(DecodedUrl='{q(path)}')"
                                  f"?$select=TimeLastModified,Length")
        except SharePointError:
            return None
        return {"modified": r.get("TimeLastModified"), "length": int(r.get("Length") or 0)}

    def review_url(self, *, document_id: str, name: str) -> str | None:
        """Where that document is open for approval, if it is already there (after a restart of the DMS, or
        when it was submitted before the SharePoint review was turned on). None when it is not."""
        site, q = self.review_site(), lambda p: quote(p.replace("'", "''"), safe="/")
        path = f"{self._review_folder(document_id)}/{name}"
        try:
            self._call("GET", f"{site}/_api/web/GetFileByServerRelativePath(DecodedUrl='{q(path)}')?$select=Exists")
        except SharePointError:
            return None
        return self.office_url(path)

    def review_share(self, *, document_id: str, name: str, emails: list[str], subject: str, message: str,
                     edit: bool = True) -> None:
        """Give each person edit (or, for a released document, read only) on that one file, and nothing else on
        the site. SharePoint sends no mail: the DMS tells them itself, with the same notification as always."""
        site = self.review_site()
        url = self.host + quote(f"{self._review_folder(document_id)}/{name}", safe="/")
        people = [{"Key": e, "DisplayText": e, "IsResolved": True, "Description": e, "EntityType": "",
                   "EntityData": {"Email": e, "AccountName": e, "PrincipalType": "UNVALIDATED_EMAIL_ADDRESS"},
                   "MultipleMatches": [], "ProviderName": "", "ProviderDisplayName": ""} for e in emails]
        r = self._call("POST", f"{site}/_api/SP.Web.ShareObject", json={
            "url": url, "peoplePickerInput": json_dumps(people), "roleValue": "role:1073741827" if edit else "role:1073741826",   # edit / read
            "groupId": 0, "propagateAcl": False, "sendEmail": False, "includeAnonymousLinkInEmail": False,
            "emailSubject": subject, "emailBody": message, "useSimplifiedRoles": True})
        if r.get("StatusCode") not in (None, 0) or r.get("ErrorMessage"):
            raise SharePointError(f"The document could not be shared with the approvers: "
                                  f"{r.get('ErrorMessage') or r.get('StatusCode')}")

    def review_link(self, *, document_id: str, name: str, edit: bool = True) -> str | None:
        """A link to that one file for anyone in the company, made by the DMS account: whoever the DMS sends it
        to opens it with their own Microsoft account, and nothing else on the site is opened to them. It raises
        where the tenant does not allow such a link; the caller then shares it with the named people, and the
        SharePoint check says why."""
        try:
            return self._graph_link(document_id, name, edit)      # the DMS account's own way of granting
        except SharePointError as e:
            graph_said = str(e)
            logger.info("No company link through Graph for %s: %s", name, graph_said)
        site = self.review_site()
        url = self.host + quote(f"{self._review_folder(document_id)}/{name}", safe="/")
        try:
            r = self._call("POST", f"{site}/_api/SP.Web.CreateOrganizationSharingLink",
                           json={"url": url, "isEditLink": bool(edit)})
        except SharePointError as e:
            # both ways refused: the check must show the Graph answer too, it is the one that can be fixed
            raise SharePointError(f"Graph: {graph_said} | SharePoint: {e}") from None
        link = (r.get("sharingLinkInfo") or {}).get("Url") or r.get("Url") or r.get("value")
        return link or None

    def _graph_link(self, document_id: str, name: str, edit: bool) -> str:
        """The company link through Microsoft Graph. SharePoint's own sharing refuses an application that signs
        in with a certificate ("the caller has no permission to grant permission"); Graph lets it make the link
        for a file it may write, which is what the DMS has on the review library."""
        u = urlparse(self.review_site())
        drives = self._graph("GET", f"sites/{u.netloc}:{u.path.rstrip('/')}:/drives?$select=id,name,webUrl").get("value", [])
        want = self._library_of(document_id).lower()
        drive = next((d for d in drives if (d.get("webUrl") or "").rstrip("/").rsplit("/", 1)[-1].lower() == want
                      or (d.get("name") or "").lower() == want), None)
        if not drive:
            raise SharePointError(f"The library {self._library_of(document_id)} was not found on {self.review_site()}")
        path = quote(f"{document_id}/{name}")
        r = self._graph("POST", f"drives/{drive['id']}/root:/{path}:/createLink",
                        json={"type": "edit" if edit else "view", "scope": "organization"})
        link = ((r.get("link") or {}).get("webUrl")) or ""
        if not link:
            raise SharePointError(f"Graph made no link for {name}")
        return link

    def review_get(self, *, document_id: str, name: str) -> bytes:
        """The file as the approvers left it, to bring back to the file server."""
        site, q = self.review_site(), lambda p: quote(p.replace("'", "''"), safe="/")
        path = f"{self._review_folder(document_id)}/{name}"
        return self._call("GET", f"{site}/_api/web/GetFileByServerRelativePath(DecodedUrl='{q(path)}')/$value", raw=True)

    def review_done(self, *, document_id: str) -> None:
        """The approval is over: the copy and every permission on it go away (to the site's recycle bin)."""
        site, q = self.review_site(), lambda p: quote(p.replace("'", "''"), safe="/")
        folder = self._review_folder(document_id)
        try:
            self._call("POST", f"{site}/_api/web/GetFolderByServerRelativePath(DecodedUrl='{q(folder)}')/recycle")
        except SharePointError as e:
            logger.info("Review copy of %s was not removed: %s", document_id, e)

    def expire_outbound(self, days: int, now: datetime | None = None) -> list[dict]:
        """Shares older than `days`: every file in <library>/<ex_folder>/<Customer>/ last uploaded (shared) more
        than `days` ago goes to the Exchange site recycle bin; a customer folder left empty goes too, and with it
        the customer's access. Returns what was removed."""
        ex = self.s.ex_site_url.rstrip("/")
        q = lambda p: quote(p.replace("'", "''"), safe="/")  # noqa: E731
        base = f"{urlparse(ex).path.rstrip('/')}/{self.s.ex_library}/{self.s.ex_folder}"
        limit = (now or datetime.now(timezone.utc)).timestamp() - days * 86400
        try:
            folders = self._call("GET", f"{ex}/_api/web/GetFolderByServerRelativePath(DecodedUrl='{q(base)}')/Folders"
                                        "?$select=Name,ServerRelativeUrl,ItemCount").get("value", [])
        except SharePointError as e:
            if " 404" in str(e):
                return []
            raise
        removed = []
        for f in folders:
            files = self._call("GET", f"{ex}/_api/web/GetFolderByServerRelativePath(DecodedUrl='{q(f['ServerRelativeUrl'])}')/Files"
                                      "?$select=Name,ServerRelativeUrl,TimeLastModified").get("value", [])
            old = [x for x in files if datetime.fromisoformat(x["TimeLastModified"].replace("Z", "+00:00")).timestamp() < limit]
            for x in old:
                self._call("POST", f"{ex}/_api/web/GetFileByServerRelativePath(DecodedUrl='{q(x['ServerRelativeUrl'])}')/recycle()")
                removed.append({"customer": f["Name"], "file": x["Name"], "sharedUtc": x["TimeLastModified"], "folderRemoved": False})
            subfolders = self._call("GET", f"{ex}/_api/web/GetFolderByServerRelativePath(DecodedUrl='{q(f['ServerRelativeUrl'])}')/Folders"
                                           "?$select=Name").get("value", [])
            if files and len(old) == len(files) and not subfolders:
                self._call("POST", f"{ex}/_api/web/GetFolderByServerRelativePath(DecodedUrl='{q(f['ServerRelativeUrl'])}')/recycle()")
                if removed:
                    removed[-1]["folderRemoved"] = True
        return removed

    def outbound_files(self, name: str) -> list[dict]:
        """The files now in <library>/<ex_folder>/<name>/ on the Large File Exchange site (what that customer or
        person can see): name and when it was put there. [] when the folder does not exist."""
        ex = self.s.ex_site_url.rstrip("/")
        q = lambda p: quote(p.replace("'", "''"), safe="/")  # noqa: E731
        folder = f"{urlparse(ex).path.rstrip('/')}/{self.s.ex_library}/{self.s.ex_folder}/{name}"
        try:
            files = self._call("GET", f"{ex}/_api/web/GetFolderByServerRelativePath(DecodedUrl='{q(folder)}')/Files"
                                      "?$select=Name,TimeLastModified,Length").get("value", [])
        except SharePointError as e:
            if " 404" in str(e):
                return []
            raise
        return [{"name": x["Name"], "utc": x.get("TimeLastModified"), "size": int(x.get("Length") or 0)} for x in files]

    def _folder_exists(self, web: str, server_relative: str) -> bool:
        try:
            r = self._call("GET", f"{web}/_api/web/GetFolderByServerRelativePath(DecodedUrl='"
                                  f"{quote(server_relative.replace(chr(39), chr(39) * 2), safe='/')}')?$select=Exists")
            return bool(r.get("Exists"))
        except SharePointError:
            return False

    # ------------------------------------------------------------------ OneDrive shortcut (Microsoft Graph)
    GRAPH = "https://graph.microsoft.com/v1.0"

    def _graph_token(self) -> str:
        if getattr(self, "_gtoken", None) and self._gtoken[1] > time.time() + 60:
            return self._gtoken[0]
        if self.s.sp_auth == "interactive":
            self._access_token()  # the sign-in (and the token cache) of the SharePoint calls
            scopes = ["https://graph.microsoft.com/Files.ReadWrite.All"]
            accounts = self._public.get_accounts()
            r = self._public.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
            if not r or "access_token" not in r:
                r = self._public.acquire_token_interactive(scopes, prompt="select_account")
            if self._msal_cache.has_state_changed:
                with open(self._cache_file, "w", encoding="utf-8") as f:
                    f.write(self._msal_cache.serialize())
        else:
            import msal
            with open(self.s.cert_path, encoding="utf-8") as f:
                key = f.read()
            r = msal.ConfidentialClientApplication(
                self.s.client_id, authority=f"https://login.microsoftonline.com/{self.s.tenant_id}",
                client_credential={"private_key": key, "thumbprint": self.s.cert_thumbprint}
            ).acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in r:
            raise SharePointError(f"Microsoft Graph token: {r.get('error_description') or r.get('error')} "
                                  "(the Entra app needs Graph Files.ReadWrite.All)")
        self._gtoken = (r["access_token"], time.time() + int(r.get("expires_in", 3600)))
        return self._gtoken[0]

    def _graph(self, method: str, path: str, json: dict | None = None) -> dict:
        r = self.http.request(method, f"{self.GRAPH}/{path.lstrip('/')}", json=json, timeout=30,
                              headers={"Authorization": f"Bearer {self._graph_token()}", "Accept": "application/json"})
        if r.status_code >= 400:
            raise SharePointError(f"Graph {method} {path.split('?')[0]} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def _ex_drive(self) -> dict:
        """The document library of the Large File Exchange site, as Graph sees it."""
        u = urlparse(self.s.ex_site_url)
        drives = self._graph("GET", f"sites/{u.netloc}:{u.path.rstrip('/')}:/drives?$select=id,name,webUrl").get("value", [])
        lib = self.s.ex_library.lower()
        drive = next((d for d in drives if (d.get("webUrl") or "").rstrip("/").rsplit("/", 1)[-1].lower() == lib
                      or (d.get("name") or "").lower() == lib), None)
        if not drive:
            raise SharePointError(f"The library {self.s.ex_library} was not found on the Exchange site")
        return drive

    def _graph_guest(self, *, email: str, where: str, message: str) -> tuple[str, bool]:
        """The person as a guest of the company, created if this is the first time. Sharing cannot name somebody
        the directory has never heard of when the caller is an application signed in with a certificate, so the
        DMS asks Entra for the guest first (Graph User.Invite.All) and only then grants the folder to that guest.
        Entra also sends the person the invitation mail, which an application cannot send itself. Returns who
        they are in the directory, and whether the mail went out."""
        body = {"invitedUserEmailAddress": email, "inviteRedirectUrl": where, "sendInvitationMessage": True,
                "invitedUserMessageInfo": {"customizedMessageBody": message[:1000]}}
        try:
            r = self._graph("POST", "invitations", json=body)
        except SharePointError as e:
            if "Request_BadRequest" not in str(e) and "sendInvitationMessage" not in str(e):
                raise
            logger.info("Entra would not send the invitation to %s, inviting without the mail: %s", email, e)
            r = self._graph("POST", "invitations", json={"invitedUserEmailAddress": email, "inviteRedirectUrl": where,
                                                         "sendInvitationMessage": False})
            return ((r.get("invitedUser") or {}).get("id") or "", False)
        return ((r.get("invitedUser") or {}).get("id") or "", True)

    def _graph_invite(self, *, folder: str, email: str, message: str) -> bool:
        """Invite one person outside the company to read that folder, through Microsoft Graph. SharePoint's own
        sharing cannot resolve an address it has never seen when the caller is an application signed in with a
        certificate ("the user could not be identified"); Graph creates the guest and grants it the folder the DMS
        may write, which is what it has on the Exchange site. Returns whether SharePoint sent the person an email:
        an application signing in with a certificate is nobody, so it often has no one to send the mail from, and
        then the access is granted all the same and the caller passes the link on itself."""
        drive = self._ex_drive()
        item = self._graph("GET", f"drives/{drive['id']}/root:/{quote(folder.strip('/'))}?$select=id,webUrl")
        where = (item.get("webUrl") or "").strip() or self.s.ex_site_url
        # the invitation names the organization, not the folder: the link goes in the message, or the person has none
        guest, emailed = self._graph_guest(email=email, where=where, message=f"{message}\n\n{where}".strip())
        who = {"objectId": guest} if guest else {"email": email}
        self._graph("POST", f"drives/{drive['id']}/items/{item['id']}/invite",
                    json={"recipients": [who], "roles": ["read"], "requireSignIn": True, "sendInvitation": False})
        return emailed

    def onedrive_shortcut(self, folder: str, name: str, user_email: str | None) -> str:
        """'Add shortcut to My files': a shortcut named `name`, inside the OneDrive folder DMS_EX_SHORTCUT_FOLDER
        (created if missing), to the folder <library>/<folder> on the Exchange site. A user whose OneDrive was
        never set up gets it set up (it takes a few minutes; the shortcut is added on the next share).
        Already there -> kept. Returns where the shortcut is."""
        drive = self._ex_drive()
        item = self._graph("GET", f"drives/{drive['id']}/root:/{quote(folder.strip('/'))}?$select=id")
        me = "me/drive" if self.s.sp_auth == "interactive" or not user_email else f"users/{quote(user_email)}/drive"
        try:
            self._graph("GET", f"{me}?$select=id")
        except SharePointError as e:
            if " 404" not in str(e) and "mysite" not in str(e).lower() and "ResourceNotFound" not in str(e):
                raise
            self.setup_onedrive()
            raise SharePointError("Your OneDrive is not set up yet. Its setup was requested now (it takes a few minutes); "
                                  "the shortcut is added on the next share") from None
        parent = "root"
        if self.s.ex_shortcut_folder:
            try:
                self._graph("POST", f"{me}/root/children", json={
                    "name": self.s.ex_shortcut_folder, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})
            except SharePointError as e:
                if "409" not in str(e) and "nameAlreadyExists" not in str(e):
                    raise
            parent = f"root:/{quote(self.s.ex_shortcut_folder)}:"
        body = {"name": name, "remoteItem": {"id": item["id"], "parentReference": {"driveId": drive["id"]}},
                "@microsoft.graph.conflictBehavior": "fail"}
        try:
            self._graph("POST", f"{me}/{parent}/children", json=body)
        except SharePointError as e:
            if "409" not in str(e) and "nameAlreadyExists" not in str(e):
                raise
            # already there: keep it, unless it points to an older folder (removed after expiry and created again)
            path = f"{self.s.ex_shortcut_folder}/{name}" if self.s.ex_shortcut_folder else name
            old = self._graph("GET", f"{me}/root:/{quote(path)}?$select=id,remoteItem")
            if (old.get("remoteItem") or {}).get("id") not in (None, item["id"]):
                self._graph("DELETE", f"{me}/items/{old['id']}")
                self._graph("POST", f"{me}/{parent}/children", json=body)
        return f"{self.s.ex_shortcut_folder}/{name}" if self.s.ex_shortcut_folder else name

    def setup_onedrive(self) -> None:
        """Ask SharePoint to create the signed-in user's OneDrive (it is ready a few minutes later). App-only
        sign-in cannot do this for someone else: then an admin runs Request-SPOPersonalSite -UserEmails <email>."""
        if self.s.sp_auth != "interactive":
            raise SharePointError("The user has no OneDrive yet. A SharePoint admin sets it up: "
                                  "Request-SPOPersonalSite -UserEmails <email> (or the user opens OneDrive once)")
        self._call("POST", f"{self.host}/_api/SP.UserProfiles.ProfileLoader.GetProfileLoader/GetUserProfile/CreatePersonalSiteEnque(false)")

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
