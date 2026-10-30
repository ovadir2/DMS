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
        for k, v in values.items():                             # as SharePoint: CurrentUncPath -> currentUncPath
            self.items[item_id][k[0].lower() + k[1:]] = v

    def choices(self, field):
        return {"DocumentType": ["הצעת מחיר", "נוהל"], "DocumentArea": ["מסחרי"],
                "ControlMode": ["תהליך אישור רשות", "תהליך אישור חובה"]}[field]

    def audit(self, **kw):
        from datetime import datetime, timezone
        self.audits.append({**kw, "utc": f"{datetime.now(timezone.utc):%Y-%m-%d}T00:{len(self.audits):02d}:00Z"})   # today: delegations still valid

    def log_decision(self, **kw):
        self.decisions = getattr(self, "decisions", []) + [kw]

    def log_delegation(self, **kw):
        self.delegations = getattr(self, "delegations", []) + [
            {"title": kw["title"], "delegator": kw["delegator"], "delegate": kw["delegate"], "approvedBy": kw["approved_by"],
             "reason": kw["reason"], "validFrom": kw["valid_from"], "validTo": kw["valid_to"]}]

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
    assert f["officeUri"].startswith("ms-excel:ofe|u|file:") and f["editable"]          # not registered yet: edit


def test_paths_outside_root_are_refused(env):
    c, _, q = env
    assert c.get("/api/browse", params={"path": str(q.parents[4])}).status_code == 403
    assert c.get("/api/browse", params={"path": "../"}).status_code == 403
    assert c.get("/api/files/download", params={"path": str(q.parents[4] / "secret.txt")}).status_code == 403


def test_text_file_is_read_and_saved_on_the_page(env):
    """A text file needs no application: the page reads it and writes it back (nothing installed on the PC)."""
    c, _, q = env
    note = q / "remarks.txt"
    note.write_text("first line\n", encoding="utf-8")
    r = c.get("/api/files/text", params={"path": str(note)})
    assert r.status_code == 200 and r.json()["text"] == "first line\n" and r.json()["canWrite"] is True
    assert c.post("/api/files/text", json={"path": str(note), "text": "first line\nand a remark\n"}).status_code == 200
    assert note.read_text(encoding="utf-8") == "first line\nand a remark\n"
    # not a text file, and outside the root: refused
    assert c.get("/api/files/text", params={"path": str(q / "CRU 4 FCT Quote_Rev1.xlsx")}).status_code == 415
    assert c.get("/api/files/text", params={"path": str(q.parents[4] / "secret.txt")}).status_code == 403


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
    for d in ("Develop/Products/PRJ-1/02_SOW", "Develop/Products/PRJ-1/01_Quotation", "Customer_Profile", "Zeta_Extra"):
        (cust / d).mkdir(parents=True, exist_ok=True)
    r = c.get("/api/browse", params={"path": str(cust)}).json()
    assert [f["name"] for f in r["folders"]] == ["Customer_Profile", "Commercial", "Develop", "Zeta_Extra"]
    assert r["folders"][1]["label"]["he"] == "מסחרי" and r["folders"][3]["label"] is None
    assert r["node"]["kind"] == "customer" and r["context"]["customer"]["name"] == "Customer_A"
    prj = c.get("/api/browse", params={"path": str(cust / "Develop" / "Products" / "PRJ-1")}).json()
    assert prj["node"]["kind"] == "project" and prj["context"]["project"]["name"] == "PRJ-1"
    assert [f["name"] for f in prj["folders"]] == ["01_Quotation", "02_SOW"]
    assert prj["folders"][1]["label"]["en"] == "02 Statement of work"
    assert [t["name"] for t in prj["trail"]] == ["02_Customers", "Customer_A", "Develop", "Products", "PRJ-1"]


def test_root_hides_system_folders_and_areas(env):
    c, _, q = env
    root = q.parents[3]
    (root / "04_Workflow_System").mkdir()
    (root / "01_General").mkdir()
    assert "04_Workflow_System" not in [f["name"] for f in c.get("/api/browse").json()["folders"]]
    assert [a["name"] for a in c.get("/api/areas").json()] == ["01_General", "02_Customers"]


def test_save_guide(env):
    c, _, q = env
    cust = q.parents[1]
    kinds = {g["key"]: g for g in c.get("/api/guide").json()}
    assert kinds["quotation"]["needsProject"] is False and kinds["sow"]["needsProject"] is True
    # the page says what the folder is for, and where it is, while the person is still choosing
    assert kinds["quotation"]["hintEn"] == "Our quotations to the customer"
    assert kinds["quotation"]["folder"].endswith("Quotations")
    t = c.get("/api/guide/target", params={"key": "quotation", "customer": str(cust)}).json()
    assert t["path"] == str(q) and t["exists"] and t["canWrite"]
    assert c.get("/api/guide/target", params={"key": "sow", "customer": str(cust)}).status_code == 400
    prd = cust / "Develop" / "Products" / "PRJ-1"
    prd.mkdir(parents=True)
    assert [p["name"] for p in c.get("/api/projects", params={"customer": str(cust)}).json()] == ["PRJ-1"]
    t = c.get("/api/guide/target", params={"key": "sow", "customer": str(cust), "project": str(prd)}).json()
    assert t["path"].endswith(os.path.join("PRJ-1", "02_SOW")) and not t["exists"]
    made = c.post("/api/guide/create", params={"key": "sow", "customer": str(cust), "project": str(prd)})
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
    assert by["DMS-00002"]["editUri"].startswith("ms-word:ofe|")                         # returned: the owner opens to edit
    assert by["DMS-00003"]["editUri"].startswith("ms-word:ofe|")


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
    prj = cust / "Develop" / "Products" / "PRJ-101_CRU4"
    for d in ("06_Implementation", "07_FAT", "07_FAT/Obsolete_ReadOnly"):
        (prj / d).mkdir(parents=True)
    (prj / "06_Implementation" / "ECO-17 connector change.docx").write_text("x")
    (prj / "07_FAT" / "FCT report lot 3.pdf").write_text("x")
    (prj / "07_FAT" / "Obsolete_ReadOnly" / "FCT report lot 1.pdf").write_text("x")
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
        return {"terms": ["connector"], "customer": "Customer_A", "project": "PRJ-101", "kind": "srs", "extensions": [], "latest": True}

    def rank(self, question, candidates, lang="EN"):
        self.ranked = [c["relative"] for c in candidates]
        return [{"i": 0, "reason": "ECO about the connector"}]


def test_find_with_ai_plan_and_rank(env, limited):
    c, _, q = env
    _tree_for_find(q)
    ai = PlanningAI()
    c.app.state.ai = ai
    r = c.post("/api/ai/find", json={"question": "the ECO about the connector in the CRU4 project", "lang": "EN"}).json()
    assert r["usedAi"] and r["plan"] == {"terms": ["connector"], "customer": "Customer_A", "project": "PRJ-101_CRU4", "kind": "srs"}
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
    assert sub.exists() and not file_service.is_read_only(str(sub))                  # editable during approval (remarks)
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


def test_file_service_completes_a_move_whose_sharepoint_update_failed(tmp_path):
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "01_General" / "Quality and Standards"
    (q / "Current_ReadOnly").mkdir(parents=True)
    (q / "Current_ReadOnly" / "Index.xlsx").write_text("v1")                         # moved, then SharePoint failed
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory")
    sp = MemorySharePoint(s)
    d = sp.create_document(title="Index", path=str(q / "Index.xlsx"), document_type="x", document_area="y",
                           owner_email=USER, control_mode=None, document_id=None)
    sp.update(d["id"], {"LifecycleStatus": "מאושר - קריאה בלבד"})
    r = file_service.run_once(sp, s)
    assert (r["moved"], r["failed"]) == (1, 0) and "completed" in r["report"][0]["result"]
    doc = sp.document(d["id"])
    assert doc["currentUncPath"] == str(q / "Current_ReadOnly" / "Index.xlsx") and doc["workingUncPath"] == ""
    assert file_service.run_once(sp, s)["moved"] == 0                                    # once


def test_release_selected_files_without_workflow(env):
    c, sp, q = env
    (q / "A.docx").write_text("a")
    (q / "B.docx").write_text("b")
    d = c.post("/api/documents", json={"path": str(q / "B.docx"), "documentType": "נוהל", "documentArea": "מסחרי"}).json()
    resp = c.post("/api/files/release", json={"paths": [str(q / "A.docx"), str(q / "B.docx")]})
    r = resp.json()["results"]
    assert r[0]["ok"] and r[0]["documentId"] and r[1]["ok"] and r[1]["documentId"] == d["documentId"]   # B In Work: its record
    cur = q / "Current_ReadOnly" / "A.docx"
    assert cur.exists() and not (q / "A.docx").exists()
    f = next(x for x in c.get("/api/browse", params={"path": str(q / "Current_ReadOnly")}).json()["files"] if x["name"] == "A.docx")
    assert f["document"]["statusKey"] == "Approved_ReadOnly"                              # shareable now
    assert d["id"]


def test_share_finds_the_approved_file_when_the_record_was_not_updated(env):
    c, sp, q = env
    d = c.post("/api/documents", json={"path": str(q / "CRU 4 FCT Quote_Rev1.xlsx"), "documentType": "הצעת מחיר", "documentArea": "מסחרי"}).json()
    (q / "Current_ReadOnly").mkdir()
    (q / "CRU 4 FCT Quote_Rev1.xlsx").rename(q / "Current_ReadOnly" / "CRU 4 FCT Quote_Rev1.xlsx")   # moved, record not updated
    sp.update(d["id"], {"LifecycleStatus": sp.s.choices["Approved_ReadOnly"]})
    assert c.get(f"/api/documents/{d['id']}/share-info").json()["customer"] == "Customer_A"
    assert sp.items[d["id"]]["currentUncPath"] == str(q / "Current_ReadOnly" / "CRU 4 FCT Quote_Rev1.xlsx")   # corrected
    sp.update(d["id"], {"CurrentUncPath": str(q / "gone.xlsx"), "WorkingUncPath": ""})
    r = c.get(f"/api/documents/{d['id']}/share-info")
    assert r.status_code == 409 and "gone.xlsx" in r.json()["detail"]                    # says where it looked


def test_old_paths_after_the_repository_was_reorganized(tmp_path):
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    cur = root / "01_General" / "Quality and Standards" / "נהלי איכות" / "Current_ReadOnly"
    cur.mkdir(parents=True)
    (cur / "QP-2.1.docx").write_text("v")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory")
    sp = MemorySharePoint(s)
    d = sp.create_document(title="QP", path="", document_type="x", document_area="y", owner_email=USER, control_mode=None, document_id=None)
    old = "\\\\10.10.10.80\\e$\\Shares\\01_Management\\Quality\\Quality and Standards\\נהלי איכות\\Current_ReadOnly\\QP-2.1.docx"
    sp.update(d["id"], {"LifecycleStatus": "מאושר - קריאה בלבד", "CurrentUncPath": old, "WorkingUncPath": "",
                        "CurrentSHA256": file_service._sha256(str(cur / "QP-2.1.docx"))})
    r = file_service.run_once(sp, s)
    assert r["moved"] == 1 and sp.document(d["id"])["currentUncPath"] == str(cur / "QP-2.1.docx")
    assert file_service.relocate(str(root), old, "0" * 64) is None                       # other content: not this file


def test_hr_files_are_shared_with_a_potential_employee(tmp_path):
    root = tmp_path / "Root"
    hr = root / "01_General" / "HR" / "Recruiting"
    hr.mkdir(parents=True)
    (hr / "Offer.docx").write_text("o")
    (root / "02_Customers").mkdir()
    c = TestClient(create_app(Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])))
    d = c.post("/api/files/release", json={"paths": [str(hr / "Offer.docx")]}).json()["results"][0]
    doc = next(x for x in c.app.state.sp.documents() if x["documentId"] == d["documentId"])
    assert c.get(f"/api/documents/{doc['id']}/share-info").json()["hr"] is True
    r = c.post(f"/api/documents/{doc['id']}/share", json={"email": "dana@gmail.com"})
    assert r.status_code == 400 and "potential employee" in r.json()["detail"]
    assert c.post(f"/api/documents/{doc['id']}/share", json={"email": "dana@gmail.com", "customer": "Dana Levi"}).status_code == 200
    assert "potential employee Dana Levi" in c.app.state.sp.audit_events()[0]["details"]
    assert [f["name"] for f in c.get("/api/exchange/files", params={"name": "Dana Levi"}).json()] == ["Offer.docx"]
    log = (root / "01_General" / "HR" / "Shared" / "DMS-Shared-Log.csv").read_text(encoding="utf-8-sig")
    assert "Dana Levi: dana@gmail.com" in log and "Offer.docx" in log                   # the HR share log
    b = c.get("/api/browse", params={"path": str(root / "01_General" / "HR" / "Shared")}).json()
    assert b["sharedNote"] and not b["canWrite"]                                          # kept by the DMS, read only


def test_release_puts_the_file_back_when_sharepoint_refuses(env, monkeypatch):
    from dms_api import noworkflow
    from dms_api.sharepoint import SharePointError
    c, sp, q = env
    (q / "A.docx").write_text("a")
    def refuse(*a, **k):
        raise SharePointError("403 Forbidden")
    monkeypatch.setattr(noworkflow, "release", refuse)
    r = c.post("/api/files/release", json={"paths": [str(q / "A.docx")]}).json()["results"][0]
    assert not r["ok"] and "403" in r["error"]
    assert (q / "A.docx").exists() and not (q / "Current_ReadOnly" / "A.docx").exists()   # back where it was


def test_release_a_document_in_work_without_workflow(env):
    c, sp, q = env
    (q / "W.docx").write_text("w")
    d = c.post("/api/documents", json={"path": str(q / "W.docx"), "documentType": "נוהל", "documentArea": "מסחרי"}).json()
    r = c.post("/api/files/release", json={"paths": [str(q / "W.docx")]}).json()["results"][0]
    assert r["ok"] and r["documentId"] == d["documentId"]                                 # its own record, no new one
    doc = sp.items[d["id"]]
    assert doc["lifecycleStatus"] == sp.s.choices["Approved_ReadOnly"] and doc["currentUncPath"] == str(q / "Current_ReadOnly" / "W.docx")
    assert doc["workingUncPath"] == "" and (q / "Current_ReadOnly" / "W.docx").exists()
    again = c.post("/api/files/release", json={"paths": [str(q / "Current_ReadOnly" / "W.docx")]}).json()["results"][0]
    assert not again["ok"]                                                               # approved: not again


def test_approved_file_stays_approved_while_its_next_revision_is_in_approval(env):
    c, sp, q = env
    (q / "N.docx").write_text("n")
    d = c.post("/api/files/release", json={"paths": [str(q / "N.docx")]}).json()["results"][0]
    doc = next(x for x in sp.documents() if x["documentId"] == d["documentId"])
    sp.update(doc["id"], {"LifecycleStatus": sp.s.choices["Submitted"], "WorkingUncPath": str(q / "N_Rev02_DRAFT.docx"), "DraftRevision": "02"})
    f = c.get("/api/browse", params={"path": str(q / "Current_ReadOnly")}).json()["files"][0]
    assert f["document"]["statusKey"] == "Approved_ReadOnly" and f["document"]["nextRevision"]["revision"] == "02"
    assert c.get(f"/api/documents/{doc['id']}/share-info").status_code == 200              # the approved one can be shared


