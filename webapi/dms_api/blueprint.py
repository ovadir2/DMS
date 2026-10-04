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


# A product of a customer: 02_Customers\<Customer>\Develop\Products\<Product>, with the development stages.
# (Called "project" in the code and the API: the customer's unit of work.)
PRODUCTS = ("Develop", "Products")
PROJECT = _dev_stages()


def _ate() -> dict:
    return N({
        "FCT": ("FCT", "FCT", _dev_stages()), "FTP": ("FTP", "FTP", {}),
        "ICT": ("ICT", "ICT", _same("Logging", "Source", "T1", "T4", "T5", "T9", "T10")),
        "JTAG": ("JTAG", "JTAG", _same("CopyToCurrent", "Logging", "T1", "T2"))})


CUSTOMER = N({
    "Customer_Profile": ("Customer profile", "פרופיל לקוח", {}, "Contacts, requirements, general agreements", "אנשי קשר, דרישות, הסכמים כלליים"),
    "Commercial": ("Commercial", "מסחרי", N({
        "RFQ": ("RFQ", "בקשות להצעת מחיר (RFQ)", {}, "Requests for quotation from the customer", "בקשות להצעת מחיר מהלקוח"),
        "Quotations": ("Quotations", "הצעות מחיר", {}, "Our quotations to the customer", "הצעות המחיר שלנו ללקוח"),
        "Contracts": ("Contracts and orders", "חוזים והזמנות", {}, "Contracts and purchase orders", "חוזים והזמנות רכש"),
        "NDA": ("NDA", "הסכמי סודיות (NDA)", {})}),
        "RFQ, quotations, contracts, NDA", "בקשות להצעה, הצעות מחיר, חוזים, NDA"),
    "Pricing": ("Pricing", "תמחור", {}, "Costing and price calculations", "תמחיר וחישובי מחיר"),
    "Develop": ("Develop", "פיתוח", N({
        "ATEFiles": ("ATE files", "קבצי ATE", _ate(), "FCT, ICT, JTAG and FTP programs", "תוכניות FCT, ICT, JTAG ו-FTP"),
        "Products": ("Products", "מוצרים", {"*": ("", "", PROJECT, "Product: development stages 01-10", "מוצר: שלבי פיתוח 01-10")},
                     "One folder per product", "תיקייה לכל מוצר")}),
        "Products and ATE files", "מוצרים וקבצי ATE"),
    "Engineering": ("Engineering", "הנדסה", {}, "Engineering data of the customer's products", "נתוני הנדסה של מוצרי הלקוח"),
    "DFM": ("DFM", "DFM", {}, "Design for manufacturing reviews", "סקרי התאמה לייצור"),
    "DFT": ("DFT", "DFT", {}, "Design for test reviews", "סקרי התאמה לבדיקה"),
    "NPI": ("NPI", "הכנסת מוצר חדש (NPI)", {}, "New product introduction", "הכנסת מוצר חדש"),
    "Manufacturing": ("Manufacturing", "ייצור - הנדסה", N({
        "Assembly_Drawings": ("Assembly drawings", "שרטוטי הרכבה", {}),
        "Work_Instructions": ("Work instructions", "הוראות עבודה", {}),
        "Process_Flow": ("Process flow", "תהליך ייצור", {}), "Machine_Programs": ("Machine programs", "תוכניות מכונה", {}),
        "Stencil": ("Stencil", "סטנסיל", {}), "Pick_and_Place": ("Pick and place", "Pick and Place", {}),
        "Fixtures": ("Fixtures", "מתקנים", {}), "Photos": ("Photos", "תמונות", {}), "Videos": ("Videos", "סרטונים", {})}),
        "Work instructions, assembly drawings, machine programs", "הוראות עבודה, שרטוטי הרכבה, תוכניות מכונה"),
    "Quality_QC": ("Quality and QC", "איכות ובקרת איכות", N({
        "PPAP": ("PPAP", "PPAP", {}), "PFMEA": ("PFMEA", "PFMEA", {}), "Control_Plan": ("Control plan", "תוכנית בקרה", {}),
        "NCR": ("NCR", "אי-התאמה (NCR)", {}), "CAR": ("CAR", "פעולה מתקנת (CAR)", {}), "8D": ("8D", "8D", {}),
        "Certificates": ("Certificates", "תעודות", {}), "Audits": ("Audits", "מבדקים", {})}),
        "PPAP, PFMEA, NCR, certificates", "PPAP, PFMEA, אי-התאמות, תעודות"),
    "Supply_chain": ("Supply chain", "שרשרת אספקה", {}, "Customer-supplied material, forecasts, logistics", "חומר מהלקוח, תחזיות, לוגיסטיקה"),
    "Shared": ("Shared", "משותף", {}, "Files shared with the customer", "קבצים משותפים עם הלקוח"),
    "Archive": ("Archive", "ארכיון", {}),
})

