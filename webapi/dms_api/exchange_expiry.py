"""Shares with customers expire: files in <library>/<DMS_EX_FOLDER>/<Customer>/ on the Large File Exchange site
are removed DMS_EX_DAYS (default 3) days after their last share. A customer folder left empty is removed too,
and with it the customer's access. Each removal is a Control Audit row. Runs every hour inside the DMS."""
from __future__ import annotations

import logging
import os
import threading
import time

from .config import Settings

log = logging.getLogger("dms_api.exchange_expiry")


def run_once(sp, s: Settings) -> list[dict]:
    if s.ex_days <= 0 or (s.sharepoint != "memory" and not s.ex_site_url):
        return []
    removed = sp.expire_outbound(s.ex_days)
    if not removed:
        return []
    c = s.choices
    by_name = {}
    for d in sp.documents():
        if d.get("currentUncPath"):
            by_name.setdefault(os.path.basename(d["currentUncPath"].replace("\\", "/")).lower(), d.get("documentId"))
    for r in removed:
        doc_id = by_name.get(r["file"].lower()) or "Exchange"
        details = (f"Share expired after {s.ex_days} days: {r['file']} removed from {s.ex_folder}/{r['customer']} "
                   f"on the Large File Exchange site (shared {(r.get('sharedUtc') or '')[:10]})"
                   + (". The customer folder was empty and was removed: the customer has no access any more" if r["folderRemoved"] else ""))
        try:
            sp.audit(document_id=doc_id, event=c["PermissionChanged"], from_status=c["Approved_ReadOnly"],
                     to_status=c["Approved_ReadOnly"], actor="RH-DMS-Workflow-Service", details=details, source=c["WorkflowService"])
        except Exception as e:  # noqa: BLE001
            log.warning("audit of the expired share failed: %s", e)
        log.info("%s %s", doc_id, details)
    from . import shared_log
    for customer in {r["customer"] for r in removed}:
        try:
            hr = not os.path.isdir(os.path.join(s.repository_root, s.customers_folder, customer)) and shared_log.hr_has(s, customer)
            shared_log.append(s, customer, [{"Action": "Expired - removed from the Exchange site" + (" (folder removed, no access)" if r["folderRemoved"] else ""),
                                             "Shared by": "RH-DMS-Workflow-Service", "Document ID": by_name.get(r["file"].lower()) or "",
                                             "Shared with": f"{customer}:" if hr else "", "File": r["file"], "Available until": "expired"}
                                            for r in removed if r["customer"] == customer], hr=hr)
        except OSError as e:
            log.warning("Share log of %s: %s", customer, e)
    return removed


def start(sp, s: Settings, every: int = 3600) -> threading.Thread | None:
    if s.ex_days <= 0 or (s.sharepoint != "memory" and not s.ex_site_url):
        return None

    def loop():
        time.sleep(60)
        while True:
            try:
                run_once(sp, s)
            except Exception as e:  # noqa: BLE001 - keep the loop alive
                log.error("share expiry run failed: %s", e)
            time.sleep(every)

    t = threading.Thread(target=loop, name="dms-share-expiry", daemon=True)
    t.start()
    log.info("Share expiry started: files on the Exchange site are removed %s days after their last share", s.ex_days)
    return t
