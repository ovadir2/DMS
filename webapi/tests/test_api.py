"""API tests with an in-memory SharePoint and a temporary repository folder."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from dms_api import files
from dms_api.config import Settings
from dms_api.main import create_app

USER = "michaelr@rh.co.il"


class FakeSharePoint:
    def __init__(self, s: Settings):
        self.s, self.items, self.audits = s, {}, []

    def documents(self, refresh=False):
        return list(self.items.values())

    def document(self, item_id):
        return dict(self.items[item_id])

    def create_document(self, *, title, path, document_type, document_area, owner_email, control_mode, document_id):
        i = len(self.items) + 1
        self.items[i] = {"id": i, "title": title, "documentId": document_id or f"DMS-{i:05d}", "documentType": document_type,
                         "documentArea": document_area, "lifecycleStatus": self.s.choices["Working"],
                         "workingUncPath": path, "currentUncPath": None, "ownerEmail": owner_email, "modified": str(i)}
        return self.document(i)

    def update(self, item_id, values):
        key = {"LifecycleStatus": "lifecycleStatus"}
        for k, v in values.items():
            self.items[item_id][key.get(k, k)] = v

    def choices(self, field):
        return {"DocumentType": ["הצעת מחיר", "נוהל"], "DocumentArea": ["מסחרי"],
                "ControlMode": ["תהליך אישור רשות", "תהליך אישור חובה"]}[field]

    def audit(self, **kw):
        self.audits.append(kw)


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "Corporate_Data_TEST"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "CRU 4 FCT Quote_Rev1.xlsx").write_text("x")
    (root / "outside.txt").write_text("x")
    (tmp_path / "secret.txt").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER)
    sp = FakeSharePoint(s)
    return TestClient(create_app(s, sp)), sp, q


def test_browse_marks_registration(env):
    c, sp, q = env
    r = c.get("/api/browse", params={"path": str(q)})
    assert r.status_code == 200
    f = r.json()["files"][0]
    assert f["name"] == "CRU 4 FCT Quote_Rev1.xlsx" and f["document"] is None
    assert f["officeUri"].startswith("ms-excel:ofv|u|file:")


def test_paths_outside_root_are_refused(env):
    c, _, q = env
    assert c.get("/api/browse", params={"path": str(q.parents[4])}).status_code == 403
    assert c.get("/api/browse", params={"path": "../"}).status_code == 403
    assert c.get("/api/files/download", params={"path": str(q.parents[4] / "secret.txt")}).status_code == 403


def test_register_and_submit(env):
    c, sp, q = env
    path = str(q / "CRU 4 FCT Quote_Rev1.xlsx")
    r = c.post("/api/documents", json={"path": path, "documentType": "הצעת מחיר", "documentArea": "מסחרי", "submit": True})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["documentId"] == "DMS-00001" and d["statusKey"] == "Submitted" and d["title"] == "CRU 4 FCT Quote_Rev1"
    assert [a["event"] for a in sp.audits] == ["נוצר", "הוגש"]
    # registered once only
    assert c.post("/api/documents", json={"path": path, "documentType": "הצעת מחיר", "documentArea": "מסחרי"}).status_code == 409
    # the browse view shows the status
    assert c.get("/api/browse", params={"path": str(q)}).json()["files"][0]["document"]["statusKey"] == "Submitted"
    assert [x["documentId"] for x in c.get("/api/documents", params={"mine": True}).json()] == ["DMS-00001"]


def test_file_moved_to_submitted_still_matches(env):
    c, sp, q = env
    path = str(q / "CRU 4 FCT Quote_Rev1.xlsx")
    c.post("/api/documents", json={"path": path, "documentType": "הצעת מחיר", "documentArea": "מסחרי", "submit": True})
    (q / "Submitted").mkdir()
    os.replace(path, q / "Submitted" / "CRU 4 FCT Quote_Rev1.xlsx")
    sub = c.get("/api/browse", params={"path": str(q / "Submitted")}).json()["files"][0]
    assert sub["document"]["documentId"] == "DMS-00001"


def test_submit_rules(env):
    c, sp, q = env
    path = str(q / "CRU 4 FCT Quote_Rev1.xlsx")
    d = c.post("/api/documents", json={"path": path, "documentType": "נוהל", "documentArea": "מסחרי"}).json()
    assert d["statusKey"] == "Working"
    sp.items[d["id"]]["ownerEmail"] = "other@rh.co.il"
    assert c.post(f"/api/documents/{d['id']}/submit").status_code == 403
    sp.items[d["id"]]["ownerEmail"] = USER
    assert c.post(f"/api/documents/{d['id']}/submit").status_code == 200
    assert c.post(f"/api/documents/{d['id']}/submit").status_code == 409


def test_page_and_health(env):
    c, _, _ = env
    assert c.get("/api/health").json()["rootReachable"] is True
    assert "RH DMS" in c.get("/dms/dms-page", params={"lang": "HE"}).text


def test_auth_required_outside_dev(tmp_path):
    s = Settings(repository_root=str(tmp_path), auth_mode="header")
    c = TestClient(create_app(s, FakeSharePoint(s)))
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/me", headers={s.user_header: "Michaelr@rh.co.il"}).json() == {"email": USER}


def test_candidate_paths_windows_style():
    p = r"\\FS\Data\Quotations\Submitted\Q.xlsx"
    assert files.candidate_register_paths(p)[1] == r"\\FS\Data\Quotations\Q.xlsx"


def test_entra_token(tmp_path, monkeypatch):
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from dms_api import auth

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    s = Settings(repository_root=str(tmp_path), auth_mode="entra", tenant_id="tid", api_audience="app-guid")
    monkeypatch.setattr(auth, "_jwks", lambda _t: type("J", (), {"get_signing_key_from_jwt": lambda self, _x: type("K", (), {"key": key.public_key()})()})())
    c = TestClient(create_app(s, FakeSharePoint(s)))
    claims = {"aud": "app-guid", "iss": "https://login.microsoftonline.com/tid/v2.0", "exp": int(time.time()) + 60,
              "preferred_username": "Michaelr@rh.co.il"}
    good = jwt.encode(claims, key, algorithm="RS256")
    bad = jwt.encode({**claims, "aud": "other"}, key, algorithm="RS256")
    assert c.get("/api/me", headers={"Authorization": f"Bearer {good}"}).json() == {"email": USER}
    assert c.get("/api/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/client-config").json()["scope"] == "api://app-guid/access_as_user"
