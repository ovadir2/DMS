"""The API reference, written from the API itself.

Every endpoint of the DMS, its parameters and what it answers, taken from the routes as they are - so the
document cannot drift from the code the way a hand-written list does. It is written to docs\\14-API-Reference.md
by scripts\\New-DmsApiDocs.ps1 (python -m dms_api.apidocs), and the test keeps it in step.
"""
from __future__ import annotations

import os
import re

# The groups the reference is read in, in this order: who calls this part of the API and how it signs in.
GROUPS: list[tuple[str, str, str]] = [
    ("Signing in and what this person is", r"^/api/(me|client-config|health|options|areas|levels|customers|projects|people)",
     "The page asks these as soon as it opens. Windows authentication: the DMS answers as the person at the "
     "keyboard, and AD decides what they see."),
    ("The repository: folders and files", r"^/api/(browse|search|pathfinder|guide|classify|folders|items|files|blueprint)",
     "Everything the file list does. The user's own AD rights decide every one of them; the DMS writes with "
     "its own account but never in place of a right the person does not have."),
    ("Documents and the workflow", r"^/api/(documents|approvals|approver-rule|my-workflows|first-load|file-service|playground|exchange)",
     "Registering a document, submitting it, approving it, revising it, sharing it. The Document Register "
     "and the Control Audit in SharePoint are written as each of these happens."),
    ("AI Insights", r"^/api/ai/",
     "Questions about a document or about the company's knowledge, asked of the RH AI portal. The DMS never "
     "sends a file the person may not read."),
    ("Diagnostics", r"^/api/diagnostics/",
     "Why the DMS answered as it did: open them in the browser. They answer for whoever is signed in and "
     "change nothing."),
    ("Pages of the repository (the page key)", r"^/api/kpi/",
     "A dashboard or a KPI page runs in a sandbox with an opaque origin: it cannot sign in, so the DMS gives "
     "the page a key of its own, good for the folder it was opened from and for a few hours. Reading only."),
    ("The machine API", r"^/api/v1/",
     "An application, not a person: a key (X-DMS-Api-Key, or Authorization: Bearer) that names what it may "
     "read and the AD account it acts as. The DMS answers it exactly what that account may see."),
    ("Office and links", r"^/api/o/|^/dms/go/",
     "What Office opens and what a DMS link points at. The token is the address; the path on the file "
     "server is never in it."),
    ("The page itself", r"^/dms/",
     "The DMS page, its logo and its icon."),
]
HIDE = ("/api/kpi/{rest:path}",                        # the browser's own preflight question
        "/api/openapi.json", "/dms/api-docs", "/dms/api-redoc")   # the document and the two readers of it
VERBS = ("GET", "POST", "PUT", "DELETE", "PROPFIND", "LOCK", "UNLOCK")


def _schema(app) -> dict:
    return app.openapi()


def _params(op: dict) -> list[str]:
    out = []
    for p in op.get("parameters") or []:
        kind = (p.get("schema") or {}).get("type") or "string"
        out.append(f"| `{p['name']}` | {p.get('in')} | {'yes' if p.get('required') else 'no'} | {kind} | "
                   f"{(p.get('description') or '').replace('|', '/')} |")
    body = (((op.get("requestBody") or {}).get("content") or {}))
    for media, spec in body.items():
        props = ((spec.get("schema") or {}).get("properties") or {})
        required = set(((spec.get("schema") or {}).get("required") or []))
        for name, field in props.items():
            kind = field.get("type") or ("file" if field.get("format") == "binary" else "object")
            out.append(f"| `{name}` | {media.split('/')[-1]} | {'yes' if name in required else 'no'} | {kind} | "
                       f"{(field.get('description') or '').replace('|', '/')} |")
        if not props and spec.get("schema"):
            out.append(f"| _body_ | {media} | yes | object | {(spec['schema'].get('title') or '').replace('|', '/')} |")
    return out


