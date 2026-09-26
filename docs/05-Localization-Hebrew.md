# 05 - Localization (English / Hebrew)

## 1. Rules

| Element | Language behaviour | Where it is set |
| --- | --- | --- |
| Site locale | `-Language en` → LCID 1033, `-Language he` → LCID 1037 (the SharePoint UI is right-to-left) | `Provision-DMS.ps1` |
| Column display names | English or Hebrew | `Provision-DMS.ps1` (`$Fields`, `En` / `He`) |
| List, view, content type, permission level and group names | English or Hebrew | `Provision-DMS.ps1` |
| **Internal names** | Always English | Stable for Power Fx, OData, Graph and the workers |
| **Choice stored values** | English keys (`Working`, `Submitted`...) by default. With `-ChoiceLanguage he` the Hebrew label is stored instead (`בעבודה`, `הוגש לאישור`...) | English keys never break when the UI language changes. Hebrew values give an all-Hebrew SharePoint, and flows and apps must then use the Hebrew values |
| Choice captions in the apps | English or Hebrew per user | `UI Labels` → `choice.<Set>.<Key>` |
| App text | English or Hebrew per user, with a toggle | `UI Labels` → `app.*` |
| Teams notifications | Per recipient `preferredLanguage`, with `dms_Language` as the fallback | `UI Labels` → `msg.*`, rendered by DMS-U2 |
| Approval cards (one card, many approvers) | Bilingual: English, then Hebrew in `<div dir="rtl">` | DC-04 |
| Channel posts | Bilingual | DMS-U3 |

A Hebrew site shows Hebrew column headers in SharePoint, while the Canvas apps follow each user's language. The two are independent, so a Hebrew site can serve English-speaking users and the reverse is also true.

**Changing a translation** does not need a new app version. Document Control edits the row in **UI Labels**, and users see the change after they restart the app. Column display names on the site can be changed in list settings without any impact, because every consumer uses the internal names.

## 2. Writing Hebrew correctly

- Keep product names, IDs and paths in Latin script inside Hebrew sentences (`{DocumentId}`, `SHA-256`, `\\FILE-SERVER\...`). The templates already do this.
- In Hebrew text, arrows point left: `←`.
- Use a hyphen (`-`), not an en dash or em dash.
- Gender-neutral forms use a slash (`הגיש/ה`, `ממלא/ת`), as in the seeded templates.
- Scripts that contain Hebrew literals are saved as **UTF-8 with BOM** so Windows PowerShell 5.1 hosts and editors do not garble them (the provisioning script targets PowerShell 7.4+ in any case).

## 3. Notification templates (seeded in UI Labels)

Tokens in `{braces}` are replaced by DMS-U2.

