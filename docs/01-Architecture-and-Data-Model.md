# 01 - Architecture and Data Model

Source: IT-DOC-BP-001 v1.0, sections 3, 4, 6.3, 8 and 9.

## 1. Guiding principle (from the blueprint)

The Windows file server stores the files. SharePoint stores control metadata. Teams carries interaction. Power Automate orchestrates decisions. On-premises workers move files. PLM/MAE and Priority remain the final authorities.

Three hard rules shape everything below.

| Rule | Consequence in this design |
|---|---|
| REQ-01 / REQ-02 - active files stay on-premises (20+ TB) | SharePoint never holds the controlled file. The register holds UNC paths and SHA-256 checksums |
| REQ-17 - no binary content in Power Apps / Power Automate | Attachments are disabled on every list. File moves are queued as commands for an on-premises **Workflow Service**, and large uploads use the native SharePoint library plus the **Transfer Worker** |
| REQ-16 - no direct permissions to individuals | Every grant goes to a group (AD on the file server, SharePoint groups backed by Entra groups in M365) |

## 2. Site topology

The blueprint lists all five SharePoint objects on one Exchange site (section 9.1). This implementation splits them across **two site collections**. The Exchange site keeps exactly the blueprint's objects. The controlled-document register moves to an internal-only site.

| Site | URL | Sharing | Contents | Why |
|---|---|---|---|---|
| Document Control | `/sites/DocumentControl` | **Disabled** (internal only) | Document Register, Workflow History, Approval Decisions, Approver Matrix, Impact Routing, Delegations, File Action Queue, Control Audit, UI Labels | B2B guests can never reach the controlled register, even through a misconfigured folder share |
| Large File Exchange | `/sites/LargeFileExchange` | Existing and new **authenticated guests**, Specific-people links, no anonymous links | Temporary Uploads, Upload Requests, Exchange Audit, Routing Catalog | Matches blueprint 9.1 and Phase 3. The Transfer Worker gets `Sites.Selected` on this site only |

