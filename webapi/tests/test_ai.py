"""Open WebUI payloads, with the HTTP session mocked."""
from __future__ import annotations

import json

from dms_api.ai import OpenWebUI
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
