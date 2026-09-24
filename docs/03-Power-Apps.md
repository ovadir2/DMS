# 03 - Power Apps

Two responsive **Canvas** apps, both in the unmanaged solution `RH Document Control` (blueprint Appendix B).

| App | Users | Purpose |
|---|---|---|
| **Document Control Center** / מרכז בקרת מסמכים | All employees, approvers, Document Control | Register, revisions, submit for approval with dynamic approvers, history, Document Control queue, administration |
| **Large File Exchange Control** / בקרת העברת קבצים גדולים | Employees, Document Control | Blueprint 9.3: request, native upload, status, accept or reject |

### Why Canvas and not model-driven

A model-driven app needs Dataverse tables, which are a **premium** capability outside Microsoft 365 Business Premium. The blueprint (Phase 1) keeps the solution on standard connectors: SharePoint, Teams, Office 365 Users, plus Approvals. A Canvas app over SharePoint lists meets every requirement without extra licences. If the company later buys Power Apps Premium, the same data model can move to Dataverse and a model-driven app. The lists map 1:1 to tables.

## 1. Common foundations (both apps)

### 1.1 Data sources

| Source | Document Control Center | Large File Exchange Control |
|---|---|---|
| SharePoint `/sites/DocumentControl` | Document Register, Workflow History, Approval Decisions, Approver Matrix, Impact Routing, Delegations, File Action Queue, UI Labels | UI Labels |
| SharePoint `/sites/LargeFileExchange` | - | Upload Requests, Exchange Audit, Routing Catalog |
| Office 365 Users | Yes | Yes |
| Flows (Power Apps V2 trigger) | DC-00, DC-01, DC-02, DC-03, DC-07, DC-09 | EX-01, EX-03, EX-06, EX-07 |

App settings: **Data row limit = 2000**, *Delayed load* on, *Explicit column selection* on, *Formula-level error management* on.

Build the apps **inside the solution** with the Power Apps setting *Automatically create environment variables when adding data sources* switched on. Each SharePoint data source is then bound to environment variables (`dms_SiteUrl_DC`, `dms_SiteUrl_EX` and one per list). On import to TEST or PROD you only supply new values, and no formula changes are needed (blueprint Appendix B, "No hard-coded tenant URLs").

### 1.2 Localization (English / Hebrew)

All visible text comes from the **UI Labels** list. Nothing is hard-coded, so Document Control can correct a translation without republishing the app.

**App.OnStart**

```powerfx
// 1. Language: saved preference, then the browser / Teams language
LoadData(colPrefs, "dmsPrefs", true);
Set(gblLang,
    Coalesce(
        LookUp(colPrefs, Key = "lang").Value,
        If(StartsWith(Lower(Language()), "he"), "he", "en")
    )
);
Set(gblRTL, gblLang = "he");

// 2. Labels (about 320 rows, below the 2000 row limit)
ClearCollect(colLabelSrc, ShowColumns('UI Labels', Title, LabelEN, LabelHE));
ClearCollect(colL,
    ForAll(colLabelSrc, {Key: ThisRecord.Title, Text: If(gblRTL, ThisRecord.LabelHE, ThisRecord.LabelEN)})
);

// 3. User context from DC-00 (role flags without granting list-level rights)
Set(gblMe, DMS_DC00_GetUserContext.Run());
//    returns { isDocumentController: Boolean, isAdmin: Boolean, preferredLanguage: Text }

// 4. Small reference lists cached once
ClearCollect(colMatrix, Filter('Approver Matrix', IsActive = true));
ClearCollect(colImpactRules, Filter('Impact Routing', IsActive = true));
```

**Label lookups**

| Need | Formula |
|---|---|
| Static label | `LookUp(colL, Key = "app.nav.register").Text` |
| Column caption | `LookUp(colL, Key = "field.LifecycleStatus").Text` |
| Choice value | `LookUp(colL, Key = "choice.LifecycleStatus." & ThisItem.LifecycleStatus.Value).Text` |
| Message with a token | `Substitute(LookUp(colL, Key = "app.lbl.expiry").Text, "{Date}", Text(ThisItem.ExpiryDate, DateTimeFormat.ShortDate))` |

**Right-to-left layout**