Both sites are created as *Team site without a Microsoft 365 group* (STS#3). A group-connected site would add every group member to the site members and create a Teams team with its own sharing surface, which the blueprint's isolation model (8.4) rules out. Teams notifications go to a separate Document Control team and channel that you already own.

## 3. Logical architecture

```
 Users ─────────────┬─────────────────────────┬──────────────────────────────┐
  Employees         │ Canvas: Document Control │ Canvas: Large File Exchange │  Windows Explorer (mapped drive)
  Document Control  │ Center                   │ Control                     │
  Approvers         │ Teams Approvals app      │                             │
  B2B guests        │                          │ SharePoint request folder   │
────────────────────┼──────────────────────────┼─────────────────────────────┼──────────────────────────────
 M365 control plane │ SharePoint lists (metadata only) ── Power Automate (metadata only) ── Teams
────────────────────┼──────────────────────────────────────────────────────────────────────────────────────
 Integration        │ Workflow Service (gMSA, Graph Sites.Selected on DC site)   polls File Action Queue
 (on-prem server)   │ Transfer Worker (gMSA, Graph Sites.Selected on EX site)    polls Upload Requests
────────────────────┼──────────────────────────────────────────────────────────────────────────────────────
 On-premises        │ \\FILE-SERVER\Corporate_Data (NTFS, AGDLP)   CrowdStrike   Veeam (immutable + 7Y GFS)
 Systems of record  │ PLM/MAE (released engineering)   Priority ERP (operational)
```

### 3.1 Why a File Action Queue

Power Automate cannot move on-premises files without the File System connector and a data gateway, and the blueprint forbids that path (9.4 "Forbidden flow actions"). The blueprint also says *"The workflow service account, not the approver, moves files and changes permissions"* (4.2).

So every file operation is written as a **command row** in `File Action Queue`. The on-premises Workflow Service executes it and writes the result back.

| Command (`ActionType`) | Workflow Service action on the file server | Result written back |
|---|---|---|
| `VerifyWorkingFile` | Confirm the file exists under `Working`, compute SHA-256 and size | `ResultSHA256`, `ResultSizeBytes` |
| `CreateDraftCopy` | Copy `Current_ReadOnly\<name>_RevNN.<ext>` to `Working\<name>_RevNN+1_DRAFT.<ext>` | new UNC path, hash |
| `MoveToSubmitted` | Move the draft to `Submitted`, set NTFS read-only, compute SHA-256 | hash, path |
| `ReturnToWorking` | Move from `Submitted` back to `Working` (rejection or cancel) | path |
| `PromoteToCurrent` | Move the old current revision to `Obsolete_ReadOnly`, rename the draft (drop `_DRAFT`) into `Current_ReadOnly`, re-verify the hash | hash, path |
| `MakeObsolete` | Move the current revision to `Obsolete_ReadOnly` | path |
| `ReleaseToPLMQueue` | Copy to `03_Operations_Staging\PLM_Release_Queue` with a JSON manifest (DocumentId, Revision, SHA-256) - AC-14 | path |
| `ArchiveRevision` | Move obsolete revisions older than the retention window to `Archive` | path |

The worker is idempotent. It only picks up rows in `Queued`, sets them to `Processing`, and retries up to 3 times (`Attempts`). A matching Power Automate flow (DC-05) reacts to `Completed` / `Failed`.

## 4. On-premises repository

### 4.1 Physical root (blueprint 4.1)

```
\\FILE-SERVER\Corporate_Data
├── 01_Management
├── 02_Customers\${CustomerName}\{Customer_Profile, Commercial, Projects\${ProjectName}, Shared, Archive}
├── 03_Operations_Staging\{PLM_Release_Queue, MAE_Release_Queue, Priority_Import_Queue, Integration_Logs}
├── 04_Workflow_System\{Submitted_Queue, Rejected_Queue, Processing, Error_Queue}
└── 05_Exchange_Quarantine\{Inbound, Accepted, Rejected, Logs}
```

The full logical tree (Management areas, Customer/Project, Engineering, Development 01-10, NPI, Manufacturing, Test_Engineering/ATEFiles, Quality, Production, Changes, Released) is in blueprint Appendix A and is unchanged.

### 4.2 Controlled-document folder pattern

Only areas that need formal control get this pattern (blueprint 4.2 "Workflow folders are created only for areas requiring formal control").

```
<Area folder>\<DocumentId>_<ShortTitle>\
    Working\            <DocumentId>_<ShortTitle>_Rev04_DRAFT.docx   (owners: Modify)
    Submitted\          read-only while in approval
    Current_ReadOnly\   <DocumentId>_<ShortTitle>_Rev03.docx         (everyone: Read)
    Obsolete_ReadOnly\  previous revisions
```

Example: `01_Management\Company_Profile\MGT-CPR-00001_Company_Profile\Current_ReadOnly\MGT-CPR-00001_Company_Profile_Rev03.docx`

### 4.3 Identifier conventions

| Identifier | Format | Generated by |
|---|---|---|
| `DocumentId` | `<AreaCode>-<TypeCode>-<00000>`, e.g. `QA-PFM-00042` | DC-01, using the new SharePoint item ID. No race conditions |
| `Revision` | `Rev01`, `Rev02`... (released engineering keeps PLM `Rev_A`, `Rev_B`) | DC-02 |
| `WorkflowId` | `WF-<yyyy>-<000000>` | DC-03 |
| `RequestId` | `EXC-<yyyyMMdd>-<0000>` | EX-01 |

Area codes: Management `MGT`, Commercial `COM`, Development `DEV`, Manufacturing `MFG`, Test Engineering `TST`, Quality `QA`, Changes `CHG`, IT `IT`, InfoSec `SEC`.
Type codes: Company Profile `CPR`, Strategy `STR`, Policy `POL`, Procedure `PRC`, Quotation `QUO`, Contract/NDA `CNT`, SOW `SOW`, SRS `SRS`, PDR/CDR `PDR`, FAT/SAT/FDR `FAT`, Work Instruction `WI`, Test Procedure `TP`, PFMEA/Control Plan `PFM`, ECO/ECN `ECO`, IT Procedure `ITP`, Security Policy `SPL`.

## 5. Lifecycles

### 5.1 Controlled document (blueprint 4.2 and 6.2)

```
               submit (DC-03)           all approve (DC-04)          PLM release (DC-10)
  Working  ───────────────▶ Submitted ───────────────▶ Approved_ReadOnly ─────────────▶ Released_PLM
     ▲                          │                             │                               │
     └──── reject / cancel ─────┘                             └────── make obsolete (DC-09) ──┴──▶ Obsolete_ReadOnly ──(DC-13)──▶ Archived
```

| Control mode (`ControlMode`) | Behaviour | Register record |
|---|---|---|
| Collaboration | Normal create / edit / rename, no approval | Optional. Most working files never enter the register (AC-13) |
| Workflow Optional | Collaboration until the owner explicitly submits | Yes |
| Workflow Required | Release is blocked until approval completes | Yes, `DC-01` enforces it for Policy, Procedure, Contract/NDA, ECO/ECN, Work Instruction, Test Procedure, PFMEA, IT Procedure, Security Policy |
| Read-Only Record | Changes only through a new controlled revision | Yes |

### 5.2 Large-file exchange (blueprint 8.2)

```
Draft → AwaitingUpload → Uploaded → ReadyForTransfer → Transferring → Transferred → Accepted
Exceptions: Rejected | TransferFailed | Cancelled | Expired
```

The verified-deletion gate (blueprint 8.3) is implemented by the Transfer Worker. It deletes the SharePoint copy only after the `.partial` file size matches, SHA-256 is computed, the rename is atomic, and `Upload Requests` has been updated. If deletion fails, `CloudCopyDeleted` stays `No`, the item appears in the **Awaiting Cloud Deletion** view and IT is alerted (EX-04).

## 6. SharePoint data model

All tables below are generated from `scripts/Provision-DMS.ps1`, which is the single source of truth.

- Site columns are in group **DMS Columns** and have deterministic GUIDs, so DEV/TEST/PROD share IDs.
- Content types are in group **DMS Content Types**. The default *Item* / *Document* content type is removed from each list.
- Every internal name is English. Display names follow `-Language` (see [05-Localization-Hebrew.md](05-Localization-Hebrew.md)).
- `Req` = required, `Idx` = indexed (needed to keep filters delegable above 5,000 items).

<!-- BEGIN GENERATED DATA MODEL -->

### Site 1 - Document Control (`/sites/DocumentControl`)

#### Document Register / מרשם מסמכים

| Setting | Value |
|---|---|
| URL | `Lists/DocumentRegister` |
| Template | GenericList |
| Content type | DMS Controlled Document / מסמך מבוקר (parent: Item) |
| Versioning | On, 500 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Document Title / כותרת המסמך |
| Unique + indexed | DocumentId |
| Permissions | Inherited from site |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `DocumentId` | Document ID | מזהה מסמך | Single line of text | Yes | Yes |  | max 40 |
| `DocumentArea` | Document Area | תחום | Choice | Yes | Yes |  | Set: `DocumentArea` |
| `DocumentType` | Document Type | סוג מסמך | Choice | Yes | Yes |  | Set: `DocumentType` |
| `ControlMode` | Control Mode | מצב בקרה | Choice | Yes |  | Workflow Optional | Set: `ControlMode` |
| `LifecycleStatus` | Lifecycle Status | סטטוס מחזור חיים | Choice | Yes | Yes | Working | Set: `LifecycleStatus` |
| `CurrentRevision` | Current Revision | גרסה נוכחית | Single line of text |  |  |  | max 20 |
| `DraftRevision` | Draft Revision | גרסת טיוטה | Single line of text |  |  |  | max 20 |
| `DocumentOwner` | Document Owner | בעל המסמך | Person | Yes | Yes |  |  |
| `OwnerDepartment` | Owner Department | מחלקה אחראית | Single line of text |  |  |  | max 100 |
| `CustomerCode` | Customer Code | קוד לקוח | Single line of text |  | Yes |  | max 40 |
| `ProjectCode` | Project Code | קוד פרויקט | Single line of text |  | Yes |  | max 60 |
| `Classification` | Classification | סיווג | Choice | Yes |  | Internal | Set: `Classification` |
| `RetentionClass` | Retention Class | סיווג שימור | Choice | Yes |  | Record-7Y | Set: `RetentionClass` |
| `DocumentLanguage` | Document Language | שפת המסמך | Choice |  |  | English | Set: `DocumentLanguage` |
| `CurrentUncPath` | Current UNC Path | נתיב UNC - גרסה נוכחית | Multiple lines (plain) |  |  |  |  |
| `WorkingUncPath` | Working UNC Path | נתיב UNC - עבודה | Multiple lines (plain) |  |  |  |  |
| `CurrentSHA256` | Current SHA-256 | SHA-256 גרסה נוכחית | Single line of text |  |  |  | max 64 |
| `PLMReference` | PLM Reference | הפניה ל-PLM | Single line of text |  |  |  | max 100 |
| `MAEReference` | MAE Reference | הפניה ל-MAE | Single line of text |  |  |  | max 100 |
| `PriorityReference` | Priority Reference | הפניה ל-Priority | Single line of text |  |  |  | max 100 |
| `ReviewCycleMonths` | Review Cycle (Months) | מחזור סקירה (חודשים) | Number |  |  | 12 | min 1, max 60 |
| `NextReviewDate` | Next Review Date | תאריך סקירה הבא | Date only |  | Yes |  |  |
| `EffectiveDate` | Effective Date | תאריך תחילת תוקף | Date only |  |  |  |  |
| `LastApprovedUtc` | Last Approved (UTC) | אושר לאחרונה (UTC) | Date and time |  |  |  |  |
| `ActiveWorkflowId` | Active Workflow ID | מזהה תהליך פעיל | Single line of text |  |  |  | max 40 |

**Views:** All Documents / כל המסמכים (default) · My Documents / המסמכים שלי · Pending Approval / ממתינים לאישור · Due for Review (30 days) / לסקירה ב-30 הימים הקרובים · Obsolete and Archived / מבוטלים ובארכיון

#### Workflow History / היסטוריית תהליכים

| Setting | Value |
|---|---|
| URL | `Lists/WorkflowHistory` |
| Template | GenericList |
| Content type | DMS Workflow Cycle / מחזור אישור (parent: Item) |
| Versioning | On, 500 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Workflow Title / כותרת התהליך |
| Unique + indexed | WorkflowId |
| Permissions | Unique: DMS Approvers = Read; DMS Auditors = Read; DMS Document Controllers = Read; DMS Members = Read; DMS Owners = FullControl; DMS Service Accounts = ServiceContribute |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `WorkflowId` | Workflow ID | מזהה תהליך | Single line of text | Yes | Yes |  | max 40 |
| `DocumentId` | Document ID | מזהה מסמך | Single line of text | Yes | Yes |  | max 40 |
| `Revision` | Revision | גרסה | Single line of text | Yes |  |  | max 20 |
| `CycleNumber` | Cycle Number | מספר מחזור | Number |  |  | 1 | min 1 |
| `WorkflowStatus` | Workflow Status | סטטוס תהליך | Choice | Yes | Yes | Pending | Set: `WorkflowStatus` |
| `RoutingMode` | Routing Mode | אופן ניתוב | Choice |  |  | Hybrid | Set: `RoutingMode` |
| `SubmittedBy` | Submitted By | הוגש על ידי | Person |  |  |  |  |
| `SubmittedUtc` | Submitted (UTC) | הוגש (UTC) | Date and time |  |  |  |  |
| `MandatoryApprovers` | Mandatory Approvers | מאשרי חובה | Person (multi) |  |  |  |  |
| `ConditionalApprovers` | Conditional Approvers | מאשרים מותנים | Person (multi) |  |  |  |  |
| `AdditionalReviewers` | Additional Reviewers | סוקרים נוספים | Person (multi) |  |  |  |  |
| `FinalApprover` | Final Approver | מאשר סופי | Person |  |  |  |  |
| `ChangeImpact` | Change Impact | השפעת השינוי | Choice (multi) |  |  |  | Set: `ChangeImpact` |
| `ChangeSummary` | Change Summary | תקציר השינוי | Multiple lines (plain) | Yes |  |  |  |
| `SubmittedSHA256` | Submitted SHA-256 | SHA-256 בהגשה | Single line of text |  |  |  | max 64 |
| `SubmittedUncPath` | Submitted UNC Path | נתיב UNC - הגשה | Multiple lines (plain) |  |  |  |  |
| `DecisionDueDate` | Due Date | תאריך יעד | Date only |  |  |  |  |
| `CompletedUtc` | Completed (UTC) | הושלם (UTC) | Date and time |  |  |  |  |
| `FinalComment` | Final Comment | הערת סיכום | Multiple lines (plain) |  |  |  |  |

**Views:** Active Workflows / תהליכים פעילים (default) · All Workflows / כל התהליכים

#### Approval Decisions / החלטות מאשרים

| Setting | Value |
|---|---|
| URL | `Lists/ApprovalDecisions` |
| Template | GenericList |
| Content type | DMS Approval Decision / החלטת מאשר (parent: Item) |
| Versioning | On, 100 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Decision Title / כותרת ההחלטה |
| Permissions | Unique: DMS Approvers = Read; DMS Auditors = Read; DMS Document Controllers = Read; DMS Members = Read; DMS Owners = FullControl; DMS Service Accounts = ServiceContribute |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `WorkflowId` | Workflow ID | מזהה תהליך | Single line of text | Yes | Yes |  | max 40 |
| `DocumentId` | Document ID | מזהה מסמך | Single line of text | Yes | Yes |  | max 40 |
| `Revision` | Revision | גרסה | Single line of text | Yes |  |  | max 20 |
| `Approver` | Approver | מאשר | Person | Yes | Yes |  |  |
| `ApproverRole` | Approver Role | תפקיד המאשר | Choice | Yes |  |  | Set: `ApproverRole` |
| `ApprovalStage` | Approval Stage | שלב | Number |  |  | 1 | min 1 |
| `Decision` | Decision | החלטה | Choice | Yes | Yes | Pending | Set: `Decision` |
| `DecisionComment` | Decision Comment | הערת החלטה | Multiple lines (plain) |  |  |  |  |
| `DecisionUtc` | Decision (UTC) | מועד החלטה (UTC) | Date and time |  |  |  |  |
| `DelegatedFrom` | Delegated From | הואצל מאת | Person |  |  |  |  |
| `DecisionDueDate` | Due Date | תאריך יעד | Date only |  |  |  |  |
| `ApprovalRef` | Approval Reference | מזהה אישור Teams | Single line of text |  |  |  | max 100 |

**Views:** My Pending Decisions / החלטות הממתינות לי (default) · All Decisions / כל ההחלטות

#### Approver Matrix / מטריצת מאשרים

| Setting | Value |
|---|---|
| URL | `Lists/ApproverMatrix` |
| Template | GenericList |
| Content type | DMS Approver Rule / כלל מאשרים (parent: Item) |
| Versioning | On, 100 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Rule Name / שם הכלל |
| Permissions | Inherited from site |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `DocumentArea` | Document Area | תחום | Choice | Yes | Yes |  | Set: `DocumentArea` |
| `DocumentType` | Document Type | סוג מסמך | Choice | Yes | Yes |  | Set: `DocumentType` |
| `MandatoryRoles` | Mandatory Role(s) | תפקידי חובה | Single line of text |  |  |  | max 255 |
| `MandatoryApprovers` | Mandatory Approvers | מאשרי חובה | Person (multi) |  |  |  |  |
| `ConditionalRoles` | Conditional Role(s) | תפקידים מותנים | Single line of text |  |  |  | max 255 |
| `ConditionalApprovers` | Conditional Approvers | מאשרים מותנים | Person (multi) |  |  |  |  |
| `FinalRole` | Final Role | תפקיד מאשר סופי | Single line of text |  |  |  | max 255 |
| `FinalApprover` | Final Approver | מאשר סופי | Person |  |  |  |  |
| `RoutingMode` | Routing Mode | אופן ניתוב | Choice |  |  | Hybrid | Set: `RoutingMode` |
| `SlaDays` | Approval SLA (Days) | SLA לאישור (ימים) | Number |  |  | 5 | min 1, max 60 |
| `IsActive` | Active | פעיל | Yes/No |  |  | Yes |  |

**Views:** All Rules / כל הכללים (default)

#### Impact Routing / ניתוב לפי השפעה

| Setting | Value |
|---|---|
| URL | `Lists/ImpactRouting` |
| Template | GenericList |
| Content type | DMS Impact Rule / כלל השפעה (parent: Item) |
| Versioning | On, 100 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Rule Name / שם הכלל |
| Permissions | Inherited from site |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `ChangeImpact` | Change Impact | השפעת השינוי | Choice (multi) |  |  |  | Set: `ChangeImpact` |
| `IncludeRoles` | Include Role(s) | תפקידים לצירוף | Single line of text |  |  |  | max 255 |
| `IncludeApprovers` | Include Approvers | מאשרים לצירוף | Person (multi) |  |  |  |  |
| `IsActive` | Active | פעיל | Yes/No |  |  | Yes |  |

**Views:** All Impact Rules / כל כללי ההשפעה (default)

#### Delegations / האצלות סמכות

| Setting | Value |
|---|---|
| URL | `Lists/Delegations` |
| Template | GenericList |
| Content type | DMS Delegation / האצלת סמכות (parent: Item) |
| Versioning | On, 100 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Delegation Title / כותרת ההאצלה |
| Permissions | Inherited from site |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `Delegator` | Delegator | מאציל | Person | Yes | Yes |  |  |
| `DelegateTo` | Delegate | ממלא מקום | Person | Yes |  |  |  |
| `ValidFrom` | Valid From | בתוקף מתאריך | Date only | Yes |  |  |  |
| `ValidTo` | Valid To | בתוקף עד תאריך | Date only | Yes | Yes |  |  |
| `DelegationReason` | Delegation Reason | סיבת האצלה | Multiple lines (plain) |  |  |  |  |
| `DelegationStatus` | Delegation Status | סטטוס האצלה | Choice | Yes |  | Active | Set: `DelegationStatus` |
| `DelegationApprovedBy` | Delegation Approved By | האצלה אושרה על ידי | Person |  |  |  |  |

**Views:** Active Delegations / האצלות פעילות (default)

#### File Action Queue / תור פעולות קבצים

| Setting | Value |
|---|---|
| URL | `Lists/FileActionQueue` |
| Template | GenericList |
| Content type | DMS File Action / פעולת קובץ (parent: Item) |
| Versioning | On, 50 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Action Title / כותרת הפעולה |
| Permissions | Unique: DMS Auditors = Read; DMS Document Controllers = Read; DMS Owners = FullControl; DMS Service Accounts = ServiceContribute |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `DocumentId` | Document ID | מזהה מסמך | Single line of text | Yes | Yes |  | max 40 |
| `WorkflowId` | Workflow ID | מזהה תהליך | Single line of text | Yes | Yes |  | max 40 |
| `Revision` | Revision | גרסה | Single line of text | Yes |  |  | max 20 |
| `ActionType` | Action Type | סוג פעולה | Choice | Yes |  |  | Set: `ActionType` |
| `ActionStatus` | Action Status | סטטוס פעולה | Choice | Yes | Yes | Queued | Set: `ActionStatus` |
| `SourceUncPath` | Source UNC Path | נתיב UNC מקור | Multiple lines (plain) |  |  |  |  |
| `TargetUncPath` | Target UNC Path | נתיב UNC יעד | Multiple lines (plain) |  |  |  |  |
| `ResultSHA256` | Result SHA-256 | SHA-256 תוצאה | Single line of text |  |  |  | max 64 |
| `ResultSizeBytes` | Result Size (Bytes) | גודל תוצאה (בתים) | Number |  |  |  | min 0 |
| `FailureDetail` | Failure Detail | פירוט כשל | Multiple lines (plain) |  |  |  |  |
| `RequestedBy` | Requested By | התבקש על ידי | Person |  |  |  |  |
| `RequestedUtc` | Requested (UTC) | נדרש (UTC) | Date and time |  | Yes |  |  |
| `ProcessedUtc` | Processed (UTC) | עובד (UTC) | Date and time |  |  |  |  |
| `Attempts` | Attempts | ניסיונות | Number |  |  | 0 | min 0 |

**Views:** Open Actions / פעולות פתוחות (default) · Failed Actions / פעולות שנכשלו

#### Control Audit / יומן ביקורת - בקרת מסמכים

| Setting | Value |
|---|---|
| URL | `Lists/ControlAudit` |
| Template | GenericList |
| Content type | DMS Audit Event / אירוע ביקורת (parent: Item) |
| Versioning | On, 50 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Event / אירוע |
| Permissions | Unique: DMS Auditors = Read; DMS Document Controllers = Read; DMS Owners = FullControl; DMS Service Accounts = AppendOnly |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `CorrelationId` | Correlation ID | מזהה קישור | Single line of text | Yes | Yes |  | max 60 |
| `AuditEventType` | Event Type | סוג אירוע | Choice | Yes | Yes |  | Set: `EventType` |
| `FromStatus` | From Status | מסטטוס | Single line of text |  |  |  | max 40 |
| `ToStatus` | To Status | לסטטוס | Single line of text |  |  |  | max 40 |
| `ActorEmail` | Actor | מבצע | Single line of text |  |  |  | max 255 |
| `EventUtc` | Event Time (UTC) | מועד אירוע (UTC) | Date and time | Yes | Yes |  |  |
| `EventSource` | Event Source | מקור אירוע | Choice | Yes |  |  | Set: `EventSource` |
| `EventDetails` | Event Details | פרטי אירוע | Multiple lines (plain) |  |  |  |  |

**Views:** All Events / כל האירועים (default)

#### UI Labels / תוויות ממשק

| Setting | Value |
|---|---|
| URL | `Lists/UiLabels` |
| Template | GenericList |
| Content type | DMS UI Label / תווית ממשק (parent: Item) |
| Versioning | On, 50 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Label Key / מפתח תווית |
| Unique + indexed | Title |
| Permissions | Inherited from site |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `LabelArea` | Label Area | אזור תווית | Choice | Yes | Yes | App | Set: `LabelArea` |
| `LabelEN` | English Text | טקסט באנגלית | Multiple lines (plain) | Yes |  |  |  |
| `LabelHE` | Hebrew Text | טקסט בעברית | Multiple lines (plain) | Yes |  |  |  |

**Views:** All Labels / כל התוויות (default)

### Site 2 - Large File Exchange (`/sites/LargeFileExchange`)

#### Temporary Uploads / העלאות זמניות

| Setting | Value |
|---|---|
| URL | `TemporaryUploads` |
| Template | DocumentLibrary |
| Content type | DMS Exchange File / קובץ בהעברה (parent: Document) |
| Versioning | Off (temporary copies only) |
| Permissions | Unique: Exchange Document Control = DocumentController; Exchange Owners = FullControl; Exchange Service Accounts = Contribute |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `RequestId` | Request ID | מזהה בקשה | Single line of text | Yes | Yes |  | max 40 |

**Views:** By Request / לפי בקשה (default)

#### Upload Requests / בקשות העלאה

| Setting | Value |
|---|---|
| URL | `Lists/UploadRequests` |
| Template | GenericList |
| Content type | DMS Exchange Request / בקשת העברת קבצים (parent: Item) |
| Versioning | On, 100 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Request Title / כותרת הבקשה |
| Unique + indexed | RequestId |
| List-level default | RetentionClass = Temporary |
| Permissions | Unique: Exchange Auditors = Read; Exchange Document Control = DocumentController; Exchange Employees = Read; Exchange Owners = FullControl; Exchange Service Accounts = ServiceContribute |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `RequestId` | Request ID | מזהה בקשה | Single line of text | Yes | Yes |  | max 40 |
| `CustomerCode` | Customer Code | קוד לקוח | Single line of text |  | Yes |  | max 40 |
| `ProjectCode` | Project Code | קוד פרויקט | Single line of text |  | Yes |  | max 60 |
| `TransferDirection` | Direction | כיוון | Choice | Yes |  | Inbound | Set: `Direction` |
| `PackageDescription` | Package Description | תיאור החבילה | Multiple lines (plain) | Yes |  |  |  |
| `RequestedBy` | Requested By | התבקש על ידי | Person |  |  |  |  |
| `UploaderEmail` | Uploader Email | דוא"ל המעלה | Single line of text |  | Yes |  | max 255 |
| `GuestEmail` | Customer Guest Email | דוא"ל אורח הלקוח | Single line of text |  |  |  | max 255 |
| `DestinationRelativePath` | Destination Relative Path | נתיב יעד יחסי | Multiple lines (plain) |  |  |  |  |
| `ExchangeStatus` | Exchange Status | סטטוס העברה | Choice | Yes | Yes | Draft | Set: `ExchangeStatus` |
| `DriveItemId` | Drive Item ID | מזהה פריט בענן | Single line of text |  |  |  | max 255 |
| `ExchangeFileName` | File Name | שם קובץ | Single line of text |  |  |  | max 255 |
| `ExpectedSizeBytes` | Expected Size (Bytes) | גודל צפוי (בתים) | Number |  |  |  | min 0 |
| `DestinationSizeBytes` | Destination Size (Bytes) | גודל ביעד (בתים) | Number |  |  |  | min 0 |
| `SHA256` | SHA-256 | SHA-256 | Single line of text |  |  |  | max 64 |
| `UploadFolderUrl` | Upload Folder | תיקיית העלאה | Hyperlink |  |  |  |  |
| `TransferStartedUtc` | Transfer Started (UTC) | תחילת העברה (UTC) | Date and time |  |  |  |  |
| `TransferCompletedUtc` | Transfer Completed (UTC) | סיום העברה (UTC) | Date and time |  |  |  |  |
| `FailureDetail` | Failure Detail | פירוט כשל | Multiple lines (plain) |  |  |  |  |
| `CloudCopyDeleted` | Cloud Copy Deleted | העותק בענן נמחק | Yes/No |  |  | No |  |
| `RetentionClass` | Retention Class | סיווג שימור | Choice | Yes |  | Temporary | Set: `RetentionClass` |
| `ExpiryDate` | Expiry Date | תאריך תפוגה | Date only |  | Yes |  |  |
| `ReviewedBy` | Reviewed By | נבדק על ידי | Person |  |  |  |  |
| `DecisionComment` | Decision Comment | הערת החלטה | Multiple lines (plain) |  |  |  |  |
| `Attempts` | Attempts | ניסיונות | Number |  |  | 0 | min 0 |

**Views:** Active Requests / בקשות פעילות (default) · My Requests / הבקשות שלי · Failed Transfers / העברות שנכשלו · Awaiting Cloud Deletion / ממתינים למחיקה מהענן

#### Exchange Audit / יומן ביקורת - העברת קבצים

| Setting | Value |
|---|---|
| URL | `Lists/ExchangeAudit` |
| Template | GenericList |
| Content type | DMS Audit Event / אירוע ביקורת (parent: Item) |
| Versioning | On, 50 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Event / אירוע |
| Permissions | Unique: Exchange Auditors = Read; Exchange Document Control = Read; Exchange Owners = FullControl; Exchange Service Accounts = AppendOnly |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `CorrelationId` | Correlation ID | מזהה קישור | Single line of text | Yes | Yes |  | max 60 |
| `AuditEventType` | Event Type | סוג אירוע | Choice | Yes | Yes |  | Set: `EventType` |
| `FromStatus` | From Status | מסטטוס | Single line of text |  |  |  | max 40 |
| `ToStatus` | To Status | לסטטוס | Single line of text |  |  |  | max 40 |
| `ActorEmail` | Actor | מבצע | Single line of text |  |  |  | max 255 |
| `EventUtc` | Event Time (UTC) | מועד אירוע (UTC) | Date and time | Yes | Yes |  |  |
| `EventSource` | Event Source | מקור אירוע | Choice | Yes |  |  | Set: `EventSource` |
| `EventDetails` | Event Details | פרטי אירוע | Multiple lines (plain) |  |  |  |  |

**Views:** All Events / כל האירועים (default)

#### Routing Catalog / קטלוג ניתוב

| Setting | Value |
|---|---|
| URL | `Lists/RoutingCatalog` |
| Template | GenericList |
| Content type | DMS Routing Entry / ניתוב לקוח/פרויקט (parent: Item) |
| Versioning | On, 100 major versions |
| Attachments | Off (REQ-17) |
| Title column renamed | Route Name / שם הניתוב |
| Permissions | Unique: Exchange Auditors = Read; Exchange Document Control = DocumentController; Exchange Employees = Read; Exchange Owners = FullControl; Exchange Service Accounts = Read |

| Internal name | Display (EN) | Display (HE) | Type | Req | Idx | Default | Choices / rules |
|---|---|---|---|---|---|---|---|
| `CustomerCode` | Customer Code | קוד לקוח | Single line of text |  | Yes |  | max 40 |
| `CustomerName` | Customer Name | שם לקוח | Single line of text |  |  |  | max 255 |
| `ProjectCode` | Project Code | קוד פרויקט | Single line of text |  | Yes |  | max 60 |
| `ProjectName` | Project Name | שם פרויקט | Single line of text |  |  |  | max 255 |
| `DestinationRelativePath` | Destination Relative Path | נתיב יעד יחסי | Multiple lines (plain) |  |  |  |  |
| `AllowedGuestDomains` | Allowed Guest Domains | דומיינים מורשים לאורחים | Single line of text |  |  |  | max 255 |
| `IsActive` | Active | פעיל | Yes/No |  |  | Yes |  |

**Views:** Active Routes / ניתובים פעילים (default)

### Choice sets (stored key → Hebrew label)

Stored values are always the English key, so flows and Power Fx never break when the UI language changes. The Hebrew label is loaded from the **UI Labels** list (`choice.<Set>.<Key>`).

**`DocumentArea`**: `Management` ← ניהול · `Commercial` ← מסחרי · `Development` ← פיתוח · `Manufacturing` ← ייצור · `Test Engineering` ← הנדסת בדיקות · `Quality` ← איכות · `Changes` ← שינויים · `IT` ← מערכות מידע · `InfoSec` ← אבטחת מידע

**`DocumentType`**: `Company Profile` ← פרופיל חברה · `Strategy` ← אסטרטגיה · `Policy` ← מדיניות · `Procedure` ← נוהל · `Quotation` ← הצעת מחיר · `Contract / NDA` ← חוזה / NDA · `SOW` ← SOW - הגדרת עבודה · `SRS` ← SRS - דרישות מערכת · `PDR / CDR` ← PDR / CDR - סקר תכן · `FAT / SAT / FDR` ← FAT / SAT / FDR - בדיקות קבלה · `Work Instruction` ← הוראת עבודה · `Test Procedure` ← נוהל בדיקה · `PFMEA / Control Plan` ← PFMEA / תוכנית בקרה · `ECO / ECN` ← ECO / ECN - הודעת שינוי · `IT Procedure` ← נוהל מערכות מידע · `Security Policy` ← מדיניות אבטחת מידע

**`ControlMode`**: `Collaboration` ← שיתופי ללא תהליך · `Workflow Optional` ← תהליך אישור רשות · `Workflow Required` ← תהליך אישור חובה · `Read-Only Record` ← רשומה לקריאה בלבד

**`LifecycleStatus`**: `Working` ← בעבודה · `Submitted` ← הוגש לאישור · `Approved_ReadOnly` ← מאושר - קריאה בלבד · `Released_PLM` ← שוחרר ל-PLM · `Obsolete_ReadOnly` ← מבוטל - קריאה בלבד · `Archived` ← בארכיון

**`Classification`**: `Public` ← ציבורי · `Internal` ← פנימי · `Confidential` ← סודי · `Restricted` ← מוגבל

**`RetentionClass`**: `Temporary` ← זמני · `Record-7Y` ← רשומה - 7 שנים · `Legal Hold` ← הקפאה משפטית

**`DocumentLanguage`**: `English` ← אנגלית · `Hebrew` ← עברית · `Bilingual` ← דו-לשוני

**`WorkflowStatus`**: `Pending` ← ממתין · `InReview` ← בבדיקה · `Approved` ← אושר · `Rejected` ← נדחה · `Cancelled` ← בוטל · `Restarted` ← הופעל מחדש

**`RoutingMode`**: `Hybrid` ← מקבילי ואז מאשר סופי · `Sequential` ← סדרתי · `Parallel` ← מקבילי

**`ChangeImpact`**: `Financial or pricing` ← כספי / תמחור · `Contractual/customer commitment` ← חוזי / התחייבות ללקוח · `Product design` ← תכן מוצר · `Manufacturing process` ← תהליך ייצור · `Test/acceptance` ← בדיקות / קבלה · `Cybersecurity/data` ← סייבר / מידע · `Employee/organization` ← עובדים / ארגון · `Supplier/BOM` ← ספקים / BOM · `PLM/MAE/Priority integration` ← ממשק PLM/MAE/Priority

**`ApproverRole`**: `Mandatory` ← חובה · `Conditional` ← מותנה · `Reviewer` ← סוקר · `Final` ← מאשר סופי

**`Decision`**: `Pending` ← ממתין · `Approved` ← אושר · `Rejected` ← נדחה · `Delegated` ← הואצל · `Cancelled` ← בוטל · `Expired` ← פג תוקף

**`DelegationStatus`**: `Active` ← פעיל · `Expired` ← פג תוקף · `Revoked` ← בוטל

**`ActionType`**: `VerifyWorkingFile` ← אימות קובץ עבודה · `CreateDraftCopy` ← יצירת טיוטת גרסה · `MoveToSubmitted` ← העברה להגשה · `ReturnToWorking` ← החזרה לעבודה · `PromoteToCurrent` ← קידום לגרסה נוכחית · `MakeObsolete` ← העברה לבוטל · `ReleaseToPLMQueue` ← שחרור לתור PLM · `ArchiveRevision` ← העברה לארכיון

**`ActionStatus`**: `Queued` ← בתור · `Processing` ← בעיבוד · `Completed` ← הושלם · `Failed` ← נכשל · `Cancelled` ← בוטל

**`ExchangeStatus`**: `Draft` ← טיוטה · `AwaitingUpload` ← ממתין להעלאה · `Uploaded` ← הועלה · `ReadyForTransfer` ← מוכן להעברה · `Transferring` ← בהעברה · `Transferred` ← הועבר · `Accepted` ← התקבל · `Rejected` ← נדחה · `TransferFailed` ← העברה נכשלה · `Cancelled` ← בוטל · `Expired` ← פג תוקף

**`Direction`**: `Inbound` ← נכנס · `Outbound` ← יוצא

**`EventType`**: `Created` ← נוצר · `StatusChanged` ← שינוי סטטוס · `Submitted` ← הוגש · `Approved` ← אושר · `Rejected` ← נדחה · `Delegated` ← הואצל · `FileActionQueued` ← פעולת קובץ בתור · `FileActionCompleted` ← פעולת קובץ הושלמה · `FileActionFailed` ← פעולת קובץ נכשלה · `TransferCompleted` ← העברה הושלמה · `TransferFailed` ← העברה נכשלה · `CloudCopyDeleted` ← העותק בענן נמחק · `PermissionChanged` ← שינוי הרשאות · `Cancelled` ← בוטל · `Expired` ← פג תוקף

**`EventSource`**: `PowerApps` ← Power Apps · `PowerAutomate` ← Power Automate · `TransferWorker` ← Transfer Worker · `WorkflowService` ← שירות תהליכים · `Manual` ← ידני

**`LabelArea`**: `App` ← אפליקציה · `Field` ← שדה · `Choice` ← ערך בחירה · `List` ← רשימה · `Message` ← הודעה

<!-- END GENERATED DATA MODEL -->

## 7. Seed data loaded by the script

| List | Rows | Content |
|---|---|---|
| Approver Matrix | 16 | Blueprint 7.1 exactly: area, type, mandatory, conditional and final **roles**. The person columns stay empty until Document Control assigns named people or Entra groups |
| Impact Routing | 9 | Blueprint 7.2: change impact → roles to include automatically |
| UI Labels | 316 | App labels (`app.*`), notification templates (`msg.*`), every column (`field.*`), list (`list.*`) and choice value (`choice.<Set>.<Key>`) in English and Hebrew |

Seeding runs only when the list is empty, so re-running the script never overwrites business data.
