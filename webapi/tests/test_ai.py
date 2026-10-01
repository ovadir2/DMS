"""The RH AI chat client (https://chat.ai.rh-global.com/stream), with the HTTP session mocked."""
from __future__ import annotations

import json
import zipfile

from dms_api.ai import AiError, OpenWebUI
from dms_api.config import Settings


class Resp:
    def __init__(self, text, status=200):
        self.status_code, self.text = status, text if isinstance(text, str) else json.dumps(text)


class ChatSession:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def post(self, url, headers=None, json=None, files=None, timeout=None):
        self.calls.append((url, headers, json if files is None else {"upload": files["file"][0]}))
        a = self.answers.pop(0)
        return a if isinstance(a, Resp) else Resp(a)


S = dict(ai_url="https://chat.ai.rh-global.com")


def test_request_is_the_chat_page_request():
    sess = ChatSession([{"choices": [{"message": {"content": "Hello"}}]}])
    r = OpenWebUI(Settings(**S), sess).ask("hi")
    url, headers, body = sess.calls[0]
    assert url == "https://chat.ai.rh-global.com/stream" and "Authorization" not in headers
    assert body["model"] == "org-chat" and body["max_tokens"] == 4096 and body["messages"][-1] == {"role": "user", "content": "hi"}
    assert r["answer"] == "Hello"


def test_streamed_and_plain_answers():
    sse = 'data: {"choices":[{"delta":{"content":"של"}}]}\n\ndata: {"choices":[{"delta":{"content":"ום"}}]}\n\ndata: [DONE]\n'
    assert OpenWebUI.parse(sse) == "שלום"
    assert OpenWebUI.parse('{"content":"a"}\n{"content":"b"}') == "ab"
    assert OpenWebUI.parse("just text") == "just text"
    assert OpenWebUI.parse('{"message":{"role":"assistant","content":"ok"}}') == "ok"


def test_question_about_a_file_sends_its_text(tmp_path):
    f = tmp_path / "QP-2.1.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:body><w:p><w:r><w:t>הודעות ללקוחות</w:t></w:r></w:p><w:p><w:r><w:t>מוצרים רפואיים</w:t></w:r></w:p></w:body></w:document>')
    sess = ChatSession([Resp("not found", 404), "סיכום"])                          # upload fails: the text goes instead
    r = OpenWebUI(Settings(**S), sess).ask("סכם", lang="HE", file_path=str(f), context="Document: QP-2.1.docx")
    assert r["file"] == "text"
    system = sess.calls[1][2]["messages"][0]["content"]
    assert "הודעות ללקוחות\nמוצרים רפואיים" in system and "Document: QP-2.1.docx" in system and r["answer"] == "סיכום"


def test_refusal_and_unreadable_file(tmp_path):
    sess = ChatSession([Resp("no", 401)])
    try:
        OpenWebUI(Settings(**S), sess).ask("hi")
        raise AssertionError("expected AiError")
    except AiError as e:
        assert "DMS_AI_TOKEN" in str(e)
    scan = tmp_path / "scan.png"
    scan.write_bytes(b"\x89PNG")
    try:
        OpenWebUI(Settings(**S), ChatSession([Resp("x", 500)])).ask("hi", file_path=str(scan))
        raise AssertionError("expected AiError")
    except AiError as e:
        assert "no text could be read" in str(e)


def test_plan_and_rank_parse_wrapped_json():
    sess = ChatSession(['Here is the plan:\n```json\n{"terms": ["FCT", "quote"], "customer": "Customer_A", "kind": "quotation"}\n```',
                        '[{"i": 1, "reason": "newest quote"}, {"i": 9, "reason": "out of range"}, {"i": 1, "reason": "dup"}, {"x": 0}]'])
    ai = OpenWebUI(Settings(**S), sess)
    plan = ai.plan_search("latest FCT quote for Customer_A", ["Customer_A"], [("quotation", "Quotation")])
    assert plan["terms"] == ["FCT", "quote"] and "Customer_A" in sess.calls[0][2]["messages"][0]["content"]
    cands = [{"relative": "a.xlsx", "modified": "2026-01-01"}, {"relative": "b.xlsx", "modified": "2026-09-01", "documentId": "DMS-1", "status": "x"}]
    assert ai.rank("q", cands, "HE") == [{"i": 1, "reason": "newest quote"}]
    assert "Hebrew" in sess.calls[1][2]["messages"][0]["content"]


def test_xlsx_and_pptx_text(tmp_path):
    from dms_api import doc_text
    x = tmp_path / "a.xlsx"
    with zipfile.ZipFile(x, "w") as z:
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Price</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                   '<row><c t="s"><v>0</v></c><c><v>120</v></c></row></sheetData></worksheet>')
    assert "Price\t120" in doc_text.extract(str(x))
    p = tmp_path / "a.pptx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:t>Kickoff</a:t></a:p></p:sld>')
    assert "[Slide 1]\nKickoff" in doc_text.extract(str(p))


def test_answer_in_the_language_of_the_question():
    from dms_api.main import answer_lang
    assert answer_lang("נהלי שינוע", "EN") == "HE"
    assert answer_lang("calibration procedure", "HE") == "EN"
    assert answer_lang("123?", "HE") == "HE" and answer_lang("123?", "EN") == "EN"


def test_file_is_uploaded_once_and_attached_like_the_page(tmp_path):
    f = tmp_path / "trade_execution_log.csv"
    f.write_text("a,b")
    sess = ChatSession([{"id": "c0131812"}, "first line: a,b", "again"])
    ai = OpenWebUI(Settings(**S), sess)
    r = ai.ask("show the first line", file_path=str(f))
    assert sess.calls[0][0] == "https://chat.ai.rh-global.com/upload" and sess.calls[0][2] == {"upload": "trade_execution_log.csv"}
    body = sess.calls[1][2]
    assert body["files"] == [{"type": "file", "id": "c0131812"}] and r["file"] == "uploaded"
    assert body["messages"][-1]["content"].startswith("קבצים מצורפים (שמות הקבצים כפי שהמשתמש העלה): trade_execution_log.csv.")
    ai.ask("again", file_path=str(f))
    assert len(sess.calls) == 3                                                    # no second upload
