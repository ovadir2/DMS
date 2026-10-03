"""The repository tree from blueprint IT-DOC-BP-001 Appendix A (the same tree that
scripts/New-DmsFileServerTree.ps1 creates), with English and Hebrew names and short hints, so the
page can guide users to the right folder. "*" stands for any customer or project folder."""
from __future__ import annotations

# name: (English, Hebrew, children) or (English, Hebrew, children, hint EN, hint HE)
N = dict


def _dev_stages() -> dict:
    return N({
        "01_Quotation": ("01 Quotation", "01 הצעת מחיר", {}),
        "02_SOW": ("02 Statement of work", "02 תכולת עבודה (SOW)", {}),
        "03_SRS": ("03 Requirements (SRS)", "03 דרישות מערכת (SRS)", {}),
        "04_PDR": ("04 Preliminary design review", "04 סקר תכן מקדים (PDR)", {}),
        "05_CDR": ("05 Critical design review", "05 סקר תכן קריטי (CDR)", {}),
        "06_Implementation": ("06 Implementation", "06 מימוש", {}),
        "07_FAT": ("07 Factory acceptance (FAT)", "07 בדיקות קבלה במפעל (FAT)", {}),
        "08_SAT": ("08 Site acceptance (SAT)", "08 בדיקות קבלה באתר (SAT)", {}),
        "09_FDR": ("09 Final design review", "09 סקר תכן סופי (FDR)", {}),
        "10_Project_Deliverables": ("10 Project deliverables", "10 תוצרי פרויקט", {}),
        "Archive": ("Archive", "ארכיון", {}),
    })


def _same(*names: str) -> dict:
    return {n: (n.replace("_", " "), n.replace("_", " "), {}) for n in names}


