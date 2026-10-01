"""AI Insights: questions to RH's on-prem AI chat (https://chat.ai.rh-global.com).

The DMS service posts to <DMS_AI_URL><DMS_AI_PATH> (default /stream) the same request the chat page sends:
{"model": "org-chat", "messages": [...], "max_tokens": 4096}. The answer may come as one JSON, as a stream of
"data: {...}" lines (OpenAI-style chunks) or as plain text; all are read. A question about a repository file
uploads it like the page does (POST <DMS_AI_URL>/upload, field "file", cached by path and modification time)
and attaches its id; if the upload fails, the file's text (Word, Excel, PowerPoint, PDF, text) goes with the
question instead. Files are sent only after the user's AD read check, and only to the on-prem AI.
"""
from __future__ import annotations

import json
import os
import re

import logging

import requests

from . import doc_text
from .config import Settings

SYSTEM = {
    "EN": "You are AI Insights in RH's Documents Management System. Answer in English, briefly and precisely, "
          "based only on the attached document or knowledge. If the answer is not there, say so.",
    "HE": "אתה AI Insights במערכת ניהול המסמכים של RH. ענה בעברית, בקצרה ובדיוק, "
          "רק על סמך המסמך או הידע המצורפים. אם התשובה לא נמצאת שם, אמור זאת.",
}
log = logging.getLogger("dms_api.ai")
CHUNK_FIELDS = ("content", "delta", "text", "token", "chunk", "response", "answer", "output", "message", "data", "result")


class AiError(Exception):
    pass