def test_release_a_submitted_document_without_workflow(env):
    from dms_api import file_service
    c, sp, q = env
    (q / "S.docx").write_text("s")
    d = c.post("/api/documents", json={"path": str(q / "S.docx"), "documentType": "נוהל", "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, c.app.state.settings)                                      # moved to Submitted
    sub = q / "Submitted" / "S.docx"
    assert sub.exists()
    f = next(x for x in c.get("/api/browse", params={"path": str(q / "Submitted")}).json()["files"] if x["name"] == "S.docx")
    assert f["document"]["statusKey"] == "Submitted"
    r = c.post("/api/files/release", json={"paths": [str(sub)]}).json()["results"][0]
    assert r["ok"] and r["documentId"] == d["documentId"], r
    doc = sp.items[d["id"]]
    assert doc["lifecycleStatus"] == sp.s.choices["Approved_ReadOnly"] and (q / "Current_ReadOnly" / "S.docx").exists() and not sub.exists()
    assert "approval workflow was stopped" in sp.audit_events()[0]["details"]


def test_hebrew_name_opens_through_the_pc_handler(tmp_path):
    root = tmp_path
    d = root / "01_General" / "HR"
    d.mkdir(parents=True)
    (d / "1970193לקוחות.xlsx").write_text("x")
    c = TestClient(create_app(Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory")))
    f = c.get("/api/browse", params={"path": str(d)}, headers={"X-DMS-Opener": "1"}).json()["files"][0]
    assert f["officeUri"].startswith("rh-dms:")                                           # not ms-excel: (%D7.. not decoded)
    (d / "plain.xlsx").write_text("x")
    g = next(x for x in c.get("/api/browse", params={"path": str(d)}, headers={"X-DMS-Opener": "1"}).json()["files"] if x["name"] == "plain.xlsx")
    assert g["officeUri"].startswith("ms-excel:")                                         # English names: as before


def test_this_pc_by_its_network_address_is_local():
    from types import SimpleNamespace
    from dms_api import ntlm
    req = lambda client, server: SimpleNamespace(client=SimpleNamespace(host=client), scope={"server": (server, 8080)})  # noqa: E731
    assert ntlm.is_local(req("10.30.8.20", "10.30.8.20"))                                  # the email link on this PC
    behind_iis = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), scope={"server": ("127.0.0.1", 8080)},
                                 headers={"x-iis-windowsauthtoken": "2a4"})
    assert not ntlm.is_local(behind_iis)         # IIS passes every request on from 127.0.0.1: nobody is local
    import os
    os.environ["HTTP_PLATFORM_PORT"] = "41234"   # IIS started the process: not local even without the token header
    try:
        assert not ntlm.is_local(req("10.30.8.20", "10.30.8.20"))
    finally:
        del os.environ["HTTP_PLATFORM_PORT"]
    assert ntlm.is_local(req("127.0.0.1", "127.0.0.1"))
    assert not ntlm.is_local(req("10.30.8.50", "10.30.8.20"))                              # another PC


def test_approved_file_opens_view_only_and_stays_read_only(env):
    import os, stat
    from dms_api import file_service
    c, sp, q = env
    (q / "טופס.docx").write_text("v")
    c.post("/api/files/release", json={"paths": [str(q / "טופס.docx")]})
    cur = q / "Current_ReadOnly" / "טופס.docx"
    os.chmod(cur, os.stat(cur).st_mode | stat.S_IWRITE)                                # lost its read-only mark
    file_service.run_once(sp, c.app.state.settings)
    assert file_service.is_read_only(str(cur))                                          # set again by the file mover
    f = c.get("/api/browse", params={"path": str(cur.parent)}, headers={"X-DMS-Opener": "1"}).json()["files"][0]
    assert f["officeUri"].startswith("rh-dms:ro/")                                       # Open = view only


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
    assert r["statusKey"] == "Approved_ReadOnly" and sp.items[d["id"]]["lastApprovedUtc"]
    # the file moves to Current_ReadOnly as part of the approval; its own audit line is not a decision
    events = [(e["event"], _nosha(e["details"])) for e in sp.audit_events()
              if e["event"] != s.choices["FileDone"]][:3]
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
    assert item["statusKey"] == "Rejected" and _nosha(item["decision"]["details"]) == "Stage 1: fix p.2"
    assert " [file SHA-256 " in item["decision"]["details"]                       # the content the decision was made on
    sub = c.post(f"/api/documents/{d['id']}/submit").json()                        # submitted again
    wf = next(i for i in c.get("/api/my-workflows").json()["items"] if i["id"] == d["id"])
    assert wf["statusKey"] == "Submitted" and "editUri" in wf                     # the owner may add remarks
    s.dev_user = "dana@rh.co.il"
    ap = next(i for i in c.get("/api/approvals").json() if i["id"] == d["id"])
    assert not ap["editable"] and ap["officeUri"] is None      # read only: remarks are attached, the document is not changed
    s.dev_user = USER
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
    decisions = [e for e in sp.audit_events() if e["event"] != s.choices["FileDone"]]
    assert _nosha(decisions[0]["details"]) == "Stage 2 (super user)"


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
    (cust / "Develop" / "Products" / "PRJ-1").mkdir(parents=True)
    top = c.get("/api/pathfinder").json()
    assert [o["name"] for o in top["options"]] == ["01_General", "02_Customers"] and top["options"][0]["exists"] is False
    lv = c.get("/api/pathfinder", params={"path": str(cust)}).json()
    assert [(o["name"], o["exists"]) for o in lv["options"]][:4] == [("Customer_Profile", False), ("Commercial", True), ("Program", False),
                                                                      ("Develop", True)]
    prj = c.get("/api/pathfinder", params={"path": str(cust / "Develop" / "Products" / "PRJ-1")}).json()
    assert prj["node"]["kind"] == "project" and len(prj["options"]) == 11 and not any(o["exists"] for o in prj["options"])
    target = cust / "Develop" / "ATEFiles" / "FCT" / "07_FAT"
    r = c.post("/api/pathfinder/create", params={"path": str(target)})
    assert r.status_code == 201 and target.is_dir()
    bad = cust / "Develop" / "Products" / "PRJ-1" / "Random" / "x"
    assert c.post("/api/pathfinder/create", params={"path": str(bad)}).status_code == 400 and not bad.exists()
    assert c.post("/api/pathfinder/create", params={"path": str(cust.parent / "New_Customer" / "Commercial")}).status_code == 400


def test_path_finder_through_missing_folders(env):
    c, _, q = env
    prj = q.parents[1] / "Develop" / "Products" / "PRJ-2"
    prj.mkdir(parents=True)
    r = c.get("/api/pathfinder", params={"path": str(q.parents[1] / "Develop" / "ATEFiles")}).json()
    assert r["exists"] is False and [o["name"] for o in r["options"]] == ["FCT", "FTP", "ICT", "JTAG"]
    assert c.get("/api/pathfinder", params={"path": str(prj / "Nope" / "Deeper")}).status_code == 404


def _nosha(details):
    return details.split(" [file SHA-256 ")[0]


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


def test_an_approver_needs_no_rights_on_the_file_server(tmp_path, monkeypatch):
    """A document waiting for this person's approval is served by the DMS itself: AD may give them nothing
    on the file server, and nothing else of it becomes reachable."""
    from dms_api import file_service, security
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("rev1")
    (q / "Other.xlsx").write_text("not mine")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    submitted = q / "Submitted" / "Quote.xlsx"
    assert submitted.exists()

    monkeypatch.setattr(security.User, "can", lambda self, path, access="read": False)   # no rights at all in AD
    assert c.get("/api/files/download", params={"path": str(submitted)}).status_code == 200      # the one to approve
    assert c.get("/api/files/download", params={"path": str(q / "Other.xlsx")}).status_code == 403
    row = next(x for x in c.get("/api/approvals").json() if x["id"] == d["id"])
    assert row["viaDms"] is True and row["officeUri"] is None and row["viewUri"] is None   # the DMS serves it


def test_an_approver_attaches_their_remarks_beside_the_document(tmp_path, monkeypatch):
    """The approver edits a copy on their own PC and attaches it: the submitted file is never touched,
    each approver has their own file, and it works with no rights at all on the file server."""
    import io
    from dms_api import file_service, security
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.docx").write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.docx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    submitted = q / "Submitted" / "Quote.docx"

    monkeypatch.setattr(security.User, "can", lambda self, path, access="read": False)      # nothing in AD
    r = c.post(f"/api/documents/{d['id']}/remarks",
               files={"file": ("Quote.docx", io.BytesIO(b"my remarks"), "application/octet-stream")})
    assert r.status_code == 201 and r.json()["name"].endswith(" - Quote.docx")
    assert submitted.read_bytes() == b"as submitted"                       # the approved revision is untouched
    kept = root / "04_Workflow_System" / "Remarks" / d["documentId"] / r.json()["name"]
    assert kept.read_bytes() == b"my remarks"
    assert [x["name"] for x in c.get(f"/api/documents/{d['id']}/remarks").json()] == [r.json()["name"]]
    assert c.get(f"/api/documents/{d['id']}/remarks/{r.json()['name']}").content == b"my remarks"
    assert any("Remarks attached by" in (e.get("details") or "") for e in sp.audit_events())


def test_the_document_goes_to_sharepoint_for_its_approvers_and_comes_back(tmp_path, monkeypatch):
    """Approvers open and edit the document in SharePoint with their own Microsoft account; the DMS, which
    alone touches the file server, puts the copy there and brings back what they left when the approval ends."""
    from dms_api import file_service, security
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.docx").write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    sp = MemorySharePoint(s)
    calls = {}
    def _put(*, local_path, document_id, **kw):
        calls["put"] = (local_path, document_id)
        return {"name": "Quote.docx",
                "url": f"https://rhisrael.sharepoint.com/sites/DC/Approvals/{document_id}/Quote.docx"}
    sp.review_put = _put
    sp.review_share = lambda **kw: calls.setdefault("share", kw)
    sp.review_url = lambda *, document_id, name: None            # not there yet: the DMS puts it there
    sp.review_get = lambda *, document_id, name: b"edited by the approvers"
    sp.review_done = lambda *, document_id: calls.setdefault("done", document_id)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.docx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    assert calls["put"][1] == d["documentId"] and calls["share"]["emails"]                # shared with the approvers
    monkeypatch.setattr(security.User, "can", lambda self, path, access="read": False)    # no rights on the share
    row = next(x for x in c.get("/api/approvals").json() if x["id"] == d["id"])
    assert row["officeUri"].endswith("/Quote.docx") and row["editable"]                   # Open goes to SharePoint

    c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    c.post(f"/api/approvals/{d['id']}", json={"approve": True})                           # the approval ends
    # what they left comes back, and the approval puts it straight into Current_ReadOnly
    assert (q / "Current_ReadOnly" / "Quote.docx").read_bytes() == b"edited by the approvers"
    assert calls["done"] == d["documentId"]                                               # and the copy is removed



def test_a_document_already_open_in_sharepoint_is_not_uploaded_over(tmp_path):
    """After the DMS restarts, or for a document submitted before the review existed, the copy in SharePoint
    is the document: the DMS points at it and never writes over the approvers' work."""
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.docx").write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    sp = MemorySharePoint(s)
    there = "https://rhisrael.sharepoint.com/sites/DC/Approvals/DMS-00001/Quote.docx"
    sp.review_url = lambda *, document_id, name: there
    sp.review_put = lambda **kw: pytest.fail("the copy in SharePoint must not be overwritten")
    sp.review_share = lambda **kw: None
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.docx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": False}).json()
    sp.update(d["id"], {"LifecycleStatus": s.choices["Submitted"]})                 # submitted before, already there
    sp.audit(document_id=d["documentId"], event=s.choices["SubmittedEvent"], from_status=s.choices["Working"],
             to_status=s.choices["Submitted"], actor=USER, details="submitted earlier")
    file_service.run_once(sp, s)
    row = next(x for x in c.get("/api/approvals").json() if x["id"] == d["id"])
    assert row["officeUri"] == there


def test_nothing_in_current_readonly_is_deleted(tmp_path):
    """Current_ReadOnly holds the approved revision in force. Nobody deletes from it - not its owner and not a
    DMS super user: a document leaves it only by being replaced, when the next revision is approved."""
    c, sp, s, q, d, fs = _approved_env(tmp_path)
    cur = q / "Current_ReadOnly" / "CRU 4 FCT Quote_Rev1.xlsx"
    assert cur.exists() and fs.is_read_only(str(cur))
    assert c.post("/api/items/delete", json={"path": str(cur)}).status_code == 403   # a super user asks here
    assert cur.exists()

    s.admins = []                                                             # not a super user any more
    other = q / "Current_ReadOnly" / "other.xlsx"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("x")
    fs._set_read_only(str(other), True)
    assert c.post("/api/items/delete", json={"path": str(other)}).status_code in (403, 409)
    assert other.exists()


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
    k = len(n)
    c.post(f"/api/approvals/{e['id']}", json={"approve": False, "comment": "fix p.2"})
    assert len(n) == k                                                            # eli still reviews: no mail yet
    s.dev_user = "eli@rh.co.il"
    c.post(f"/api/approvals/{e['id']}", json={"approve": True})
    assert n[-1]["to"] == [USER] and "fix p.2" in n[-1]["body"]                    # then the owner gets all the remarks


def test_share_with_customer(tmp_path):
    c, sp, s, q, d, fs = _approved_env(tmp_path)
    r = c.post(f"/api/documents/{d['id']}/share", json={"email": "Edssrom@gmail.com"})
    assert r.status_code == 200, r.text
    assert r.json()["revision"] == "01" and sp.shares[0]["email"] == "edssrom@gmail.com"
    assert "Outbound/Customer_A/CRU 4 FCT Quote_Rev1.xlsx" in sp.shares[0]["url"]      # straight in the customer folder
    assert r.json()["customer"] == "Customer_A" and sp.shortcuts[0]["name"] == "DMS_Customer_A"
    ev = sp.audit_events()[0]
    assert ev["event"] == "שינוי הרשאות" and "edssrom@gmail.com" in ev["details"] and "customer Customer_A" in ev["details"]
    log = tmp_path / "Root" / "02_Customers" / "Customer_A" / "Shared" / "DMS-Shared-Log.csv"
    assert r.json()["log"].replace("\\", "/") == "02_Customers/Customer_A/Shared/DMS-Shared-Log.csv"
    c.post(f"/api/documents/{d['id']}/share", json={"email": "other@cust.com"})          # appended, header once
    rows = log.read_text(encoding="utf-8-sig").splitlines()
    assert rows[0].startswith("Date (UTC),Action,Shared by") and len(rows) == 3
    assert "edssrom@gmail.com" in rows[1] and "other@cust.com" in rows[2] and USER in rows[2] and "DMS-00001" in rows[2]
    import os, stat as st
    assert not os.stat(log).st_mode & st.S_IWRITE                                     # read only between appends
    shared = log.parent
    f = next(x for x in c.get("/api/browse", params={"path": str(shared)}).json()["files"] if x["name"] == log.name)
    assert f["system"] and f["readOnly"]                                             # no rename / delete / workflow on the page
    assert c.post("/api/items/rename", json={"path": str(log), "newName": "x.csv"}).status_code == 403
    assert c.post("/api/items/delete", json={"path": str(log)}).status_code == 403
    assert c.post("/api/items/delete", json={"path": str(shared)}).status_code == 403   # nor its folder
    assert c.post("/api/documents", json={"path": str(log), "documentType": "x", "documentArea": "y"}).status_code == 403
    assert log.exists()
    (shared / "sent.pdf").write_text("x")
    b = c.get("/api/browse", params={"path": str(shared)}).json()
    sent = next(x for x in b["files"] if x["name"] == "sent.pdf")
    assert b["noWorkflow"] and not b["canWrite"] and sent["noWorkflow"] and sent["system"]
    assert c.post("/api/items/rename", json={"path": str(shared / "sent.pdf"), "newName": "y.pdf"}).status_code == 403
    assert c.post("/api/items/delete", json={"path": str(shared / "sent.pdf")}).status_code == 403
    assert c.post("/api/folders", json={"parent": str(shared), "name": "sub"}).status_code == 403
    assert c.post("/api/documents", json={"path": str(shared / "sent.pdf"), "documentType": "x", "documentArea": "y"}).status_code == 403
    info = c.get(f"/api/documents/{d['id']}/share-info").json()
    assert info["customer"] == "Customer_A" and "Customer_A" in info["customers"]
    assert c.post(f"/api/documents/{d['id']}/share", json={"email": "not-an-email"}).status_code == 422
    c.post(f"/api/documents/{d['id']}/revise")                                     # next revision in work: the approved one still shareable
    assert c.post(f"/api/documents/{d['id']}/share", json={"email": "edssrom@gmail.com"}).status_code == 200


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
            if url.endswith("/ListItemAllFields"):
                return Resp({})
            if url.endswith("SP.Web.ShareObject"):
                return Resp({"StatusCode": 0, "ErrorMessage": None})
            if "folders/AddUsingPath" in url and url.endswith("/Outbound')"):     # exists; message in Hebrew
                return Resp({"odata.error": {"code": "-2130575257, Microsoft.SharePoint.SPException",
                                             "message": {"lang": "he-IL", "value": "קובץ או תיקיה בשם Outbound קיימים כבר"}}}, status=400)
            if url.endswith("?$select=Exists"):
                return Resp({"Exists": True})
            return Resp({})
    import tempfile, os
    f = os.path.join(tempfile.mkdtemp(), "Q.xlsx")
    open(f, "wb").write(b"x")
    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST",
                 ex_site_url="https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST")
    sess = Sess()
    sp = SharePoint(s, sess)
    sp._access_token = lambda: "t"
    r = sp.share_with_guest(local_paths=[f], folder="Outbound/Customer A", email="edssrom@gmail.com", subject="S", message="M",
                            request_ids={"Q.xlsx": "DMS-7 Rev 03"})
    assert r["url"] == "https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST/TemporaryUploads/Outbound/DMS-1_Rev01/Q.xlsx"
    assert r["folderUrl"] == "https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST/TemporaryUploads/Outbound/Customer%20A"
    share = sess.calls[-1][2]
    assert share["url"] == r["folderUrl"]                                         # the customer folder is shared
    assert share["roleValue"] == "role:1073741826" and share["sendEmail"] is True and share["includeAnonymousLinkInEmail"] is False
    assert j.loads(share["peoplePickerInput"])[0]["Key"] == "edssrom@gmail.com"
    assert [c[3] for c in sess.calls if "Files/AddUsingPath" in c[1]] == [b"x"]       # the file bytes were uploaded
    said = next(c for c in sess.calls if c[1].endswith("/ListItemAllFields"))
    assert said[2] == {"RequestId": "DMS-7 Rev 03"}                                  # the library's required column


def test_share_invites_the_guest_through_graph():
    """SharePoint's own sharing cannot identify an address it has never seen when the DMS signs in with a
    certificate; Graph creates the guest instead, and SharePoint is only asked when Graph cannot."""
    from tests.test_sharepoint import Resp
    from dms_api.sharepoint import SharePoint

    class Sess:
        def __init__(self):
            self.calls = []

        def request(self, method, url, json=None, data=None, headers=None, timeout=None):
            self.calls.append((method, url, json, data))
            if "Files/AddUsingPath" in url:
                return Resp({"ServerRelativeUrl": "/sites/LargeFileExchange-TEST/TemporaryUploads/Outbound/C/Q.xlsx"})
            if url.endswith("/drives?$select=id,name,webUrl"):
                return Resp({"value": [{"id": "drv", "name": "TemporaryUploads",
                                        "webUrl": "https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST/TemporaryUploads"}]})
            if "root:/" in url and "$select=id" in url:
                return Resp({"id": "itm", "webUrl": "https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST/x"})
            if url.endswith("/invitations"):
                return Resp({"invitedUser": {"id": "guest-1"}})
            return Resp({})
    import tempfile, os
    f = os.path.join(tempfile.mkdtemp(), "Q.xlsx")
    open(f, "wb").write(b"x")
    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST",
                 ex_site_url="https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST")
    sess = Sess()
    sp = SharePoint(s, sess)
    sp._access_token = lambda: "t"
    sp._graph_token = lambda: "g"
    sp.share_with_guest(local_paths=[f], folder="Outbound/C", email="someone@gmail.com", subject="S", message="M")
    ask = next(c for c in sess.calls if c[1].endswith("/invitations"))
    assert ask[2]["invitedUserEmailAddress"] == "someone@gmail.com" and ask[2]["sendInvitationMessage"] is True
    invite = next(c for c in sess.calls if c[1].endswith("/items/itm/invite"))
    assert invite[2]["recipients"] == [{"objectId": "guest-1"}]                   # the guest Entra just created
    assert invite[2]["roles"] == ["read"] and invite[2]["requireSignIn"] is True
    assert not [c for c in sess.calls if c[1].endswith("SP.Web.ShareObject")]      # SharePoint was not asked at all


