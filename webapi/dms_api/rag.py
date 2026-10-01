"""AI Insights - RH RAG tools on the AI portal (n8n webhook), e.g. the QMS knowledge:
https://aiportal.ai.rh-global.com/webhook/tools?tool=qms

The DMS service sends the question to <DMS_RAG_URL>?tool=<tool> as
GET (default) query parameters tool, question, chatInput, query, sessionId, lang and user, or with
DMS_RAG_METHOD=POST a JSON body from DMS_RAG_BODY, and reads the answer
from the first of: output, answer, text, response, message (also inside a list), or plain text.
"""
from __future__ import annotations

import json

import requests

from .config import Settings

ANSWER_FIELDS = ("output", "answer", "text", "response", "message", "result")


class RagError(Exception):
    pass


class RagTools:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.s = settings
        self.http = session or requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.s.rag_url and self.s.rag_tools)

    def page(self, tool: str) -> str:
        return f"{self.s.rag_url}?tool={tool}"

    def ask(self, tool: str, question: str, *, lang: str = "EN", user: str = "", session: str = "") -> dict:
        if tool not in self.s.rag_tools:
            raise RagError(f"Unknown RAG tool: {tool}")
        fill = {"tool": tool, "question": question, "session": session or user or "dms", "lang": lang, "user": user}
        template = json.loads(self.s.rag_body)
        body = {k: (v.format(**fill) if isinstance(v, str) else v) for k, v in template.items()}
        headers = {"Accept": "application/json"}
        if self.s.rag_token:                          # on-prem tools need none
            headers["Authorization"] = f"Bearer {self.s.rag_token}"
        params = {"tool": tool, "question": question, "chatInput": question, "query": question,
                  "sessionId": fill["session"], "lang": lang, "user": user}
        if self.s.rag_method == "POST":
            r = self.http.post(self.s.rag_url, params={"tool": tool}, json=body, headers=headers, timeout=180)
            if r.status_code in (404, 405):              # "not registered for POST": a GET webhook
                r = self.http.get(self.s.rag_url, params=params, headers=headers, timeout=180)
        else:
            r = self.http.get(self.s.rag_url, params=params, headers=headers, timeout=180)
        if r.status_code >= 400:
            raise RagError(f"The RAG tool answered {r.status_code}: {r.text[:200]}")
        if self._is_page(r):
            raise RagError("The RAG tool returned its web page, not an answer: the webhook needs another parameter name for the question")
        return {"answer": self._answer(r), "tool": tool}

    @staticmethod
    def _is_page(r) -> bool:
        ctype = (getattr(r, "headers", None) or {}).get("content-type", "")
        return "text/html" in ctype.lower() or (r.text or "").lstrip()[:15].lower().startswith(("<!doctype", "<html"))

    @staticmethod
    def _answer(r) -> str:
        try:
            data = r.json()
        except ValueError:
            return (r.text or "").strip()
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            for k in ANSWER_FIELDS:
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
                if isinstance(v, dict):
                    for k2 in ANSWER_FIELDS:
                        if isinstance(v.get(k2), str):
                            return v[k2].strip()
        if isinstance(data, str):
            return data.strip()
        return json.dumps(data, ensure_ascii=False)[:4000]