PROJECT = N({
    "Project_Info": ("Project info", "מידע על הפרויקט", {}, "Project card, contacts, kickoff", "כרטיס פרויקט, אנשי קשר, פתיחה"),
    "Customer_Source": ("Customer source", "חומר מהלקוח", N({
        "Drawings": ("Drawings", "שרטוטים", {}), "Specifications": ("Specifications", "מפרטים", {}),
        "BOM": ("BOM", "BOM", {}), "CAD": ("CAD", "CAD", {}), "PDFs": ("PDFs", "PDF", {}),
        "Emails": ("Emails", "מיילים", {}), "Change_Requests": ("Change requests", "בקשות שינוי", {}),
        "Other": ("Other", "אחר", {})}),
        "Files received from the customer, as received", "קבצים שהתקבלו מהלקוח, כפי שהתקבלו"),
    "Engineering": ("Engineering", "הנדסה", N({
        "Mechanical": ("Mechanical", "מכני", {}), "Electrical": ("Electrical", "חשמלי", {}), "PCB": ("PCB", "PCB", {}),
        "CAD": ("CAD", "CAD", {}), "Schematics": ("Schematics", "סכמות", {}), "Gerber": ("Gerber", "Gerber", {}),
        "ODB++": ("ODB++", "ODB++", {}), "Netlist": ("Netlist", "Netlist", {}), "BOM": ("BOM", "BOM", {}),
        "AVL": ("AVL", "AVL", {}), "DFM": ("DFM", "DFM", {}), "DFT": ("DFT", "DFT", {}),
        "Simulations": ("Simulations", "סימולציות", {}), "Calculations": ("Calculations", "חישובים", {})}),
        "Our design data: drawings, schematics, BOM, CAD", "נתוני התכן שלנו: שרטוטים, סכמות, BOM, CAD"),
    "Development": ("Development", "פיתוח", _dev_stages(),
                    "Development stages 01-10, from quotation to deliverables", "שלבי הפיתוח 01-10, מהצעת מחיר ועד תוצרים"),
    "NPI": ("NPI", "הכנסת מוצר חדש (NPI)", N({
        "Project_Plan": ("Project plan", "תוכנית פרויקט", {}), "Schedule": ("Schedule", "לוח זמנים", {}),
        "Risk_Register": ("Risk register", "ניהול סיכונים", {}), "Gate_Reviews": ("Gate reviews", "סקרי שער", {}),
        "Validation": ("Validation", "תיקוף", {}), "Transfer": ("Transfer to production", "העברה לייצור", {})}),
        "New product introduction: plan, gates, transfer", "הכנסת מוצר חדש: תוכנית, שערים, העברה לייצור"),
    "Manufacturing": ("Manufacturing", "ייצור - הנדסה", N({
        "Assembly_Drawings": ("Assembly drawings", "שרטוטי הרכבה", {}),
        "Work_Instructions": ("Work instructions", "הוראות עבודה", {}),
        "Process_Flow": ("Process flow", "תהליך ייצור", {}), "Machine_Programs": ("Machine programs", "תוכניות מכונה", {}),
        "Stencil": ("Stencil", "סטנסיל", {}), "Pick_and_Place": ("Pick and place", "Pick and Place", {}),
        "Fixtures": ("Fixtures", "מתקנים", {}), "Photos": ("Photos", "תמונות", {}), "Videos": ("Videos", "סרטונים", {})}),
        "Work instructions, assembly drawings, machine programs", "הוראות עבודה, שרטוטי הרכבה, תוכניות מכונה"),
    "Test_Engineering": ("Test engineering", "הנדסת בדיקות", N({
        "ATEFiles": ("ATE files", "קבצי ATE", N({
            "ICT": ("ICT", "ICT", _same("Logging", "Source", "T1", "T4", "T5", "T9", "T10")),
            "FCT": ("FCT", "FCT", _dev_stages()), "FTP": ("FTP", "FTP", {}),
            "JTAG": ("JTAG", "JTAG", _same("CopyToCurrent", "Logging", "T1", "T2"))})),
        "Test_Plans": ("Test plans", "תוכניות בדיקה", {}), "Test_Procedures": ("Test procedures", "נהלי בדיקה", {}),
        "Test_Reports": ("Test reports", "דוחות בדיקה", {}), "Test_Coverage": ("Test coverage", "כיסוי בדיקות", {}),
        "Yield_Analysis": ("Yield analysis", "ניתוח תפוקה", {}), "Debug": ("Debug", "דיבאג", {}),
        "Calibration": ("Calibration", "כיול", {}), "Released": ("Released", "משוחרר", {}), "Archive": ("Archive", "ארכיון", {})}),
        "Test plans, procedures, reports and ATE programs", "תוכניות, נהלים, דוחות בדיקה ותוכניות ATE"),
    "Quality": ("Quality", "איכות", N({
        "PPAP": ("PPAP", "PPAP", {}), "PFMEA": ("PFMEA", "PFMEA", {}), "Control_Plan": ("Control plan", "תוכנית בקרה", {}),
        "NCR": ("NCR", "אי-התאמה (NCR)", {}), "CAR": ("CAR", "פעולה מתקנת (CAR)", {}), "8D": ("8D", "8D", {}),
        "Certificates": ("Certificates", "תעודות", {}), "Audits": ("Audits", "מבדקים", {})}),
        "PPAP, PFMEA, NCR, certificates", "PPAP, PFMEA, אי-התאמות, תעודות"),
    "Production": ("Production", "ייצור שוטף", N({
        "Builds": ("Builds", "סדרות ייצור", {}), "Travelers": ("Travelers", "כרטיסי עבודה", {}),
        "Reports": ("Reports", "דוחות", {}), "KPIs": ("KPIs", "מדדים", {}), "OEE": ("OEE", "OEE", {})}),
        "Builds, travelers, production reports", "סדרות ייצור, כרטיסי עבודה, דוחות ייצור"),
    "Changes": ("Changes", "שינויים", N({
        "ECO": ("ECO", "הוראת שינוי הנדסי (ECO)", {}), "ECN": ("ECN", "הודעת שינוי (ECN)", {}),
        "Deviations": ("Deviations", "חריגות", {}), "Waivers": ("Waivers", "ויתורים", {})}),
        "Engineering changes: ECO, ECN, deviations", "שינויים הנדסיים: ECO, ECN, חריגות"),
    "Released": ("Released", "שוחרר", _same("Rev_A", "Rev_B", "Rev_C", "Current"),
                 "Released revisions for production", "גרסאות משוחררות לייצור"),
    "Archive": ("Archive", "ארכיון", {}),
})