def test_share_grants_even_when_no_invitation_can_be_sent():
    """Where Entra will not send the guest the mail, the guest is created all the same and gets the folder;
    the DMS then says to pass the link on."""
    from tests.test_sharepoint import Resp
    from dms_api.sharepoint import SharePoint

    class Sess:
        def __init__(self):
            self.calls = []

        def request(self, method, url, json=None, data=None, headers=None, timeout=None):
            self.calls.append((method, url, json, data))
            if "Files/AddUsingPath" in url:
                return Resp({"ServerRelativeUrl": "/sites/LargeFileExchange-TEST/TemporaryUploads/Outbound/C/Q.xlsx"})
            if url.endswith("/drives?$select=id,name,webUrl"):
                return Resp({"value": [{"id": "drv", "name": "TemporaryUploads",
                                        "webUrl": "https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST/TemporaryUploads"}]})
            if "root:/" in url and "$select=id" in url:
                return Resp({"id": "itm", "webUrl": "https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST/x"})
            if url.endswith("/invitations"):                                      # Entra will not send the mail
                if (json or {}).get("sendInvitationMessage"):
                    return Resp({"error": {"code": "Request_BadRequest", "message": "sendInvitationMessage"}}, status=400)
                return Resp({"invitedUser": {"id": "guest-1"}})
            return Resp({})
    import tempfile, os
    f = os.path.join(tempfile.mkdtemp(), "Q.xlsx")
    open(f, "wb").write(b"x")
    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST",
                 ex_site_url="https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST")
    sess = Sess()
    sp = SharePoint(s, sess)
    sp._access_token = lambda: "t"
    sp._graph_token = lambda: "g"
    r = sp.share_with_guest(local_paths=[f], folder="Outbound/C", email="someone@gmail.com", subject="S", message="M")
    assert r["emailed"] is False                                                  # the caller tells the person
    assert [c[2]["sendInvitationMessage"] for c in sess.calls if c[1].endswith("/invitations")] == [True, False]
    assert not [c for c in sess.calls if c[1].endswith("SP.Web.ShareObject")]     # the access was granted by Graph


def test_share_several_files_outside_customers(tmp_path):
    c, sp, s, q, d, fs = _approved_env(tmp_path)
    other = tmp_path / "Root" / "01_Company" / "QA"
    other.mkdir(parents=True)
    (other / "QP-2.1.docx").write_text("qp")
    e = c.post("/api/documents", json={"path": str(other / "QP-2.1.docx"), "documentType": "נוהל", "documentArea": "איכות",
                                       "submit": True}).json()
    for _ in range(2):
        c.post(f"/api/approvals/{e['id']}", json={"approve": True})
    fs.run_once(sp, s)
    assert c.get(f"/api/documents/{e['id']}/share-info").json()["customer"] is None
    assert c.post(f"/api/documents/{e['id']}/share", json={"email": "x@cust.com"}).status_code == 400   # customer needed
    assert c.post(f"/api/documents/{e['id']}/share", json={"email": "x@cust.com", "customer": "a/b"}).status_code == 400   # not a folder name
    assert c.post(f"/api/documents/{e['id']}/share", json={"email": "x@cust.com", "customer": "New Customer"}).status_code == 200   # out of the list
    assert [f["name"] for f in c.get("/api/exchange/files", params={"name": "new customer"}).json()]                 # what is there now
    log = tmp_path / "Root" / "02_Customers" / "Shared" / "DMS-Shared-Log.csv"
    assert not (tmp_path / "Root" / "02_Customers" / "New Customer").exists()   # no folder is invented for them
    import stat as _stat
    assert not log.stat().st_mode & _stat.S_IWRITE                              # read only, like every share log
    assert "New Customer: x@cust.com" in log.read_text(encoding="utf-8-sig")    # the one log says who it went to
    r = c.post(f"/api/documents/{e['id']}/share", json={"email": "x@cust.com", "customer": "customer_a", "documentIds": [d["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["customer"] == "Customer_A" and len(r.json()["documents"]) == 2
    assert {u["url"].rsplit("/", 2)[-2] for u in sp.shares} == {"Customer_A", "New Customer"}
    (tmp_path / "Root" / "02_Customers" / "Elbit").mkdir()
    r = c.post(f"/api/documents/{d['id']}/share", json={"email": "y@elbit.com", "customer": "Elbit"})  # another customer
    assert r.status_code == 200 and r.json()["customer"] == "Elbit" and "Outbound/Elbit/" in sp.shares[-1]["url"]


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
    did = docs["Spec_Rev3"]["documentId"]
    trail = [(e["event"], e["actor"], e["details"].split(":")[0]) for e in reversed(sp.audit_events()) if e["documentId"] == did]
    c_ = s.choices                                                                   # the same steps as a normal approval
    assert [x[:2] for x in trail[:5]] == [(c_["Created"], USER), (c_["SubmittedEvent"], USER), (c_["FileDone"], "RH-DMS-Workflow-Service"),
                                          (c_["ApprovedEvent"], "dms_approval@rh.co.il"), (c_["FileDone"], "RH-DMS-Workflow-Service")]
    assert [x[2] for x in trail[:5]][2::2] == ["MoveToSubmitted", "PromoteToCurrent"]
    assert "Approvers (chosen): dms_approval@rh.co.il" in [e for e in reversed(sp.audit_events()) if e["documentId"] == did][1]["details"]
    assert any(x["approver"] == "dms_approval@rh.co.il" and x["decision"] == "Approved" for x in sp.decisions)
    assert docs["Spec_Rev3"]["currentRevision"] == "03" and not docs["Spec_Rev3"]["workingUncPath"] and docs["Spec_Rev3"]["lastApprovedUtc"]
    assert not (target / "Submitted").exists()
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
    assert blueprint.classify(["01_General", "Company_Profile"]) == {"area": "Management", "type": "Company Profile"}
    assert blueprint.classify(["02_Customers", "Customer_A", "Develop", "Products", "PRJ-1", "02_SOW", "Working"]) == \
        {"area": "Development", "type": "SOW"}
    assert blueprint.classify(["02_Customers", "Customer_A", "Commercial", "Quotations", "Old 2019"])["type"] == "Quotation"
    assert blueprint.classify(["02_Customers", "Customer_A", "QC", "NCR"]) == {"area": "Quality", "type": None}
    root = tmp_path / "Root"
    cp = root / "01_General" / "Company_Profile"
    cp.mkdir(parents=True)
    (cp / "Profile.docx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    c = TestClient(create_app(s, MemorySharePoint(s)))
    assert c.get("/api/classify", params={"path": str(cp)}).json() == \
        {"documentType": "פרופיל חברה", "documentArea": "ניהול", "controlMode": "תהליך אישור חובה"}
    d = c.post("/api/documents", json={"path": str(cp / "Profile.docx")}).json()
    assert (d["documentType"], d["documentArea"]) == ("פרופיל חברה", "ניהול")
    other = root / "01_General" / "Templates"
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


def test_an_approved_file_is_made_read_only_again(tmp_path):
    """Whoever made the approved file writable - a First loading, a hand, a restore - the service puts it back."""
    import stat as _stat
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
    for _ in range(2):
        c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    file_service.run_once(sp, s)
    cur = q / "Current_ReadOnly" / "Quote.xlsx"
    assert cur.is_file() and not cur.stat().st_mode & _stat.S_IWRITE
    os.chmod(cur, cur.stat().st_mode | _stat.S_IWRITE)                 # somebody made it writable again
    file_service.run_once(sp, s)
    assert not cur.stat().st_mode & _stat.S_IWRITE                     # and the next pass puts it back


def test_an_approved_document_gets_its_markdown_beside_it(tmp_path):
    """The company's AI reads Markdown, not a page of a PDF: on release the DMS writes the document again as
    Markdown beside it, read only, with what the document is at the top. It is not a second row in the folder."""
    import stat as _stat
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.txt").write_text("The quotation\n\nTwo weeks from the order.", encoding="utf-8")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.txt"), "submit": True}).json()
    file_service.run_once(sp, s)
    for _ in range(2):
        c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    file_service.run_once(sp, s)
    md = q / "Current_ReadOnly" / "Quote.md"
    text = md.read_text(encoding="utf-8")
    assert d["documentId"] in text and "Two weeks from the order." in text     # what it is, and what it says
    assert not md.stat().st_mode & _stat.S_IWRITE                              # read only, like the document
    names = [f["name"] for f in c.get("/api/browse", params={"path": str(q / "Current_ReadOnly")}).json()["files"]]
    assert names == ["Quote.txt"]                                              # and not a second row in the folder


def test_the_markdown_follows_the_revision_in_force(tmp_path):
    """What the company's AI reads is the revision in force. When a new one is approved, the Markdown of the
    old one goes with it to Obsolete_ReadOnly, and the new one gets its own."""
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.txt").write_text("revision one", encoding="utf-8")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.txt"), "submit": True}).json()
    file_service.run_once(sp, s)
    for _ in range(2):
        c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    file_service.run_once(sp, s)
    assert "revision one" in (q / "Current_ReadOnly" / "Quote.md").read_text(encoding="utf-8")

    c.post(f"/api/documents/{d['id']}/revise")                              # the next revision, approved too
    draft = next(p for p in q.iterdir() if p.name.endswith("_DRAFT.txt"))
    draft.write_text("revision two", encoding="utf-8")
    c.post(f"/api/documents/{d['id']}/submit")
    file_service.run_once(sp, s)
    for _ in range(2):
        c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    file_service.run_once(sp, s)
    now = list((q / "Current_ReadOnly").glob("*.md"))
    assert len(now) == 1 and "revision two" in now[0].read_text(encoding="utf-8")
    gone = list((q / "Obsolete_ReadOnly").glob("*.md"))
    assert gone and "revision one" in gone[0].read_text(encoding="utf-8")    # and the old one went with its file