| Key | English | עברית |
| --- | --- | --- |
| `msg.approval.title` | Approval required: {DocumentId} {Revision} - {Title} | <div dir="rtl">נדרש אישור: {DocumentId} {Revision} - {Title}</div> |
| `msg.approval.body` | {Submitter} submitted {DocumentId} revision {Revision} for your approval. Change summary: {ChangeSummary}. File (read-only): {UncPath}. SHA-256: {Sha}. Due: {DueDate}. | <div dir="rtl">{Submitter} הגיש/ה את {DocumentId} גרסה {Revision} לאישורך. תקציר השינוי: {ChangeSummary}. קובץ (קריאה בלבד): {UncPath}. SHA-256: {Sha}. תאריך יעד: {DueDate}.</div> |
| `msg.approved.owner` | {DocumentId} revision {Revision} was approved and is now the current read-only revision. | <div dir="rtl">{DocumentId} גרסה {Revision} אושרה והיא כעת הגרסה הנוכחית לקריאה בלבד.</div> |
| `msg.rejected.owner` | {DocumentId} revision {Revision} was rejected by {Approver}. Comment: {Comment}. The draft was returned to Working. | <div dir="rtl">{DocumentId} גרסה {Revision} נדחתה על ידי {Approver}. הערה: {Comment}. הטיוטה הוחזרה לתיקיית העבודה.</div> |
| `msg.reminder` | Reminder: {DocumentId} revision {Revision} has been waiting for your decision for {Days} days. | <div dir="rtl">תזכורת: {DocumentId} גרסה {Revision} ממתינה להחלטתך {Days} ימים.</div> |
| `msg.escalation` | Escalation: {Approver} has not decided on {DocumentId} {Revision} for {Days} days. | <div dir="rtl">הסלמה: {Approver} טרם החליט/ה על {DocumentId} {Revision} כבר {Days} ימים.</div> |
| `msg.cancelled` | The approval of {DocumentId} revision {Revision} was cancelled by {Actor}. Reason: {Comment}. | <div dir="rtl">תהליך האישור של {DocumentId} גרסה {Revision} בוטל על ידי {Actor}. סיבה: {Comment}.</div> |
| `msg.draft.ready` | Draft {Revision} of {DocumentId} is ready for editing: {UncPath} | <div dir="rtl">טיוטה {Revision} של {DocumentId} מוכנה לעריכה: {UncPath}</div> |
| `msg.review.due` | {DocumentId} - {Title} is due for periodic review on {NextReviewDate}. | <div dir="rtl">{DocumentId} - {Title} מגיע לסקירה תקופתית בתאריך {NextReviewDate}.</div> |
| `msg.review.overdue` | {DocumentId} - {Title} is overdue for periodic review (due {NextReviewDate}). | <div dir="rtl">{DocumentId} - {Title} חרג ממועד הסקירה התקופתית ({NextReviewDate}).</div> |
| `msg.obsolete` | {DocumentId} - {Title} is now obsolete (read-only). Reason: {Comment}. | <div dir="rtl">{DocumentId} - {Title} בוטל (קריאה בלבד). סיבה: {Comment}.</div> |
| `msg.fileaction.failed` | File action {ActionType} failed for {DocumentId} {Revision}: {Error} | <div dir="rtl">פעולת הקובץ {ActionType} נכשלה עבור {DocumentId} {Revision}: {Error}</div> |
| `msg.delegation.active` | {Delegate} is acting for {Delegator} from {ValidFrom} to {ValidTo}. | <div dir="rtl">{Delegate} ממלא/ת את מקומו/ה של {Delegator} מתאריך {ValidFrom} עד {ValidTo}.</div> |
| `msg.ex.created` | Exchange request {RequestId} was created. Upload through: {UploadUrl}. The link expires on {ExpiryDate}. | <div dir="rtl">בקשת העברה {RequestId} נוצרה. העלאה דרך: {UploadUrl}. הקישור בתוקף עד {ExpiryDate}.</div> |
| `msg.ex.transferred` | {RequestId}: {FileName} ({SizeGB} GB) was transferred and verified (SHA-256 {Sha}). It is waiting in quarantine for Document Control. | <div dir="rtl">{RequestId}: {FileName} ({SizeGB} GB) הועבר ואומת (SHA-256 {Sha}). הקובץ ממתין בהסגר לבקרת מסמכים.</div> |
| `msg.ex.failed` | {RequestId}: transfer failed. {Error}. IT was notified. The cloud copy was kept. | <div dir="rtl">{RequestId}: ההעברה נכשלה. {Error}. מערכות מידע קיבלו הודעה. העותק בענן נשמר.</div> |
| `msg.ex.accepted` | {RequestId}: {FileName} was accepted by {Actor} and routed to {Destination}. | <div dir="rtl">{RequestId}: {FileName} התקבל על ידי {Actor} ונותב אל {Destination}.</div> |
| `msg.ex.rejected` | {RequestId}: {FileName} was rejected by {Actor}. Reason: {Comment}. | <div dir="rtl">{RequestId}: {FileName} נדחה על ידי {Actor}. סיבה: {Comment}.</div> |
| `msg.ex.expiring` | {RequestId}: the upload link expires in {Days} days. | <div dir="rtl">{RequestId}: קישור ההעלאה יפוג בעוד {Days} ימים.</div> |
| `msg.ex.expired` | {RequestId} expired and its temporary content was removed. | <div dir="rtl">{RequestId} פג תוקף והתוכן הזמני הוסר.</div> |
| `msg.ex.deletefailed` | {RequestId}: the cloud copy could not be deleted after a verified transfer. Manual action required. | <div dir="rtl">{RequestId}: לא ניתן היה למחוק את העותק בענן לאחר העברה מאומתת. נדרשת פעולה ידנית.</div> |

## 4. Application labels (seeded in UI Labels)

Column captions (`field.*`, 108), list names (`list.*`, 13) and choice captions (`choice.*`, 127) are generated from the same definitions as the SharePoint schema, so they always match. They are listed in [01-Architecture-and-Data-Model.md](01-Architecture-and-Data-Model.md).