CUSTOMER = N({
    "Customer_Profile": ("Customer profile", "פרופיל לקוח", {}, "Contacts, requirements, general agreements", "אנשי קשר, דרישות, הסכמים כלליים"),
    "Commercial": ("Commercial", "מסחרי", N({
        "RFQ": ("RFQ", "בקשות להצעת מחיר (RFQ)", {}, "Requests for quotation from the customer", "בקשות להצעת מחיר מהלקוח"),
        "Quotations": ("Quotations", "הצעות מחיר", {}, "Our quotations to the customer", "הצעות המחיר שלנו ללקוח"),
        "Contracts": ("Contracts and orders", "חוזים והזמנות", {}, "Contracts and purchase orders", "חוזים והזמנות רכש"),
        "NDA": ("NDA", "הסכמי סודיות (NDA)", {})}),
        "RFQ, quotations, contracts, NDA", "בקשות להצעה, הצעות מחיר, חוזים, NDA"),
    "Projects": ("Projects", "פרויקטים", {"*": ("", "", PROJECT, "Project", "פרויקט")},
                 "One folder per project", "תיקייה לכל פרויקט"),
    "Shared": ("Shared", "משותף", {}, "Files shared with the customer", "קבצים משותפים עם הלקוח"),
    "Archive": ("Archive", "ארכיון", {}),
})

MANAGEMENT = N({k: (en, he, {}) for k, en, he in (
    ("Company_Profile", "Company profile", "פרופיל חברה"), ("Strategy", "Strategy", "אסטרטגיה"),
    ("Sales_Marketing", "Sales and marketing", "מכירות ושיווק"), ("HR", "HR", "משאבי אנוש"), ("Finance", "Finance", "כספים"),
    ("IT", "IT", "מערכות מידע"), ("Quality_System", "Quality system", "מערכת איכות"),
    ("Engineering_Standards", "Engineering standards", "תקני הנדסה"), ("Manufacturing_Standards", "Manufacturing standards", "תקני ייצור"),
    ("Development_Standards", "Development standards", "תקני פיתוח"), ("Project_Management", "Project management", "ניהול פרויקטים"),
    ("Templates", "Templates", "תבניות"), ("Training", "Training", "הדרכה"), ("Suppliers", "Suppliers", "ספקים"),
    ("Certifications", "Certifications", "הסמכות"), ("Legal", "Legal", "משפטי"), ("Assets", "Assets", "נכסים"),
    ("AI_Automation", "AI and automation", "AI ואוטומציה"), ("Knowledge_Base", "Knowledge base", "מאגר ידע"),
    ("Archive", "Archive", "ארכיון"))})

ROOT = N({
    "01_Management": ("Management", "הנהלה", MANAGEMENT, "Company-wide areas: procedures, standards, HR, finance",
                      "תחומי החברה: נהלים, תקנים, משאבי אנוש, כספים"),
    "02_Customers": ("Customers", "לקוחות", {"*": ("", "", CUSTOMER, "Customer", "לקוח")},
                     "One folder per customer, with its commercial files and projects", "תיקייה לכל לקוח, עם המסמכים המסחריים והפרויקטים"),
})
# 03_Operations_Staging, 04_Workflow_System and 05_Exchange_Quarantine are system folders, not shown to users.
HIDDEN_AT_ROOT = ("03_Operations_Staging", "04_Workflow_System", "05_Exchange_Quarantine")


def _node(parts: list[str]):
    """The blueprint node for a folder path (parts relative to the root), or None."""
    node: tuple | None = ("", "", ROOT)
    for p in parts:
        children = node[2] if node else {}
        node = children.get(p) or next((v for k, v in children.items() if k.lower() == p.lower()), None) or children.get("*")
        if node is None:
            return None
    return node


def describe(parts: list[str]) -> dict | None:
    """Names and hint for a folder. A customer or project folder keeps its own name."""
    node = _node(parts)
    if not node or not parts:
        return None
    name = parts[-1]
    en, he = node[0] or name, node[1] or name           # customers and projects keep their own names
    hint = (node[3], node[4]) if len(node) > 3 else ("", "")
    kind = "customer" if len(parts) == 2 and parts[0] == "02_Customers" else \
           "project" if len(parts) == 4 and parts[0] == "02_Customers" and parts[2] == "Projects" else "area"
    return {"en": en, "he": he, "hintEn": hint[0], "hintHe": hint[1], "kind": kind}


