"""API tests with an in-memory SharePoint and a temporary repository folder."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from dms_api import files
from dms_api.config import Settings
from dms_api.main import create_app
from dms_api.security import User

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
        self.audits.append({**kw, "utc": f"2026-10-01T10:{len(self.audits):02d}:00Z"})

    def log_delegation(self, **kw):
        self.delegations = getattr(self, "delegations", []) + [
            {"title": kw["title"], "delegator": kw["delegator"], "delegate": kw["delegate"], "approvedBy": kw["approved_by"], "reason": kw["reason"]}]

    def audit_events(self, refresh=False):
        return [{"documentId": a["document_id"], "event": a["event"], "fromStatus": a["from_status"], "toStatus": a["to_status"],
                 "actor": a["actor"], "utc": a["utc"], "source": "ידני", "details": a["details"]} for a in reversed(self.audits)]


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "Corporate_Data_TEST"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (root / "02_Customers" / "Customer_B" / "Projects" / "PRJ-77_Radar").mkdir(parents=True)
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
    assert "Documents Management System" in c.get("/dms/dms-page", params={"lang": "HE"}).text


def test_auth_required_outside_dev(tmp_path):
    s = Settings(repository_root=str(tmp_path), auth_mode="header")
    c = TestClient(create_app(s, FakeSharePoint(s)))
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/me", headers={s.user_header: "Michaelr@rh.co.il"}).json()["email"] == USER


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
    assert c.get("/api/me", headers={"Authorization": f"Bearer {good}"}).json()["email"] == USER
    assert c.get("/api/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/client-config").json()["scope"] == "api://app-guid/access_as_user"


class LimitedUser(User):
    """A user AD does not let into Customer_B."""

    def can(self, path, access="read"):
        return "Customer_B" not in path and (access == "read" or "Quotations" in path)


@pytest.fixture
def limited(env, monkeypatch):
    from dms_api import auth
    c, sp, q = env
    monkeypatch.setattr(auth, "_resolve", lambda _r: LimitedUser(email=USER))
    return c, sp, q


def test_customers_follow_ad(env, limited):
    c, _, q = limited
    assert [x["name"] for x in c.get("/api/customers").json()] == ["Customer_A"]
    b = q.parents[2] / "Customer_B"
    assert c.get("/api/browse", params={"path": str(b)}).status_code == 403
    root = c.get("/api/browse", params={"path": str(q.parents[2])}).json()
    assert [f["name"] for f in root["folders"]] == ["Customer_A"]


def test_customers_all_for_full_access(env):
    c, _, _ = env
    assert [x["name"] for x in c.get("/api/customers").json()] == ["Customer_A", "Customer_B"]
    assert [x["name"] for x in c.get("/api/customers", params={"q": "_b"}).json()] == ["Customer_B"]


def test_upload_saves_into_the_folder(env, limited):
    c, _, q = limited
    r = c.post("/api/files/upload", data={"folder": str(q)}, files={"file": ("New Quote.xlsx", b"data")})
    assert r.status_code == 201, r.text
    assert (q / "New Quote.xlsx").read_bytes() == b"data" and r.json()["document"] is None
    # same name again is refused unless overwrite
    assert c.post("/api/files/upload", data={"folder": str(q)}, files={"file": ("New Quote.xlsx", b"x")}).status_code == 409
    assert c.post("/api/files/upload", data={"folder": str(q), "overwrite": "true"},
                  files={"file": ("New Quote.xlsx", b"v2")}).status_code == 201
    assert (q / "New Quote.xlsx").read_bytes() == b"v2"
    # no write permission on Commercial (only Quotations), no saving outside root, no partial files left
    assert c.post("/api/files/upload", data={"folder": str(q.parent)}, files={"file": ("a.txt", b"x")}).status_code == 403
    assert c.post("/api/files/upload", data={"folder": str(q.parents[5])}, files={"file": ("a.txt", b"x")}).status_code == 403
    assert not [p for p in os.listdir(q) if p.endswith(".partial")]


def test_upload_refuses_workflow_folders_and_bad_names(env):
    c, _, q = env
    (q / "Current_ReadOnly").mkdir()
    assert c.post("/api/files/upload", data={"folder": str(q / "Current_ReadOnly")}, files={"file": ("a.txt", b"x")}).status_code == 403
    assert c.post("/api/files/upload", data={"folder": str(q)}, files={"file": ("a|b.txt", b"x")}).status_code == 403


def test_search(env, limited):
    c, sp, q = env
    r = c.get("/api/search", params={"q": "quot"}).json()
    assert any(x["kind"] == "file" and x["name"] == "CRU 4 FCT Quote_Rev1.xlsx" for x in r)
    assert any(x["kind"] == "folder" and x["name"] == "Quotations" for x in r)
    assert [x["name"] for x in c.get("/api/search", params={"q": "radar", "scope": "project"}).json()] == []
    c.post("/api/documents", json={"path": str(q / "CRU 4 FCT Quote_Rev1.xlsx"), "documentType": "נוהל", "documentArea": "מסחרי"})
    docs = c.get("/api/search", params={"q": "DMS-000", "scope": "document"}).json()
    assert docs[0]["document"]["documentId"] == "DMS-00001"


def test_search_project_with_full_access(env):
    c, _, _ = env
    assert [x["name"] for x in c.get("/api/search", params={"q": "radar", "scope": "project"}).json()] == ["PRJ-77_Radar"]


def test_new_folder_rename_delete(env):
    c, sp, q = env
    r = c.post("/api/folders", json={"parent": str(q), "name": "2026"})
    assert r.status_code == 201 and (q / "2026").is_dir()
    assert c.post("/api/folders", json={"parent": str(q), "name": "2026"}).status_code == 409
    assert c.post("/api/folders", json={"parent": str(q), "name": "a/b"}).status_code == 403
    assert c.post("/api/folders", json={"parent": str(q), "name": "Current_ReadOnly"}).status_code == 403
    (q / "2026" / "draft.docx").write_text("x")
    r = c.post("/api/items/rename", json={"path": str(q / "2026" / "draft.docx"), "newName": "offer.docx"})
    assert r.status_code == 200 and (q / "2026" / "offer.docx").exists()
    r = c.post("/api/items/rename", json={"path": str(q / "2026"), "newName": "2026_Offers"})
    assert r.status_code == 200 and (q / "2026_Offers" / "offer.docx").exists()
    r = c.post("/api/items/delete", json={"path": str(q / "2026_Offers")})
    assert r.status_code == 200 and not (q / "2026_Offers").exists()
    root = q.parents[3]
    assert os.path.exists(r.json()["recycledTo"]) and "Recycle" in r.json()["recycledTo"]
    # the structure folders are protected
    assert c.post("/api/items/delete", json={"path": str(root / "02_Customers" / "Customer_A")}).status_code == 403
    assert c.post("/api/items/rename", json={"path": str(root / "02_Customers"), "newName": "x"}).status_code == 403


def test_controlled_files_are_protected(env):
    c, sp, q = env
    f = q / "CRU 4 FCT Quote_Rev1.xlsx"
    c.post("/api/documents", json={"path": str(f), "documentType": "נוהל", "documentArea": "מסחרי"})
    assert c.post("/api/items/delete", json={"path": str(f)}).status_code == 409
    assert c.post("/api/items/rename", json={"path": str(f), "newName": "x.xlsx"}).status_code == 409
    assert c.post("/api/items/delete", json={"path": str(q)}).status_code in (403, 409)   # skeleton folder holding it
    (q / "Current_ReadOnly").mkdir()
    (q / "Current_ReadOnly" / "a.xlsx").write_text("x")
    assert c.post("/api/items/delete", json={"path": str(q / "Current_ReadOnly" / "a.xlsx")}).status_code == 403
    assert f.exists()


def test_actions_need_ad_write(env, limited):
    c, _, q = limited
    other = q.parent / "Contracts"
    other.mkdir()
    assert c.post("/api/folders", json={"parent": str(other), "name": "x"}).status_code == 403
    assert c.post("/api/items/delete", json={"path": str(other)}).status_code == 403


def test_blueprint_labels_order_and_context(env):
    c, _, q = env
    cust = q.parents[1]                                  # Customer_A
    for d in ("Projects/PRJ-1/Development/02_SOW", "Projects/PRJ-1/Engineering", "Customer_Profile", "Zeta_Extra"):
        (cust / d).mkdir(parents=True, exist_ok=True)
    r = c.get("/api/browse", params={"path": str(cust)}).json()
    assert [f["name"] for f in r["folders"]] == ["Customer_Profile", "Commercial", "Projects", "Zeta_Extra"]
    assert r["folders"][1]["label"]["he"] == "מסחרי" and r["folders"][3]["label"] is None
    assert r["node"]["kind"] == "customer" and r["context"]["customer"]["name"] == "Customer_A"
    prj = c.get("/api/browse", params={"path": str(cust / "Projects" / "PRJ-1")}).json()
    assert prj["node"]["kind"] == "project" and prj["context"]["project"]["name"] == "PRJ-1"
    assert [f["name"] for f in prj["folders"]] == ["Engineering", "Development"]
    dev = c.get("/api/browse", params={"path": str(cust / "Projects" / "PRJ-1" / "Development")}).json()
    assert dev["folders"][0]["label"]["en"] == "02 Statement of work"
    assert [t["name"] for t in dev["trail"]] == ["02_Customers", "Customer_A", "Projects", "PRJ-1", "Development"]


def test_root_hides_system_folders_and_areas(env):
    c, _, q = env
    root = q.parents[3]
    (root / "04_Workflow_System").mkdir()
    (root / "01_Management").mkdir()
    assert "04_Workflow_System" not in [f["name"] for f in c.get("/api/browse").json()["folders"]]
    assert [a["name"] for a in c.get("/api/areas").json()] == ["01_Management", "02_Customers"]


def test_save_guide(env):
    c, _, q = env
    cust = q.parents[1]
    kinds = {g["key"]: g for g in c.get("/api/guide").json()}
    assert kinds["quotation"]["needsProject"] is False and kinds["eco"]["needsProject"] is True
    t = c.get("/api/guide/target", params={"key": "quotation", "customer": str(cust)}).json()
    assert t["path"] == str(q) and t["exists"] and t["canWrite"]
    assert c.get("/api/guide/target", params={"key": "eco", "customer": str(cust)}).status_code == 400
    (cust / "Projects" / "PRJ-1").mkdir(parents=True)
    assert [p["name"] for p in c.get("/api/projects", params={"customer": str(cust)}).json()] == ["PRJ-1"]
    t = c.get("/api/guide/target", params={"key": "eco", "customer": str(cust), "project": str(cust / "Projects" / "PRJ-1")}).json()
    assert t["path"].endswith(os.path.join("PRJ-1", "Changes", "ECO")) and not t["exists"]
    made = c.post("/api/guide/create", params={"key": "eco", "customer": str(cust), "project": str(cust / "Projects" / "PRJ-1")})
    assert made.status_code == 201 and os.path.isdir(made.json()["path"])


def test_levels_cascade(env, limited):
    c, _, q = env
    root = q.parents[3]
    (root / "04_Workflow_System").mkdir()
    (q / "Current_ReadOnly").mkdir()
    lv = c.get("/api/levels", params={"path": str(q)}).json()
    assert [l["selected"] for l in lv] == ["02_Customers", "Customer_A", "Commercial", "Quotations"]
    assert [o["name"] for o in lv[0]["options"]] == ["02_Customers"]          # system folder hidden
    assert [o["name"] for o in lv[1]["options"]] == ["Customer_A"]            # AD: no Customer_B
    assert lv[2]["options"][0]["label"]["he"] == "מסחרי"
    assert len(lv) == 4                                                       # Current_ReadOnly is not offered
    nxt = c.get("/api/levels", params={"path": str(q.parent)}).json()
    assert nxt[-1]["selected"] is None and [o["name"] for o in nxt[-1]["options"]] == ["Quotations"]


def test_my_workflows(env):
    c, sp, q = env
    a = c.post("/api/documents", json={"path": str(q / "CRU 4 FCT Quote_Rev1.xlsx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    (q / "B.docx").write_text("x")
    b = c.post("/api/documents", json={"path": str(q / "B.docx"), "documentType": "נוהל", "documentArea": "מסחרי", "submit": True}).json()
    (q / "C.docx").write_text("x")
    c.post("/api/documents", json={"path": str(q / "C.docx"), "documentType": "נוהל", "documentArea": "מסחרי"})
    # the flow: A approved, B rejected (back to Working)
    sp.items[a["id"]]["lifecycleStatus"] = "מאושר - קריאה בלבד"
    sp.audit(document_id=a["documentId"], event="אושר", from_status="הוגש לאישור", to_status="מאושר - קריאה בלבד", actor="boss@rh.co.il", details="ok")
    sp.items[b["id"]]["lifecycleStatus"] = "בעבודה"
    sp.audit(document_id=b["documentId"], event="נדחה", from_status="הוגש לאישור", to_status="בעבודה", actor="boss@rh.co.il", details="fix p.3")
    # someone else's document is not listed
    sp.items[99] = {**sp.items[a["id"]], "id": 99, "documentId": "DMS-00099", "ownerEmail": "other@rh.co.il"}
    r = c.get("/api/my-workflows").json()
    assert r["summary"] == {"Working": 1, "Submitted": 0, "Approved_ReadOnly": 1, "Rejected": 1}
    by = {i["documentId"]: i for i in r["items"]}
    assert set(by) == {"DMS-00001", "DMS-00002", "DMS-00003"}
    assert by["DMS-00002"]["statusKey"] == "Rejected" and by["DMS-00002"]["decision"]["details"] == "fix p.3"
    assert by["DMS-00001"]["decision"]["actor"] == "boss@rh.co.il" and by["DMS-00001"]["submittedUtc"]
    assert [e["event"] for e in by["DMS-00001"]["history"]] == ["נוצר", "הוגש", "אושר"]


class FakeAI:
    enabled = True

    def __init__(self):
        self.calls = []

    def ask(self, question, **kw):
        self.calls.append((question, kw))
        return {"answer": "summary", "sources": ["x.pdf"], "model": "m"}


def test_ai_insights(env, limited):
    c, sp, q = env
    ai = FakeAI()
    c.app.state.ai = ai
    r = c.post("/api/ai/ask", json={"question": "סכם את המסמך", "path": str(q / "CRU 4 FCT Quote_Rev1.xlsx"), "lang": "HE"})
    assert r.status_code == 200 and r.json()["answer"] == "summary"
    q_, kw = ai.calls[-1]
    assert kw["file_path"].endswith("CRU 4 FCT Quote_Rev1.xlsx") and kw["lang"] == "HE" and "Not registered" in kw["context"]
    assert c.post("/api/ai/ask", json={"question": "What is our NDA policy?"}).json()["sources"] == ["x.pdf"]
    assert ai.calls[-1][1]["file_path"] is None
    b = q.parents[2] / "Customer_B" / "secret.pdf"
    b.write_text("x")
    assert c.post("/api/ai/ask", json={"question": "Summarize", "path": str(b)}).status_code == 403
    c.app.state.ai = type("Off", (), {"enabled": False})()
    assert c.post("/api/ai/ask", json={"question": "hi"}).status_code == 503


def _tree_for_find(q):
    cust = q.parents[1]
    prj = cust / "Projects" / "PRJ-101_CRU4"
    for d in ("Changes/ECO", "Test_Engineering/Test_Reports", "Development/Obsolete_ReadOnly"):
        (prj / d).mkdir(parents=True)
    (prj / "Changes" / "ECO" / "ECO-17 connector change.docx").write_text("x")
    (prj / "Test_Engineering" / "Test_Reports" / "FCT report lot 3.pdf").write_text("x")
    (prj / "Development" / "Obsolete_ReadOnly" / "FCT report lot 1.pdf").write_text("x")
    secret = q.parents[2] / "Customer_B" / "Commercial"
    secret.mkdir(parents=True)
    (secret / "FCT quote Customer_B.xlsx").write_text("x")
    return prj


def test_find_without_ai_uses_keywords_and_ad(env, limited):
    c, _, q = env
    _tree_for_find(q)
    r = c.post("/api/ai/find", json={"question": "FCT quote"}).json()
    names = [x["name"] for x in r["suggestions"]]
    assert r["usedAi"] is False and names[0] == "CRU 4 FCT Quote_Rev1.xlsx"
    assert "FCT quote Customer_B.xlsx" not in names            # AD: Customer_B is not visible
    assert "FCT report lot 1.pdf" not in names                  # superseded revisions are not offered
    assert "FCT report lot 3.pdf" in names


class PlanningAI(FakeAI):
    def plan_search(self, question, customers, kinds):
        self.seen_customers = customers
        return {"terms": ["connector"], "customer": "Customer_A", "project": "PRJ-101", "kind": "eco", "extensions": [], "latest": True}

    def rank(self, question, candidates, lang="EN"):
        self.ranked = [c["relative"] for c in candidates]
        return [{"i": 0, "reason": "ECO about the connector"}]


def test_find_with_ai_plan_and_rank(env, limited):
    c, _, q = env
    _tree_for_find(q)
    ai = PlanningAI()
    c.app.state.ai = ai
    r = c.post("/api/ai/find", json={"question": "the ECO about the connector in the CRU4 project", "lang": "EN"}).json()
    assert r["usedAi"] and r["plan"] == {"terms": ["connector"], "customer": "Customer_A", "project": "PRJ-101_CRU4", "kind": "eco"}
    assert ai.seen_customers == ["Customer_A"]                  # the AI only hears about allowed customers
    assert all("Customer_B" not in p for p in ai.ranked)
    assert [x["name"] for x in r["suggestions"]] == ["ECO-17 connector change.docx"]
    assert r["suggestions"][0]["reason"] == "ECO about the connector"


def test_playground_memory_mode(tmp_path):
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory")
    c = TestClient(create_app(s))
    assert c.get("/api/client-config").json()["playground"] is True
    assert "הצעת מחיר" in c.get("/api/options").json()["DocumentType"]
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "documentType": "הצעת מחיר", "documentArea": "מסחרי", "submit": True}).json()
    assert d["statusKey"] == "Submitted"
    r = c.post(f"/api/playground/decide/{d['id']}", params={"approve": False, "comment": "fix p.2"}).json()
    assert r["statusKey"] == "Working"
    wf = c.get("/api/my-workflows").json()
    assert wf["items"][0]["statusKey"] == "Rejected" and wf["items"][0]["decision"]["details"] == "fix p.2"
    c.post(f"/api/documents/{d['id']}/submit")
    assert c.post(f"/api/playground/decide/{d['id']}").json()["statusKey"] == "Approved_ReadOnly"
    s2 = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER)
    assert TestClient(create_app(s2, FakeSharePoint(s2))).post("/api/playground/decide/1").status_code == 404


def test_file_service_moves_by_status(tmp_path):
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote_DRAFT.xlsx").write_text("v1")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", file_service_seconds=1)
    sp = MemorySharePoint(s)
    d = sp.create_document(title="Q", path=str(q / "Quote_DRAFT.xlsx"), document_type="x", document_area="y",
                           owner_email=USER, control_mode=None, document_id=None)
    sp.update(d["id"], {"LifecycleStatus": "הוגש לאישור"})
    r = file_service.run_once(sp, s)
    assert (r["moved"], r["failed"]) == (1, 0) and r["report"][0]["result"].startswith("MoveToSubmitted")
    sub = q / "Submitted" / "Quote_DRAFT.xlsx"
    assert sub.exists() and file_service.is_read_only(str(sub))
    assert sp.document(d["id"])["workingUncPath"] == str(q / "Quote_DRAFT.xlsx")      # Submitted record not touched
    sp.update(d["id"], {"LifecycleStatus": "בעבודה"})                                  # rejected
    file_service.run_once(sp, s)
    assert (q / "Quote_DRAFT.xlsx").exists() and not file_service.is_read_only(str(q / "Quote_DRAFT.xlsx"))
    sp.update(d["id"], {"LifecycleStatus": "מאושר - קריאה בלבד"})                      # approved without passing Submitted
    file_service.run_once(sp, s)
    cur = q / "Current_ReadOnly" / "Quote.xlsx"
    doc = sp.document(d["id"])
    assert cur.exists() and file_service.is_read_only(str(cur))
    assert doc["currentUncPath"] == str(cur) and len(doc["currentSHA256"]) == 64 and doc["workingUncPath"] == ""
    r = file_service.run_once(sp, s)
    assert (r["moved"], r["failed"]) == (0, 0)                                          # idempotent
    events = [e["event"] for e in sp.audit_events()]
    assert events.count("פעולת קובץ הושלמה") == 3 and sp.audit_events()[0]["source"] == "שירות תהליכים"
    c = TestClient(create_app(Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory"), sp))
    assert c.get("/api/browse", params={"path": str(q / "Current_ReadOnly")}).json()["files"][0]["document"]["statusKey"] == "Approved_ReadOnly"


def test_super_user(env):
    c, sp, q = env
    d = c.post("/api/documents", json={"path": str(q / "CRU 4 FCT Quote_Rev1.xlsx"), "documentType": "נוהל", "documentArea": "מסחרי"}).json()
    sp.items[d["id"]]["ownerEmail"] = "someone@rh.co.il"
    assert c.post(f"/api/documents/{d['id']}/submit").status_code == 403
    assert c.get("/api/my-workflows", params={"everyone": True}).json()["items"][0]["documentId"] == "DMS-00001"  # registered by me
    c.app.state.settings.admins = [USER]
    assert c.get("/api/me").json()["admin"] is True
    assert c.post(f"/api/documents/{d['id']}/submit").status_code == 200
    sp.items[d["id"]]["documentId"] = "DMS-00077"           # not mine at all any more
    assert c.get("/api/my-workflows").json()["items"] == []
    assert [i["documentId"] for i in c.get("/api/my-workflows", params={"everyone": True}).json()["items"]] == ["DMS-00077"]


class RuleSP(FakeSharePoint):
    def __init__(self, s, rule):
        super().__init__(s)
        self.rule = rule

    def approver_rule(self, document_type):
        return self.rule


def _approvals_env(tmp_path, rule, me=USER, admins=()):
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=me, approvals="page", admins=list(admins))
    sp = RuleSP(s, rule)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "documentType": "הצעת מחיר", "documentArea": "מסחרי", "submit": True}).json()
    return c, sp, s, d


def test_page_approvals_two_stages(tmp_path):
    rule = {"mandatory": [USER, "dana@rh.co.il"], "final": "boss@rh.co.il"}
    c, sp, s, d = _approvals_env(tmp_path, rule)
    a = c.get("/api/approvals").json()
    assert [x["documentId"] for x in a] == ["DMS-00001"] and a[0]["stage"] == 1 and a[0]["pending"] == [USER, "dana@rh.co.il"]
    r = c.post(f"/api/approvals/{d['id']}", json={"approve": True, "comment": "ok"}).json()
    assert r["statusKey"] == "Submitted" and r["pending"] == ["dana@rh.co.il"]
    assert c.get("/api/approvals").json() == []                                         # not mine any more
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).status_code == 403
    s.dev_user = "dana@rh.co.il"
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).json()["stage"] == 2
    s.dev_user = "boss@rh.co.il"
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": False}).status_code == 400   # a comment is required
    r = c.post(f"/api/approvals/{d['id']}", json={"approve": True, "comment": "final"}).json()
    assert r["statusKey"] == "Approved_ReadOnly" and sp.items[d["id"]]["LastApprovedUtc"]
    events = [(e["event"], e["details"]) for e in sp.audit_events()][:3]
    assert events == [("אושר", "Stage 2: final"), ("אושר", "Stage 1"), ("אושר", "Stage 1: ok")]


def test_page_approvals_reject_and_waiting_for(tmp_path):
    rule = {"mandatory": ["dana@rh.co.il"], "final": "boss@rh.co.il"}
    c, sp, s, d = _approvals_env(tmp_path, rule)
    wf = c.get("/api/my-workflows").json()["items"][0]
    assert wf["stage"] == 1 and wf["pending"] == ["dana@rh.co.il"]                      # who it waits for
    s.dev_user = "dana@rh.co.il"
    r = c.post(f"/api/approvals/{d['id']}", json={"approve": False, "comment": "fix p.2"}).json()
    assert r["statusKey"] == "Working"
    s.dev_user = USER
    item = c.get("/api/my-workflows").json()["items"][0]
    assert item["statusKey"] == "Rejected" and item["decision"]["details"] == "Stage 1: fix p.2"
    c.post(f"/api/documents/{d['id']}/submit")                                          # new cycle: the old rejection no longer counts
    s.dev_user = "dana@rh.co.il"
    assert c.get("/api/approvals").json()[0]["pending"] == ["dana@rh.co.il"]


def test_super_user_can_decide_any_stage(tmp_path):
    rule = {"mandatory": ["dana@rh.co.il"], "final": "boss@rh.co.il"}
    c, sp, s, d = _approvals_env(tmp_path, rule, me="roneno@rh.co.il", admins=["roneno@rh.co.il"])
    assert c.get("/api/approvals").json() == []
    assert c.get("/api/approvals", params={"everyone": True}).json()[0]["mine"] is False
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).json()["stage"] == 2
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).json()["statusKey"] == "Approved_ReadOnly"
    assert sp.audit_events()[0]["details"] == "Stage 2 (super user)"


def test_flow_mode_keeps_teams(env):
    c, _, _ = env
    assert c.get("/api/approvals").json() == []
    assert c.post("/api/approvals/1", json={"approve": True}).status_code == 409


def test_withdraw_and_resubmit(tmp_path):
    rule = {"mandatory": ["dana@rh.co.il"], "final": "boss@rh.co.il"}
    c, sp, s, d = _approvals_env(tmp_path, rule, me="roneno@rh.co.il", admins=["roneno@rh.co.il"])
    s.dev_user = "dana@rh.co.il"
    c.post(f"/api/approvals/{d['id']}", json={"approve": True})                       # stage 1 done
    assert c.post(f"/api/documents/{d['id']}/withdraw").status_code == 403             # not owner, not super user
    s.dev_user = "roneno@rh.co.il"
    r = c.post(f"/api/documents/{d['id']}/withdraw").json()
    assert r["statusKey"] == "Working" and sp.audit_events()[0]["event"] == "בוטל"
    assert c.post(f"/api/documents/{d['id']}/withdraw").status_code == 409
    c.post(f"/api/documents/{d['id']}/submit")
    s.dev_user = "dana@rh.co.il"
    assert c.get("/api/approvals").json()[0]["stage"] == 1                             # a new cycle starts at stage 1


def test_system_files_hidden(env):
    c, _, q = env
    (q / "Thumbs.db").write_text("x")
    (q / "desktop.ini").write_text("x")
    names = [f["name"] for f in c.get("/api/browse", params={"path": str(q)}).json()["files"]]
    assert "Thumbs.db" not in names and "desktop.ini" not in names and "CRU 4 FCT Quote_Rev1.xlsx" in names
    assert all(x["name"] != "Thumbs.db" for x in c.get("/api/search", params={"q": "thumbs"}).json())


def test_file_service_report_and_old_layout(tmp_path):
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    old = q / "COM-QUO-00001_CRU4_FCT_Quote"                 # the old per-document layout
    (old / "Submitted").mkdir(parents=True)
    (old / "Submitted" / "COM-QUO-00001_Rev01_DRAFT.xlsx").write_text("v1")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory")
    sp = MemorySharePoint(s)
    a = sp.create_document(title="CRU", path=str(old / "Working" / "COM-QUO-00001_Rev01_DRAFT.xlsx"), document_type="x",
                           document_area="y", owner_email=USER, control_mode=None, document_id="COM-QUO-00001")
    b = sp.create_document(title="Out", path=r"\\OTHER\share\x.xlsx", document_type="x", document_area="y",
                           owner_email=USER, control_mode=None, document_id=None)
    sp.update(a["id"], {"LifecycleStatus": "מאושר - קריאה בלבד"})
    sp.update(b["id"], {"LifecycleStatus": "הוגש לאישור"})
    r = file_service.run_once(sp, s)
    by = {x["documentId"]: x["result"] for x in r["report"]}
    assert r["moved"] == 1 and (old / "Current_ReadOnly" / "COM-QUO-00001_Rev01.xlsx").exists()
    assert by["COM-QUO-00001"].startswith("PromoteToCurrent") and "outside the repository root" in by["DMS-00002"]
    assert file_service.run_once(sp, s)["report"][0]["result"].startswith("current:")


def test_path_finder(env):
    c, _, q = env
    cust = q.parents[1]
    (cust / "Projects" / "PRJ-1").mkdir(parents=True)
    top = c.get("/api/pathfinder").json()
    assert [o["name"] for o in top["options"]] == ["01_Management", "02_Customers"] and top["options"][0]["exists"] is False
    lv = c.get("/api/pathfinder", params={"path": str(cust)}).json()
    assert [(o["name"], o["exists"]) for o in lv["options"]] == [("Customer_Profile", False), ("Commercial", True), ("Projects", True),
                                                                  ("Shared", False), ("Archive", False)]
    prj = c.get("/api/pathfinder", params={"path": str(cust / "Projects" / "PRJ-1")}).json()
    assert prj["node"]["kind"] == "project" and len(prj["options"]) == 12 and not any(o["exists"] for o in prj["options"])
    target = cust / "Projects" / "PRJ-1" / "Test_Engineering" / "ATEFiles" / "FCT" / "07_FAT"
    r = c.post("/api/pathfinder/create", params={"path": str(target)})
    assert r.status_code == 201 and target.is_dir()
    bad = cust / "Projects" / "PRJ-1" / "Random" / "x"
    assert c.post("/api/pathfinder/create", params={"path": str(bad)}).status_code == 400 and not bad.exists()
    assert c.post("/api/pathfinder/create", params={"path": str(cust.parent / "New_Customer" / "Commercial")}).status_code == 400


def test_path_finder_through_missing_folders(env):
    c, _, q = env
    prj = q.parents[1] / "Projects" / "PRJ-2"
    prj.mkdir(parents=True)
    r = c.get("/api/pathfinder", params={"path": str(prj / "Test_Engineering" / "ATEFiles")}).json()
    assert r["exists"] is False and [o["name"] for o in r["options"]] == ["ICT", "FCT", "FTP", "JTAG"]
    assert c.get("/api/pathfinder", params={"path": str(prj / "Nope" / "Deeper")}).status_code == 404


def _approved_env(tmp_path):
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "CRU 4 FCT Quote_Rev1.xlsx").write_text("rev1")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "CRU 4 FCT Quote_Rev1.xlsx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    assert sp.document(d["id"])["draftRevision"] == "01"
    c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    file_service.run_once(sp, s)
    return c, sp, s, q, d, file_service


def test_new_revision_from_the_approved_copy(tmp_path):
    c, sp, s, q, d, fs = _approved_env(tmp_path)
    cur = q / "Current_ReadOnly" / "CRU 4 FCT Quote_Rev1.xlsx"
    assert cur.exists() and sp.document(d["id"])["currentRevision"] == "01"
    r = c.post(f"/api/documents/{d['id']}/revise")
    assert r.status_code == 200, r.text
    draft = q / "CRU 4 FCT Quote_Rev02_DRAFT.xlsx"
    assert r.json()["draft"] == str(draft) and draft.read_text() == "rev1" and not fs.is_read_only(str(draft))
    doc = sp.document(d["id"])
    assert doc["lifecycleStatus"] == "בעבודה" and doc["draftRevision"] == "02" and doc["currentUncPath"] == str(cur)
    assert c.post(f"/api/documents/{d['id']}/revise").status_code == 409            # only from Approved
    draft.write_text("rev2")
    c.post(f"/api/documents/{d['id']}/submit")
    c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    fs.run_once(sp, s)
    new = q / "Current_ReadOnly" / "CRU 4 FCT Quote_Rev02.xlsx"
    assert new.read_text() == "rev2" and (q / "Obsolete_ReadOnly" / "CRU 4 FCT Quote_Rev1.xlsx").exists()
    doc = sp.document(d["id"])
    assert doc["currentRevision"] == "02" and doc["currentUncPath"] == str(new) and not cur.exists()


def test_new_revision_from_an_uploaded_file(tmp_path):
    c, sp, s, q, d, fs = _approved_env(tmp_path)
    r = c.post(f"/api/documents/{d['id']}/revise", data={"submit": "true"}, files={"file": ("my new quote.xlsx", b"fresh")})
    assert r.status_code == 200 and r.json()["statusKey"] == "Submitted"
    assert (q / "CRU 4 FCT Quote_Rev02_DRAFT.xlsx").read_bytes() == b"fresh"


def test_workflow_folders_are_untouchable(tmp_path):
    c, sp, s, q, d, fs = _approved_env(tmp_path)
    cur = q / "Current_ReadOnly"
    assert c.post("/api/items/delete", json={"path": str(cur)}).status_code == 403
    assert c.post("/api/items/rename", json={"path": str(cur), "newName": "x"}).status_code == 403
    assert c.post("/api/folders", json={"parent": str(cur), "name": "x"}).status_code == 403
    assert c.post("/api/files/upload", data={"folder": str(cur)}, files={"file": ("a.txt", b"x")}).status_code == 403
    (q / "Other").mkdir()
    (q / "Other" / "Submitted").mkdir()                       # an unregistered folder holding a workflow folder
    assert c.post("/api/items/delete", json={"path": str(q / "Other")}).status_code == 403
    b = c.get("/api/browse", params={"path": str(cur)}).json()
    assert b["managed"] is True and b["canWrite"] is False


def test_repository_changes_are_audited(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory")
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    c.post("/api/files/upload", data={"folder": str(q)}, files={"file": ("a.txt", b"x")})
    c.post("/api/folders", json={"parent": str(q), "name": "2026"})
    c.post("/api/items/rename", json={"path": str(q / "a.txt"), "newName": "b.txt"})
    c.post("/api/items/delete", json={"path": str(q / "b.txt")})
    rows = [(e["documentId"], e["details"].split(":")[0], e["actor"]) for e in reversed(sp.audit_events())]
    assert rows == [("FS", "upload", USER), ("FS", "new-folder", USER), ("FS", "rename", USER), ("FS", "delete", USER)]
    assert str(root) not in sp.audit_events()[0]["details"]                          # paths relative to the root


def test_notifications_follow_the_approval(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Q.xlsx").write_text("x")
    (q / "R.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 page_url="https://dms/dms/dms-page?lang=EN")

    class Rules(MemorySharePoint):
        def approver_rule(self, t):
            return {"mandatory": ["dana@rh.co.il", "eli@rh.co.il"], "final": "boss@rh.co.il"}
    sp = Rules(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Q.xlsx"), "documentType": "x", "documentArea": "y", "submit": True}).json()
    n = sp.notifications
    assert n[-1]["to"] == ["dana@rh.co.il", "eli@rh.co.il"] and "waiting" in n[-1]["subject"] and n[-1]["link"].endswith("view=approvals")
    for who in ("dana@rh.co.il", "eli@rh.co.il"):
        s.dev_user = who
        c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    assert n[-1]["to"] == ["boss@rh.co.il"] and len(n) == 2                       # stage 1 complete -> final approver only
    s.dev_user = "boss@rh.co.il"
    c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    assert n[-1]["to"] == [USER] and "approved" in n[-1]["subject"]
    s.dev_user = USER
    e = c.post("/api/documents", json={"path": str(q / "R.xlsx"), "documentType": "x", "documentArea": "y", "submit": True}).json()
    c.post(f"/api/documents/{e['id']}/withdraw")
    assert "withdrawn" in n[-1]["subject"] and n[-1]["to"] == ["dana@rh.co.il", "eli@rh.co.il"]
    c.post(f"/api/documents/{e['id']}/submit")
    s.dev_user = "dana@rh.co.il"
    c.post(f"/api/approvals/{e['id']}", json={"approve": False, "comment": "fix p.2"})
    assert n[-1]["to"] == [USER] and "fix p.2" in n[-1]["body"]


def test_share_with_customer(tmp_path):
    c, sp, s, q, d, fs = _approved_env(tmp_path)
    r = c.post(f"/api/documents/{d['id']}/share", json={"email": "Edssrom@gmail.com"})
    assert r.status_code == 200, r.text
    assert r.json()["revision"] == "01" and sp.shares[0]["email"] == "edssrom@gmail.com"
    assert "Outbound/DMS-00001_Rev01/CRU 4 FCT Quote_Rev1.xlsx" in sp.shares[0]["url"]
    ev = sp.audit_events()[0]
    assert ev["event"] == "שינוי הרשאות" and "edssrom@gmail.com" in ev["details"]
    assert c.post(f"/api/documents/{d['id']}/share", json={"email": "not-an-email"}).status_code == 422
    c.post(f"/api/documents/{d['id']}/revise")                                     # in work again: not shareable
    assert c.post(f"/api/documents/{d['id']}/share", json={"email": "edssrom@gmail.com"}).status_code == 409


def test_share_payloads():
    import json as j
    from tests.test_sharepoint import Resp
    from dms_api.sharepoint import SharePoint

    class Sess:
        def __init__(self):
            self.calls = []

        def request(self, method, url, json=None, data=None, headers=None, timeout=None):
            self.calls.append((method, url, json, data))
            if "Files/AddUsingPath" in url:
                return Resp({"ServerRelativeUrl": "/sites/LargeFileExchange-TEST/TemporaryUploads/Outbound/DMS-1_Rev01/Q.xlsx"})
            if url.endswith("SP.Web.ShareObject"):
                return Resp({"StatusCode": 0, "ErrorMessage": None})
            return Resp({})
    import tempfile, os
    f = os.path.join(tempfile.mkdtemp(), "Q.xlsx")
    open(f, "wb").write(b"x")
    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST",
                 ex_site_url="https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST")
    sess = Sess()
    sp = SharePoint(s, sess)
    sp._access_token = lambda: "t"
    r = sp.share_with_guest(local_path=f, folder="Outbound/DMS-1_Rev01", email="edssrom@gmail.com", subject="S", message="M")
    assert r["url"] == "https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST/TemporaryUploads/Outbound/DMS-1_Rev01/Q.xlsx"
    share = sess.calls[-1][2]
    assert share["roleValue"] == "role:1073741826" and share["sendEmail"] is True and share["includeAnonymousLinkInEmail"] is False
    assert j.loads(share["peoplePickerInput"])[0]["Key"] == "edssrom@gmail.com"
    assert sess.calls[2][3] == b"x"                                                # the file bytes were uploaded


class FakeLinker:
    enabled = True

    def __init__(self, registered):
        self.registered, self.replaced = set(registered), []

    def is_registered(self, path):
        return path in self.registered

    def replace(self, old, new):
        self.replaced.append((old, new))


def _wait(c, job_id):
    import time
    for _ in range(200):
        j = c.get(f"/api/first-load/{job_id}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("first load did not finish")


def test_first_loading(tmp_path):
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    old = tmp_path / "OldRepo" / "CRU4"
    (old / "Tests").mkdir(parents=True)
    (old / "Spec_Rev3.pdf").write_text("spec")
    (old / "Tests" / "FCT plan.docx").write_text("plan")
    (old / "Thumbs.db").write_text("x")
    root = tmp_path / "Root"
    target = root / "02_Customers" / "Customer_A" / "Projects" / "PRJ-1" / "Customer_Source"
    target.mkdir(parents=True)
    (target / "Spec_Rev3.pdf").write_text("spec")            # already moved manually; FCT plan is still only in the source
    os.remove(old / "Spec_Rev3.pdf")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    linker = FakeLinker({str(old / "Spec_Rev3.pdf")})
    c.app.state.linker = linker
    body = {"source": str(old), "target": str(target), "documentType": "שרטוט", "documentArea": "פיתוח"}
    dry = _wait(c, c.post("/api/first-load", json=body).json()["id"])
    assert dry["total"] == 2 and all(r["result"].startswith("plan") for r in dry["rows"]) and not sp.items
    assert {r["fileLinker"] for r in dry["rows"]} == {"registered - would be updated", "not registered"}
    j = _wait(c, c.post("/api/first-load", json={**body, "dryRun": False}).json()["id"])
    by = {os.path.basename(r["target"]): r for r in j["rows"]}
    assert by["Spec_Rev3.pdf"]["result"] == "loaded" and by["Spec_Rev3.pdf"]["revision"] == "03"
    assert by["FCT plan.docx"]["result"] == "loaded" and by["FCT plan.docx"]["revision"] == "01"
    cur = target / "Current_ReadOnly" / "Spec_Rev3.pdf"
    assert cur.exists() and file_service.is_read_only(str(cur)) and (target / "Tests" / "Current_ReadOnly" / "FCT plan.docx").exists()
    assert not (target / "Spec_Rev3.pdf").exists()
    docs = {d["title"]: d for d in sp.documents()}
    assert docs["Spec_Rev3"]["lifecycleStatus"] == "מאושר - קריאה בלבד" and docs["Spec_Rev3"]["currentUncPath"] == str(cur)
    assert len(docs["Spec_Rev3"]["currentSHA256"]) == 64
    assert linker.replaced == [(str(old / "Spec_Rev3.pdf"), str(cur))] and by["Spec_Rev3.pdf"]["fileLinker"] == "updated"
    assert any("DMS First loading" in e["details"] for e in sp.audit_events())
    assert j["report"] and os.path.isfile(j["report"])
    again = _wait(c, c.post("/api/first-load", json={**body, "dryRun": False}).json()["id"])
    assert all(r["result"] == "skipped - already loaded" for r in again["rows"])
    assert file_service.run_once(sp, s)["moved"] == 0                                   # the file service leaves them alone
    s.admins = []
    assert c.post("/api/first-load", json=body).status_code == 403


def test_first_loading_writes_a_full_log(tmp_path):
    from dms_api.memory import MemorySharePoint
    old = tmp_path / "Old"
    old.mkdir()
    (old / "A_Rev2.pdf").write_text("a")
    root = tmp_path / "Root"
    target = root / "02_Customers" / "Customer_A" / "Commercial"
    target.mkdir(parents=True)
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    c.app.state.linker = FakeLinker({str(old / "A_Rev2.pdf")})
    j = _wait(c, c.post("/api/first-load", json={"source": str(old), "target": str(target), "documentType": "x",
                                                 "documentArea": "y", "dryRun": False}).json()["id"])
    log = open(j["log"], encoding="utf-8-sig").read()
    for text in ("started by", "source: " + str(old), "copied from the source", "SHA-256", "registered DMS-00001",
                 "WebAPI#1", "WebAPI#2", "Finished: 1 files - loaded: 1", "CSV report"):
        assert text in log, text
    assert j["log"].endswith(".log") and j["report"].replace(".csv", ".log") == j["log"]
    summary = [a for a in sp.audits if a["documentId"].startswith("FIRST-LOAD-")]
    assert len(summary) == 1 and "loaded: 1" in summary[0]["details"] and j["log"] in summary[0]["details"]
    assert sorted(a["name"][-3:] for a in sp.attachments) == ["csv", "log"]


def test_skeleton_is_protected_content_is_not(env):
    c, _, q = env
    content = q / "Old quotes 2019" / "Archive A"
    content.mkdir(parents=True)
    (q.parent / "NDA").mkdir()                                # an empty blueprint folder
    assert c.post("/api/items/delete", json={"path": str(q.parent / "NDA")}).status_code == 403
    assert c.post("/api/items/rename", json={"path": str(q), "newName": "Quotes"}).status_code == 403
    assert c.post("/api/items/rename", json={"path": str(content), "newName": "Archive B"}).status_code == 200
    assert c.post("/api/items/delete", json={"path": str(q / "Old quotes 2019")}).status_code == 200


def test_ai_questions_are_kept_in_control_audit(env):
    c, sp, q = env
    assert c.post("/api/ai/chat-log", json={"question": "What is the FCT lead time?"}).status_code == 204
    c.post("/api/ai/find", json={"question": "FCT quote Customer_A"})
    rows = [a for a in sp.audits if a["document_id"] == "AI"]
    assert [r["details"].split(":")[0] for r in rows] == ["ai-chat", "ai-find"]
    assert "FCT lead time" in rows[0]["details"]


def test_rag_tool_answers_and_is_audited(env):
    c, sp, q = env

    class Http:
        def __init__(self):
            self.sent = []

        def post(self, url, json=None, headers=None, timeout=None):
            self.sent.append((url, json, headers))
            class R:
                status_code, text = 200, ""
                def json(self):
                    return {"answer": "**Calibration** is yearly.", "sources": [
                        {"display_id": "QP-11.0", "display_section": "3.1 Shipping", "snippet": "x",
                         "filename": "QP-11.0-V12.docx", "available": True, "rerank_score": 0.8}]}
            return R()
    http = Http()
    rag = c.app.state.rag
    assert c.get("/api/ai/status").json()["rag"] == []                  # not configured
    rag.http, rag.s.rag_url, rag.s.rag_tools = http, "https://aiportal.ai.rh-global.com/webhook/tools", ["qms"]
    assert c.get("/api/ai/status").json()["rag"] == [{"tool": "qms", "page": "https://aiportal.ai.rh-global.com/webhook/tools?tool=qms"}]
    r = c.post("/api/ai/rag", json={"question": "How often is calibration?", "tool": "qms"}).json()
    assert r["answer"] == "**Calibration** is yearly." and r["sources"][0]["name"] == "QP-11.0"
    c.post("/api/ai/rag", json={"question": "And for ESD?", "tool": "qms"})
    url, body, headers = http.sent[1]
    assert url == "https://aiportal.ai.rh-global.com/webhook/qms-chat" and "Authorization" not in headers
    assert body["question"] == "And for ESD?" and [m["role"] for m in body["history"]] == ["user", "assistant"]
    rows = [a for a in sp.audits if a["document_id"] == "AI"]
    assert rows[0]["details"].startswith("ai-rag") and "Sources: QP-11.0 | 3.1 Shipping" in rows[0]["details"]


def test_type_without_matrix_rule_goes_to_the_super_user(tmp_path):
    c, sp, s, d = _approvals_env(tmp_path, None, admins=[USER])
    a = c.get("/api/approvals").json()
    assert [x["documentId"] for x in a] == ["DMS-00001"] and a[0]["pending"] == [USER]
    r = c.post(f"/api/approvals/{d['id']}", json={"approve": True, "comment": "pilot"}).json()
    assert r["statusKey"] == "Approved_ReadOnly"


def test_type_and_area_inherited_from_the_blueprint_folder(tmp_path):
    from dms_api import blueprint
    from dms_api.memory import MemorySharePoint
    assert blueprint.classify(["01_Management", "Company_Profile"]) == {"area": "Management", "type": "Company Profile"}
    assert blueprint.classify(["02_Customers", "Customer_A", "Projects", "PRJ-1", "Development", "02_SOW", "Working"]) == \
        {"area": "Development", "type": "SOW"}
    assert blueprint.classify(["02_Customers", "Customer_A", "Commercial", "Quotations", "Old 2019"])["type"] == "Quotation"
    assert blueprint.classify(["02_Customers", "Customer_A", "Projects", "PRJ-1", "Quality", "NCR"]) == {"area": "Quality", "type": None}
    root = tmp_path / "Root"
    cp = root / "01_Management" / "Company_Profile"
    cp.mkdir(parents=True)
    (cp / "Profile.docx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    c = TestClient(create_app(s, MemorySharePoint(s)))
    assert c.get("/api/classify", params={"path": str(cp)}).json() == \
        {"documentType": "פרופיל חברה", "documentArea": "ניהול", "controlMode": "תהליך אישור חובה"}
    d = c.post("/api/documents", json={"path": str(cp / "Profile.docx")}).json()
    assert (d["documentType"], d["documentArea"]) == ("פרופיל חברה", "ניהול")
    other = root / "01_Management" / "Templates"
    other.mkdir()
    (other / "T.docx").write_text("x")
    assert c.post("/api/documents", json={"path": str(other / "T.docx")}).status_code == 400   # the folder sets no type


def test_first_loading_takes_the_type_from_each_folder(tmp_path):
    from dms_api.memory import MemorySharePoint
    old = tmp_path / "Old"
    (old / "Quotations").mkdir(parents=True)
    (old / "Quotations" / "Q1.xlsx").write_text("q")
    (old / "NDA").mkdir()
    (old / "NDA" / "N1.pdf").write_text("n")
    root = tmp_path / "Root"
    target = root / "02_Customers" / "Customer_A" / "Commercial"
    target.mkdir(parents=True)
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    j = _wait(c, c.post("/api/first-load", json={"source": str(old), "target": str(target), "dryRun": False}).json()["id"])
    assert sorted((r["documentType"], r["result"]) for r in j["rows"]) == [("הצעת מחיר", "loaded"), ("חוזה / NDA", "loaded")]
    assert sorted(d["documentType"] for d in sp.documents()) == ["הצעת מחיר", "חוזה / NDA"]


def test_withdraw_returns_the_file_with_its_name_and_it_can_be_submitted_again(tmp_path):
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("v1")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "submit": True}).json()
    file_service.run_once(sp, s)
    assert (q / "Submitted" / "Quote.xlsx").is_file() and not (q / "Quote.xlsx").exists()
    assert c.post(f"/api/documents/{d['id']}/withdraw").json()["statusKey"] == "Working"
    assert (q / "Quote.xlsx").read_text() == "v1" and not (q / "Submitted" / "Quote.xlsx").exists()   # back now
    (q / "Quote.xlsx").write_text("v2")
    (q / "Submitted").mkdir(exist_ok=True)
    (q / "Submitted" / "Quote.xlsx").write_text("stale")                       # a leftover copy
    assert c.post(f"/api/documents/{d['id']}/submit").json()["statusKey"] == "Submitted"
    file_service.run_once(sp, s)
    assert sorted(p.name for p in (q / "Submitted").iterdir()) == ["Quote.xlsx"]  # same name, no timestamp
    assert (q / "Submitted" / "Quote.xlsx").read_text() == "v2"


def test_withdraw_finds_a_file_renamed_with_a_timestamp(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    (q / "Submitted").mkdir(parents=True)
    (q / "Quote.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "submit": True}).json()
    (q / "Quote.xlsx").rename(q / "Submitted" / "Quote_20261001101500.xlsx")   # what older versions did
    c.post(f"/api/documents/{d['id']}/withdraw")
    assert (q / "Quote.xlsx").is_file() and list((q / "Submitted").iterdir()) == []
    assert c.post(f"/api/documents/{d['id']}/submit").status_code == 200


def test_delete_a_working_document(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "submit": True}).json()
    assert c.post(f"/api/documents/{d['id']}/delete").status_code == 409            # submitted: withdraw first
    c.post(f"/api/documents/{d['id']}/withdraw")
    r = c.post(f"/api/documents/{d['id']}/delete").json()
    assert r["lifecycleStatus"] == "בארכיון" and not (q / "Quote.xlsx").exists()
    assert list((root / "04_Workflow_System" / "Recycle").rglob("Quote.xlsx"))
    assert sp.audit_events()[0]["event"] == "בוטל" and "Working document deleted" in sp.audit_events()[0]["details"]
    assert c.get("/api/my-workflows").json()["items"] == []


def test_rename_a_working_document(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("x")
    (q / "Other.xlsx").write_text("y")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx")}).json()
    r = c.post(f"/api/documents/{d['id']}/rename", json={"newName": "Quote CRU4_Rev2"}).json()
    assert r["workingUncPath"] == str(q / "Quote CRU4_Rev2.xlsx") and r["title"] == "Quote CRU4_Rev2" and r["draftRevision"] == "02"
    assert (q / "Quote CRU4_Rev2.xlsx").is_file() and not (q / "Quote.xlsx").exists()
    assert sp.audit_events()[0]["details"] == "Renamed: Quote.xlsx -> Quote CRU4_Rev2.xlsx"
    assert c.post(f"/api/documents/{d['id']}/rename", json={"newName": "Other.xlsx"}).status_code == 409   # name taken
    c.post(f"/api/documents/{d['id']}/submit")
    assert c.post(f"/api/documents/{d['id']}/rename", json={"newName": "X"}).status_code == 409             # submitted


def test_main_search_covers_folders_file_names_and_document_ids(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    qa = root / "01_Management" / "Quality" / "Quality and Standards"
    qa.mkdir(parents=True)
    (qa / "QP-2.1 V06 הודעות ללקוחות.docx").write_text("x")
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "CRU 4 FCT Quote_Rev1.xlsx").write_text("x")
    (root / "04_Workflow_System" / "Recycle").mkdir(parents=True)
    (root / "04_Workflow_System" / "Recycle" / "QP-2.1 old.docx").write_text("x")      # system folder: never found
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    c = TestClient(create_app(s, MemorySharePoint(s)))
    d = c.post("/api/documents", json={"path": str(q / "CRU 4 FCT Quote_Rev1.xlsx")}).json()
    names = lambda text: [(x["kind"], x["name"]) for x in c.get("/api/search", params={"q": text, "scope": "quick"}).json()]  # noqa: E731
    assert ("file", "QP-2.1 V06 הודעות ללקוחות.docx") in names("QP-2.1")                 # Management, file name
    assert all("old" not in n for _, n in names("QP-2.1"))
    assert ("folder", "Quality and Standards") in names("standards")                    # folder
    assert names(d["documentId"])[0] == ("document", "CRU 4 FCT Quote_Rev1")            # Document ID first
    assert names("quote fct")[0][0] == "document"                                       # words in any order
    assert ("file", "CRU 4 FCT Quote_Rev1.xlsx") not in names("quote fct")              # not listed twice


def test_open_link_uses_the_short_path_only_when_long():
    from dms_api import files
    short = r"\\srv\Shares\02_Customers\A\Quote.xlsx"
    assert files.office_uri(short) == "ms-excel:ofv|u|file://srv/Shares/02_Customers/A/Quote.xlsx"
    assert files.short_path("\\\\srv\\" + "x" * 300 + ".docx").endswith(".docx")        # unchanged off Windows


def test_sharepoint_check_for_super_users(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    root.mkdir()
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    c = TestClient(create_app(s, MemorySharePoint(s)))
    r = c.get("/api/diagnostics/sharepoint").json()
    assert [l["list"] for l in r["lists"]] == ["Lists/DocumentRegister", "Lists/ControlAudit", "Lists/ApproverMatrix", "Lists/DmsNotifications", "Lists/Delegations"]
    assert all(l["canAdd"] for l in r["lists"]) and r["errors"] == []
    s.admins = []
    assert c.get("/api/diagnostics/sharepoint").status_code == 403


def test_list_info_reads_the_add_permission():
    from dms_api.sharepoint import SharePoint
    sp = SharePoint.__new__(SharePoint)
    sp._list = lambda rel: rel
    sp._call = lambda m, url: {"Title": "Control Audit", "ItemCount": 0, "EffectiveBasePermissions": {"High": "0", "Low": "1"}}
    assert sp.list_info("Lists/ControlAudit") == {"list": "Lists/ControlAudit", "exists": True, "title": "Control Audit", "items": 0,
                                                 "canRead": True, "canAdd": False, "canEdit": False}


def test_start_workflow_with_chosen_approvers(tmp_path):
    rule = {"mandatory": ["dana@rh.co.il"], "final": "boss@rh.co.il"}
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, approvals="page", admins=[])
    sp = RuleSP(s, rule)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "documentType": "הצעת מחיר", "documentArea": "מסחרי",
                                       "submit": True, "approvers": ["Avi@rh.co.il", "eli@rh.co.il", "avi@rh.co.il"]}).json()
    assert sp.audit_events()[0]["details"] == "Submitted from the DMS page. Approvers (chosen): avi@rh.co.il; eli@rh.co.il"
    s.dev_user = "dana@rh.co.il"
    assert c.get("/api/approvals").json() == []                                       # the matrix approver is not asked
    s.dev_user = "avi@rh.co.il"
    a = c.get("/api/approvals").json()
    assert a[0]["pending"] == ["avi@rh.co.il", "eli@rh.co.il"] and a[0]["chosen"]
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).json()["statusKey"] == "Submitted"
    s.dev_user = "eli@rh.co.il"
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).json()["statusKey"] == "Approved_ReadOnly"   # no final stage
    (q / "New.xlsx").write_text("x")
    assert c.post("/api/documents", json={"path": str(q / "New.xlsx"), "documentType": "x", "documentArea": "y", "submit": True, "approvers": ["not-an-email"]}).status_code == 400
    assert len(sp.documents()) == 1                                                      # nothing registered
    assert c.get("/api/approver-rule", params={"documentType": "הצעת מחיר"}).json()["final"] == "boss@rh.co.il"


def test_people_list_for_choosing_approvers(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    root.mkdir()
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=["boss@rh.co.il"])
    c = TestClient(create_app(s, MemorySharePoint(s)))
    emails = [p["email"] for p in c.get("/api/people/list").json()]
    assert "boss@rh.co.il" in emails and USER in emails and len(emails) == len(set(emails))


def test_directory_people_from_sharepoint_people_search():
    from dms_api.sharepoint import SharePoint
    sp = SharePoint.__new__(SharePoint)
    sp.s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST")
    cell = lambda **kv: {"Cells": [{"Key": k, "Value": v} for k, v in kv.items()]}  # noqa: E731
    pages = [{"PrimaryQueryResult": {"RelevantResults": {"TotalRows": 3, "Table": {"Rows": [
        cell(PreferredName="Dana Levi", WorkEmail="Dana.Levi@rh.co.il", JobTitle="QA", Department="Quality"),
        cell(PreferredName="No Mail", WorkEmail=None),
        cell(PreferredName="Avi Cohen", WorkEmail="avi@rh.co.il", JobTitle=None, Department=None)]}}}}]
    calls = []
    sp._call = lambda m, url: (calls.append(url), pages.pop(0))[1]
    people = sp.directory_people()
    assert [p["email"] for p in people] == ["avi@rh.co.il", "dana.levi@rh.co.il"] and people[1]["title"] == "QA · Quality"
    assert "sourceid='b09a7990-05ea-4af9-81ef-edfab16c4e31'" in calls[0]
    assert sp.directory_people() is people                                             # cached


def test_notification_log_and_test_notification(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "submit": True, "approvers": ["avi@rh.co.il"]})
    n = c.get("/api/diagnostics/sharepoint").json()["notifications"]
    assert n["on"] and n["last"][0]["to"] == ["avi@rh.co.il"] and n["last"][0]["result"] == "written to DMS Notifications"
    assert c.post("/api/diagnostics/notify-test").json() == {"to": USER}
    assert sp.notifications[-1]["to"] == [USER]


def test_submit_again_remembers_the_chosen_approvers(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "submit": True, "approvers": ["avi@rh.co.il", "eli@rh.co.il"]}).json()
    c.post(f"/api/documents/{d['id']}/withdraw")
    assert c.get(f"/api/documents/{d['id']}/approvers").json()["chosen"] == ["avi@rh.co.il", "eli@rh.co.il"]
    c.post(f"/api/documents/{d['id']}/submit")                                         # nothing said: the same people
    assert sp.audit_events()[0]["details"].endswith("Approvers (chosen): avi@rh.co.il; eli@rh.co.il")
    c.post(f"/api/approvals/{d['id']}", json={"approve": False, "comment": "fix"})
    c.post(f"/api/documents/{d['id']}/submit", json={"approvers": []})                 # back to the Approver Matrix
    assert sp.audit_events()[0]["details"] == "Submitted from the DMS page"
    assert c.get(f"/api/documents/{d['id']}/approvers").json()["chosen"] == []


def test_notifications_in_the_users_page_language(tmp_path):
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "A.xlsx").write_text("x")
    (q / "B.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page", admins=[USER],
                 page_url="https://dms.rh.co.il/dms/dms-page?lang=EN")
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    c.post("/api/documents", json={"path": str(q / "A.xlsx"), "submit": True, "approvers": ["avi@rh.co.il"]}, headers={"X-DMS-Lang": "HE"})
    n = sp.notifications[-1]
    assert n["subject"].endswith("ממתין לאישורך") and 'dir="rtl"' in n["body"] and "waiting" not in n["body"]
    assert n["link"] == "https://dms.rh.co.il/dms/dms-page?lang=HE&view=approvals"
    c.post("/api/documents", json={"path": str(q / "B.xlsx"), "submit": True, "approvers": ["avi@rh.co.il"]})
    n = sp.notifications[-1]
    assert n["subject"].endswith("waiting for your approval") and "ממתין" not in n["body"] and n["link"].endswith("lang=EN&view=approvals")


def test_delegate_an_approval(tmp_path):
    rule = {"mandatory": ["dana@rh.co.il"], "final": "boss@rh.co.il"}
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, approvals="page", admins=[])
    sp = RuleSP(s, rule)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "documentType": "x", "documentArea": "y", "submit": True}).json()
    assert c.post(f"/api/approvals/{d['id']}/delegate", json={"to": "avi@rh.co.il"}).status_code == 409   # not my approval
    s.dev_user = "dana@rh.co.il"
    r = c.post(f"/api/approvals/{d['id']}/delegate", json={"to": "Avi@rh.co.il", "comment": "on vacation"}).json()
    assert r["pending"] == ["avi@rh.co.il"] and r["delegated"] == [{"from": "dana@rh.co.il", "to": "avi@rh.co.il"}]
    assert sp.audit_events()[0]["details"] == "Delegated: dana@rh.co.il -> avi@rh.co.il: on vacation"
    assert sp.delegations[-1] == {"title": "DMS-00001: dana@rh.co.il -> avi@rh.co.il", "delegator": "dana@rh.co.il",
                                  "delegate": "avi@rh.co.il", "approvedBy": "dana@rh.co.il", "reason": "DMS-00001 Quote: on vacation"}
    assert c.get("/api/approvals").json() == []                                         # no longer Dana's
    s.dev_user = "avi@rh.co.il"
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).json()["stage"] == 2
    s.dev_user, s.admins = USER, [USER]                                                  # a super user, for the final approver
    r = c.post(f"/api/approvals/{d['id']}/delegate", json={"to": "eli@rh.co.il", "from": "boss@rh.co.il"}).json()
    assert r["pending"] == ["eli@rh.co.il"] and "(by " in sp.audit_events()[0]["details"]
    s.dev_user = "eli@rh.co.il"
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).json()["statusKey"] == "Approved_ReadOnly"