def markdown(app, version: str = "") -> str:
    """The whole reference, as the file in docs\\ holds it."""
    api = _schema(app)
    seen: set[str] = set()
    lines = ["# 14 - API reference", "",
             "Every endpoint of the DMS, written from the API itself "
             "(`python -m dms_api.apidocs`, or `scripts\\New-DmsApiDocs.ps1`), so it cannot drift from the "
             "code. The machine API has a guide of its own in `13-Machine-API.md`, the KPI Builder in "
             "`15-KPI-Builder-Contract.md`, and the page key in `12-KPI-Integration.md`.", "",
             "**Swagger**: the same thing to try and to generate a client from - "
             "`https://dms-pilot.rh.tech/dms/api-docs` (Swagger UI), `/dms/api-redoc` (ReDoc), and the "
             "OpenAPI document itself at `/api/openapi.json`. A copy of the document is in the repository "
             "as `dms-openapi.json`, for a client generated without reaching the server.", ""]
    if version:
        lines += [f"Written from DMS {version}.", ""]
    lines += ["## How a caller is known", "",
              "| | How it signs in | What it may do |",
              "| --- | --- | --- |",
              "| A person on the page | Windows authentication (IIS), the browser's own sign-in | whatever AD gives that person, and nothing else |",
              "| A page of the repository | `?t=<page key>`, minted when the page is opened | read the folder it was opened from |",
              "| An application | `X-DMS-Api-Key: <key>` or `Authorization: Bearer <key>` | the key's scopes, as the AD account the key acts as |", ""]
    for title, pattern, blurb in GROUPS:
        rows = []
        for path, ops in sorted(api["paths"].items()):
            if path in HIDE or path in seen or not re.search(pattern, path):
                continue
            seen.add(path)
            rows.append((path, ops))
        if not rows:
            continue
        lines += [f"## {title}", "", blurb, ""]
        for path, ops in rows:
            for verb in VERBS:
                op = ops.get(verb.lower())
                if not op:
                    continue
                doc = (op.get("description") or op.get("summary") or "").strip()
                head, _, rest = doc.partition("\n\n")
                lines += [f"### {verb} {path}", ""]
                lines += [" ".join(head.split()) or "_(no description)_", ""]
                if rest.strip():
                    lines += ["\n".join(l.rstrip() for l in rest.strip().splitlines()), ""]
                rows_p = _params(op)
                if rows_p:
                    lines += ["| Parameter | In | Required | Type | |", "| --- | --- | --- | --- | --- |"]
                    lines += rows_p
                    lines += [""]
    # Routes the schema does not carry (an image, a file answer): they are endpoints all the same.
    for route in app.routes:
        path, end = getattr(route, "path", ""), getattr(route, "endpoint", None)
        if not path.startswith(("/api", "/dms")) or end is None or path in HIDE or path in api["paths"]:
            continue
        if "## The rest" not in lines:
            lines += ["## The rest", "",
                      "Answers that are not JSON - an image, a file, a page - and so are not in the "
                      "machine-readable schema.", ""]
        for verb in sorted(getattr(route, "methods", []) or []):
            if verb not in VERBS or f"### {verb} {path}\n" in "\n".join(lines):
                continue
            lines += [f"### {verb} {path}", "",
                      " ".join(((end.__doc__ or "").strip().split("\n\n")[0]).split()) or "_(no description)_", ""]
    return "\n".join(lines).rstrip() + "\n"


def openapi_json(app) -> str:
    """The OpenAPI document as the repository keeps it (docs\\dms-openapi.json): the version without the
    build, so the file changes when the API does and not at every commit."""
    import json
    from .openapi import spec
    return json.dumps(spec(app, "1.1"), indent=1, ensure_ascii=False, sort_keys=True) + "\n"


if __name__ == "__main__":   # pragma: no cover - the writer, run by the script
    import sys
    from .config import Settings
    import subprocess
    from .main import create_app
    app = create_app(Settings(repository_root=os.environ.get("DMS_REPOSITORY_ROOT", "") or ".",
                              auth_mode="dev", sharepoint="memory"))
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        where = subprocess.run(["git", "-C", here, "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        where = ""
    if "--openapi" in sys.argv:
        sys.stdout.write(openapi_json(app))
    else:
        sys.stdout.write(markdown(app, where))