# Quality procedures in operation, by division (Hebrew folder names, as on the file server)
_QPROC = N({
    "חטיבות": ("חטיבות", "חטיבות", {}),
    "כלל חברה": ("כלל חברה", "כלל חברה", _same("ארכיון", "Training")),
    "מערכות מידע": ("מערכות מידע", "מערכות מידע", _same("ארכיון")),
    "מפעל ייצור": ("מפעל ייצור", "מפעל ייצור", _same("ארכיון")),
    "משאבי אנוש": ("משאבי אנוש", "משאבי אנוש", _same("ארכיון")),
    "נהלי אחזקה": ("נהלי אחזקה", "נהלי אחזקה", {}),
    "רכש ואספקה": ("רכש ואספקה", "רכש ואספקה", _same("ארכיון")),
    "תשתיות איכות": ("תשתיות איכות", "תשתיות איכות", _same("ארכיון")),
})

MANAGEMENT = N({k: (en, he, {}) for k, en, he in (
    ("Company_Profile", "Company profile", "פרופיל חברה"), ("Strategy", "Strategy", "אסטרטגיה"),
    ("Commercial", "Commercial", "מסחרי"), ("Sales_Marketing", "Sales and marketing", "מכירות ושיווק"),
    ("Engineering", "Engineering", "הנדסה"), ("Project_Management", "Project management", "ניהול פרויקטים"),
    ("Planners", "Planners", "תכנון"), ("Supply_chain", "Supply chain", "שרשרת אספקה"),
    ("Quality_System", "Quality system", "מערכת איכות"), ("Quality and Standards", "Quality and standards", "איכות ותקנים"),
    ("Certifications", "Certifications", "הסמכות"), ("HR", "HR", "משאבי אנוש"), ("Training", "Training", "הדרכה"),
    ("Finance", "Finance", "כספים"), ("Legal", "Legal", "משפטי"), ("Assets", "Assets", "נכסים"),
    ("IT", "IT", "מערכות מידע"), ("DB_Management", "Database management", "ניהול בסיסי נתונים"),
    ("AI_Automation", "AI and automation", "AI ואוטומציה"), ("Templates", "Templates", "תבניות"),
    ("Archive", "Archive", "ארכיון"))})
MANAGEMENT["Quality and Standards"] = ("Quality and standards", "איכות ותקנים", N({
    "נהלי איכות בתפעול": ("נהלי איכות בתפעול", "נהלי איכות בתפעול", _QPROC,
                          "Quality procedures in operation, by division", "נהלי האיכות בתפעול, לפי חטיבה")}),
    "Company quality procedures and standards", "נהלי האיכות והתקנים של החברה")