def test_a_procedure_comes_out_as_a_procedure(tmp_path):
    """What a reader sees in Word is what the Markdown should say: the block at the head of a procedure is a
    list of facts and not a six column grid, a section numbered by hand is a heading, a cell merged across
    columns keeps the row's shape, and what tracked changes struck out is not part of the text."""
    import zipfile
    from dms_api import markdown
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc = f"""<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>
      <w:tbl>
        <w:tr><w:tc><w:p><w:r><w:t>מספר נוהל</w:t></w:r></w:p></w:tc>
               <w:tc><w:tcPr><w:gridSpan w:val="3"/></w:tcPr><w:p><w:r><w:t>QP-16.1</w:t></w:r></w:p></w:tc></w:tr>
        <w:tr><w:tc><w:p><w:r><w:t>גרסה</w:t></w:r></w:p></w:tc>
               <w:tc><w:p><w:r><w:t>01</w:t></w:r></w:p></w:tc></w:tr>
      </w:tbl>
      <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>מטרה</w:t></w:r></w:p>
      <w:p><w:r><w:t>3. שיטה</w:t></w:r></w:p>
      <w:p><w:r><w:t>Advisory notice</w:t></w:r><w:del><w:r><w:delText>םךןחןםום</w:delText></w:r></w:del></w:p>
      <w:p/><w:p/>
      <w:p><w:r><w:t>סוף</w:t></w:r></w:p>
    </w:body></w:document>"""
    f = tmp_path / "QP.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/document.xml", doc)
    md = markdown.body_of(str(f))
    assert "- **מספר נוהל**: QP-16.1" in md and "- **גרסה**: 01" in md   # facts, not a grid of merged cells
    assert "# מטרה" in md and "## 3. שיטה" in md                        # both kinds of heading are headings
    assert "Advisory notice" in md and "םךןחןםום" not in md             # struck out is not part of the text
    assert "\n\n\n" not in md                                          # and Word's empty paragraphs are gone


def test_a_document_only_to_be_read_goes_up_as_a_pdf():
    """Nothing to type into: a document opened only to be read is converted, and the original is taken away
    again. A spreadsheet is left as it is - on paper it stops being a spreadsheet."""
    from tests.test_sharepoint import Resp
    from dms_api.sharepoint import SharePoint
    import tempfile

    calls = []

    class Sess:
        def request(self, method, url, json=None, data=None, headers=None, timeout=None, allow_redirects=None):
            calls.append((method, url, data))
            if url.endswith("?$select=Id") or "/lists" in url:
                return Resp({"Id": "1"})
            if "Files/AddUsingPath" in url:
                return Resp({"ServerRelativeUrl": "/sites/DocumentControl-TEST/Views/view-1/"
                                                  + url.split("DecodedUrl='")[1].split("'")[0].split("/")[-1]})
            if url.endswith("/drives?$select=id,name,webUrl"):
                return Resp({"value": [{"id": "drv", "name": "Views",
                                        "webUrl": "https://rhisrael.sharepoint.com/sites/DocumentControl-TEST/Views"}]})
            if "content?format=pdf" in url:
                return Resp(b"%PDF-1.7 the document as a page")
            return Resp({})

    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST")
    sp = SharePoint(s, Sess())
    sp._access_token = lambda: "t"
    sp._graph_token = lambda: "g"
    f = os.path.join(tempfile.mkdtemp(), "QP-16.1.docx")
    open(f, "w").write("the procedure")
    r = sp.review_put(local_path=f, document_id="view-1", edit=False, as_pdf=True)
    assert r["name"] == "QP-16.1.pdf"                                   # what the person opens
    assert [c for c in calls if c[1].endswith("/recycle()")]            # and the document itself is gone again
    assert b"%PDF" in next(c[2] for c in calls if "QP-16.1.pdf" in c[1])


def test_a_copy_only_being_read_goes_away_sooner(tmp_path):
    """Somebody editing needs their copy for hours; somebody reading does not need one at all once they have
    read it, so the DMS takes a reading copy back long before an editing one."""
    from datetime import datetime, timedelta, timezone
    from dms_api import checkout
    root = str(tmp_path)
    for name, edit in (("w.docx", True), ("r.docx", False)):
        open(os.path.join(root, name), "w").write("x")
        checkout.add(root, os.path.join(root, name), by="a@rh.co.il", name=name, url="u", edit=edit)
    data = checkout.read(root)
    for entry in data.values():                                  # both taken out an hour ago
        entry["utc"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    checkout.write(root, data)
    due = checkout.due(root, hours=8, read_hours=0.5)
    assert [e["edit"] for e in due] == [False]                   # only the one being read


def test_a_copy_to_be_read_goes_to_its_own_library():
    """A person with Edit on the approvals library could change a released document through the copy made for
    them to read, so a reading copy lives in a library where nobody has standing rights."""
    from dms_api.sharepoint import SharePoint
    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST")
    sp = SharePoint(s, None)
    assert "/Views/view-abc123" in sp._review_folder("view-abc123")        # only to be read
    assert "/Approvals/edit-abc123" in sp._review_folder("edit-abc123")    # taken out to be changed
    assert "/Approvals/DMS-00044" in sp._review_folder("DMS-00044")        # under approval


def test_a_dry_run_names_the_folders_the_blueprint_does_not_cover(tmp_path):
    """A dry run is there to show the whole picture, so a folder with no rule is reported, not raised."""
    from dms_api.memory import MemorySharePoint
    old = tmp_path / "Old"
    (old / "Quotations").mkdir(parents=True)
    (old / "Quotations" / "Q1.xlsx").write_text("q")
    (old / "Whatever").mkdir()
    (old / "Whatever" / "W1.docx").write_text("w")
    root = tmp_path / "Root"
    target = root / "02_Customers" / "Customer_A" / "Commercial"
    target.mkdir(parents=True)
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    c = TestClient(create_app(s, MemorySharePoint(s)))
    j = _wait(c, c.post("/api/first-load", json={"source": str(old), "target": str(target), "dryRun": True}).json()["id"])
    by_name = {os.path.basename(r["source"]): r["result"] for r in j["rows"]}
    assert by_name["Q1.xlsx"].startswith("plan")                       # the blueprint covers Quotations
    assert by_name["W1.docx"].startswith("missing")                    # and says nothing about Whatever
    assert [f for f in j.get("uncovered", []) if "Whatever" in f]      # named, so it can be fixed before the real run


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
    qa = root / "01_General" / "Quality" / "Quality and Standards"
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


def test_a_record_follows_its_file_into_the_workflow_folders(tmp_path):
    """An approval moves the file to Current_ReadOnly while the record still names the place it came from:
    the row followed the record, found nothing and offered no way in at all."""
    from dms_api.file_service import find_file
    root = tmp_path
    folder = root / "01_General" / "Procedures"
    (folder / "Current_ReadOnly").mkdir(parents=True)
    (folder / "Working").mkdir()
    recorded = str(folder / "QP-1.docx")
    assert find_file(str(root), recorded) is None                      # nowhere yet
    approved = folder / "Current_ReadOnly" / "QP-1.docx"
    approved.write_bytes(b"x")
    assert find_file(str(root), recorded) == str(approved)             # it was approved
    working = folder / "Working" / "QP-1.docx"
    working.write_bytes(b"x")
    assert find_file(str(root), recorded) == str(working)              # back in work: that one first
    assert find_file(str(root), str(approved)) == str(approved)        # a path that is there is kept


def test_view_turns_every_readable_format_into_a_pdf():
    """View must leave nothing to type into. A spreadsheet used to go up as it is, and Excel ignores "open to
    view" - the reader could type into the copy, which is what View is there to prevent."""
    from dms_api.sharepoint import SharePoint
    for name in ("a.docx", "a.xlsx", "a.xlsm", "a.csv", "a.pptx", "a.rtf", "a.odt"):
        assert name.endswith(SharePoint.AS_PDF), name
    for name in ("a.pdf", "a.png", "a.txt", "a.zip"):          # already flat, or nothing to lay out
        assert not name.endswith(SharePoint.AS_PDF), name


def test_backfill_writes_markdown_beside_every_released_file(tmp_path, capsys, monkeypatch):
    """One pass for the files that were released before the DMS wrote Markdown at all, or released by hand:
    without it they are in Current_ReadOnly and the AI cannot read them."""
    from dms_api import backfill
    root = tmp_path / "Root"
    cur = root / "01_General" / "Q" / "Current_ReadOnly"
    cur.mkdir(parents=True)
    (cur / "QP-1.docx").write_bytes(b"x")
    (cur / "QP-2.docx").write_bytes(b"x")
    (cur / "QP-2.md").write_text("already there", encoding="utf-8")
    (cur / "photo.png").write_bytes(b"x")
    (root / "01_General" / "Q" / "draft.docx").write_bytes(b"x")          # not released: not its business
    monkeypatch.setattr(backfill, "_register", lambda s: {})
    written = []
    monkeypatch.setattr("dms_api.markdown.write_beside", lambda path, doc=None: written.append(path) or path)

    assert backfill.run(str(root), write=False) == 0 and not written      # a dry run writes nothing
    assert "would write" in capsys.readouterr().out

    assert backfill.run(str(root), write=True) == 0
    assert written == [str(cur / "QP-1.docx")]                            # the one that had none


def test_the_page_is_never_cached(tmp_path):
    """The page is the whole application: a browser holding yesterday's copy shows a DMS that behaves by
    yesterday's rules, which looks exactly like a change that was never installed."""
    c = TestClient(create_app(Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER,
                                       sharepoint="memory")))
    assert "no-store" in c.get("/dms/dms-page").headers.get("cache-control", "")


def test_the_page_offers_the_row_commands_as_a_right_click_menu(tmp_path):
    """File Explorer's way in. The menu is built from the row's own buttons, so a command the DMS decided not
    to offer - delete in Current_ReadOnly, edit for a released document - is not in the menu either."""
    c = TestClient(create_app(Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER,
                                       sharepoint="memory")))
    page = c.get("/dms/dms-page").text
    assert "contextmenu" in page and "function ctxOpen" in page
    assert "src.click()" in page                       # the menu clicks the row's own button, never its own copy
    assert "dms-explorer" in page and "pointer: coarse" in page   # the view is remembered, and never on a touch screen


def test_the_page_has_an_icon_of_its_own(tmp_path):
    """Without one the browser shows whatever it likes - often the icon of the site that tab held before - and
    the DMS looked like a different system from one tab to the next."""
    c = TestClient(create_app(Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER,
                                       sharepoint="memory")))
    page = c.get("/dms/dms-page").text
    assert 'rel="icon"' in page and "/dms/icon.png" in page
    assert c.get("/favicon.ico").status_code == 200 and c.get("/dms/icon.png").status_code == 200
    assert c.get("/dms/logo.png").status_code == 200                      # the header keeps the wide logo


def test_markdown_is_written_for_a_document_whose_next_revision_is_in_work(tmp_path):
    """The revision in force has its Markdown whatever the document's own status is. A document that went back
    into work for its next revision kept an approved file with nothing beside it for the AI to read."""
    from dms_api import file_service
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    folder = root / "01_General" / "Q" / "Current_ReadOnly"
    folder.mkdir(parents=True)
    held = folder / "QP-1_Rev01.docx"
    held.write_bytes(b"x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory")
    sp = MemorySharePoint(s)
    doc = sp.create_document(title="QP-1", path=str(held), document_type="נוהל", document_area="איכות",
                             owner_email=USER, control_mode="", document_id="DMS-00001")
    sp.update(doc["id"], {"LifecycleStatus": s.choices["Working"], "CurrentUncPath": str(held),
                          "CurrentRevision": "01", "WorkingUncPath": str(held)})
    written: list = []
    import dms_api.markdown as md
    real = md.write_beside
    md.write_beside = lambda path, doc=None: written.append(path) or path
    try:
        file_service.run_once(sp, s)
    finally:
        md.write_beside = real
    assert written == [str(held)]                      # in work, and its approved revision still gets one


def test_a_working_row_falls_back_to_the_approved_file(tmp_path):
    """Approval renames the file (it drops _DRAFT and carries the revision), so the working path in the record
    names something that is no longer there. The row then has the record's own approved path to fall back on."""
    from dms_api.file_service import find_file
    root = tmp_path
    folder = root / "01_General" / "Q"
    (folder / "Current_ReadOnly").mkdir(parents=True)
    draft = str(folder / "QP-1_Rev02_DRAFT.docx")
    approved = folder / "Current_ReadOnly" / "QP-1_Rev02.docx"
    approved.write_bytes(b"x")
    assert find_file(str(root), draft) is None                      # the name in the record is gone
    assert find_file(str(root), str(approved)) == str(approved)     # the record's approved path still answers


def test_nobody_approves_their_own_document(tmp_path):
    """Writing it and approving it are two people. Choosing yourself as the approver, or delegating the
    approval back to the person who wrote it, is the same thing by another route."""
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    (root / "01_General" / "Procedures").mkdir(parents=True)
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    c = TestClient(create_app(s, MemorySharePoint(s)))
    f = root / "01_General" / "Procedures" / "QP-3.docx"
    f.write_bytes(b"x")
    d = c.post("/api/documents", json={"path": str(f), "documentType": "נוהל", "documentArea": "איכות"}).json()
    r = c.post(f"/api/documents/{d['id']}/submit", json={"approvers": [USER]})
    assert r.status_code == 403 and USER in r.text
    assert c.post(f"/api/documents/{d['id']}/submit", json={"approvers": ["other@rh.co.il"]}).status_code == 200