def leaves(tree: dict, prefix: tuple = ()) -> list[tuple]:
    """Every folder path (as name tuples) of a blueprint subtree, parents before children; "*" is skipped."""
    out = []
    for name, v in tree.items():
        if name == "*":
            continue
        out.append(prefix + (name,))
        out += leaves(v[2], prefix + (name,))
    return out


def order(parts: list[str]) -> list[str]:
    """Blueprint order of the expected subfolders of a folder (empty when not in the blueprint)."""
    node = _node(parts)
    return [k for k in (node[2] if node else {}) if k != "*"]


# "What are you saving?" -> where it belongs. {c} = the customer folder, {p} = the project folder.
SAVE_GUIDE = [
    ("rfq", "RFQ from the customer", "בקשה להצעת מחיר מהלקוח", "{c}/Commercial/RFQ"),
    ("quotation", "Quotation", "הצעת מחיר", "{c}/Commercial/Quotations"),
    ("contract", "Contract or purchase order", "חוזה או הזמנת רכש", "{c}/Commercial/Contracts"),
    ("nda", "NDA", "הסכם סודיות", "{c}/Commercial/NDA"),
    ("cust_drawing", "Drawing from the customer", "שרטוט מהלקוח", "{p}/Customer_Source/Drawings"),
    ("cust_spec", "Specification from the customer", "מפרט מהלקוח", "{p}/Customer_Source/Specifications"),
    ("cust_bom", "BOM from the customer", "BOM מהלקוח", "{p}/Customer_Source/BOM"),
    ("bom", "Our BOM", "BOM שלנו", "{p}/Engineering/BOM"),
    ("schematics", "Schematics", "סכמות", "{p}/Engineering/Schematics"),
    ("pcb", "PCB / Gerber files", "קבצי PCB / Gerber", "{p}/Engineering/Gerber"),
    ("sow", "Statement of work (SOW)", "תכולת עבודה (SOW)", "{p}/Development/02_SOW"),
    ("srs", "Requirements (SRS)", "דרישות מערכת (SRS)", "{p}/Development/03_SRS"),
    ("pdr", "Preliminary design review (PDR)", "סקר תכן מקדים (PDR)", "{p}/Development/04_PDR"),
    ("cdr", "Critical design review (CDR)", "סקר תכן קריטי (CDR)", "{p}/Development/05_CDR"),
    ("fat", "Factory acceptance test (FAT)", "בדיקות קבלה במפעל (FAT)", "{p}/Development/07_FAT"),
    ("deliverable", "Project deliverable", "תוצר פרויקט", "{p}/Development/10_Project_Deliverables"),
    ("plan", "Project plan / schedule", "תוכנית פרויקט / לוח זמנים", "{p}/NPI/Project_Plan"),
    ("work_instruction", "Work instruction", "הוראת עבודה", "{p}/Manufacturing/Work_Instructions"),
    ("assembly", "Assembly drawing", "שרטוט הרכבה", "{p}/Manufacturing/Assembly_Drawings"),
    ("test_procedure", "Test procedure", "נוהל בדיקה", "{p}/Test_Engineering/Test_Procedures"),
    ("test_report", "Test report", "דוח בדיקה", "{p}/Test_Engineering/Test_Reports"),
    ("ppap", "PPAP", "PPAP", "{p}/Quality/PPAP"),
    ("ncr", "Non-conformance (NCR)", "אי-התאמה (NCR)", "{p}/Quality/NCR"),
    ("eco", "Engineering change (ECO)", "הוראת שינוי הנדסי (ECO)", "{p}/Changes/ECO"),
    ("released", "Released revision", "גרסה משוחררת", "{p}/Released/Current"),
]