ROOT = N({
    "01_Management": ("Management", "הנהלה", MANAGEMENT, "Company-wide areas: procedures, standards, HR, finance",
                      "תחומי החברה: נהלים, תקנים, משאבי אנוש, כספים"),
    "02_Customers": ("Customers", "לקוחות", {"*": ("", "", CUSTOMER, "Customer", "לקוח")},
                     "One folder per customer, with its commercial files and products", "תיקייה לכל לקוח, עם המסמכים המסחריים והמוצרים"),
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


def product_index(parts: list[str]) -> int | None:
    """Index of the product folder in a path (02_Customers/<c>/Develop/Products/<product>/...), else None."""
    n = 2 + len(PRODUCTS)
    if len(parts) > n and parts[0].lower() == "02_customers" and [p.lower() for p in parts[2:n]] == [p.lower() for p in PRODUCTS]:
        return n
    return None


def describe(parts: list[str]) -> dict | None:
    """Names and hint for a folder. A customer or project folder keeps its own name."""
    node = _node(parts)
    if not node or not parts:
        return None
    name = parts[-1]
    en, he = node[0] or name, node[1] or name           # customers and projects keep their own names
    hint = (node[3], node[4]) if len(node) > 3 else ("", "")
    kind = "customer" if len(parts) == 2 and parts[0] == "02_Customers" else \
           "project" if product_index(parts) == len(parts) - 1 else "area"
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
    ("pricing", "Pricing / costing", "תמחור", "{c}/Pricing"),
    ("sow", "Statement of work (SOW)", "תכולת עבודה (SOW)", "{p}/02_SOW"),
    ("srs", "Requirements (SRS)", "דרישות מערכת (SRS)", "{p}/03_SRS"),
    ("pdr", "Preliminary design review (PDR)", "סקר תכן מקדים (PDR)", "{p}/04_PDR"),
    ("cdr", "Critical design review (CDR)", "סקר תכן קריטי (CDR)", "{p}/05_CDR"),
    ("fat", "Factory acceptance test (FAT)", "בדיקות קבלה במפעל (FAT)", "{p}/07_FAT"),
    ("deliverable", "Product deliverable", "תוצר מוצר", "{p}/10_Project_Deliverables"),
    ("fct", "FCT program", "תוכנית FCT", "{c}/Develop/ATEFiles/FCT"),
    ("ict", "ICT program", "תוכנית ICT", "{c}/Develop/ATEFiles/ICT"),
    ("dfm", "DFM report", "דוח DFM", "{c}/DFM"),
    ("dft", "DFT report", "דוח DFT", "{c}/DFT"),
    ("npi", "NPI document", "מסמך NPI", "{c}/NPI"),
    ("work_instruction", "Work instruction", "הוראת עבודה", "{c}/Manufacturing/Work_Instructions"),
    ("assembly", "Assembly drawing", "שרטוט הרכבה", "{c}/Manufacturing/Assembly_Drawings"),
    ("ppap", "PPAP", "PPAP", "{c}/Quality_QC/PPAP"),
    ("pfmea", "PFMEA / control plan", "PFMEA / תוכנית בקרה", "{c}/Quality_QC/PFMEA"),
    ("ncr", "Non-conformance (NCR)", "אי-התאמה (NCR)", "{c}/Quality_QC/NCR"),
]


# Document type and area inherited from the blueprint folder (English keys of the SharePoint choices;
# LABELS gives the Hebrew value used on a Hebrew site). The deepest matching folder wins.
_C = "02_Customers/*"
_P = "02_Customers/*/Develop/Products/*"
CLASSIFY = {
    "01_Management": ("Management", None),
    "01_Management/Company_Profile": ("Management", "Company Profile"),
    "01_Management/Strategy": ("Management", "Strategy"),
    "01_Management/Quality_System": ("Quality", "Procedure"),
    "01_Management/Quality and Standards": ("Quality", "Procedure"),
    "01_Management/Engineering": ("Development", "Procedure"),
    "01_Management/Commercial": ("Commercial", None),
    "01_Management/Planners": ("Manufacturing", None),
    "01_Management/Supply_chain": ("Manufacturing", None),
    "01_Management/Project_Management": ("Management", "Procedure"),
    "01_Management/HR": ("Management", "Policy"),
    "01_Management/IT": ("IT", "IT Procedure"),
    "01_Management/DB_Management": ("IT", "IT Procedure"),
    _C: ("Commercial", None),
    f"{_C}/Commercial/RFQ": ("Commercial", "Quotation"),
    f"{_C}/Commercial/Quotations": ("Commercial", "Quotation"),
    f"{_C}/Commercial/Contracts": ("Commercial", "Contract / NDA"),
    f"{_C}/Commercial/NDA": ("Commercial", "Contract / NDA"),
    f"{_C}/Pricing": ("Commercial", "Quotation"),
    f"{_C}/Develop": ("Development", None),
    f"{_C}/Develop/ATEFiles": ("Test Engineering", None),
    f"{_C}/Engineering": ("Development", None),
    f"{_C}/DFM": ("Manufacturing", None),
    f"{_C}/DFT": ("Test Engineering", None),
    f"{_C}/NPI": ("Development", None),
    f"{_C}/Manufacturing": ("Manufacturing", None),
    f"{_C}/Manufacturing/Work_Instructions": ("Manufacturing", "Work Instruction"),
    f"{_C}/Quality_QC": ("Quality", None),
    f"{_C}/Quality_QC/PFMEA": ("Quality", "PFMEA / Control Plan"),
    f"{_C}/Quality_QC/Control_Plan": ("Quality", "PFMEA / Control Plan"),
    f"{_C}/Supply_chain": ("Manufacturing", None),
    _P: ("Development", None),
    f"{_P}/01_Quotation": ("Commercial", "Quotation"),
    f"{_P}/02_SOW": ("Development", "SOW"),
    f"{_P}/03_SRS": ("Development", "SRS"),
    f"{_P}/04_PDR": ("Development", "PDR / CDR"),
    f"{_P}/05_CDR": ("Development", "PDR / CDR"),
    f"{_P}/07_FAT": ("Development", "FAT / SAT / FDR"),
    f"{_P}/08_SAT": ("Development", "FAT / SAT / FDR"),
    f"{_P}/09_FDR": ("Development", "FAT / SAT / FDR"),
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
        k = product_index(norm)
        if k is not None:
            norm[k] = "*"
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


def folder_list() -> list[str]:
    """Every blueprint folder as a Windows path relative to the root, with <Customer> and <Project>
    for the instance folders. scripts/blueprint-folders.txt is this list (the tree script reads it)."""
    out = []

    def walk(tree, prefix):
        for name, v in tree.items():
            key = {"02_Customers": "<Customer>", PRODUCTS[-1]: "<Product>"}.get(prefix[-1] if prefix else "", None) if name == "*" else name
            if key is None:
                continue
            path = prefix + [key]
            out.append("\\".join(path))
            walk(v[2], path)
    walk(ROOT, [])
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(folder_list()))
