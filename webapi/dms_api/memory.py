"""An in-memory Document Register and Control Audit, for trying the page on a PC without
SharePoint (DMS_SHAREPOINT=memory). Everything is lost when the service stops."""
from __future__ import annotations

from datetime import datetime, timezone

from .config import Settings

CHOICES = {
    "he": {"DocumentType": ["הצעת מחיר", "נוהל", "שרטוט", "דוח בדיקה", "הוראת עבודה"], "DocumentArea": ["מסחרי", "פיתוח", "ייצור", "איכות"],
           "ControlMode": ["תהליך אישור רשות", "תהליך אישור חובה"]},
    "en": {"DocumentType": ["Quotation", "Procedure", "Drawing", "Test report", "Work instruction"],
           "DocumentArea": ["Commercial", "Development", "Manufacturing", "Quality"], "ControlMode": ["Workflow Optional", "Workflow Required"]},
}


class MemorySharePoint:
    def __init__(self, s: Settings):
        self.s, self.items, self.audits = s, {}, []

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

    def audit(self, *, document_id, event, from_status, to_status, actor, details) -> None:
        self.audits.append({"documentId": document_id, "event": event, "fromStatus": from_status, "toStatus": to_status,
                            "actor": actor, "utc": datetime.now(timezone.utc).isoformat(), "source": self.s.choices["Manual"],
                            "details": details})

    def audit_events(self, refresh: bool = False) -> list[dict]:
        return list(reversed(self.audits))

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