# Document type and area inherited from the blueprint folder (English keys of the SharePoint choices;
# LABELS gives the Hebrew value used on a Hebrew site). The deepest matching folder wins.
_P = "02_Customers/*/Projects/*"
CLASSIFY = {
    "01_Management": ("Management", None),
    "01_Management/Company_Profile": ("Management", "Company Profile"),
    "01_Management/Strategy": ("Management", "Strategy"),
    "01_Management/Quality_System": ("Quality", "Procedure"),
    "01_Management/Engineering_Standards": ("Development", "Procedure"),
    "01_Management/Development_Standards": ("Development", "Procedure"),
    "01_Management/Manufacturing_Standards": ("Manufacturing", "Procedure"),
    "01_Management/Project_Management": ("Management", "Procedure"),
    "01_Management/HR": ("Management", "Policy"),
    "01_Management/IT": ("IT", "IT Procedure"),
    "02_Customers/*": ("Commercial", None),
    "02_Customers/*/Commercial/RFQ": ("Commercial", "Quotation"),
    "02_Customers/*/Commercial/Quotations": ("Commercial", "Quotation"),
    "02_Customers/*/Commercial/Contracts": ("Commercial", "Contract / NDA"),
    "02_Customers/*/Commercial/NDA": ("Commercial", "Contract / NDA"),
    _P: ("Development", None),
    f"{_P}/Development/01_Quotation": ("Commercial", "Quotation"),
    f"{_P}/Development/02_SOW": ("Development", "SOW"),
    f"{_P}/Development/03_SRS": ("Development", "SRS"),
    f"{_P}/Development/04_PDR": ("Development", "PDR / CDR"),
    f"{_P}/Development/05_CDR": ("Development", "PDR / CDR"),
    f"{_P}/Development/07_FAT": ("Development", "FAT / SAT / FDR"),
    f"{_P}/Development/08_SAT": ("Development", "FAT / SAT / FDR"),
    f"{_P}/Development/09_FDR": ("Development", "FAT / SAT / FDR"),
    f"{_P}/Manufacturing": ("Manufacturing", None),
    f"{_P}/Manufacturing/Work_Instructions": ("Manufacturing", "Work Instruction"),
    f"{_P}/Production": ("Manufacturing", None),
    f"{_P}/Test_Engineering": ("Test Engineering", None),
    f"{_P}/Test_Engineering/Test_Procedures": ("Test Engineering", "Test Procedure"),
    f"{_P}/Quality": ("Quality", None),
    f"{_P}/Quality/PFMEA": ("Quality", "PFMEA / Control Plan"),
    f"{_P}/Quality/Control_Plan": ("Quality", "PFMEA / Control Plan"),
    f"{_P}/Changes": ("Changes", None),
    f"{_P}/Changes/ECO": ("Changes", "ECO / ECN"),
    f"{_P}/Changes/ECN": ("Changes", "ECO / ECN"),
}
LABELS = {
    "Management": "ניהול", "Commercial": "מסחרי", "Development": "פיתוח", "Manufacturing": "ייצור",
    "Test Engineering": "הנדסת בדיקות", "Quality": "איכות", "Changes": "שינויים", "IT": "מערכות מידע",
    "Company Profile": "פרופיל חברה", "Strategy": "אסטרטגיה", "Policy": "מדיניות", "Procedure": "נוהל",
    "Quotation": "הצעת מחיר", "Contract / NDA": "חוזה / NDA", "SOW": "SOW - הגדרת עבודה", "SRS": "SRS - דרישות מערכת",
    "PDR / CDR": "PDR / CDR - סקר תכן", "FAT / SAT / FDR": "FAT / SAT / FDR - בדיקות קבלה",
    "Work Instruction": "הוראת עבודה", "Test Procedure": "נוהל בדיקה", "PFMEA / Control Plan": "PFMEA / תוכנית בקרה",
    "ECO / ECN": "ECO / ECN - הודעת שינוי", "IT Procedure": "נוהל מערכות מידע",
    "Workflow Required": "תהליך אישור חובה",
}


def classify(parts: list[str]) -> dict:
    """{'area', 'type'} (English keys or None) for a folder (parts relative to the root). Customer and
    project names and the DMS workflow folders do not count."""
    from .config import WORKFLOW_FOLDERS
    parts = [p for p in parts if p not in WORKFLOW_FOLDERS]
    norm = list(parts)
    if len(norm) > 1 and norm[0].lower() == "02_customers":
        norm[1] = "*"
        if len(norm) > 3 and norm[2].lower() == "projects":
            norm[3] = "*"
    keys = {k.lower(): v for k, v in CLASSIFY.items()}
    for n in range(len(norm), 0, -1):
        hit = keys.get("/".join(norm[:n]).lower())
        if hit:
            return {"area": hit[0], "type": hit[1]}
    return {"area": None, "type": None}


def choice(key: str | None, values: list[str]) -> str | None:
    """The site's value of a choice: the English key or its Hebrew label, whichever the site uses."""
    if not key:
        return None
    for v in (key, LABELS.get(key)):
        if v and v in values:
            return v
    return None
