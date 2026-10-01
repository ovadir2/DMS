"""AI Insights - RH RAG tools on the AI portal (n8n), e.g. the QMS knowledge.

The tool page https://aiportal.ai.rh-global.com/webhook/tools?tool=qms is a chat page; its questions go to
POST <DMS_RAG_URL>/<tool>-chat (e.g. /webhook/qms-chat) with {question, sessionId, history}. The answer
comes back with its sources (display_id, display_section, snippet, filename). The DMS keeps the last turns
of each user's conversation per tool, so follow-up questions work like in the portal.
"""
from __future__ import annotations

import requests

from .config import Settings

ANSWER_FIELDS = ("answer", "output", "content", "text", "response", "message", "result")
HISTORY_TURNS = 6                                     # messages kept per user and tool


class RagError(Exception):
    pass


class RagTools:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.s = settings
        self.http = session or requests.Session()
        self.history: dict[tuple[str, str], list[dict]] = {}

    @property
    def base(self) -> str:
        url = self.s.rag_url.rstrip("/")
        return url[: -len("/tools")] if url.endswith("/tools") else url

    @property
    def enabled(self) -> bool:
        return bool(self.base and self.s.rag_tools)

    def page(self, tool: str) -> str:
        return f"{self.base}/tools?tool={tool}"

    def ask(self, tool: str, question: str, *, user: str = "", new: bool = False) -> dict:
        if tool not in self.s.rag_tools:
            raise RagError(f"Unknown RAG tool: {tool}")
        key = (user.lower(), tool)
        if new:
            self.history.pop(key, None)
        history = self.history.setdefault(key, [])
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.s.rag_token:                          # on-prem tools normally need none
            headers["Authorization"] = f"Bearer {self.s.rag_token}"
        body = {"question": question, "sessionId": f"dms-{user or 'user'}-{tool}", "history": list(history)}
        r = self.http.post(f"{self.base}/{tool}-chat", json=body, headers=headers, timeout=180)
        if r.status_code in (401, 403):
            raise RagError("The RAG tool asks for a sign-in token (DMS_RAG_TOKEN in the service .env)")
        if r.status_code >= 400:
            raise RagError(f"The RAG tool answered {r.status_code}: {r.text[:200]}")
        answer, sources = self._parse(r)
        history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        del history[:-HISTORY_TURNS]
        return {"answer": answer, "sources": sources, "tool": tool}

    @staticmethod
    def _parse(r) -> tuple[str, list[dict]]:
        try:
            data = r.json()
        except ValueError:
            text = (r.text or "").strip()
            if text.lower().startswith(("<!doctype", "<html")):
                raise RagError("The RAG tool returned a web page, not an answer") from None
            return text, []
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, str):
            return data.strip(), []
        if not isinstance(data, dict):
            raise RagError("Unexpected answer from the RAG tool")
        for k in ("json", "data", "body"):                       # n8n sometimes wraps the item
            if isinstance(data.get(k), dict) and not any(isinstance(data.get(f), str) for f in ANSWER_FIELDS):
                data = data[k]
        answer = next((data[k].strip() for k in ANSWER_FIELDS if isinstance(data.get(k), str) and data[k].strip()), "")
        if not answer:
            raise RagError("The RAG tool sent no answer text")
        sources = []
        for src in data.get("sources") or []:
            if not isinstance(src, dict):
                continue
            name = src.get("display_id") or src.get("filename") or ""
            if name:
                sources.append({"name": name, "section": (src.get("display_section") or "").strip(),
                                "file": src.get("filename") or "", "snippet": (src.get("snippet") or "")[:400],
                                "score": src.get("rerank_score")})
        return answer, sources