| Property | Formula |
|---|---|
| Every label and text input `Align` | `If(gblRTL, Align.Right, Align.Left)` |
| Gallery template control `X` | `If(gblRTL, Parent.TemplateWidth - Self.Width - 16, 16)` |
| Horizontal containers | Put controls in the reading order of each language with `If(gblRTL, ...)` on `X`, or use two containers with `Visible = gblRTL` and `Visible = !gblRTL` for complex headers |
| Icons that show direction (back / next) | `Icon = If(gblRTL, Icon.ChevronRight, Icon.ChevronLeft)` for Back |
| Dates | `Text(value, DateTimeFormat.ShortDate, If(gblRTL, "he-IL", "en-US"))` |

**Language toggle** (header of every screen)

```powerfx
// tglLang.OnChange
Set(gblLang, If(Self.Value, "he", "en"));
Set(gblRTL, gblLang = "he");
ClearCollect(colL, ForAll(colLabelSrc, {Key: ThisRecord.Title, Text: If(gblRTL, ThisRecord.LabelHE, ThisRecord.LabelEN)}));
ClearCollect(colPrefs, {Key: "lang", Value: gblLang});
SaveData(colPrefs, "dmsPrefs")     // remembers the choice on this device
```

### 1.3 Design system

| Token | Value |
|---|---|
| Font | `Font.'Segoe UI'` (it renders Hebrew correctly) |
| Primary | `ColorValue("#0F4C81")` |
| Success / Warning / Danger | `#107C10` / `#C19C00` / `#A4262C` |
| Surface / Border | `#FFFFFF` / `#E1E1E1` |
| Spacing | 8 / 16 / 24 |
| Status chip | Rounded rectangle, fill by status: Working grey, Submitted amber, Approved green, Released blue, Obsolete dark grey, Rejected red |

Use responsive containers. Set the screen `Width = Max(App.Width, App.MinScreenWidth)`, and use a vertical container per screen with a header, body and footer.

### 1.4 Guardrails (blueprint 9.3, applied to both apps)

- There is **no** attachment control, `JSONFormat.IncludeBinaryData`, file variable or image upload anywhere.
- The apps never `Patch` controlled lists directly. Every write goes through a flow, which runs as the service connection, validates on the server and writes the audit event. Users only need **Read** on the lists.
- Buttons are disabled while a flow runs (`gblBusy`), and states that must not repeat (Submitted, ReadyForTransfer, Transferring, Transferred) disable their button.
- UNC paths are shown as text with **Copy** (`Copy(ThisItem.CurrentUncPath)`). Browsers block `file://` links, so the app does not try to launch them.

## 2. App 1 - Document Control Center

### 2.1 Screens

| Screen | Purpose | Main controls |
|---|---|---|
| `scrHome` | Personal dashboard | 5 tiles (my documents, waiting for my approval, in approval, due for review, failed file actions for Document Control), recent activity gallery, **New document** |
| `scrRegister` | Search and browse | Search box, filters (Area, Type, Status, Owner = me), gallery with status chips, sort |
| `scrDocument` | Record detail | Metadata form (view mode), paths with Copy, checksum, PLM/MAE/Priority references, **Approval history** gallery, action bar |
| `scrNewDocument` | Register a controlled document | Edit form: Title, Area, Type, Control mode (locked to *Workflow Required* for mandatory types), Owner, Department, Customer, Project, Classification, Retention, Language, Review cycle, Working UNC path |
| `scrSubmit` | Submit revision for approval | Locked required approvers, suggested conditional approvers, add reviewers, Change Impact, Change Summary, Due date, routing mode (Document Control only) |
| `scrMyApprovals` | Approver inbox | Pending Approval Decisions for me, with a deep link to the Teams Approvals app (the decision itself is made in Teams) |
| `scrDocControl` | Document Control queue | Tabs: In approval, Failed file actions, Overdue reviews, Obsolete requests. Actions: cancel workflow, retry file action, make obsolete |
| `scrAdmin` | Reference data | Approver Matrix, Impact Routing, Delegations and UI Labels galleries with edit forms (visible only when `gblMe.isDocumentController`) |

### 2.2 Key formulas

**Register gallery `galRegister.Items`** (delegable: `StartsWith` and `=` on indexed columns)

