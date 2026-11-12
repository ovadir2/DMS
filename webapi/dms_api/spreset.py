"""Empty the SharePoint lists and libraries the pilot filled, with the DMS's own account.

No second sign-in and nothing to install: the DMS already talks to SharePoint with its certificate, so the
clearing goes the same way. The lists are emptied, never deleted - the columns, the views and the Approver
Matrix (which holds the rules, not the pilot's data) stay as they are.

    cd webapi
    .\\.venv\\Scripts\\python -m dms_api.spreset             # says what it would empty
    .\\.venv\\Scripts\\python -m dms_api.spreset --write     # does it
"""
from __future__ import annotations

import logging
from urllib.parse import quote, urlparse

from .sharepoint import AUDIT, DECISIONS, DELEGATIONS, NOTIFY, REGISTER, SharePoint, SharePointError

logger = logging.getLogger("dms_api.spreset")

# What the pilot wrote. The Approver Matrix is not here on purpose: those are the rules of the company.
LISTS = (REGISTER, AUDIT, DECISIONS, DELEGATIONS, NOTIFY)


def _items(sp: SharePoint, url: str) -> list[dict]:
    out: list[dict] = []
    page_url = f"{url}/items?$select=Id&$top=500"
    while page_url:
        page = sp._call("GET", page_url)          # noqa: SLF001 - this module is part of the DMS
        out.extend(page.get("value", []))
        page_url = page.get("odata.nextLink")
    return out


def _delete(sp: SharePoint, url: str) -> None:
    sp._call("POST", url, headers={"IF-MATCH": "*", "X-HTTP-Method": "DELETE"})   # noqa: SLF001


def clear_list(sp: SharePoint, rel: str, *, write: bool = False) -> dict:
    """One list of the control site, emptied item by item. Returns what was found and what was removed."""
    url = sp._list(rel)                                                            # noqa: SLF001
    try:
        items = _items(sp, url)
    except SharePointError as e:
        return {"list": rel, "found": 0, "removed": 0, "error": str(e)}
    removed, failed = 0, ""
    if write:
        for item in items:
            try:
                _delete(sp, f"{url}/items({item['Id']})")
                removed += 1
            except SharePointError as e:
                failed = str(e)
                break
    return {"list": rel, "found": len(items), "removed": removed, **({"error": failed} if failed else {})}


def clear_library(sp: SharePoint, site: str, title: str, *, write: bool = False) -> dict:
    """A document library of that site: every folder and every file in it, so the copies the DMS left for
    approving and for reading are gone. The library itself stays."""
    root = f"{urlparse(site).path.rstrip('/')}/{title}"
    base = f"{site}/_api/web/GetFolderByServerRelativePath(DecodedUrl='{quote(root, safe='/')}')"
    try:
        folders = sp._call("GET", f"{base}/Folders?$select=Name,ServerRelativeUrl").get("value", [])  # noqa: SLF001
        files = sp._call("GET", f"{base}/Files?$select=Name,ServerRelativeUrl").get("value", [])      # noqa: SLF001
    except SharePointError as e:
        return {"library": title, "found": 0, "removed": 0, "error": str(e)}
    inside = [f for f in folders if f.get("Name") not in ("Forms",)] + files
    removed, failed = 0, ""
    if write:
        for item in inside:
            kind = "GetFolderByServerRelativePath" if item in folders else "GetFileByServerRelativePath"
            try:
                _delete(sp, f"{site}/_api/web/{kind}(DecodedUrl='{quote(item['ServerRelativeUrl'], safe='/')}')")
                removed += 1
            except SharePointError as e:
                failed = str(e)
                break
    return {"library": title, "found": len(inside), "removed": removed, **({"error": failed} if failed else {})}


def run(sp: SharePoint, *, write: bool = False, libraries: tuple[str, ...] = ("Approvals", "Views"),
        exchange: bool = True) -> list[dict]:
    """Everything the pilot wrote in SharePoint: the lists of the control site, the two libraries where the
    DMS puts copies, and what was shared on the Exchange site."""
    out = [clear_list(sp, rel, write=write) for rel in LISTS]
    site = sp.review_site()
    for title in libraries:
        if title:
            out.append(clear_library(sp, site, title, write=write))
    if exchange and sp.s.ex_site_url:
        try:
            lists = sp._call("GET", f"{sp.s.ex_site_url}/_api/web/lists?$select=Title,BaseTemplate,Hidden"  # noqa: SLF001
                             ).get("value", [])
        except SharePointError as e:
            out.append({"library": sp.s.ex_site_url, "found": 0, "removed": 0, "error": str(e)})
            lists = []
        for one in lists:
            if one.get("BaseTemplate") == 101 and not one.get("Hidden") and one.get("Title") != "Site Assets":
                out.append(clear_library(sp, sp.s.ex_site_url, one["Title"], write=write))
    return out


def main(argv: list[str]) -> int:   # pragma: no cover - the command
    from .config import Settings
    write = "--write" in argv
    s = Settings.from_env()
    if not s.site_url:
        print("DMS_SITE_URL is not set: run this from webapi, where the .env is.")
        return 2
    sp = SharePoint(s)
    print(f"Control site : {s.site_url}")
    print(f"Exchange site: {s.ex_site_url or '(none)'}\n")
    rows = run(sp, write=write, libraries=(s.review_library, s.view_library))
    for r in rows:
        what = r.get("list") or r.get("library")
        line = f"  {what:<28} {r['found']:>5} item(s)"
        if write:
            line += f" -> removed {r['removed']}"
        if r.get("error"):
            line += f"   FAILED: {r['error'][:160]}"
        print(line)
    total = sum(r["found"] for r in rows)
    if not write:
        print(f"\n{total} item(s) would be removed. Nothing was changed. Add --write to do it.")
    else:
        print(f"\nRemoved {sum(r['removed'] for r in rows)} of {total}.")
    return 1 if any(r.get("error") for r in rows) else 0


if __name__ == "__main__":   # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv))
