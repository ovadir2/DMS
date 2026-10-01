"""SharePoint REST payloads, with the HTTP session mocked."""
from __future__ import annotations

import json

from dms_api.config import Settings
from dms_api.sharepoint import SharePoint


class Resp:
    def __init__(self, body, status=200):
        self.status_code, self._b = status, body
        self.content = json.dumps(body).encode() if body is not None else b""
        self.text = self.content.decode()

    def json(self):
        return self._b


class Session:
    def __init__(self):
        self.calls = []

    def request(self, method, url, json=None, headers=None, timeout=None):
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