| Key | English | עברית |
| --- | --- | --- |
| `app.title.dcc` | Document Control Center | מרכז בקרת מסמכים |
| `app.title.lfe` | Large File Exchange Control | בקרת העברת קבצים גדולים |
| `app.nav.home` | Home | ראשי |
| `app.nav.register` | Document Register | מרשם מסמכים |
| `app.nav.approvals` | My Approvals | האישורים שלי |
| `app.nav.doccontrol` | Document Control | בקרת מסמכים |
| `app.nav.admin` | Administration | ניהול |
| `app.nav.settings` | Settings | הגדרות |
| `app.tile.mydocs` | My documents | המסמכים שלי |
| `app.tile.pending` | Waiting for my approval | ממתינים לאישורי |
| `app.tile.submitted` | In approval | בתהליך אישור |
| `app.tile.duereview` | Due for review | לסקירה תקופתית |
| `app.tile.failed` | Failed file actions | פעולות קבצים שנכשלו |
| `app.btn.new` | New document | מסמך חדש |
| `app.btn.newrev` | Create new revision | יצירת גרסה חדשה |
| `app.btn.submit` | Submit for approval | הגשה לאישור |
| `app.btn.cancelwf` | Cancel workflow | ביטול תהליך |
| `app.btn.changeapprovers` | Change approvers (restart) | שינוי מאשרים (הפעלה מחדש) |
| `app.btn.obsolete` | Make obsolete | העברה לבוטל |
| `app.btn.openfolder` | Open folder | פתיחת תיקייה |
| `app.btn.copypath` | Copy UNC path | העתקת נתיב UNC |
| `app.btn.save` | Save | שמירה |
| `app.btn.cancel` | Cancel | ביטול |
| `app.btn.back` | Back | חזרה |
| `app.btn.search` | Search | חיפוש |
| `app.btn.newrequest` | New request | בקשה חדשה |
| `app.btn.ready` | Ready for transfer | מוכן להעברה |
| `app.btn.accept` | Accept | קבלה |
| `app.btn.reject` | Reject | דחייה |
| `app.btn.upload` | Open upload folder | פתיחת תיקיית העלאה |
| `app.lbl.language` | Language | שפה |
| `app.lbl.required` | Required | שדה חובה |
| `app.lbl.requiredapprovers` | Required approvers (cannot be removed) | מאשרי חובה (לא ניתן להסיר) |
| `app.lbl.addreviewers` | Add reviewers | הוספת סוקרים |
| `app.lbl.impact` | What does this change affect? | על מה משפיע השינוי? |
| `app.lbl.summary` | Change summary | תקציר השינוי |
| `app.lbl.history` | Approval history | היסטוריית אישורים |
| `app.lbl.checksum` | Checksum (SHA-256) | ערך בקרה (SHA-256) |
| `app.lbl.search` | Search by ID, title, customer or project | חיפוש לפי מזהה, כותרת, לקוח או פרויקט |
| `app.lbl.nodata` | No items to show | אין פריטים להצגה |
| `app.lbl.expiry` | Upload link expires on | קישור ההעלאה בתוקף עד |
| `app.err.required` | Complete all required fields | יש למלא את כל שדות החובה |
| `app.err.approvers` | A required approver is missing | חסר מאשר חובה |
| `app.err.duplicate` | A request for this package is already in progress | בקשה עבור חבילה זו כבר בטיפול |
| `app.err.path` | The destination route is not approved | נתיב היעד אינו מאושר |
| `app.ok.submitted` | Submitted. Approvers were notified in Teams. | הוגש. המאשרים קיבלו הודעה ב-Teams. |
| `app.ok.saved` | Saved | נשמר |

## 5. תקציר מנהלים (עברית)

<div dir="rtl">

**מטרה.** להקים מערכת בקרת מסמכים ארגונית לפי תכנית IT-DOC-BP-001, שבה הקבצים נשארים בשרת הקבצים המקומי ו-Microsoft 365 משמש כשכבת בקרה בלבד (מטא-דאטה, אישורים, התראות והעברת קבצים חיצונית).

**מבנה.** שני אתרי SharePoint:

- **בקרת מסמכים** (פנימי בלבד, שיתוף חיצוני חסום): מרשם מסמכים, היסטוריית תהליכים, החלטות מאשרים, מטריצת מאשרים, ניתוב לפי השפעה, האצלות סמכות, תור פעולות קבצים, יומן ביקורת ותוויות ממשק.
- **העברת קבצים גדולים** (אורחים מאומתים בלבד, ללא קישורים אנונימיים): העלאות זמניות, בקשות העלאה, יומן ביקורת וקטלוג ניתוב.

**מחזור חיים של מסמך.** בעבודה ← הוגש לאישור ← מאושר (קריאה בלבד) ← שוחרר ל-PLM ← מבוטל ← ארכיון. דחייה מחזירה את הטיוטה לתיקיית העבודה.

**אישורים דינמיים.** מאשרי החובה והמאשר הסופי נקבעים ממטריצת המאשרים, ומאשרים נוספים מתווספים לפי השפעת השינוי. המגיש יכול להוסיף סוקרים אך אינו יכול להסיר מאשרי חובה. הבדיקה מתבצעת גם בשרת. שינוי מאשרים לאחר הגשה מבטל את המחזור ופותח מחזור חדש. האישור מתבצע באפליקציית האישורים של Teams.

**הזזת קבצים.** Power Automate לא נוגע בקבצים. כל פעולת קובץ נרשמת כפקודה בתור, ושירות מקומי (חשבון gMSA) מבצע אותה, מחשב SHA-256 ומדווח חזרה. קידום גרסה נחסם אם ערך הבקרה שונה מזה שאושר.

**הרשאות.** כל ההרשאות ניתנות לקבוצות בלבד (AD ו-Entra). היסטוריית האישורים ניתנת לכתיבה רק על ידי חשבון השירות, ויומני הביקורת הם בהוספה בלבד.

**שפה.** כל שמות העמודות, התצוגות וההודעות זמינים באנגלית ובעברית. הערכים השמורים נשארים באנגלית כדי שהתהליכים לא יישברו בעת החלפת שפה.

**הפעלה.** מריצים את `Provision-DMS.ps1` עם `-Language he`, משייכים קבוצות Entra לקבוצות SharePoint, ממלאים אנשים במטריצת המאשרים, מייבאים את פתרון Power Platform ומבצעים פיילוט של שבועיים לפי שלב 10 בתכנית.

</div>
