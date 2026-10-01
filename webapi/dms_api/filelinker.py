"""File Linker: keep its links pointing at the documents after the DMS First loading.

WebAPI#1 (check):  is a path registered in File Linker?      DMS_FL_CHECK_URL   GET, {path} in the URL
WebAPI#2 (update): replace a registered path with a new one.  DMS_FL_UPDATE_URL  POST (or DMS_FL_UPDATE_METHOD)

Both are configured in .env, because File Linker is RH's own application:
  DMS_FL_CHECK_URL=https://filelinker/api/links/exists?path={path}
  DMS_FL_UPDATE_URL=https://filelinker/api/links/replace
  DMS_FL_UPDATE_BODY={"oldPath": "{old}", "newPath": "{new}"}      (JSON template, {old} / {new} are filled in)
  DMS_FL_REGISTERED_FIELD=registered       (the JSON field that says "registered"; empty = any 200 with a non-empty body)
  DMS_FL_AUTH=windows | bearer | none      (windows: the service's Windows login; bearer: DMS_FL_TOKEN)
A 404 from WebAPI#1 means "not registered".
"""
from __future__ import annotations

import json
from urllib.parse import quote

import requests

from .config import Settings


class FileLinkerError(Exception):
    pass


class FileLinker:
    def __init__(self, s: Settings, session: requests.Session | None = None):
        self.s = s
        self.http = session or requests.Session()
        if session is None and s.fl_auth == "windows":
            try:
                from requests_negotiate_sspi import HttpNegotiateAuth  # type: ignore[import-not-found]
                self.http.auth = HttpNegotiateAuth()
            except ImportError:
                pass

    @property
    def enabled(self) -> bool:
        return bool(self.s.fl_check_url and self.s.fl_update_url)

    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        if self.s.fl_auth == "bearer" and self.s.fl_token:
            h["Authorization"] = f"Bearer {self.s.fl_token}"
        return h

    def is_registered(self, path: str) -> bool:
        """WebAPI#1."""
        r = self.http.get(self.s.fl_check_url.replace("{path}", quote(path, safe="")), headers=self._headers(), timeout=30)
        if r.status_code == 404:
            return False
        if r.status_code >= 400:
            raise FileLinkerError(f"WebAPI#1 {r.status_code}: {r.text[:200]}")
        if not r.content:
            return False
        try:
            body = r.json()
        except ValueError:
            return r.text.strip().lower() in ("true", "1", "yes")
        if self.s.fl_registered_field and isinstance(body, dict):
            return bool(body.get(self.s.fl_registered_field))
        return bool(body)

    def replace(self, old: str, new: str) -> None:
        """WebAPI#2."""
        template = self.s.fl_update_body or '{"oldPath": "{old}", "newPath": "{new}"}'
        esc = lambda v: json.dumps(v)[1:-1]  # noqa: E731 - JSON-escape inside the template's quotes
        body = json.loads(template.replace("{old}", esc(old)).replace("{new}", esc(new)))
        r = self.http.request(self.s.fl_update_method, self.s.fl_update_url, json=body,
                              headers={**self._headers(), "Content-Type": "application/json"}, timeout=30)
        if r.status_code >= 400:
            raise FileLinkerError(f"WebAPI#2 {r.status_code}: {r.text[:200]}")
