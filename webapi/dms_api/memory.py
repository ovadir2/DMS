"""An in-memory Document Register and Control Audit, for trying the page on a PC without
SharePoint (DMS_SHAREPOINT=memory). Everything is lost when the service stops."""
from __future__ import annotations

from datetime import datetime, timezone

from .config import Settings

# The same choices Provision-DMS.ps1 creates on the sites (English key, Hebrew value)
_PAIRS = {
    "DocumentType": [("Company Profile", "פרופיל חברה"), ("Strategy", "אסטרטגיה"), ("Policy", "מדיניות"), ("Procedure", "נוהל"),
                     ("Quotation", "הצעת מחיר"), ("Contract / NDA", "חוזה / NDA"), ("SOW", "SOW - הגדרת עבודה"),
                     ("SRS", "SRS - דרישות מערכת"), ("PDR / CDR", "PDR / CDR - סקר תכן"), ("FAT / SAT / FDR", "FAT / SAT / FDR - בדיקות קבלה"),
                     ("Work Instruction", "הוראת עבודה"), ("Test Procedure", "נוהל בדיקה"), ("PFMEA / Control Plan", "PFMEA / תוכנית בקרה"),
                     ("ECO / ECN", "ECO / ECN - הודעת שינוי"), ("IT Procedure", "נוהל מערכות מידע"), ("Security Policy", "מדיניות אבטחת מידע")],
    "DocumentArea": [("Management", "ניהול"), ("Commercial", "מסחרי"), ("Development", "פיתוח"), ("Manufacturing", "ייצור"),
                     ("Test Engineering", "הנדסת בדיקות"), ("Quality", "איכות"), ("Changes", "שינויים"), ("IT", "מערכות מידע"),
                     ("InfoSec", "אבטחת מידע")],
    "ControlMode": [("Collaboration", "שיתופי ללא תהליך"), ("Workflow Optional", "תהליך אישור רשות"),
                    ("Workflow Required", "תהליך אישור חובה"), ("Read-Only Record", "רשומה לקריאה בלבד")],
}
CHOICES = {lang: {f: [p[i] for p in pairs] for f, pairs in _PAIRS.items()} for i, lang in ((0, "en"), (1, "he"))}


class MemorySharePoint:
    def __init__(self, s: Settings):
        self.s, self.items, self.audits, self.notifications = s, {}, [], []

    def documents(self, refresh: bool = False) -> list[dict]:
        return [dict(i) for i in self.items.values()]

    def document(self, item_id: int) -> dict:
        return dict(self.items[item_id])

    def create_document(self, *, title, path, document_type, document_area, owner_email, control_mode, document_id) -> dict:
        i = len(self.items) + 1
        now = datetime.now(timezone.utc).isoformat()
        self.items[i] = {"id": i, "title": title, "documentId": document_id or f"{self.s.document_id_prefix}-{i:05d}",
                         "documentType": document_type, "documentArea": document_area, "controlMode": control_mode,
                         "lifecycleStatus": self.s.choices["Working"], "workingUncPath": path, "currentUncPath": None,
                         "currentSHA256": None, "currentRevision": None, "ownerEmail": owner_email,
                         "ownerName": owner_email.split("@")[0], "modified": now, "created": now}
        return self.document(i)

    def update(self, item_id: int, values: dict) -> None:
        names = {"LifecycleStatus": "lifecycleStatus", "DocumentId": "documentId", "WorkingUncPath": "workingUncPath",
                 "CurrentUncPath": "currentUncPath"}
        for k, v in values.items():
            self.items[item_id][names.get(k, k[0].lower() + k[1:])] = v
        self.items[item_id]["modified"] = datetime.now(timezone.utc).isoformat()

    def choices(self, field: str) -> list[str]:
        return CHOICES[self.s.choice_language][field]

    def audit(self, *, document_id, event, from_status, to_status, actor, details, source=None) -> int:
        self.audits.append({"documentId": document_id, "event": event, "fromStatus": from_status, "toStatus": to_status,
                            "actor": actor, "utc": datetime.now(timezone.utc).isoformat(), "source": source or self.s.choices["Manual"],
                            "details": details})
        return len(self.audits)

    def attach(self, audit_id: int, name: str, path: str) -> None:
        self.attachments = getattr(self, "attachments", []) + [{"auditId": audit_id, "name": name, "path": path}]

    def share_with_guest(self, *, local_path, folder, email, subject, message) -> dict:
        url = f"memory://{self.s.ex_library}/{folder}/{local_path.replace(chr(92), '/').rsplit('/', 1)[-1]}"
        self.shares = getattr(self, "shares", []) + [{"email": email, "url": url, "subject": subject, "message": message}]
        return {"url": url}

    def people(self, q: str) -> list[dict]:
        """Playground: the super users, you and a few sample colleagues."""
        pool = list(dict.fromkeys([*(self.s.admins or []), *([self.s.dev_user] if self.s.dev_user else []),
                                   "dana.levi@rh.co.il", "avi.cohen@rh.co.il", "quality.manager@rh.co.il"]))
        q = q.lower()
        return [{"email": e, "name": e.split("@")[0].replace(".", " ").title(), "title": ""} for e in pool if q in e.lower()]

    def list_info(self, rel: str) -> dict:
        n = {"Lists/DocumentRegister": len(self.items), "Lists/ControlAudit": len(self.audits),
             "Lists/DmsNotifications": len(self.notifications)}.get(rel, 0)
        return {"list": rel, "exists": True, "title": rel.split("/")[-1], "items": n, "canRead": True, "canAdd": True, "canEdit": True}

    def notify(self, *, to, subject, body, link, ref) -> None:
        self.notifications.append({"to": list(to), "subject": subject, "body": body, "link": link, "ref": ref})

    def audit_events(self, refresh: bool = False) -> list[dict]:
        return list(reversed(self.audits))

    def approver_rule(self, document_type: str) -> dict | None:
        """Playground: the super users (or you) approve every document type."""
        people = ([self.s.dev_user] if self.s.dev_user else []) or self.s.admins
        return {"mandatory": people[:1], "final": people[0]} if people else None

    # Playground only: decide an approval as if the approvers did it in Teams
    def decide(self, item_id: int, approve: bool, actor: str, comment: str = "") -> dict:
        c = self.s.choices
        d = self.items[item_id]
        if d["lifecycleStatus"] != c["Submitted"]:
            raise ValueError("Only a submitted document can be approved or rejected")
        new = c["Approved_ReadOnly"] if approve else c["Working"]
        self.update(item_id, {"LifecycleStatus": new})
        self.audit(document_id=d["documentId"], event=c["ApprovedEvent"] if approve else c["RejectedEvent"],
                   from_status=c["Submitted"], to_status=new, actor=actor, details=comment)
        return self.document(item_id)