```powerfx
SortByColumns(
    Filter('Document Register',
        (IsBlank(txtSearch.Value) || StartsWith(DocumentId, txtSearch.Value) || StartsWith(Title, txtSearch.Value)
            || StartsWith(CustomerCode, txtSearch.Value) || StartsWith(ProjectCode, txtSearch.Value)),
        (IsBlank(ddArea.Selected.Value)   || DocumentArea.Value   = ddArea.Selected.Value),
        (IsBlank(ddType.Selected.Value)   || DocumentType.Value   = ddType.Selected.Value),
        (IsBlank(ddStatus.Selected.Value) || LifecycleStatus.Value = ddStatus.Selected.Value),
        (!tglMine.Value || DocumentOwner.Email = User().Email)
    ),
    "DocumentId", SortOrder.Ascending
)
```

**Choice dropdowns with localized text** (for example `ddStatus.Items`)

```powerfx
AddColumns(Choices('Document Register'.LifecycleStatus),
    Label, LookUp(colL, Key = "choice.LifecycleStatus." & Value).Text)
// DisplayFields = ["Label"], filter uses .Value (the English key)
```

**Action bar visibility on `scrDocument`** (`varDoc` is the selected register item)

```powerfx
btnNewRevision.Visible = varDoc.LifecycleStatus.Value in ["Approved_ReadOnly", "Released_PLM"]
                         && (varDoc.DocumentOwner.Email = User().Email || gblMe.isDocumentController)
                         && IsBlank(varDoc.ActiveWorkflowId)
btnSubmit.Visible      = varDoc.LifecycleStatus.Value = "Working"
                         && varDoc.ControlMode.Value <> "Collaboration"
                         && varDoc.DocumentOwner.Email = User().Email
btnCancelWf.Visible    = varDoc.LifecycleStatus.Value = "Submitted"
                         && (varDoc.DocumentOwner.Email = User().Email || gblMe.isDocumentController)
btnObsolete.Visible    = gblMe.isDocumentController
                         && varDoc.LifecycleStatus.Value in ["Approved_ReadOnly", "Released_PLM"]
```

**Approval history `galHistory.Items`**

```powerfx
SortByColumns(Filter('Approval Decisions', DocumentId = varDoc.DocumentId), "Created", SortOrder.Descending)
```

**New document `btnSave.OnSelect`**

```powerfx
If(
    IsBlank(txtTitle.Value) || IsBlank(ddArea.Selected) || IsBlank(ddType.Selected) || IsBlank(ppOwner.Selected),
    Notify(LookUp(colL, Key = "app.err.required").Text, NotificationType.Error),
    Set(gblBusy, true);
    Set(varResult, DMS_DC01_RegisterDocument.Run(
        txtTitle.Value, ddArea.Selected.Value, ddType.Selected.Value, ddControlMode.Selected.Value,
        ppOwner.Selected.Email, txtDepartment.Value, txtCustomer.Value, txtProject.Value,
        ddClassification.Selected.Value, ddRetention.Selected.Value, ddLanguage.Selected.Value,
        numReviewMonths.Value, txtWorkingPath.Value));
    Set(gblBusy, false);
    If(varResult.status = "ok",
        Notify(LookUp(colL, Key = "app.ok.saved").Text & " " & varResult.documentid, NotificationType.Success);
        Set(varDoc, LookUp('Document Register', DocumentId = varResult.documentid));
        Navigate(scrDocument),
        Notify(varResult.message, NotificationType.Error))
)
```

`ddControlMode.DisplayMode` locks the mode for mandatory types:

```powerfx
If(ddType.Selected.Value in ["Policy","Procedure","Contract / NDA","ECO / ECN","Work Instruction","Test Procedure",
    "PFMEA / Control Plan","IT Procedure","Security Policy"], DisplayMode.Disabled, DisplayMode.Edit)
// ddControlMode.Default: same test → "Workflow Required", else "Workflow Optional"
```

**Submit screen - build approvers (`scrSubmit.OnVisible`)**

