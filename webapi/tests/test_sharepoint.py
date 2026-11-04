"""SharePoint REST payloads, with the HTTP session mocked."""
from __future__ import annotations

import json

from dms_api.config import Settings
from dms_api.sharepoint import SharePoint


class Resp:
    def __init__(self, body, status=200):
        self.status_code, self._b = status, body
        if isinstance(body, bytes):                       # a file, not JSON (a document converted to a PDF)
            self.content, self.text = body, ""
            return
        self.content = json.dumps(body).encode() if body is not None else b""
        self.text = self.content.decode()

    def json(self):
        return self._b


class Session:
    def __init__(self):
        self.calls = []

    def request(self, method, url, json=None, headers=None, timeout=None, data=None):
        self.calls.append((method, url, json, headers))
        if url.endswith("/ensureuser"):
            return Resp({"Id": 7})
        if method == "POST" and url.endswith("/items"):
            return Resp({"Id": 12})
        if "MERGE" in (headers or {}).values():
            return Resp(None, 204)
        return Resp({"Id": 12, "Title": "Q", "DocumentId": "DMS-00012", "LifecycleStatus": "בעבודה",
                     "DocumentOwner": {"EMail": "a@rh.co.il", "Title": "A"}})


def test_create_document_payloads():
    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST")
    sess = Session()
    sp = SharePoint(s, sess)
    sp._access_token = lambda: "t"
    d = sp.create_document(title="Q", path=r"\\FS\Q.xlsx", document_type="הצעת מחיר", document_area="מסחרי",
                           owner_email="a@rh.co.il", control_mode=None, document_id=None)
    ensure, create, merge, get = sess.calls
    assert ensure[2] == {"logonName": "i:0#.f|membership|a@rh.co.il"}
    assert "GetList('/sites/DocumentControl-TEST/Lists/DocumentRegister')/items" in create[1]
    assert create[2]["DocumentOwnerId"] == 7 and create[2]["LifecycleStatus"] == "בעבודה"
    assert merge[2] == {"DocumentId": "DMS-00012"} and merge[3]["IF-MATCH"] == "*"
    assert d["documentId"] == "DMS-00012" and d["ownerEmail"] == "a@rh.co.il"


def test_the_library_of_reading_copies_is_read_only():
    """A library made from the site's permissions gives its members Edit, so a reader could type into the
    copy the DMS made for them to read. The view library stops inheriting them and everyone who could
    write there is left with Read."""
    from dms_api.sharepoint import SharePoint
    calls = []

    class Sess:
        def request(self, method, url, json=None, data=None, headers=None, timeout=None, allow_redirects=None):
            calls.append((method, url))
            if url.endswith("?$select=HasUniqueRoleAssignments"):
                return Resp({"HasUniqueRoleAssignments": False})
            if "getbyname('Read')" in url:
                return Resp({"Id": 1073741826})
            if "roleassignments?$expand" in url:
                return Resp({"value": [
                    {"PrincipalId": 7, "RoleDefinitionBindings": [{"Id": 1073741830, "Name": "Edit"}]},
                    {"PrincipalId": 9, "RoleDefinitionBindings": [{"Id": 1073741826, "Name": "Read"}]}]})
            return Resp({"Id": "1"})

    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST")
    sp = SharePoint(s, Sess())
    sp._access_token = lambda: "t"
    sp.ensure_review_library("Views")
    urls = [u for _m, u in calls]
    assert any("breakroleinheritance(copyRoleAssignments=true,clearSubscopes=true)" in u for u in urls)
    assert any("addroleassignment(principalid=7,roledefid=1073741826)" in u for u in urls)
    assert any("removeroleassignment(principalid=7,roledefid=1073741830)" in u for u in urls)
    assert not any("principalid=9" in u for u in urls)          # already only reading
    calls.clear()
    sp.ensure_review_library("Approvals")                        # the approvals library keeps its permissions
    assert not any("roleassignment" in u for _m, u in calls)
