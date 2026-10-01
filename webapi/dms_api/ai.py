"""AI Insights: questions to RH's on-prem RAG LLM (Open WebUI, https://chat.ai.rh-global.com).

The DMS service calls the Open WebUI API with its own service token:
- a question about one repository file: the file is uploaded to Open WebUI (cached by path and
  modification time) and attached to the chat, so the answer is grounded in that file;
- a question to the company knowledge bases (DMS_AI_KNOWLEDGE_IDS), with RAG sources.
Files are sent only after the user's AD read check, and only to the on-prem LLM.
"""
from __future__ import annotations

import os
import time

import requests

from .config import Settings

SYSTEM = {
    "EN": "You are AI Insights in RH's Documents Management System. Answer in English, briefly and precisely, "
          "based only on the attached document or knowledge. If the answer is not there, say so.",
    "HE": "אתה AI Insights במערכת ניהול המסמכים של RH. ענה בעברית, בקצרה ובדיוק, "
          "רק על סמך המסמך או הידע המצורפים. אם התשובה לא נמצאת שם, אמור זאת.",
}


class AiError(Exception):
    pass


class OpenWebUI:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.s = settings
        self.base = settings.ai_url.rstrip("/")
        self.http = session or requests.Session()
        self._files: dict[tuple[str, float], str] = {}       # (path, mtime) -> Open WebUI file id

    @property
    def enabled(self) -> bool:
        return bool(self.base and self.s.ai_token and self.s.ai_model)

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.s.ai_token}", "Accept": "application/json"}

    def _check(self, r: requests.Response, what: str) -> dict:
        if r.status_code >= 400:
            raise AiError(f"{what}: {r.status_code} {r.text[:200]}")
        return r.json()

    def upload(self, path: str) -> str:
        key = (os.path.normcase(path), os.path.getmtime(path))
        if key in self._files:
            return self._files[key]
        if os.path.getsize(path) > self.s.ai_max_file_mb * 1024 * 1024:
            raise AiError(f"The file is larger than {self.s.ai_max_file_mb} MB")
        with open(path, "rb") as f:
            r = self.http.post(f"{self.base}/api/v1/files/", headers=self._h(),
                               files={"file": (os.path.basename(path), f)}, timeout=120)
        file_id = self._check(r, "Upload to AI")["id"]
        self._wait_processed(file_id)
        self._files[key] = file_id
        return file_id

    def _wait_processed(self, file_id: str, seconds: int = 90) -> None:
        """Newer Open WebUI versions extract the text in the background; older ones return when done."""
        end = time.time() + seconds
        while time.time() < end:
            r = self.http.get(f"{self.base}/api/v1/files/{file_id}/process/status", headers=self._h(), timeout=30)
            if r.status_code == 404:
                return                                          # no status endpoint: processed on upload
            status = (r.json() or {}).get("status") if r.content else None
            if status in (None, "completed"):
                return
            if status == "failed":
                raise AiError("The AI could not read this file")
            time.sleep(2)
        raise AiError("The AI is still reading the file, try again in a minute")

    def ask(self, question: str, *, lang: str = "EN", file_path: str | None = None, context: str = "",
            use_knowledge: bool = True) -> dict:
        if not self.enabled:
            raise AiError("AI Insights is not configured")
        files = []
        if file_path:
            files.append({"type": "file", "id": self.upload(file_path)})
        elif use_knowledge:
            files += [{"type": "collection", "id": k} for k in self.s.ai_knowledge_ids]
        messages = [{"role": "system", "content": SYSTEM.get(lang, SYSTEM["EN"]) + (f"\n\n{context}" if context else "")},
                    {"role": "user", "content": question}]
        body = {"model": self.s.ai_model, "messages": messages, "stream": False}
        if files:
            body["files"] = files
        r = self.http.post(f"{self.base}/api/chat/completions", headers={**self._h(), "Content-Type": "application/json"},
                           json=body, timeout=180)
        data = self._check(r, "AI")
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise AiError("Unexpected answer from the AI") from e
        sources = []
        for src in data.get("sources") or []:
            name = (src.get("source") or {}).get("name") or ((src.get("metadata") or [{}])[0] or {}).get("name")
            if name and name not in sources:
                sources.append(name)
        return {"answer": answer, "sources": sources, "model": self.s.ai_model}