```powerfx
Set(varRule, LookUp(colMatrix, DocumentType.Value = varDoc.DocumentType.Value));
ClearCollect(colRequired,
    ForAll(varRule.MandatoryApprovers As p, {Email: Lower(p.Email), Name: p.DisplayName, Role: "Mandatory", Locked: true}),
    If(!IsBlank(varRule.FinalApprover.Email),
        {Email: Lower(varRule.FinalApprover.Email), Name: varRule.FinalApprover.DisplayName, Role: "Final", Locked: true})
);
ClearCollect(colSuggested,
    ForAll(varRule.ConditionalApprovers As p, {Email: Lower(p.Email), Name: p.DisplayName, Role: "Conditional", Include: true})
);
Clear(colReviewers);
Reset(cmbImpact); Reset(txtSummary)
```

**When Change Impact changes (`cmbImpact.OnChange`)** - impact approvers become locked

```powerfx
RemoveIf(colRequired, Role = "Impact");
ForAll(cmbImpact.SelectedItems As imp,
    ForAll(Filter(colImpactRules, imp.Value in ChangeImpact.Value) As r,
        ForAll(r.IncludeApprovers As p,
            If(IsBlank(LookUp(colRequired, Email = Lower(p.Email))),
                Collect(colRequired, {Email: Lower(p.Email), Name: p.DisplayName, Role: "Impact", Locked: true})))));
// Remove suggestions that are now required
RemoveIf(colSuggested, Email in colRequired.Email)
```

`cmbImpact.Items`:

```powerfx
AddColumns(Choices('Workflow History'.ChangeImpact), Label, LookUp(colL, Key = "choice.ChangeImpact." & Value).Text)
```

**Add reviewer (`cmbReviewer.Items`, search as you type)**

```powerfx
Filter(Office365Users.SearchUserV2({searchTerm: Self.SearchText, top: 15, isSearchTermRequired: true}).value,
       AccountEnabled = true && !(Lower(Mail) in colRequired.Email) && Lower(Mail) <> Lower(User().Email))
// btnAddReviewer.OnSelect:
Collect(colReviewers, {Email: Lower(cmbReviewer.Selected.Mail), Name: cmbReviewer.Selected.DisplayName, Role: "Reviewer"})
```

**Submit (`btnSubmit.OnSelect`)**

```powerfx
If(
    IsBlank(txtSummary.Value) || CountRows(colRequired) = 0,
    Notify(LookUp(colL, Key = "app.err.required").Text, NotificationType.Error),
    // A conditional approver that was unticked needs a justification (audit)
    CountRows(Filter(colSuggested, !Include)) > 0 && IsBlank(txtJustification.Value),
    Notify(LookUp(colL, Key = "app.err.approvers").Text, NotificationType.Error),
    Set(gblBusy, true);
    Set(varResult, DMS_DC03_SubmitForApproval.Run(
        varDoc.DocumentId,
        varDoc.DraftRevision,
        txtSummary.Value,
        Concat(cmbImpact.SelectedItems, Value, ";"),
        Concat(Filter(colRequired, Role in ["Mandatory","Impact"]), Email, ";"),
        Concat(Filter(colSuggested, Include), Email, ";"),
        Concat(colReviewers, Email, ";"),
        First(Filter(colRequired, Role = "Final")).Email,
        Text(dpDue.SelectedDate, "yyyy-mm-dd"),
        txtJustification.Value));
    Set(gblBusy, false);
    If(varResult.status = "ok",
        Notify(LookUp(colL, Key = "app.ok.submitted").Text, NotificationType.Success); Back(),
        Notify(varResult.message, NotificationType.Error))
)
```

The flow recomputes the required set from the matrix and impact rules, so a tampered client cannot drop an approver (see DC-03).

**Required approver chips (`galRequired`)**. Items = `colRequired`. Show a lock icon, and do **not** show a remove icon. `galSuggested` has a checkbox bound to `Include`, and `galReviewers` has a remove icon (`Remove(colReviewers, ThisItem)`).

**Home tiles**

```powerfx
lblMyDocs.Text    = CountRows(Filter('Document Register', DocumentOwner.Email = User().Email))
lblPending.Text   = CountRows(Filter('Approval Decisions', Approver.Email = User().Email && Decision.Value = "Pending"))
lblInReview.Text  = CountRows(Filter('Workflow History', WorkflowStatus.Value = "InReview"))
lblDue.Text       = CountRows(Filter('Document Register', NextReviewDate <= DateAdd(Today(), 30)
                        && LifecycleStatus.Value in ["Approved_ReadOnly","Released_PLM"]))
lblFailed.Visible = gblMe.isDocumentController
lblFailed.Text    = CountRows(Filter('File Action Queue', ActionStatus.Value = "Failed"))
```