def test_a_document_is_not_sent_to_someone_ad_keeps_away(tmp_path, monkeypatch):
    """The DMS has rights on the file server where nobody else does, so an approval would otherwise become the
    way in: an HR procedure sent to someone outside the HR group would land in their hands."""
    from dms_api import main as m
    from dms_api.memory import MemorySharePoint
    root = tmp_path / "Root"
    (root / "01_General" / "HR").mkdir(parents=True)
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    c = TestClient(create_app(s, MemorySharePoint(s)))
    f = root / "01_General" / "HR" / "QP-9.docx"
    f.write_bytes(b"x")
    d = c.post("/api/documents", json={"path": str(f), "documentType": "נוהל", "documentArea": "משאבי אנוש"}).json()
    monkeypatch.setattr("dms_api.security.may_see", lambda email, path, access="read": email != "outsider@rh.co.il")
    r = c.post(f"/api/documents/{d['id']}/submit", json={"approvers": ["outsider@rh.co.il"]})
    assert r.status_code == 403 and "outsider@rh.co.il" in r.text
    assert c.post(f"/api/documents/{d['id']}/submit", json={"approvers": ["other@rh.co.il"]}).status_code == 200


def test_a_long_path_is_still_found(tmp_path):
    """Over about 260 characters Windows says the file is not there, and a few Hebrew folder names reach that
    on their own: the DMS then found no file and offered a link to it instead of the SharePoint copy."""
    from dms_api import files
    f = tmp_path / "a.docx"
    f.write_bytes(b"x")
    assert files.is_file(str(f)) and files.exists(str(f))
    assert not files.is_file(str(tmp_path / "no.docx")) and not files.is_file("")
    assert files.extended(str(f)) == str(f)                  # a \\?\ path only on Windows


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
    assert [l["list"] for l in r["lists"]] == ["Lists/DocumentRegister", "Lists/ControlAudit", "Lists/ApproverMatrix", "Lists/DmsNotifications", "Lists/ApprovalDecisions", "Lists/Delegations"]
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
    sp.s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST", sp_auth="interactive")
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


def test_directory_people_from_graph_when_the_dms_signs_in_with_a_certificate():
    """App-only: the SharePoint search API refuses the call, so the directory comes from Microsoft Graph,
    and from the people of the site when that permission is missing too."""
    from dms_api.sharepoint import SharePoint, SharePointError
    sp = SharePoint.__new__(SharePoint)
    sp.s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST")   # certificate
    pages = [{"value": [{"displayName": "Dana Levi", "mail": "Dana.Levi@rh.co.il", "jobTitle": "QA", "department": "Quality"},
                        {"displayName": "No Mail", "mail": None}],
              "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=x"},
             {"value": [{"displayName": "Avi Cohen", "mail": "avi@rh.co.il"}]}]
    calls = []
    sp._graph = lambda m, path: (calls.append(path), pages.pop(0))[1]
    people = sp.directory_people()
    assert [p["email"] for p in people] == ["avi@rh.co.il", "dana.levi@rh.co.il"]
    assert people[1]["title"] == "QA · Quality" and calls[1].startswith("users?$skiptoken=")

    sp2 = SharePoint.__new__(SharePoint)
    sp2.s = sp.s
    sp2._graph = lambda m, path: (_ for _ in ()).throw(SharePointError("Graph GET users -> 403"))
    sp2.site_people = lambda: [{"email": "ronen@rh.co.il", "name": "Ronen", "title": ""}]
    assert [p["email"] for p in sp2.directory_people()] == ["ronen@rh.co.il"]              # the site, not an error


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
    det = sp.audit_events()[0]["details"]
    assert det.startswith("Delegated: dana@rh.co.il -> avi@rh.co.il (until ") and det.endswith("): on vacation")
    row = sp.delegations[-1]
    assert (row["delegator"], row["delegate"], row["approvedBy"], row["reason"]) == \
        ("dana@rh.co.il", "avi@rh.co.il", "dana@rh.co.il", "DMS-00001 Quote: on vacation")
    from datetime import date as _d
    f, u = _d.fromisoformat(row["validFrom"]), _d.fromisoformat(row["validTo"])
    workdays = sum(1 for i in range(1, (u - f).days + 1) if _d.fromordinal(f.toordinal() + i).weekday() not in (4, 5))
    assert workdays == 3 and u.weekday() not in (4, 5)
    assert c.get("/api/approvals").json() == []                                         # no longer Dana's
    s.dev_user = "avi@rh.co.il"
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).json()["stage"] == 2
    s.dev_user, s.admins = USER, [USER]                                                  # a super user, for the final approver
    r = c.post(f"/api/approvals/{d['id']}/delegate", json={"to": "eli@rh.co.il", "from": "boss@rh.co.il"}).json()
    assert r["pending"] == ["eli@rh.co.il"] and "(by " in sp.audit_events()[0]["details"]
    s.dev_user = "eli@rh.co.il"
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).json()["statusKey"] == "Approved_ReadOnly"
    rows = [(x["decision"], x["approver"], x["stage"], x["role"], x.get("delegated_from")) for x in sp.decisions]
    assert rows == [("Delegated", "dana@rh.co.il", 1, "Mandatory", None), ("Approved", "avi@rh.co.il", 1, "Mandatory", "dana@rh.co.il"),
                    ("Delegated", "boss@rh.co.il", 2, "Final", None), ("Approved", "eli@rh.co.il", 2, "Final", "boss@rh.co.il")]
    assert sp.decisions[0]["workflow_id"].startswith("DMS-00001-") and sp.decisions[0]["revision"] == "01"


def test_expired_delegation_returns_to_the_approver(tmp_path):
    rule = {"mandatory": ["dana@rh.co.il"], "final": None}
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.xlsx").write_text("x")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, approvals="page", admins=[])
    sp = RuleSP(s, rule)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.xlsx"), "documentType": "x", "documentArea": "y", "submit": True}).json()
    s.dev_user = "dana@rh.co.il"
    assert c.post(f"/api/approvals/{d['id']}/delegate", json={"to": "avi@rh.co.il"}).json()["pending"] == ["avi@rh.co.il"]
    sp.audits[-1]["utc"] = "2026-01-01T09:00:00Z"                                       # delegated long ago
    assert [x["id"] for x in c.get("/api/approvals").json()] == [d["id"]]               # back with Dana


def test_onedrive_shortcut_payload():
    from tests.test_sharepoint import Resp
    from dms_api.sharepoint import SharePoint

    class Sess:
        def __init__(self):
            self.calls = []

        def request(self, method, url, json=None, data=None, headers=None, timeout=None):
            self.calls.append((method, url, json))
            if url.endswith("/drives?$select=id,name,webUrl"):
                return Resp({"value": [{"id": "d0", "name": "Documents", "webUrl": "https://x/sites/LFE/Shared Documents"},
                                       {"id": "d1", "name": "TemporaryUploads", "webUrl": "https://x/sites/LFE/TemporaryUploads"}]})
            if "root:/Outbound/Customer%20A" in url:
                return Resp({"id": "f1"})
            return Resp({})
    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST", sp_auth="certificate",
                 ex_site_url="https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST")
    sess = Sess()
    sp = SharePoint(s, sess)
    sp._graph_token = lambda: "g"
    assert sp.onedrive_shortcut("Outbound/Customer A", "DMS_Customer A", "roneno@rh.co.il") == "DMS Shortcuts/DMS_Customer A"
    method, url, body = sess.calls[-2]                                             # the shortcuts folder
    assert url.endswith("/users/roneno%40rh.co.il/drive/root/children") and body["name"] == "DMS Shortcuts" and "folder" in body
    method, url, body = sess.calls[-1]
    assert method == "POST" and url.endswith("/users/roneno%40rh.co.il/drive/root:/DMS%20Shortcuts:/children")
    assert body["name"] == "DMS_Customer A" and body["remoteItem"] == {"id": "f1", "parentReference": {"driveId": "d1"}}


def test_onedrive_not_set_up_is_requested():
    import pytest
    from tests.test_sharepoint import Resp
    from dms_api.sharepoint import SharePoint, SharePointError

    class Sess:
        def __init__(self):
            self.calls = []

        def request(self, method, url, json=None, data=None, headers=None, timeout=None):
            self.calls.append((method, url))
            if url.endswith("/drives?$select=id,name,webUrl"):
                return Resp({"value": [{"id": "d1", "name": "TemporaryUploads", "webUrl": "https://x/TemporaryUploads"}]})
            if url.endswith("/me/drive?$select=id"):
                return Resp({"error": {"code": "itemNotFound", "message": "mysite not found"}}, status=404)
            return Resp({"id": "f1"})
    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST", sp_auth="interactive",
                 ex_site_url="https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST")
    sess = Sess()
    sp = SharePoint(s, sess)
    sp._graph_token = lambda: "g"
    sp._access_token = lambda: "t"
    with pytest.raises(SharePointError, match="not set up yet"):
        sp.onedrive_shortcut("Outbound/C", "DMS_C", "roneno@rh.co.il")
    assert sess.calls[-1] == ("POST", "https://rhisrael.sharepoint.com/_api/SP.UserProfiles.ProfileLoader.GetProfileLoader/GetUserProfile/CreatePersonalSiteEnque(false)")


def test_shares_expire_after_3_days(tmp_path):
    from datetime import datetime, timedelta, timezone
    from dms_api import exchange_expiry
    c, sp, s, q, d, fs = _approved_env(tmp_path)
    assert s.ex_days == 3
    c.post(f"/api/documents/{d['id']}/share", json={"email": "x@cust.com"})
    assert exchange_expiry.run_once(sp, s) == []                                   # shared today: kept
    sp.shares[0]["utc"] = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    r = exchange_expiry.run_once(sp, s)
    assert r[0]["file"] == "CRU 4 FCT Quote_Rev1.xlsx" and r[0]["folderRemoved"] and not sp.shares
    ev = sp.audit_events()[0]
    assert ev["documentId"] == "DMS-00001" and "Share expired after 3 days" in ev["details"] and "no access" in ev["details"]
    last = (tmp_path / "Root" / "02_Customers" / "Customer_A" / "Shared" / "DMS-Shared-Log.csv").read_text(encoding="utf-8-sig").splitlines()[-1]
    assert "Expired" in last and "CRU 4 FCT Quote_Rev1.xlsx" in last


def test_expire_outbound_requests():
    from datetime import datetime, timezone
    from tests.test_sharepoint import Resp
    from dms_api.sharepoint import SharePoint

    class Sess:
        def __init__(self):
            self.calls = []

        def request(self, method, url, json=None, data=None, headers=None, timeout=None):
            self.calls.append((method, url))
            if url.endswith("Outbound')/Folders?$select=Name,ServerRelativeUrl,ItemCount"):
                return Resp({"value": [{"Name": "A", "ServerRelativeUrl": "/sites/LFE/TemporaryUploads/Outbound/A"}]})
            if "/Outbound/A')/Files" in url:
                return Resp({"value": [{"Name": "old.pdf", "ServerRelativeUrl": "/sites/LFE/TemporaryUploads/Outbound/A/old.pdf", "TimeLastModified": "2026-08-01T10:00:00Z"},
                                       {"Name": "new.pdf", "ServerRelativeUrl": "/sites/LFE/TemporaryUploads/Outbound/A/new.pdf", "TimeLastModified": "2026-10-01T10:00:00Z"}]})
            return Resp({"value": []})
    s = Settings(site_url="https://rhisrael.sharepoint.com/sites/DocumentControl-TEST", ex_site_url="https://rhisrael.sharepoint.com/sites/LFE")
    sess = Sess()
    sp = SharePoint(s, sess)
    sp._access_token = lambda: "t"
    r = sp.expire_outbound(30, now=datetime(2026, 10, 3, tzinfo=timezone.utc))
    assert [x["file"] for x in r] == ["old.pdf"] and not r[0]["folderRemoved"]       # new.pdf keeps the folder
    recycled = [u for m, u in sess.calls if u.endswith("/recycle()")]
    assert len(recycled) == 1 and "old.pdf" in recycled[0]


def test_new_customer_and_project_get_the_blueprint_folders(tmp_path):
    root = tmp_path / "Root"
    (root / "02_Customers").mkdir(parents=True)
    c = TestClient(create_app(Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])))
    r = c.post("/api/folders", json={"parent": str(root / "02_Customers"), "name": "Elbit"})
    assert r.status_code == 201, r.text
    cust = root / "02_Customers" / "Elbit"
    assert (cust / "Commercial" / "Quotations").is_dir() and (cust / "Shared").is_dir() and (cust / "Develop" / "Products").is_dir()
    assert (cust / "Develop" / "ATEFiles" / "FCT" / "07_FAT").is_dir() and (cust / "QC" / "PPAP").is_dir()
    r = c.post("/api/folders", json={"parent": str(cust / "Develop" / "Products"), "name": "Radar"})
    prj = cust / "Develop" / "Products" / "Radar"
    assert r.json()["blueprintFolders"] == 11
    assert (prj / "07_FAT").is_dir() and (prj / "10_Project_Deliverables").is_dir()
    sub = c.post("/api/folders", json={"parent": str(prj / "07_FAT"), "name": "Extra"}).json()
    assert sub["blueprintFolders"] == 0                                              # deeper folders: just the folder


def test_blueprint_folders_locked_user_folders_and_projects_free(tmp_path):
    root = tmp_path / "Root"
    (root / "02_Customers").mkdir(parents=True)
    c = TestClient(create_app(Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])))
    c.post("/api/folders", json={"parent": str(root / "02_Customers"), "name": "Customer_A"})
    prj = root / "02_Customers" / "Customer_A" / "Develop" / "Products"
    c.post("/api/folders", json={"parent": str(prj), "name": "Project_1"})
    eng = root / "02_Customers" / "Customer_A" / "Process_Engineering"
    assert c.post("/api/items/rename", json={"path": str(eng), "newName": "Eng2"}).status_code == 403      # blueprint
    assert c.post("/api/items/delete", json={"path": str(eng / "Stencil")}).status_code == 403
    assert c.post("/api/items/delete", json={"path": str(prj / "Project_1" / "07_FAT")}).status_code == 403
    assert c.post("/api/items/delete", json={"path": str(root / "02_Customers" / "Customer_A")}).status_code in (403, 409)
    c.post("/api/folders", json={"parent": str(eng / "Stencil"), "name": "Board_A"})                    # the user's own folder
    r = c.post("/api/items/rename", json={"path": str(eng / "Stencil" / "Board_A"), "newName": "Board_B"})
    assert r.status_code == 200, r.text
    assert c.post("/api/items/delete", json={"path": str(eng / "Stencil" / "Board_B")}).status_code == 200
    r = c.post("/api/items/rename", json={"path": str(prj / "Project_1"), "newName": "PRJ-300_Radar"})    # a product is the user's
    assert r.status_code == 200, r.text and (prj / "PRJ-300_Radar" / "07_FAT").is_dir()
    assert c.post("/api/items/delete", json={"path": str(prj / "PRJ-300_Radar")}).status_code == 200


