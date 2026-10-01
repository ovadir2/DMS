"""Open WebUI payloads, with the HTTP session mocked."""
from __future__ import annotations

import json

from dms_api.ai import AiError, OpenWebUI
from dms_api.config import Settings


class Resp:
    def __init__(self, body, status=200):
        self.status_code, self._b = status, body
        self.content = json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        return self._b


class Session:
    def __init__(self):
        self.calls = []

    def post(self, url, headers=None, json=None, files=None, timeout=None):
        self.calls.append(("POST", url, json, files))
        if url.endswith("/api/v1/files/"):
            return Resp({"id": "f-1"})
        return Resp({"choices": [{"message": {"content": "The quote is valid 30 days."}}],
                     "sources": [{"source": {"name": "CRU 4 FCT Quote_Rev1.xlsx"}}]})

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None, None))
        return Resp({"status": "completed"})


def test_ask_about_a_file_uploads_once(tmp_path):
    f = tmp_path / "CRU 4 FCT Quote_Rev1.xlsx"
    f.write_bytes(b"x")
    s = Settings(ai_url="https://chat.ai.rh-global.com/", ai_token="t", ai_model="rh-rag", ai_knowledge_ids=["kb1"])
    sess = Session()
    ai = OpenWebUI(s, sess)
    r = ai.ask("Validity?", lang="HE", file_path=str(f), context="Document: x")
    assert r == {"answer": "The quote is valid 30 days.", "sources": ["CRU 4 FCT Quote_Rev1.xlsx"], "model": "rh-rag"}
    up, status, chat = sess.calls
    assert up[1] == "https://chat.ai.rh-global.com/api/v1/files/" and status[1].endswith("/f-1/process/status")
    assert chat[1].endswith("/api/chat/completions") and chat[2]["files"] == [{"type": "file", "id": "f-1"}]
    assert chat[2]["model"] == "rh-rag" and "בעברית" in chat[2]["messages"][0]["content"] and chat[2]["stream"] is False
    ai.ask("Again?", file_path=str(f))
    assert [c[1].rsplit("/", 2)[-1] for c in sess.calls[3:]] == ["completions"]       # cached, no second upload


def test_general_question_uses_knowledge(tmp_path):
    s = Settings(ai_url="https://chat.ai.rh-global.com", ai_token="t", ai_model="rh-rag", ai_knowledge_ids=["kb1", "kb2"])
    sess = Session()
    OpenWebUI(s, sess).ask("NDA policy?")
    assert sess.calls[0][2]["files"] == [{"type": "collection", "id": "kb1"}, {"type": "collection", "id": "kb2"}]


class ChatSession(Session):
    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)

    def post(self, url, headers=None, json=None, files=None, timeout=None):
        self.calls.append(("POST", url, json, files))
        return Resp({"choices": [{"message": {"content": self.answers.pop(0)}}]})


def test_plan_and_rank_parse_wrapped_json():
    s = Settings(ai_url="https://chat.ai.rh-global.com", ai_token="t", ai_model="rh-rag")
    sess = ChatSession(['Here is the plan:\n```json\n{"terms": ["FCT", "quote"], "customer": "Customer_A", "kind": "quotation"}\n```',
                        '[{"i": 1, "reason": "newest quote"}, {"i": 9, "reason": "out of range"}, {"i": 1, "reason": "dup"}, {"x": 0}]'])
    ai = OpenWebUI(s, sess)
    plan = ai.plan_search("latest FCT quote for Customer_A", ["Customer_A"], [("quotation", "Quotation")])
    assert plan["terms"] == ["FCT", "quote"] and "Customer_A" in sess.calls[0][2]["messages"][0]["content"]
    cands = [{"relative": "a.xlsx", "modified": "2026-01-01"}, {"relative": "b.xlsx", "modified": "2026-09-01", "documentId": "DMS-1", "status": "x"}]
    assert ai.rank("q", cands, "HE") == [{"i": 1, "reason": "newest quote"}]
    assert "Hebrew" in sess.calls[1][2]["messages"][0]["content"]


def test_model_defaults_to_the_first_offered():
    class Models(Session):
        def get(self, url, headers=None, timeout=None):
            self.calls.append(("GET", url, None, None))
            return Resp({"data": [{"id": "rh-rag"}, {"id": "other"}]})
    http = Models()
    ai = OpenWebUI(Settings(ai_url="https://chat.ai.rh-global.com", ai_token="t"), http)
    assert ai.enabled
    ai.ask("hello")
    assert http.calls[0][1].endswith("/api/models") and http.calls[1][2]["model"] == "rh-rag"


def test_no_token_sends_no_authorization_and_explains_a_refusal():
    class Refuse(Session):
        def post(self, url, headers=None, json=None, files=None, timeout=None):
            self.calls.append(("POST", url, headers, None))
            return Resp({"detail": "Not authenticated"}, 401)
    http = Refuse()
    ai = OpenWebUI(Settings(ai_url="https://chat.ai.rh-global.com", ai_model="m"), http)
    assert ai.enabled
    try:
        ai.ask("hi")
        raise AssertionError("expected AiError")
    except AiError as e:
        assert "DMS_AI_TOKEN" in str(e)
    assert "Authorization" not in http.calls[0][2]


def test_answer_in_the_language_of_the_question():
    from dms_api.main import answer_lang
    assert answer_lang("נהלי שינוע", "EN") == "HE"
    assert answer_lang("calibration procedure", "HE") == "EN"
    assert answer_lang("123?", "HE") == "HE" and answer_lang("123?", "EN") == "EN"