`CountRows` over SharePoint is not delegable. The tiles are accurate up to the 2000-row limit and are informational only. The lists behind them stay far below that for any single filter. Use the *Due for Review* SharePoint view for audits.

### 2.3 Build steps

1. Power Apps → Solutions → `RH Document Control` → New → App → Canvas app → *Tablet* format → name **Document Control Center**.
2. Add the data sources in 1.1. Add the flows after they exist (flows first, see 04).
3. Settings → Display → *Scale to fit* off, *Lock aspect ratio* off (responsive).
4. Paste `App.OnStart` (1.2). Add the header component `cmpHeader` (title, language toggle, user photo `Office365Users.UserPhotoV2(User().Email)`).
5. Build the screens in 2.1 using vertical and horizontal containers. Bind every `Text` to `colL`.
6. Apply the formulas in 2.2.
7. Test in both languages. Publish, then share with the **Entra group** `GG_DMS_PilotUsers` (Phase 8), and later `GG_DMS_Employees`. Never share with individuals.
8. Set `gblMe`-driven visibility for the admin screens. Hiding a screen is not security. The flows and list permissions enforce the real rules.

### 2.4 Copilot prompt (Power Apps "Describe your app")

Copilot scaffolds best from Dataverse, so use it to create the *layout*. Then connect the SharePoint lists and paste the formulas above.

```text
Create a responsive tablet canvas app called "Document Control Center" for an enterprise document
control system. Use a clean corporate style with a dark blue header (#0F4C81) and the Segoe UI font.

Screens:
1. Home: header with app title, a language toggle (English/Hebrew) and the user photo; five KPI tiles
   (My documents, Waiting for my approval, In approval, Due for review, Failed file actions); a gallery
   of my recent documents; a "New document" button.
2. Register: search box, dropdown filters for Area, Type and Status, a "Mine only" toggle, and a gallery
   with Document ID, Title, Type, Revision, a colored status chip, Owner and Next review date.
3. Document details: read-only form with all metadata, two text fields showing UNC paths each with a
   Copy button, a checksum field, an approval history gallery (approver, role, stage, decision, date,
   comment), and an action bar with New revision, Submit for approval, Cancel workflow, Make obsolete.
4. New document: edit form with Title, Area, Type, Control mode, Owner (people picker), Department,
   Customer code, Project code, Classification, Retention class, Document language, Review cycle
   months and Working UNC path; Save and Cancel buttons.
5. Submit for approval: a gallery of locked required approvers with a lock icon, a gallery of
   suggested approvers with checkboxes, a people search box to add reviewers, a multi-select
   combo box "What does this change affect?", a multi-line Change summary, a Due date picker, a
   Justification text box, and a Submit button.
6. My approvals: gallery of pending decisions with document, revision, role, due date and a button
   "Open in Teams".
7. Document Control: tabbed view with In approval, Failed file actions, Overdue reviews.
8. Administration: tabs for Approver matrix, Impact routing, Delegations and UI labels, each a
   gallery with an edit form.
Do not add any attachment or file upload control. All text must come from variables so it can be
translated; support right-to-left layout for Hebrew.
```

## 3. App 2 - Large File Exchange Control (blueprint 9.3)

### 3.1 Screens

| Screen | Purpose | Main controls |
|---|---|---|
| `scrHome` | Dashboard | My requests, pending acceptance (Document Control), failures, **New request** |
| `scrNewRequest` | Create request | Customer (Routing Catalog), Project (filtered by customer), Direction, Package description, Destination route (from catalog, read-only), Guest email (optional), Submit |
| `scrRequestStatus` | Track request | State chip, file name, size (GB), SHA-256, destination, expiry, cloud-deletion state, actions |
| `scrDocumentControl` | Accept or reject | Transferred and failed queue, comment, routing destination, Accept / Reject |

### 3.2 Formulas (blueprint, adjusted to this data model)