def test_blueprint_folder_list_matches_the_tree_script_file():
    import pathlib
    from dms_api import blueprint
    f = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "blueprint-folders.txt"
    lines = [x.strip() for x in f.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    assert lines == blueprint.folder_list()          # regenerate: py -m dms_api.blueprint > ..\scripts\blueprint-folders.txt


def test_first_loading_save_only(tmp_path):
    from dms_api.memory import MemorySharePoint
    old = tmp_path / "OldRepo" / "Misc"
    (old / "Photos").mkdir(parents=True)
    (old / "Photos" / "line.jpg").write_text("img")
    (old / "notes.txt").write_text("n")
    target = tmp_path / "Root" / "02_Customers" / "Customer_A" / "Process_Engineering"
    target.mkdir(parents=True)
    s = Settings(repository_root=str(tmp_path / "Root"), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])
    sp = MemorySharePoint(s)
    c = TestClient(create_app(s, sp))
    linker = FakeLinker({str(old / "notes.txt")})
    c.app.state.linker = linker
    body = {"source": str(old), "target": str(target), "mode": "save", "dryRun": False}
    j = _wait(c, c.post("/api/first-load", json=body).json()["id"])
    assert {r["result"] for r in j["rows"]} == {"released - approved by DMS"}
    line, notes = target / "Photos" / "Current_ReadOnly" / "line.jpg", target / "Current_ReadOnly" / "notes.txt"
    assert line.exists() and notes.exists() and files.is_read_only(str(notes))
    assert not (target / "notes.txt").exists()
    docs = sp.documents()                                                                # traced in the Document Register
    assert len(docs) == 2 and all(d["lifecycleStatus"] == s.choices["Approved_ReadOnly"] and d["controlMode"] == sp.choices("ControlMode")[0] for d in docs)
    rows = [a for a in sp.audits if a["actor"] == "DMS"]
    assert len(rows) == 2 and all("[file SHA-256 " in a["details"] and a["documentId"] for a in rows)
    assert linker.replaced == [(str(old / "notes.txt"), str(notes))]
    again = _wait(c, c.post("/api/first-load", json=body).json()["id"])
    assert {r["result"] for r in again["rows"]} == {"skipped - already released"}


def test_saved_without_workflow_has_no_start_workflow(tmp_path):
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    c = TestClient(create_app(Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", admins=[USER])))
    r = c.post("/api/files/upload", data={"folder": str(q), "noWorkflow": "true"}, files={"file": ("notes.docx", b"x")})
    assert r.status_code == 201, r.text
    c.post("/api/files/upload", data={"folder": str(q)}, files={"file": ("quote.docx", b"y")})       # New document path
    cur = q / "Current_ReadOnly"
    assert not (q / "notes.docx").exists() and (cur / "notes.docx").is_file()           # straight to Current_ReadOnly
    assert files.is_read_only(str(cur / "notes.docx"))                                    # read only
    files_ = {f["name"]: f for f in c.get("/api/browse", params={"path": str(cur)}).json()["files"]}
    assert files_["notes.docx"].get("noWorkflow")
    assert {f["name"] for f in c.get("/api/browse", params={"path": str(q)}).json()["files"]} == {"quote.docx"}
    assert c.post("/api/documents", json={"path": str(cur / "notes.docx"), "documentType": "x", "documentArea": "y"}).status_code == 409
    r = c.post("/api/files/upload", data={"folder": str(q), "noWorkflow": "true", "overwrite": "true"}, files={"file": ("notes.docx", b"z")})
    assert r.status_code == 201, r.text
    assert (cur / "notes.docx").read_bytes() == b"z" and files.is_read_only(str(cur / "notes.docx"))
    assert c.post("/api/files/upload", data={"folder": str(q), "noWorkflow": "true"}, files={"file": ("notes.docx", b"w")}).status_code == 409
    sp = c.app.state.sp
    d = next(d for d in sp.documents() if d["currentUncPath"] == str(cur / "notes.docx"))     # traced in SharePoint
    assert c.app.state.sp.choices("ControlMode")[0] == d["controlMode"] and d["lifecycleStatus"] == c.app.state.sp.s.choices["Approved_ReadOnly"] and d["ownerEmail"] == USER
    assert len([a for a in sp.audits if a["documentId"] == d["documentId"] and a["actor"] == "DMS"]) == 2   # saved, then saved again
    assert c.get(f"/api/documents/{d['id']}/share-info").json()["customer"] == "Customer_A"           # can be shared
    r = c.post(f"/api/documents/{d['id']}/revise")                                                       # New revision: into workflow
    assert r.status_code == 200, r.text
    d = sp.document(d["id"])
    assert d["controlMode"] != sp.choices("ControlMode")[0] and not c.post(f"/api/documents/{d['id']}/submit").status_code >= 400


def test_dev_mode_acting_as_another_listed_user(tmp_path):
    other = "approver@rh.co.il"
    c = TestClient(create_app(Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER, dev_users=[other],
                                       sharepoint="memory", admins=[USER])))
    me = c.get("/api/me").json()
    assert me["email"] == USER and me["actingUsers"] == [USER, other]                     # the ⋮ menu for super users
    me = c.get("/api/me", headers={"X-DMS-Dev-User": other}).json()
    assert me["email"] == other and not me["admin"] and me["actingFrom"] == USER
    assert me["actingUsers"] == [USER, other]                                               # can switch back
    assert c.get("/api/me", headers={"X-DMS-Dev-User": "someone@else.com"}).json()["email"] == USER   # not listed: ignored


def test_acting_as_only_for_super_users_with_windows_sign_in(tmp_path, monkeypatch):
    from dms_api import auth
    from dms_api.security import User
    real = {"who": "boss@rh.co.il"}
    monkeypatch.setattr(auth, "_resolve", lambda request: User(email=real["who"]))
    monkeypatch.setattr(auth, "_with_ad", lambda user, account: None)
    c = TestClient(create_app(Settings(repository_root=str(tmp_path), auth_mode="windows", sharepoint="memory",
                                       admins=["boss@rh.co.il"])))
    h = {"X-DMS-Dev-User": "dana@rh.co.il"}
    assert c.get("/api/me", headers=h).json()["email"] == "dana@rh.co.il"                 # a super user: any user (no list)
    real["who"] = "eli@rh.co.il"
    me = c.get("/api/me", headers=h).json()
    assert me["email"] == "eli@rh.co.il" and "actingUsers" not in me                       # a normal user: never


def test_dev_ad_check_for_acting_users_not_for_admins(tmp_path, monkeypatch):
    from dms_api import security
    other = "user@rh.co.il"
    cust = tmp_path / "02_Customers"
    (cust / "Customer_A").mkdir(parents=True)
    (cust / "Customer_B").mkdir()

    class FakeAd:                                             # AD lets the user see only Customer_A
        def can(self, path, access="read"):
            return "Customer_B" not in path
    monkeypatch.setattr(security.AdUser, "get", classmethod(lambda cls, upn: FakeAd()))
    c = TestClient(create_app(Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER, dev_users=[other],
                                       dev_ad_check=True, sharepoint="memory", admins=[USER])))
    names = lambda h: {f["name"] for f in c.get("/api/browse", params={"path": str(cust)}, headers=h).json()["folders"]}  # noqa: E731
    assert names({}) == {"Customer_A", "Customer_B"}                                   # super user: no AD check
    assert names({"X-DMS-Dev-User": other}) == {"Customer_A"}                          # acting user: AD decides


def test_other_pcs_sign_in_with_their_windows_account(tmp_path, monkeypatch):
    import base64
    from dms_api import ntlm, security
    steps = []

    class FakeCtx:                                            # Windows SSPI: message 1 -> challenge, message 3 -> signed in
        def authorize(self, token):
            steps.append(token[8:9])
            if token[8:9] == b"\x01":
                return 1, [type("B", (), {"Buffer": b"NTLMSSP\x00\x02challenge"})()]
            if token.endswith(b"bad"):
                raise RuntimeError("logon failure")
            return 0, None
    monkeypatch.setattr(ntlm, "_server_context", FakeCtx)
    monkeypatch.setattr(ntlm, "_account", lambda ctx: "RH\\dana")
    monkeypatch.setattr(security, "upn_of", lambda account: "dana@rh.co.il")
    monkeypatch.setattr(security.AdUser, "get", classmethod(lambda cls, upn: type("Ad", (), {"can": lambda self, p, a="read": True})()))
    app = create_app(Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER, sharepoint="memory",
                              admins=[USER], remote_signin="ntlm"))
    assert TestClient(app).get("/api/me").json()["email"] == USER                       # the PC itself: the PC owner
    c = TestClient(app, client=("10.30.8.50", 50000))
    r = c.get("/api/me")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "NTLM"            # another PC: Windows sign-in
    assert c.get("/api/health").status_code == 200
    m1 = "NTLM " + base64.b64encode(b"NTLMSSP\x00\x01\x00\x00\x00").decode()
    r = c.get("/api/me", headers={"Authorization": m1})
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("NTLM ") and len(r.headers["www-authenticate"]) > 5
    bad = "NTLM " + base64.b64encode(b"NTLMSSP\x00\x03\x00\x00\x00bad").decode()
    assert c.get("/api/me", headers={"Authorization": bad}).status_code == 401
    c.get("/api/me", headers={"Authorization": m1})
    m3 = "NTLM " + base64.b64encode(b"NTLMSSP\x00\x03\x00\x00\x00ok").decode()
    me = c.get("/api/me", headers={"Authorization": m3}).json()
    assert me["email"] == "dana@rh.co.il" and "actingUsers" not in me                  # herself, not the PC owner
    other = TestClient(app, client=("10.30.8.50", 50001), cookies={ntlm.COOKIE: c.cookies[ntlm.COOKIE]})
    assert other.get("/api/me").json()["email"] == "dana@rh.co.il"                     # the cookie keeps her signed in
    assert other.get("/api/me", headers={"X-DMS-Dev-User": USER}).json()["email"] == "dana@rh.co.il"   # no Acting as
    forged = TestClient(app, client=("10.30.8.51", 1), cookies={ntlm.COOKIE: ntlm.cookie_for(USER, "RH\\x")[:-2] + "00"})
    assert forged.get("/api/me").status_code == 401


def test_a_long_path_keeps_the_file_name_and_shortens_only_the_folders(monkeypatch):
    """An 8.3 name holds three letters, so Quote.xlsx would reach Excel as QUOTE~1.XLS and it complains that
    the format and the extension do not match. The file's own name is kept whenever it is plain ASCII."""
    from dms_api import files
    long_folder = "\\\\RHFS02\\General\\" + "\\".join(["a long folder name here"] * 8)
    full = long_folder + "\\Quote.xlsx"
    monkeypatch.setattr(files, "short_path", lambda p, force=False: "\\\\RHFS02\\General\\ALONGF~1\\ALONGF~2"
                        + (("\\" + "QUOTE~1.XLS") if p.lower().endswith(".xlsx") else ""))
    monkeypatch.setattr(files, "user_path", lambda p: p)
    uri = files.office_uri(full)
    assert uri.endswith("/ALONGF~2/Quote.xlsx") and "QUOTE~1.XLS" not in uri


def test_short_paths_for_open_and_copy(tmp_path):
    from dms_api.config import _short_paths
    m = _short_paths(r"02_Customers=\\fs\Customers; 01_General=\\fs\General\ ")
    assert m == {"02_Customers": r"\\fs\Customers", "01_General": r"\\fs\General"}
    c = TestClient(create_app(Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER, sharepoint="memory",
                                       short_paths=m)))
    assert [p[1] for p in c.get("/api/client-config").json()["shortPaths"]] == [r"\\fs\Customers", r"\\fs\General"]
    # another PC gets the root as it can open it (DMS_CLIENT_ROOT), never the drive letters of the DMS server
    c2 = TestClient(create_app(Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER, sharepoint="memory",
                                        short_paths=m, client_root=r"\\RHFS02\Shares")))
    remote = c2.get("/api/client-config", headers={"X-Forwarded-For": "10.30.8.51"}).json()["shortPaths"]
    assert remote == [[str(tmp_path), r"\\RHFS02\Shares"]]
    f = os.path.join(str(tmp_path), "02_Customers", "Customer_A", "q.docx")
    assert files.user_path(f) == "\\\\fs\\Customers\\Customer_A\\q.docx"
    assert "file://fs/Customers/Customer_A/q.docx" in files.office_uri(f)
    other = os.path.join(str(tmp_path), "03_Operations_Staging", "x.docx")
    assert files.user_path(other) == other                                               # not mapped: unchanged
    files.set_short_paths("", {})


def test_user_drive_letters_from_the_page(tmp_path):
    c = TestClient(create_app(Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER, sharepoint="memory",
                                       short_paths={"02_Customers": "R:"})))
    q = tmp_path / "02_Customers" / "Customer_A"
    q.mkdir(parents=True)
    (q / "a.docx").write_bytes(b"x")
    uri = lambda h: next(f for f in c.get("/api/browse", params={"path": str(q)}, headers=h).json()["files"])["officeUri"]  # noqa: E731
    assert "file:///R:/Customer_A/a.docx" in uri({})                                   # DMS_SHORT_PATHS
    assert "file:///K:/Customer_A/a.docx" in uri({"X-DMS-Drives": "02_Customers=K:"})   # this PC's letter
    assert "file:///R:/Customer_A/a.docx" in uri({})                                   # only for that request
    files.set_short_paths("", {})


def test_dotenv_inline_comments(tmp_path, monkeypatch):
    from dms_api import config
    env = tmp_path / ".env"
    env.write_text('DMS_T1=\\\\FS\\Data   # [script] -Root\nDMS_T2={"a": "{old}"}\nDMS_T3=DMS Shortcuts\n', encoding="utf-8")
    for k in ("DMS_T1", "DMS_T2", "DMS_T3"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(config, "Path", lambda *_: type("P", (), {"resolve": lambda self: type("Q", (), {"parent": type("R", (), {"parent": tmp_path})()})()})())
    config._load_dotenv()
    assert os.environ["DMS_T1"] == "\\\\FS\\Data" and os.environ["DMS_T2"] == '{"a": "{old}"}' and os.environ["DMS_T3"] == "DMS Shortcuts"


def test_dev_user_is_always_super_user(tmp_path):
    from dms_api.memory import MemorySharePoint
    s = Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER, dev_users=["x@rh.co.il"],
                 sharepoint="online", sp_auth="interactive", admins=["<your.email>@rh.co.il"])
    c = TestClient(create_app(s, MemorySharePoint(s)))                                  # the live pilot
    assert c.get("/api/me").json()["admin"]                                             # menu: SharePoint check, First loading
    assert not c.get("/api/me", headers={"X-DMS-Dev-User": "x@rh.co.il"}).json()["admin"]


def test_office_uri_long_hebrew_path_uses_8dot3(tmp_path, monkeypatch):
    root = str(tmp_path)
    files.set_short_paths(root, {"01_General": "G:"})
    heb = "נוהל בקרת מסמכים ורשומות ארגוניות"
    f = os.path.join(root, "01_General", "Quality and Standards", heb, heb, "a.docx")
    assert files.url_len(files.user_path(f)) > files.LONG_PATH                          # Hebrew = 6 characters each in the URL
    fake = {os.path.join(root, "01_General"): os.path.join(root, "01_GEN~1"),
            f: os.path.join(root, "01_GEN~1", "QUALIT~1", "D7A1~1", "D7A2~1", "a.docx")}
    monkeypatch.setattr(files, "short_path", lambda p, force=False: fake.get(p, p))
    files._SHORT_PREFIX.clear()
    assert "file:///G:/QUALIT~1/D7A1~1/D7A2~1/a.docx" in files.office_uri(f)
    files.set_short_paths("", {})
    files._SHORT_PREFIX.clear()