class OpenWebUI:
    """The RH AI chat client (the name is kept for the rest of the service)."""

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.s = settings
        self.base = settings.ai_url.rstrip("/")
        self.http = session or requests.Session()
        self._files: dict[tuple[str, float], str] = {}       # (path, mtime) -> uploaded file id

    @property
    def enabled(self) -> bool:
        return bool(self.base)

    def _h(self) -> dict:
        h = {"Accept": "*/*", "Content-Type": "application/json"}
        if self.s.ai_token:                                   # on-prem: normally none
            h["Authorization"] = f"Bearer {self.s.ai_token}"
        return h

    def upload(self, path: str) -> str:
        """Upload a file like the chat page (📎); returns its id."""
        key = (os.path.normcase(path), os.path.getmtime(path))
        if key in self._files:
            return self._files[key]
        if os.path.getsize(path) > self.s.ai_max_file_mb * 1024 * 1024:
            raise AiError(f"The file is larger than {self.s.ai_max_file_mb} MB")
        h = {k: v for k, v in self._h().items() if k != "Content-Type"}
        with open(path, "rb") as f:
            r = self.http.post(self.base + "/" + self.s.ai_upload_path.lstrip("/"), headers=h,
                               files={"file": (os.path.basename(path), f)}, timeout=120)
        if r.status_code >= 400:
            raise AiError(f"Upload: {r.status_code} {r.text[:200]}")
        try:
            data = json.loads(r.text)
        except ValueError:
            data = r.text.strip().strip('"')
        if isinstance(data, list) and data:
            data = data[0]
        file_id = data if isinstance(data, str) else next(
            (str(x) for x in (data.get("id"), data.get("file_id"), (data.get("file") or {}).get("id") if isinstance(data.get("file"), dict) else None,
                              (data.get("data") or {}).get("id") if isinstance(data.get("data"), dict) else None) if x), "")
        if not file_id or len(file_id) > 200:
            raise AiError("Upload: no file id in the answer")
        self._files[key] = file_id
        return file_id

    def chat(self, messages: list[dict], timeout: int = 180, files: list[dict] | None = None) -> str:
        url = self.base + "/" + (self.s.ai_path or "/stream").lstrip("/")
        body = {"model": self.s.ai_model or "org-chat", "messages": messages, "max_tokens": self.s.ai_max_tokens}
        if files:
            body["files"] = files
        r = self.http.post(url, headers=self._h(), json=body, timeout=timeout)
        if r.status_code in (401, 403):
            raise AiError("AI: the RH AI asks for a sign-in token (DMS_AI_TOKEN in the service .env)")
        if r.status_code >= 400:
            raise AiError(f"AI: {r.status_code} {r.text[:200]}")
        answer = self.parse(r.text)
        if not answer.strip():
            raw = (r.text or "").strip()
            log.warning("RH AI answer not read (%s): %r", r.headers.get("content-type") if hasattr(r, "headers") else "", raw[:2000])
            raise AiError("AI: the RH AI sent an empty answer" if not raw else
                          f"AI: the DMS could not read the RH AI answer. It starts with: {raw[:300]}")
        return answer.strip()

    @staticmethod
    def parse(text: str) -> str:
        """One JSON answer, a stream of 'data: {...}' / JSON lines (any common chunk shape), or plain text."""
        def piece(obj, depth=0) -> str:
            if isinstance(obj, str):
                return obj
            if depth > 3 or not isinstance(obj, dict):
                return ""
            if str(obj.get("type") or obj.get("event") or "").lower() in ("start", "end", "done", "meta", "metadata", "sources", "ping", "usage"):
                return ""
            ch = (obj.get("choices") or [None])[0]
            if isinstance(ch, dict):
                return (ch.get("delta") or {}).get("content") or (ch.get("message") or {}).get("content") or ch.get("text") or ""
            for k in CHUNK_FIELDS:
                v = obj.get(k)
                if isinstance(v, str):
                    return v
                if isinstance(v, (dict, list)):
                    got = "".join(piece(x, depth + 1) for x in (v if isinstance(v, list) else [v]))
                    if got:
                        return got
            return ""
        body = (text or "").strip()
        try:
            whole = json.loads(body)
            if isinstance(whole, dict):
                return piece(whole) or body                     # a JSON answer that is not a chunk: keep it
            if isinstance(whole, list) and whole and all(isinstance(x, dict) for x in whole):
                return "".join(piece(x) for x in whole) or body
            return body if not isinstance(whole, str) else whole
        except ValueError:
            pass
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if lines and (any(ln.startswith("data:") for ln in lines) or all(ln.startswith("{") for ln in lines)):
            out = []
            for ln in lines:
                if ln.startswith("data:"):
                    ln = ln[5:].strip()
                elif ln.startswith(("event:", "id:", "retry:", ":")):
                    continue
                if not ln or ln == "[DONE]":
                    continue
                try:
                    out.append(piece(json.loads(ln)))
                except ValueError:
                    out.append(ln)
            return "".join(out)
        return body

    def ask(self, question: str, *, lang: str = "EN", file_path: str | None = None, context: str = "") -> dict:
        if not self.enabled:
            raise AiError("AI Insights is not configured")
        system = SYSTEM.get(lang, SYSTEM["EN"]) + (f"\n\n{context}" if context else "")
        files, user_text, attached = None, question, "uploaded"
        if file_path:
            name = os.path.basename(file_path)
            try:
                file_id = self.upload(file_path) if self.s.ai_upload_path else ""
            except (AiError, requests.RequestException, OSError):
                file_id = ""
            if file_id:                                       # as the page does: id + the attached-files line
                files = [{"type": "file", "id": file_id}]
                user_text = f"קבצים מצורפים (שמות הקבצים כפי שהמשתמש העלה): {name}.\n\n{question}"
            else:                                             # no upload: the text goes with the question
                attached = "text"
                text = doc_text.extract(file_path, self.s.ai_max_chars)
                if not text.strip():
                    raise AiError("AI: the file could not be uploaded and no text could be read from it")
                system += f"\n\nThe document's text ({name}):\n<<<\n{text}\n>>>"
        answer = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user_text}], files=files)
        return {"answer": answer, "sources": [], "model": self.s.ai_model or "org-chat", "file": attached if file_path else None}

    # ------------------------------------------------------------------ AI-assisted file finding
    def _complete(self, system: str, user: str, timeout: int = 25) -> str:
        return self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], timeout=timeout)

    @staticmethod
    def _json(text: str):
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)          # the model may wrap the JSON in prose or ``` fences
        if not m:
            raise AiError("The AI did not return JSON")
        return json.loads(m.group(0))

    def plan_search(self, question: str, customers: list[str], kinds: list[tuple[str, str]]) -> dict:
        """Turn a free-text request into search terms. Only folder names the user may see are offered."""
        system = ("You turn a request for a file in a company document repository into a JSON search plan. "
                  "Reply with JSON only: {\"terms\": [keywords that may appear in the file or folder name, in the "
                  "language of the names, 1-6 items], \"customer\": one of the customers or null, \"project\": a project "
                  "name or code mentioned or null, \"kind\": one of the kinds or null, \"extensions\": [like \".xlsx\"] or [], "
                  "\"latest\": true if the user wants the newest version}.\n"
                  f"Customers: {', '.join(customers[:300])}\nKinds: {', '.join(f'{k} ({en})' for k, en in kinds)}")
        plan = self._json(self._complete(system, question))
        if not isinstance(plan, dict):
            raise AiError("The AI returned an invalid plan")
        return plan

    def rank(self, question: str, candidates: list[dict], lang: str = "EN") -> list[dict]:
        """Pick and explain the best candidates. The AI sees only names and paths the user may already see."""
        listing = "\n".join(f"{i}. {c['relative']} | modified {c['modified'][:10]}"
                             + (f" | DMS {c['documentId']} {c['status']}" if c.get("documentId") else "") for i, c in enumerate(candidates))
        system = ("You help a user find files. From the numbered list, choose up to 8 files that best match the request, best first. "
                  "Reply with JSON only: [{\"i\": number, \"reason\": short reason}]. "
                  + ("Write the reasons in Hebrew." if lang == "HE" else "Write the reasons in English."))
        picks = self._json(self._complete(system, f"Request: {question}\n\nFiles:\n{listing}"))
        out = []
        for p in picks if isinstance(picks, list) else []:
            try:
                i = int(p.get("i"))
            except (TypeError, ValueError, AttributeError):
                continue
            if 0 <= i < len(candidates) and all(o["i"] != i for o in out):
                out.append({"i": i, "reason": str(p.get("reason") or "")[:300]})
        return out