**New Request `btnSubmit.OnSelect`**

```powerfx
If(
    IsBlank(ddCustomer.Selected.CustomerCode) || IsBlank(ddProject.Selected.ProjectCode) || IsBlank(txtPackageDescription.Value),
    Notify(LookUp(colL, Key = "app.err.required").Text, NotificationType.Error),
    Set(gblBusy, true);
    Set(varRequest, DMS_EX01_CreateExchangeRequest.Run(
        ddCustomer.Selected.CustomerCode,
        ddProject.Selected.ProjectCode,
        ddDirection.Selected.Value,
        txtPackageDescription.Value,
        ddProject.Selected.ID,            // route is resolved on the server from the Routing Catalog ID
        Lower(User().Email),
        Lower(txtGuestEmail.Value)));
    Set(gblBusy, false);
    If(varRequest.status = "ok",
        Launch(varRequest.uploadurl);     // native SharePoint library upload page for the request folder
        Set(varSel, LookUp('Upload Requests', RequestId = varRequest.requestid));
        Navigate(scrRequestStatus),
        Notify(varRequest.message, NotificationType.Error))
)
```

`ddCustomer.Items`:

```powerfx
Distinct(Filter('Routing Catalog', IsActive = true), CustomerCode)
// ddProject.Items:
Filter('Routing Catalog', IsActive = true && CustomerCode = ddCustomer.Selected.Value)
```

Destinations always come from the Routing Catalog, never from free text (blueprint guardrail "Destination routes must come from approved customer/project routing data", AC-09).

**Dashboard gallery**

```powerfx
SortByColumns(
    Filter('Upload Requests', UploaderEmail = Lower(User().Email) || gblMe.isDocumentController),
    "Modified", SortOrder.Descending)
```

**Action visibility**

```powerfx
btnReadyForTransfer.Visible = ThisItem.ExchangeStatus.Value = "Uploaded"
btnCancel.Visible           = ThisItem.ExchangeStatus.Value in ["Draft","AwaitingUpload","Uploaded"]
btnAccept.Visible           = ThisItem.ExchangeStatus.Value = "Transferred" && gblMe.isDocumentController
btnReject.Visible           = btnAccept.Visible
btnUpload.Visible           = ThisItem.ExchangeStatus.Value in ["AwaitingUpload","Uploaded"]
lblSize.Text                = Text(ThisItem.ExpectedSizeBytes / 1073741824, "0.00") & " GB"
lblCloud.Text               = LookUp(colL, Key = "field.CloudCopyDeleted").Text & ": " &
                              If(ThisItem.CloudCopyDeleted, "✓", "✗")
```

### 3.3 Copilot prompt

```text
Create a responsive tablet canvas app called "Large File Exchange Control". Four screens:
Home (tiles for My requests, Pending acceptance, Failed transfers, a gallery of requests with a colored
status chip, and a New request button); New request (dropdowns for Customer and Project, a Direction
dropdown Inbound/Outbound, a multi-line Package description, a read-only Destination route label, an
optional Customer guest email, and a Submit button); Request status (status chip, file name, size in GB,
SHA-256, destination, expiry date, cloud copy deleted indicator, and buttons Open upload folder, Ready for
transfer, Cancel); Document Control (gallery of Transferred and TransferFailed requests with a comment box
and Accept / Reject buttons). Never include an attachment or file upload control; uploads happen in the
SharePoint library opened with Launch(). Support English and Hebrew right-to-left labels from variables.
```

## 4. Test script (both apps)

| # | Test | Expected |
|---|---|---|
| 1 | Switch language on every screen | All text changes, alignment mirrors, and no raw keys (`app.xxx`) are visible |
| 2 | Register a Policy | Control mode is locked to *Workflow Required*. The ID is `MGT-POL-00001` |
| 3 | Submit without a summary | Error, nothing is created |
| 4 | Try to remove a locked approver | Not possible in the UI. A crafted flow call is rejected by DC-03 |
| 5 | Untick a conditional approver without a justification | Error |
| 6 | Double-click Submit | One Workflow History item only (`gblBusy` + DC-03 idempotency check) |
| 7 | Exchange request, upload 2+ GB | Upload happens in the SharePoint page. The app only shows metadata (AC-01, AC-03) |