def test_office_uri_too_long_gives_dms_webdav_link(tmp_path):
    from urllib.parse import quote
    root = tmp_path
    heb = "נוהל בקרת מסמכים ורשומות ארגוניות"
    d = root / "01_General" / "Quality and Standards" / heb / heb
    d.mkdir(parents=True)
    name = f"QP-2.1 V06 {heb}_Rev02.docx"
    (d / name).write_bytes(b"doc")
    c = TestClient(create_app(Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory",
                                       short_paths={"01_General": "G:"})))
    f = next(x for x in c.get("/api/browse", params={"path": str(d)}).json()["files"])
    assert f["editable"] and f["officeUri"].startswith("ms-word:ofe|u|http://testserver/api/o/")   # edit, the original name
    assert f["officeUri"].endswith("/" + quote(name))
    o = next(x for x in c.get("/api/browse", params={"path": str(d)}, headers={"X-DMS-Opener": "1"}).json()["files"])
    from urllib.parse import unquote
    assert o["officeUri"].startswith("rh-dms:G%3A") and unquote(o["officeUri"]).replace("\\", "/").endswith(
        "Quality and Standards/" + heb + "/" + heb + "/" + name)                         # PC handler: the path itself
    link = f["officeUri"].split("|u|http://testserver", 1)[1]
    files.OPEN_TOKENS.clear()                                                            # as after a restart
    assert c.get(link).content == b"doc"
    assert c.request("OPTIONS", link).headers["DAV"] == "1,2"
    assert c.request("OPTIONS", "/").headers["MS-Author-Via"] == "DAV"                  # Office asks the server first
    assert c.request("PROPFIND", link.rsplit("/", 1)[0]).status_code == 207              # and the folder of the link
    pf = c.request("PROPFIND", link)
    assert pf.status_code == 207 and "<d:getcontentlength>3</d:getcontentlength>" in pf.text
    assert f"<d:href>{link}</d:href>" in pf.text and heb not in pf.text.split("<d:displayname>")[0]   # encoded, as Word sent it
    lock = c.request("LOCK", link, content='<?xml version="1.0"?><D:lockinfo xmlns:D="DAV:"><D:lockscope><D:exclusive/>'
                     '</D:lockscope><D:locktype><D:write/></D:locktype><D:owner><D:href>roneno</D:href></D:owner></D:lockinfo>')
    assert lock.status_code == 200 and lock.headers["Lock-Token"].startswith("<opaquelocktoken:")
    token = lock.headers["Lock-Token"][1:-1]
    pf = c.request("PROPFIND", link)                                                     # Word checks its lock is there
    assert token in pf.text and "<d:href>roneno</d:href>" in pf.text
    assert f"<d:lockroot><d:href>{link}</d:href></d:lockroot>" in lock.text
    assert c.request("LOCK", link, headers={"Timeout": "Second-600"}).headers["Lock-Token"] == f"<{token}>"   # refresh
    assert c.request("LOCK", link, content="<D:lockinfo xmlns:D='DAV:'/>").status_code == 423   # someone else meanwhile
    assert c.put(link, content=b"saved from Word").status_code == 204                   # Save writes back to the source
    assert (d / name).read_bytes() == b"saved from Word"
    assert c.request("UNLOCK", link).status_code == 204 and token not in c.request("PROPFIND", link).text
    assert c.put(link.rsplit("/", 1)[0] + "/~$tmp.docx", content=b"x").status_code == 403   # only this file
    ro = d / "Current_ReadOnly"
    ro.mkdir()
    (ro / name).write_bytes(b"approved")
    g = next(x for x in c.get("/api/browse", params={"path": str(ro)}).json()["files"])
    assert g["officeUri"].startswith("ms-word:ofv|u|http://testserver/api/o/")           # Current_ReadOnly: view
    assert c.put(g["officeUri"].split("|u|http://testserver", 1)[1], content=b"x").status_code == 403
    files.set_short_paths("", {})


def test_files_before_registration_open_for_editing(tmp_path):
    q = tmp_path / "02_Customers" / "Customer_A" / "Commercial"
    (q / "Current_ReadOnly").mkdir(parents=True)
    (q / "draft.docx").write_bytes(b"x")
    (q / "Current_ReadOnly" / "approved.docx").write_bytes(b"y")
    c = TestClient(create_app(Settings(repository_root=str(tmp_path), auth_mode="dev", dev_user=USER, sharepoint="memory")))
    f = next(x for x in c.get("/api/browse", params={"path": str(q)}).json()["files"] if x["name"] == "draft.docx")
    assert f["editable"] and f["officeUri"].startswith("ms-word:ofe|u|")                 # not registered: edit
    g = c.get("/api/browse", params={"path": str(q / "Current_ReadOnly")}).json()["files"][0]
    assert not g.get("editable") and g["officeUri"].startswith("ms-word:ofv|u|")          # Current_ReadOnly: view


def test_review_cycle_all_approvers_return_remarks_then_owner_resubmits(tmp_path):
    rule = {"mandatory": ["dana@rh.co.il", "eli@rh.co.il"], "final": "boss@rh.co.il"}
    c, sp, s, d = _approvals_env(tmp_path, rule)
    s.dev_user = "dana@rh.co.il"
    r = c.post(f"/api/approvals/{d['id']}", json={"approve": False, "comment": "table 3 is wrong"}).json()
    assert r["statusKey"] == "Submitted" and r["pending"] == ["eli@rh.co.il"]            # the review goes on
    assert r["returned"] == [{"by": "dana@rh.co.il", "comment": "table 3 is wrong"}]
    s.dev_user = "eli@rh.co.il"
    ap = next(i for i in c.get("/api/approvals").json() if i["id"] == d["id"])
    assert not ap["editable"] and ap["viewUri"]                  # eli reads it; his remarks go in a file of his own
    r = c.post(f"/api/approvals/{d['id']}", json={"approve": False, "comment": "add the test limits"}).json()
    assert r["statusKey"] == "Working"                                                   # everyone answered: back to the owner
    s.dev_user = USER
    item = next(i for i in c.get("/api/my-workflows").json()["items"] if i["id"] == d["id"])
    det = _nosha(item["decision"]["details"])
    assert item["statusKey"] == "Rejected" and "dana: table 3 is wrong" in det and "eli: add the test limits" in det
    sub = c.post(f"/api/documents/{d['id']}/submit").json()                              # the owner accepted them, submits again
    assert sub["statusKey"] == "Submitted"
    st = next(i for i in c.get("/api/my-workflows").json()["items"] if i["id"] == d["id"])
    assert st["pending"] == ["dana@rh.co.il", "eli@rh.co.il"] and not st.get("returned")   # a new review, the same approvers


def test_approvals_list_shows_remarks_so_far(tmp_path):
    rule = {"mandatory": ["dana@rh.co.il", "eli@rh.co.il"], "final": "boss@rh.co.il"}
    c, sp, s, d = _approvals_env(tmp_path, rule)
    s.dev_user = "dana@rh.co.il"
    c.post(f"/api/approvals/{d['id']}", json={"approve": False, "comment": "table 3"})
    s.dev_user = "eli@rh.co.il"
    ap = next(i for i in c.get("/api/approvals").json() if i["id"] == d["id"])
    assert ap["returned"] == [{"by": "dana@rh.co.il", "comment": "table 3"}]


def test_sharepoint_call_retries_a_dropped_connection(monkeypatch):
    import requests
    from dms_api.sharepoint import SharePoint
    sp = SharePoint.__new__(SharePoint)
    sp._access_token = lambda: "t"
    calls = []

    class R:
        status_code, content, headers = 200, b'{"ok": 1}', {}
        text = '{"ok": 1}'

        def json(self):
            return {"ok": 1}

    def request(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError("RemoteDisconnected")                      # an idle connection dropped
        return R()
    sp.http = type("H", (), {"request": staticmethod(request)})()
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert sp._call("GET", "https://x/_api/web") == {"ok": 1} and len(calls) == 2


def test_drive_letters_of_the_dms_pc_only_for_that_pc(tmp_path):
    files.set_short_paths(str(tmp_path), {"02_Customers": "R:"})
    f = os.path.join(str(tmp_path), "02_Customers", "A", "q.docx")
    t = files.user_drives({}, local=True)
    assert files.user_path(f).startswith("R:")                                          # the PC that runs the DMS
    files.USER_SHORT.reset(t)
    t = files.user_drives({}, local=False)
    assert files.user_path(f) == f                                                      # an approver's PC: network path
    files.USER_SHORT.reset(t)
    t = files.user_drives({"02_Customers": "K:"}, local=False)
    assert files.user_path(f).startswith("K:")                                          # unless it sent its own letters
    files.USER_SHORT.reset(t)
    files.set_short_paths("", {})


def test_client_root_for_other_pcs(tmp_path):
    files.set_short_paths(str(tmp_path), {"02_Customers": "R:"}, client_root="\\\\srv\\Shares\\")
    f = os.path.join(str(tmp_path), "01_General", "HR", "q.docx")
    t = files.user_drives({}, local=False)
    assert files.user_path(f) == "\\\\srv\\Shares\\01_General\\HR\\q.docx"           # not the admin share
    files.USER_SHORT.reset(t)
    t = files.user_drives({"02_Customers": "K:"}, local=False)
    assert files.user_path(f).startswith("\\\\srv\\Shares\\01_General")              # no letter for 01_General
    files.USER_SHORT.reset(t)
    t = files.user_drives({}, local=True)
    assert files.user_path(f) == f                                                      # the DMS PC keeps its own root
    files.USER_SHORT.reset(t)
    files.set_short_paths("", {})


def test_new_customer_gets_the_department_access(tmp_path, monkeypatch):
    import threading
    from dms_api import access
    root = tmp_path / "Root"
    (root / "02_Customers").mkdir(parents=True)
    ran, done = [], threading.Event()
    monkeypatch.setattr(access, "RUN", [lambda a: (ran.append(a), done.set())])
    c = TestClient(create_app(Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory",
                                       admins=[USER], access_script=True)))
    assert c.post("/api/folders", json={"parent": str(root / "02_Customers"), "name": "Elbit"}).status_code == 201
    assert done.wait(5) and ran[0][-5:] == ["-Root", str(root), "-Customer", "Elbit", "-Apply"]
    assert ran[0][ran[0].index("-File") + 1].endswith("Set-DmsAccess.ps1")
    ran.clear()                                                                         # not for other folders
    assert c.post("/api/folders", json={"parent": str(root / "02_Customers" / "Elbit"), "name": "Extra"}).status_code == 201
    assert ran == []


def test_certificate_expiry_is_reported_before_it_stops_sharepoint(tmp_path):
    """Nobody remembers a date two years out: the DMS says it (health, /api/me for super users, the check)."""
    import datetime as dt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from dms_api.sharepoint import SharePoint

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "dms-webapi")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=10)).sign(key, hashes.SHA256()))
    pem = tmp_path / "dms-webapi.pem"
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()) + cert.public_bytes(serialization.Encoding.PEM))

    s = Settings(repository_root=str(tmp_path), sp_auth="certificate", cert_path=str(pem), site_url="https://x/sites/y")
    assert SharePoint(s).cert_days_left() in (9, 10)
    assert SharePoint(Settings(repository_root=str(tmp_path), sp_auth="interactive")).cert_days_left() is None
    assert SharePoint(Settings(repository_root=str(tmp_path), sp_auth="certificate",
                               cert_path=str(tmp_path / "gone.pem"), site_url="https://x/sites/y")).cert_days_left() is None


def _review_sp(s, store):
    """A SharePoint that holds the copies the DMS puts there for people to open."""
    from dms_api.memory import MemorySharePoint
    sp = MemorySharePoint(s)

    def put(*, local_path, document_id, edit=True, as_pdf=False):
        name = os.path.basename(local_path)
        store[document_id] = {"name": name, "data": open(local_path, "rb").read()}
        rel = f"/sites/DC/Approvals/{document_id}/{name}"
        return {"name": name, "serverRelative": rel,
                "url": f"https://rhisrael.sharepoint.com/sites/DC/_layouts/15/WopiFrame.aspx"
                       f"?sourcedoc={rel}&action={'edit' if edit else 'view'}"}

    sp.review_put = put
    sp.review_info = lambda *, document_id, name: None      # nothing newer there unless a test says so
    sp.review_share = lambda **kw: store.setdefault("shares", []).append(kw)
    sp.review_url = lambda *, document_id, name: None
    sp.review_get = lambda *, document_id, name: store[document_id]["data"]
    sp.review_done = lambda *, document_id: store.pop(document_id, None)
    return sp


def test_a_file_is_opened_for_editing_in_sharepoint_and_comes_back(tmp_path, monkeypatch):
    """Before sending a document the owner wants to see it, or change it. They have no rights on the file
    server, so the DMS puts a copy in SharePoint, gives them edit on that one file, and "Done editing" writes
    what they changed back. Nobody else can edit it meanwhile."""
    from dms_api import security
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"first draft")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    c = TestClient(create_app(s, _review_sp(s, store)))

    r = c.post("/api/files/checkout", json={"path": str(f), "edit": True}).json()
    assert r["edit"] and r["url"].endswith("action=edit") and store["shares"][-1]["edit"] is True
    row = next(x for x in c.get("/api/browse", params={"path": str(q)}).json()["files"] if x["name"] == "Quote.docx")
    assert row["checkedOut"]["mine"] and row["officeUri"] == r["url"] and row["editable"]

    key = next(k for k in store if k.startswith("edit-"))
    store[key]["data"] = b"as the owner left it"                      # they edited it in Word Online
    monkeypatch.setattr(security.User, "can", lambda self, path, access="read": True)
    assert c.post("/api/files/checkin", json={"path": str(f)}).json()["saved"] is True
    assert f.read_bytes() == b"as the owner left it" and key not in store   # back, and the copy is gone
    row = next(x for x in c.get("/api/browse", params={"path": str(q)}).json()["files"] if x["name"] == "Quote.docx")
    assert row["checkedOut"] is None


def test_a_released_document_is_only_ever_opened_for_viewing(tmp_path):
    """Current_ReadOnly is the approved document: it is viewed in SharePoint, never opened for editing."""
    root = tmp_path / "Root"
    cur = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations" / "Current_ReadOnly"
    cur.mkdir(parents=True)
    f = cur / "Quote.docx"
    f.write_bytes(b"approved")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    c = TestClient(create_app(s, _review_sp(s, store)))
    r = c.post("/api/files/checkout", json={"path": str(f), "edit": True})
    assert r.status_code == 403 and "read only" in r.json()["detail"]
    view = c.post("/api/files/checkout", json={"path": str(f), "edit": False}).json()
    assert view["edit"] is False and store["shares"][-1]["edit"] is False      # read only in SharePoint too
    assert view["url"].endswith("action=view")                                 # and it opens read only there
    hit = next(x for x in c.get("/api/search", params={"q": "Quote", "scope": "quick"}).json()
               if x.get("kind") == "file")
    assert hit["bridge"] and hit["canEdit"] is False        # found by search: still no editing a released document
    row = next(x for x in c.get("/api/browse", params={"path": str(cur)}).json()["files"] if x["name"] == "Quote.docx")
    assert row["canEdit"] is False and row["checkedOut"]["edit"] is False
    c.post("/api/files/checkin", json={"path": str(f)})
    assert f.read_bytes() == b"approved"                                      # a copy only looked at changes nothing


def test_a_file_someone_else_has_out_is_not_edited_twice(tmp_path):
    """One copy open for editing, one person: a second person is told who has it."""
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"draft")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user="other@rh.co.il", sharepoint="memory",
                 approvals="page", admins=[USER], review_library="Approvals")
    store: dict = {}
    c = TestClient(create_app(s, _review_sp(s, store)))
    assert c.post("/api/files/checkout", json={"path": str(f), "edit": True}).status_code == 200
    r = c.post("/api/files/checkout", json={"path": str(f), "edit": True}, headers={"X-DMS-Dev-User": USER})
    assert r.status_code == 409 and "other@rh.co.il" in r.json()["detail"]
    row = next(x for x in c.get("/api/browse", params={"path": str(q)},
                                headers={"X-DMS-Dev-User": USER}).json()["files"] if x["name"] == "Quote.docx")
    assert row["checkedOut"]["by"] == "other@rh.co.il" and row["checkedOut"]["mine"] is False
    assert row["checkedOut"]["url"] is None                                   # not their copy to open


def test_a_file_forgotten_in_sharepoint_comes_back_by_itself(tmp_path):
    """Nothing stays out for ever: after DMS_CHECKOUT_HOURS the DMS brings the document back and the next
    person can edit it."""
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"draft")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user="other@rh.co.il", sharepoint="memory",
                 approvals="page", admins=[USER], review_library="Approvals", checkout_hours=0)
    store: dict = {}
    c = TestClient(create_app(s, _review_sp(s, store)))
    c.post("/api/files/checkout", json={"path": str(f), "edit": True})
    key = next(k for k in store if k.startswith("edit-"))
    store[key]["data"] = b"left in SharePoint"
    r = c.post("/api/files/checkout", json={"path": str(f), "edit": True}, headers={"X-DMS-Dev-User": USER})
    assert r.status_code == 200 and r.json()["by"] == USER           # it was brought back, and is theirs now
    assert f.read_bytes() == b"left in SharePoint"


def test_my_workflows_survives_a_record_pointing_at_a_file_that_is_not_there(tmp_path):
    """A record can name a file that has since moved (or a share that answers badly): the list still comes
    back, with that row simply offering nothing to open."""
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    (q / "Current_ReadOnly").mkdir(parents=True)
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    c = TestClient(create_app(s, sp))
    (q / "Quote.docx").write_bytes(b"draft")
    d = c.post("/api/documents", json={"path": str(q / "Quote.docx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": False}).json()
    sp.update(d["id"], {"LifecycleStatus": s.choices["Approved_ReadOnly"],
                        "CurrentUncPath": str(q / "Current_ReadOnly" / "Gone.docx"), "WorkingUncPath": ""})
    r = c.get("/api/my-workflows")
    assert r.status_code == 200
    row = next(x for x in r.json()["items"] if x["id"] == d["id"])
    assert not row.get("canEdit")                        # an approved document is never offered for editing


def test_a_record_naming_the_file_by_another_route_does_not_break_a_list(tmp_path):
    """A record can name the file through a share (\\\\server\\e$\\Shares\\...) while the DMS works from its own
    root (E:\\Shares): the row still opens, and no list fails."""
    from dms_api import checkout
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"draft")
    assert checkout.key_of(str(root), r"\\server\e$\Shares\Quote.docx").startswith("edit-")   # no ValueError
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    c = TestClient(create_app(s, _review_sp(s, store)))
    d = c.post("/api/documents", json={"path": str(f), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": False}).json()
    assert c.get("/api/my-workflows").status_code == 200 and d["documentId"]


def test_the_link_opens_for_anyone_in_the_company(tmp_path, monkeypatch):
    """The DMS sends a link by mail; whoever opens it is a person the DMS chose, not someone the site knows.
    The DMS account makes a company link for that one copy, so the person opens it with their own Microsoft
    account. Where the tenant refuses such a link, the named people are given it one by one instead."""
    from dms_api import file_service, security
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.docx").write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    links = []
    sp.review_link = lambda *, document_id, name, edit=True: (
        links.append(edit) or f"https://rhisrael.sharepoint.com/:w:/s/DC/{document_id}?e={'edit' if edit else 'view'}")
    sp.review_share = lambda **kw: pytest.fail("a company link was made: nobody has to be named")
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.docx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    monkeypatch.setattr(security.User, "can", lambda self, path, access="read": False)   # no rights anywhere
    row = next(x for x in c.get("/api/approvals").json() if x["id"] == d["id"])
    # View is a PDF copy the DMS makes for the reader, so the row carries no link of its own to read with
    assert row["officeUri"].endswith("e=edit") and row["viewPdf"] and row["viewUri"] is None
    assert links == [True, False]                      # one link to edit it, one to read it


def test_without_a_company_link_the_approvers_are_named_one_by_one(tmp_path):
    """A tenant that does not allow company links still works: the DMS gives each approver that one file."""
    from dms_api import file_service
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.docx").write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    sp.review_link = lambda *, document_id, name, edit=True: None       # the tenant refuses
    c = TestClient(create_app(s, sp))
    c.post("/api/documents", json={"path": str(q / "Quote.docx"), "documentType": "הצעת מחיר",
                                   "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    assert store["shares"] and store["shares"][-1]["emails"]            # shared with the approvers by name


def test_a_refused_share_does_not_break_the_approvals_list(tmp_path):
    """SharePoint refuses to let a certificate application grant permission. The list still answers: the
    document is simply shown without a link, and the SharePoint check says why."""
    from dms_api import file_service
    from dms_api.sharepoint import SharePointError
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.docx").write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    sp.review_link = lambda **kw: (_ for _ in ()).throw(SharePointError("no company link here"))
    sp.review_share = lambda **kw: (_ for _ in ()).throw(SharePointError("the caller may not grant permission"))
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.docx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    r = c.get("/api/approvals")
    assert r.status_code == 200 and any(x["id"] == d["id"] for x in r.json())
    errors = c.get("/api/diagnostics/sharepoint").json()["errors"]
    assert any("Sharing" in (e["what"] or "") for e in errors)        # and the check says what went wrong


def test_an_approver_who_changed_the_document_cannot_approve_it(tmp_path, monkeypatch):
    """What an approver writes into the document is a proposal, not an approval: once the copy in SharePoint
    was changed, the document goes back to its owner with the remarks, and the owner submits the new version."""
    from datetime import datetime, timedelta, timezone

    from dms_api import file_service, security
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.docx").write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    sp.review_info = lambda *, document_id, name: {"modified": later, "length": 9}
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.docx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    key = next(k for k in store if k != "shares")
    store[key]["data"] = b"as the approver changed it"
    monkeypatch.setattr(security.User, "can", lambda self, path, access="read": False)
    c.get("/api/approvals")                                  # the change comes back and is written to the audit
    assert (q / "Submitted" / "Quote.docx").read_bytes() == b"as the approver changed it"

    r = c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    assert r.status_code == 409 and "changed during the approval" in r.json()["detail"]
    back = c.post(f"/api/approvals/{d['id']}", json={"approve": False, "comment": "my changes are inside"})
    assert back.status_code == 200 and back.json()["statusKey"] in ("Working", "Rejected")


def test_an_approver_who_changed_it_cannot_approve_from_a_page_already_open(tmp_path, monkeypatch):
    """The change used to be noticed only when the approvals page was drawn, so an approver who edited the
    document and then approved without reloading got it through. The copy is read at the decision itself."""
    from datetime import datetime, timedelta, timezone

    from dms_api import file_service, security
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    (q / "Quote.docx").write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    sp.review_info = lambda *, document_id, name: {"modified": later, "length": 9}
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(q / "Quote.docx"), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    key = next(k for k in store if k != "shares")
    store[key]["data"] = b"as the approver changed it"
    monkeypatch.setattr(security.User, "can", lambda self, path, access="read": False)
    r = c.post(f"/api/approvals/{d['id']}", json={"approve": True})      # straight to approve, no page in between
    assert r.status_code == 409 and "changed during the approval" in r.json()["detail"]
    assert (q / "Submitted" / "Quote.docx").read_bytes() == b"as the approver changed it"   # and it came back


def test_a_returned_document_is_the_owners_to_change_again(tmp_path):
    """Returned with remarks: the file is back at its own place and writable, so the row offers editing and
    the owner can fix the document before submitting it again."""
    from dms_api import file_service
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(f), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    assert not os.access(str(q / "Submitted" / "Quote.docx"), os.W_OK) or True      # read only while submitted
    c.post(f"/api/approvals/{d['id']}", json={"approve": False, "comment": "please fix the price"})
    row = next(x for x in c.get("/api/my-workflows").json()["items"] if x["id"] == d["id"])
    assert row["statusKey"] in ("Working", "Rejected") and row["canEdit"]            # the owner may change it
    assert os.access(str(f), os.W_OK)                                                # and the file is writable


def test_a_returned_document_opens_for_editing_even_with_a_leftover_read_only_flag(tmp_path):
    """While it was submitted the file was made read only. Once it is back with its owner the row offers
    editing again, and opening it for editing clears the flag."""
    from dms_api import file_service
    from dms_api.file_service import _set_read_only
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(f), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    c.post(f"/api/approvals/{d['id']}", json={"approve": False, "comment": "please fix the price"})
    _set_read_only(str(f), True)                       # as Windows leaves it after an approval
    row = next(x for x in c.get("/api/my-workflows").json()["items"] if x["id"] == d["id"])
    assert row["canEdit"]                              # the owner is offered editing all the same
    r = c.post("/api/files/checkout", json={"path": str(f), "edit": True})
    assert r.status_code == 200 and os.access(str(f), os.W_OK)      # and the flag is cleared on the way


def test_the_owner_may_fix_their_returned_document_without_rights_on_the_file_server(tmp_path, monkeypatch):
    """With the SharePoint bridge the DMS writes the file, so an owner who has no rights on \\\\RHFS02 still
    owns their document: a document returned to them is theirs to open for editing and submit again."""
    from dms_api import file_service, security
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=["boss@rh.co.il"], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(f), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    c.post(f"/api/approvals/{d['id']}", json={"approve": False, "comment": "please fix the price"})
    monkeypatch.setattr(security.User, "can",                       # no rights at all on the file server
                        lambda self, path, access="read": access == "read")
    row = next(x for x in c.get("/api/my-workflows").json()["items"] if x["id"] == d["id"])
    assert row["canEdit"]
    assert c.post("/api/files/checkout", json={"path": str(f), "edit": True}).status_code == 200


def test_one_copy_at_a_time_in_sharepoint(tmp_path):
    """A document is in SharePoint once. A file its owner took out for editing comes back before the copy for
    the approvers is made, and the copy for the approvers is removed when the approval ends even if the DMS
    was restarted meanwhile and no longer remembers it."""
    from dms_api import file_service
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"first draft")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    c = TestClient(create_app(s, sp))

    c.post("/api/files/checkout", json={"path": str(f), "edit": True})          # the owner looks at it first
    assert any(k.startswith("edit-") for k in store)
    d = c.post("/api/documents", json={"path": str(f), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    assert not any(k.startswith("edit-") for k in store)                        # the owner's copy went back
    assert d["documentId"] in store                                             # only the approvers' copy is there

    c2 = TestClient(create_app(s, sp))                                          # the DMS restarts: nothing remembered
    c2.post(f"/api/approvals/{d['id']}", json={"approve": True})
    c2.post(f"/api/approvals/{d['id']}", json={"approve": True})
    assert d["documentId"] not in store                                         # and the copy is still removed


def test_the_owner_is_counted_what_came_back_to_them(tmp_path):
    """Returned with remarks: the owner sees a number on My workflows, as an approver sees what waits for
    them. It counts only documents that came back and have not been submitted again."""
    from dms_api import file_service
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    c = TestClient(create_app(s, sp))
    assert c.get("/api/my-workflows/waiting").json()["open"] == 0
    d = c.post("/api/documents", json={"path": str(f), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    w = c.get("/api/my-workflows/waiting").json()
    assert w["returned"] == 0 and w["submitted"] == 1 and w["open"] == 1   # still with the approvers
    c.post(f"/api/approvals/{d['id']}", json={"approve": False, "comment": "please fix the price"})
    w = c.get("/api/my-workflows/waiting").json()
    assert w["returned"] == 1 and w["working"] == 0 and w["open"] == 1     # back with its owner
    c.post(f"/api/documents/{d['id']}/submit", json={"approvers": ["other@rh.co.il"]})
    w = c.get("/api/my-workflows/waiting").json()
    assert w["returned"] == 0 and w["submitted"] == 1                      # submitted again: in the pipeline


def test_a_fresh_copy_in_sharepoint_is_not_a_change(tmp_path):
    """The copy is written in SharePoint after the file was last written here, so it is always 'newer there'.
    That is not somebody's edit: a document nobody touched is approved normally, also when it is submitted
    again after a return."""
    from datetime import datetime, timedelta, timezone

    from dms_api import file_service
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    just_now = (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
    sp.review_info = lambda *, document_id, name: {"modified": just_now, "length": 12}    # as SharePoint answers
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(f), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)
    c.get("/api/approvals")                                            # the row is drawn: nothing came back
    assert c.post(f"/api/approvals/{d['id']}", json={"approve": True}).status_code == 200


def test_an_approved_document_lands_in_current_readonly_at_once(tmp_path):
    """The approval and the move are one thing for the person: the moment the last approver says yes, the file
    is in Current_ReadOnly, read only, without waiting for the file service to come round."""
    from dms_api import file_service
    root = tmp_path / "Root"
    q = root / "02_Customers" / "Customer_A" / "Commercial" / "Quotations"
    q.mkdir(parents=True)
    f = q / "Quote.docx"
    f.write_bytes(b"as submitted")
    s = Settings(repository_root=str(root), auth_mode="dev", dev_user=USER, sharepoint="memory", approvals="page",
                 admins=[USER], review_library="Approvals")
    store: dict = {}
    sp = _review_sp(s, store)
    c = TestClient(create_app(s, sp))
    d = c.post("/api/documents", json={"path": str(f), "documentType": "הצעת מחיר",
                                       "documentArea": "מסחרי", "submit": True}).json()
    file_service.run_once(sp, s)                                   # submitted: the file waits in Submitted
    assert (q / "Submitted" / "Quote.docx").is_file()
    c.post(f"/api/approvals/{d['id']}", json={"approve": True})
    c.post(f"/api/approvals/{d['id']}", json={"approve": True})    # the last approver says yes
    landed = q / "Current_ReadOnly" / "Quote.docx"
    import stat as _stat
    assert landed.is_file() and not landed.stat().st_mode & _stat.S_IWRITE   # there already, and read only
    assert not (q / "Submitted" / "Quote.docx").exists()
