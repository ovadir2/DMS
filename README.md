# Enterprise Document Control - Implementation Package

Implementation of **IT-DOC-BP-001 "Enterprise Document Control and Large-File Exchange Blueprint"** (On-Premises Windows repository + Microsoft 365 control plane, about 260 Business Premium users).

> **What the DMS needs:** a Windows file server, IIS on a Windows server, and a SharePoint site for the
> register and the audit.
>
> **Power Apps is not used.** The DMS page is the application; the Power Apps design is kept as
> [`docs/03-Power-Apps.md`](docs/03-Power-Apps.md) for a tenant that wants that route, and nothing in the
> pilot depends on it.
>
> **Power Automate carries the notifications.** The DMS writes a row to DMS Notifications at every step
> and the flow sends it as mail or to Teams. The approvals themselves are on the DMS page
> (`DMS_APPROVALS=page`); running them in a flow instead is the optional route in
> [`docs/04-Power-Automate.md`](docs/04-Power-Automate.md).
>
> Files stay on `\\FILE-SERVER\Corporate_Data`. SharePoint holds metadata only. Power Apps and Power Automate never touch binary content. PLM/MAE and Priority remain the systems of record.

## Package contents

| Path | What it is |
| --- | --- |
| [`scripts/Provision-DMS.ps1`](scripts/Provision-DMS.ps1) | Ready-to-run, idempotent PnP PowerShell. Creates both sites, 108 site columns, 12 content types, 13 lists and libraries, 23 views, 4 permission levels, 11 SharePoint groups, unique permissions, sharing policy, Sites.Selected grants and seed data (approver matrix, impact routing, 316 bilingual UI labels) |
| [`docs/01-Architecture-and-Data-Model.md`](docs/01-Architecture-and-Data-Model.md) | Site topology, on-prem folder pattern, lifecycles, ID conventions, and the **full column catalogue** (type, required, indexed, default, choices, EN/HE names) generated from the script |
| [`docs/02-Security-and-Permissions.md`](docs/02-Security-and-Permissions.md) | AD AGDLP groups, NTFS matrix, SharePoint groups and permission levels, lifecycle permission matrix, tenant hardening, dynamic-approver policy |
| [`docs/03-Power-Apps.md`](docs/03-Power-Apps.md) | Two Canvas apps: screens, controls, Power Fx, RTL/localization, build steps and Copilot prompts |
| [`docs/04-Power-Automate.md`](docs/04-Power-Automate.md) | 4 utility + 13 document-control + 7 exchange flows: triggers, step logic, expressions, Copilot prompts, and on-prem worker contracts |
| [`docs/05-Localization-Hebrew.md`](docs/05-Localization-Hebrew.md) | Language rules, EN/HE notification templates, app labels, Hebrew executive summary |
| [`docs/06-Copilot-Prompts.md`](docs/06-Copilot-Prompts.md) | Copy-paste Copilot prompts, follow-ups and check lists that build every flow in Power Automate, with the Hebrew choice values |
| [`docs/07-Approval-Flow.md`](docs/07-Approval-Flow.md) | Pilot approval flow as a diagram, plus the editable Hebrew deck [`docs/presentations/DMS-Approval-Flow.pptx`](docs/presentations/DMS-Approval-Flow.pptx) |
| [`docs/08-Pilot-Process.md`](docs/08-Pilot-Process.md) | The pilot process end to end: DMS page, approval, file moves, roles, and the step-by-step pilot test with one super user |
| [`docs/10-Installation-and-Settings.md`](docs/10-Installation-and-Settings.md) | How the DMS is installed on a server, what to run afterwards, and every key in `webapi\.env` with what it does |
| [`docs/11-Project-Context.md`](docs/11-Project-Context.md) | The brief as it was actually given: the standing rules, the decisions and what each was a reaction to, and what is still open - enough to carry the work on without the conversation it came from |
| [`docs/12-KPI-Integration.md`](docs/12-KPI-Integration.md) | KPIs and dashboards: where a KPI package lives, how a page of the repository runs and reads its data, and how the KPI Builder publishes |
| [`docs/13-Machine-API.md`](docs/13-Machine-API.md) | The machine API: a key for an application, what each endpoint answers, and the AD account a key acts as |
| [`docs/15-KPI-Builder-Contract.md`](docs/15-KPI-Builder-Contract.md) | What the KPI Builder sends the DMS and gets back: its key, the departments, publishing a KPI, and what its page may do at runtime |
| [`docs/14-API-Reference.md`](docs/14-API-Reference.md) | Every endpoint of the DMS with its parameters, written from the API itself (`scripts/New-DmsApiDocs.ps1`) |
| [`docs/dms-openapi.json`](docs/dms-openapi.json) | The OpenAPI (Swagger) document of the whole API - served live at `/api/openapi.json`, shown at `/dms/api-docs` |
| [`docs/Go-Live.md`](docs/Go-Live.md) | From the pilot to production: the names, the pilot's data, first loading, separating the package from what exists only to try it, and what the pilot taught |

## Quick start

Prerequisites: PowerShell 7.4+, `Install-Module PnP.PowerShell -Scope CurrentUser`, an Entra app registration for PnP interactive login (`Register-PnPEntraIDAppForInteractiveLogin`) with SharePoint *Sites.FullControl.All* (delegated), and a SharePoint Administrator account.

```powershell
cd dms/scripts

# English
./Provision-DMS.ps1 -TenantName contoso -ClientId <pnp-app-id> -OwnerUpn it.admin@contoso.com

# Hebrew, with Entra groups, guest domain allow-list and Sites.Selected grants
./Provision-DMS.ps1 -TenantName contoso -ClientId <pnp-app-id> -OwnerUpn it.admin@contoso.com -Language he `
    -AllowedGuestDomains customer-a.com, customer-b.com `
    -TransferWorkerAppId <transfer-app-id> -WorkflowServiceAppId <workflow-app-id> `
    -GroupMembers @{
        DcOwners      = @('<GG_DMS_ITAdmins object id>')
        DcControllers = @('<GG_DMS_DocumentControl object id>')
        DcApprovers   = @('<GG_DMS_Approvers object id>')
        DcMembers     = @('<GG_DMS_Employees object id>')
        DcAuditors    = @('<GG_DMS_Auditors object id>')
        DcService     = @('svc-dms-flows@contoso.com')
        ExOwners      = @('<GG_DMS_ITAdmins object id>')
        ExControllers = @('<GG_DMS_DocumentControl object id>')
        ExEmployees   = @('<GG_DMS_Employees object id>')
        ExAuditors    = @('<GG_DMS_Auditors object id>')
        ExService     = @('svc-dms-flows@contoso.com')
    }
```

The script can be re-run safely. Existing objects are skipped or refreshed, and seed data is only loaded into empty lists. A transcript is written to `scripts/logs/`.

Two language switches:

- `-Language en|he` sets the DMS content language (column, list, view and group names).
- `-SiteLanguage en|he` sets the SharePoint interface language (site locale 1033 / 1037). It defaults to `-Language`. Example: `-SiteLanguage he -Language en` gives Hebrew SharePoint menus with English DMS content.

- `-Multilingual` makes the sites bilingual. Each user sees menus, the site title, list, column and content-type names in the language of their own Microsoft 365 profile (Hebrew or English). Stored choice values stay English keys, and view and group names use the `-Language` language.

- `-ChoiceLanguage en|he` sets the language of the stored dropdown values (default `en`). For a SharePoint site with no English at all, use `-SiteLanguage he -Language he -ChoiceLanguage he` without `-Multilingual`. Flows and apps must then compare against the Hebrew values listed in `docs/01` (the "Hebrew label" column).

Re-running the script on an existing site brings list, column, content-type, view and group names and dropdown values to the current language. Add `-ReseedData` to also reload the Approver Matrix, Impact Routing and UI Labels rows (this removes any people already assigned there, so use it only before go-live).

The site locale is fixed when the site is created and can't be changed later. Pick it before the first run.

## Groups and access

After `Provision-DMS.ps1`, run `scripts/Connect-DmsGroups.ps1`. It creates the Entra groups (`GG_DMS_ITAdmins`, `GG_DMS_DocumentControl`, `GG_DMS_Approvers`, `GG_DMS_Auditors`, `GG_DMS_PilotUsers`, and a dynamic `GG_DMS_Employees`) and adds them to the SharePoint groups of both sites. `-PilotMode` gives only the pilot users access. People are then managed in Entra only.

The on-premises repository tree (docs/01 §4) is built by `scripts/New-DmsFileServerTree.ps1`: the root folders, the 20 management areas and the full customer/project tree from blueprint Appendix A, and per document the `Working / Submitted / Current_ReadOnly / Obsolete_ReadOnly` folders. `-CreateAdGroups` creates the `DL_FS_*` groups and `-ApplyAcl` sets the NTFS permissions from docs/02 §3.2. `-DocumentParent` places a controlled document inside a project folder (e.g. `Development\02_SOW`). It supports `-WhatIf`.

For the pilot, `scripts/New-DmsPilotFlowPackage.ps1` builds `scripts/out/DC-P1-PilotApproval.zip`, a ready-made approval flow (Document Register status "Submitted" → mandatory approvers → final approver → status + Control Audit row). Import it in Power Automate with **My flows > Import > Import Package (Legacy)**.

The on-prem side of the approval runs inside the DMS itself (`webapi/dms_api/file_service.py`, `DMS_FILE_SERVICE_SECONDS`): it moves each document's file to match its status, Submitted → `Submitted` (read-only), Approved → `Current_ReadOnly` (the previous revision → `Obsolete_ReadOnly`, the path and SHA-256 written back to the register), rejected → back to `Working`. Every move writes a Control Audit row.

`scripts/New-DmsNotifyFlowPackage.ps1` creates the **DMS Notifications** list and builds `scripts/out/DC-P2-PilotNotifications.zip`: with approvals on the DMS page, it sends each step (waiting for approval, approved, rejected, withdrawn) to the right people by email and Teams.

`scripts/Set-DmsAccess.ps1` and `scripts/Get-DmsAccess.ps1` set and report the department access on the repository folders, from `scripts/dms-access.csv` (the groups themselves stay managed in AD by IT). `scripts/new_access_workbook.py` builds `scripts/dms-access-template.xlsx`: every blueprint folder by levels, for IT to fill in.

`webapi/` is **RH - Documents Management System**, a web page and API inside the company network that wraps the file server repository: users sign in with their Windows login, see the customers and folders AD allows them, upload, create, rename and delete files and folders, start the approval workflow with the status shown on each file, follow **My workflows**, and ask **AI Insights** (the RH on-prem RAG LLM) about documents (`/dms/dms-page?lang=EN`). RH Navigator links to it and the Explorer right-click can open it. See [webapi/README.md](webapi/README.md).

## Deployment sequence (maps to blueprint section 10)

| # | Step | Blueprint phase | Reference |
| --- | --- | --- | --- |
| 1 | Governance, licences, DLP (SharePoint, Teams, Office 365 Users, Approvals, Office 365 Groups in *Business*) | 1 | 02 §7 |
| 2 | AD groups, NTFS ACLs, quarantine folders, controlled-folder pattern, CrowdStrike and Veeam scope | 2 | 02 §3, 01 §4 |
| 3 | **Run `Provision-DMS.ps1`** | 3 | this README |
| 4 | Guest isolation tests (Customer A vs B) | 4 | 02 §5.2 |
| 5 | Entra apps (Transfer Worker, Workflow Service) with certificates and Sites.Selected | 5 | 02 §7 |
| 6 | Integration server: Transfer Worker + Workflow Service scheduled tasks | 6 | 04 §5 |
| 7 | Assign people in Approver Matrix / Impact Routing, fill Routing Catalog | - | 01 §7 |
| 8 | Solution `RH Document Control`: connection references, environment variables, flows | 7 | 04 |
| 9 | Canvas apps, pilot group share | 8 | 03 |
| 10 | External onboarding, pilot, production | 9-10 | blueprint 13 |

## Requirements, and whether they are met

This is the specification of the system as it stands: every requirement the DMS answers, where it came
from, and how it is met. The blueprint's own requirements came first; the rest were asked for on the pilot,
by the people using it, and each row is the rule that came out of a real day's work. **Checked** means it
was tried on the pilot and behaved as written; **built** means it is in the product but nobody has put it
through its paces yet. What was asked for and is not there yet has a table of its own, below.

### From the blueprint

| Req | What it asks for | How it is met | Status |
| --- | --- | --- | --- |
| REQ-01, REQ-02 | Files stay on the file server; SharePoint holds metadata only | The register stores the UNC path and SHA-256; no content ever leaves the file server | Checked |
| REQ-03, REQ-16 | Access by AD groups | AGDLP groups, SharePoint groups backed by Entra groups (02) | Checked |
| REQ-04, REQ-05 | Control modes per document | `ControlMode`: Collaboration / Workflow Optional / Workflow Required / Read-Only Record | Checked |
| REQ-06 | Approvers per document and revision | Approver Matrix + Impact Routing + approvers chosen per submission, validated on the server | Checked |
| REQ-07 | Approvals without attachments | Approvals on the DMS page (pilot) or Teams Approvals; the file never travels | Checked |
| REQ-08, REQ-09, REQ-10 | Large-file exchange with customers | A separate site, a folder per customer, guest invitation by the DMS account, share log | Checked |
| REQ-11, REQ-12, REQ-13 | Malware gate, backup, retention | CrowdStrike gate (EX-06), Veeam scope, `RetentionClass` | Built |
| REQ-14 | Audit and history | Indexed metadata, append-only Control Audit and Approval Decisions, version history | Checked |
| REQ-15 | PLM / Priority references | Reference columns and the `ReleaseToPLMQueue` manifest (DC-10) | Built |
| REQ-17 | No attachments anywhere | Attachments disabled on every list; moves through the file service | Checked |

### What the pilot demanded

| Req | What it asks for | How it is met | Status |
| --- | --- | --- | --- |
| REQ-P01 | Nothing is installed or configured on an approver's PC | The approval happens in the browser and in SharePoint; the DMS opens, converts and writes back with its own account | Checked |
| REQ-P02 | Approvers need no rights at all on the file server | The DMS is the only account with rights there; a copy is put in SharePoint for the person who must read or change it | Checked |
| REQ-P03 | Visibility follows the AD groups, always | Every listing, search and open is checked against the user's own token; a workflow does not grant sight of a document, and a person who may not see the folder cannot be its approver | Checked |
| REQ-P04 | An approved document cannot be changed | `Current_ReadOnly` is read only on the file system itself: the AD groups that could see it keep Read and Execute, only the DMS keeps Modify, and the file carries the read-only flag | Checked |
| REQ-P05 | An approved document is taken out only by the person whose document it is, and it is put aside, not erased | Delete in `Current_ReadOnly` is offered to the owner alone and refused for anyone else, super users included; the file moves to `Obsolete_ReadOnly` beside it (made if it is not there) and stays read only, so the document can still be found and read; its Markdown is removed, because the AI answers from the revision in force and that lives in `Current_ReadOnly` only; the record stays, with no revision in force, and the move is written to Control Audit | Checked |
| REQ-P06 | View means reading, not editing | SharePoint turns the document into a PDF, the DMS fetches it and deletes the copy, and serves the PDF itself: there is nothing to type into and nothing left behind | Checked |
| REQ-P07 | Nobody approves their own document | Choosing yourself as an approver, and delegating back to the author, are both refused | Checked |
| REQ-P08 | The company AI reads the documents in force | `<document>.md` is written beside every released document, at the moment of release; the Markdown of a replaced revision is removed so nothing quotes it | Checked |
| REQ-P09 | The page works the way people already work | A folder tree and a detailed list, right-click for the commands of the row, double-click to open, drag files or a folder in from Windows | Checked |
| REQ-P10 | A document comes back by itself when it is closed | Office releases its lock when the document is closed; the DMS writes the copy back to the file server and removes it, with "Done editing" kept for when that does not happen | Built |
| REQ-P11 | A link can be shared without exposing the file server | Copy link gives a token the DMS resolves; Copy path still gives the path for whoever works that way | Built |
| REQ-P12 | What cannot be done is visible, not hidden | Every menu offers the same lines in the same order, with what does not apply greyed and the reason in its tooltip | Checked |
| REQ-P13 | Every released document is readable by the AI, whatever it was written in | `.docx`, `.xlsx` (every sheet under its own name, each value under its own heading, dates as dates, a formula's worked-out value or the formula itself), `.pptx` (slide by slide, with the speaker notes) and text are read by the DMS itself; `.pdf` with a text layer through pypdf; `.xls` with `xlrd`; a legacy `.doc` or `.ppt` through the PDF SharePoint makes of it. Only a scanned PDF with no text layer stays unreadable | Checked, except a scanned PDF |
| REQ-P14b | A dashboard page is a tool, not a document | An HTML file with `dashboard_` in its name (`dashboard_DB.html`) opens in a tab and runs there, served by the DMS into a sandbox so it cannot act as the person reading it. Dropped or uploaded, it is saved in the folder itself - writable, so a newer one replaces it - and never released into `Current_ReadOnly`, registered or approved | Checked |
| REQ-P15 | A KPI package dropped into a department's KPIs folder lands as one KPI | The folder `<KPIs>/<KPI_ID>` is made if it is not there; the page that runs the KPI stays at its root, writable, and is replaced by a newer build; every other file of the package is released into its `Current_ReadOnly`, read only and approved, under the DMS's ordinary rules. A drop anywhere else is unchanged. `docs/12-KPI-Integration.md` says what is built and what the Builder still owes | Partly: the drop, the sandboxed page and the Builder launch are built; the package contract and its validation are not |
| REQ-P16 | A KPI is started from the folder it belongs to | Right-clicking a department's or a customer's `KPIs` folder offers ＋ New KPI, and one KPI's folder offers Edit KPI, where the person may add there and the Builder is configured (`DMS_KPI_BUILDER_URL`). The DMS works out the address: it checks the folder against the blueprint and the person against AD, so a folder named by a browser grants nothing | Checked (the Builder itself is another application) |
| REQ-P17 | What is done on the file server by hand does not leave the DMS wrong | `Sync-DmsFileServer.ps1` reads both sides: a record whose file moved is pointed at it, one whose file is gone is archived and says so in Control Audit, a file left in `Current_ReadOnly` that nobody registered is reported (and adopted with `-Register`), a released file made writable is made read only again, Markdown is filled in and removed where it does not belong, and missing blueprint folders are listed. Nothing changes without `-Write` | Checked |
| REQ-P18 | A new customer starts as a copy of the customer skeleton, AD rights and all | One folder under `02_Customers` is the shape (`DMS_CUSTOMER_SKELETON`, `Customer_Skeleton`). Making a customer - on the page or with `New-DmsCustomer.ps1` - copies its folders and, on the file server, the NTFS permissions each folder carries, which the blueprint cannot hold. The skeleton is not a customer: it is out of the customer lists and no document may be filed in it, so the shape stays a shape | Checked |
| REQ-P19 | An application can ask the DMS, and it is answered as its AD account, not as a super user | A caller with no person behind it uses a key of its own (`DMS_API_KEYS`, made by `New-DmsApiKey.ps1`): a name, what it may read, **the AD account it acts as**, and a line in the log for every call. Every answer is filtered folder by folder against that account's own AD rights, and a key that names no account is told nothing. `GET /api/v1/customers`, `GET /api/v1/documents` (what is approved and where its file is) and `GET /api/v1/approved-documents` (DocID, DocName, DocRev, DocDMSpath for every Markdown under `Current_ReadOnly` - the list the RAG indexes); the key never appears in the log or in an answer, and nothing under `/api/v1` writes. `docs/13-Machine-API.md` | Checked |
| REQ-P14 | The DMS keeps itself in order without being asked | One pass (`DMS_FILE_SERVICE_SECONDS`) moves files to match each document's status, puts back a read-only flag that was cleared, writes a Markdown that is missing, and brings back a copy whose editor has closed it | Built: the pass exists; it is off until that setting is given a value |
| REQ-P20 | A document waiting for an answer is open to the people it waits on | The approvers of the stage and the owner may write in it while `DMS_SUBMITTED_EDITABLE` allows it - a remark is answered in the document itself. One rule, used by the approvals row, the file list and the checkout alike | Checked |
| REQ-P21 | A command that cannot be used says why, where it would have been | The greyed line stays in place and carries its reason - released by the DMS, the state of its record, no Modify in AD, somebody has it out, a folder the DMS keeps - in the row and in the right-click menu | Checked |
| REQ-P22 | One answer decides one document | A decision redraws the table, so a second click landed on the next document: clicks are ignored while a decision is on its way, and the question names the document it is about | Checked |
| REQ-P23 | Released means read only on the file server, always | Every listing puts the read-only flag back on a file in `Current_ReadOnly` or `Obsolete_ReadOnly` that arrived without it - copied by hand, restored from a backup - so View cannot be saved over | Checked |
| REQ-P24 | The copies the DMS makes for reading cannot be written in | The `Views` library stops inheriting the site's permissions and everyone who could write there is left with Read; the copy itself is a PDF, and it is removed minutes later | Built |
| REQ-P25 | A reader is told when a save would go nowhere | Opening a writable file read-only in Word or Excel says so once, on the page; where it is already obvious - a released file, a PDF from the bridge - it says nothing | Checked |
| REQ-P26 | The KPI Builder publishes without a browser | `POST /api/v1/kpi/publish` with the department's name and the two files: the page lands writable in `KPIs\<KPI>`, the data is released into its `Current_ReadOnly`, and the folders are made on the first publish | Built |
| REQ-P27 | An application needs three questions, not thirty | What is released (`/api/v1/approved-documents`, the RAG's list), the departments and the customers - each answered as the key's AD account, with publishing the only thing a key may write | Built |
| REQ-P28 | Every endpoint is described, and the description cannot drift | Swagger UI at `/dms/api-docs`, the document at `/api/openapi.json`, the reference in `docs/14-API-Reference.md` - all generated from the routes, with a test that fails when an endpoint is missing or undescribed | Checked |
| REQ-P29 | The structure this company really has is the structure the DMS knows | The departments and their folders are in the blueprint, in both languages, each with its KPIs folder; a department added later is learned from the file server (`scripts\Update-DmsBlueprint.ps1`) without touching the code | Checked |
| REQ-P30 | Going live is a rename, not a rebuild | The SharePoint sites lose their `-TEST`, the `.env` follows, the IIS site and pool are renamed, and `Reset-DmsPilotData.ps1` clears what the pilot was played with - the lists emptied, the file server back to the blueprint | Checked |
| REQ-P31 | A super user may answer for somebody, and only for the people named | "Acting as" is limited to the accounts `DMS_DEV_USERS` names - nobody when it names nobody - and `DMS_ACTING_AS=0` takes it away; the real account is in every audit line | Checked |
| REQ-P32 | Whether this installation is still a pilot is one command | `Test-DmsProductionReady.ps1` reads the `.env` the way the DMS does, asks the DMS, and looks at the file server: the sign-in, the names, the upkeep pass, the certificate, the canaries, what is still checked out | Checked |
| REQ-P33 | The page can always be brought back to a known state | The logo fetches the page again under a fresh address - the browser's copy is never what is shown after an install - and lands at the top of the repository, in the tree and the list at once | Checked |
| REQ-P34 | AI Insights asks one thing | The document on the screen when there is one, and otherwise everything the company has released. The person is not asked to choose which knowledge base their question belongs to | Checked |
| REQ-P35 | No script carries one installation's names | The address comes from `DMS_PAGE_URL`, the IIS site is the one whose folder holds the scripts, the application is the folder they sit in - so a rename needs no editing in `scripts\` | Checked |
| REQ-P36 | A document's state is where its file sits | Four folders beside the document: `Working` (its owner's), `Submitted` (waiting for an answer), `Current_ReadOnly` (the revision in force), `Obsolete_ReadOnly` (the revisions it replaced). The DMS moves the file as the state changes, and the register holds the path; nobody files by hand | Checked |
| REQ-P37 | A replaced revision is kept, and stops being the answer | On approval the new revision goes to `Current_ReadOnly` and the one it replaces moves to `Obsolete_ReadOnly`, read only, with its Markdown removed - what is obsolete stays for the audit and is never read as current, by a person or by the AI | Checked |
| REQ-P38 | The Markdown lives only beside the revision in force | `<document>.md` is written into `Current_ReadOnly` when a document is released and goes when that revision does, so the AI's list is the documents in force and nothing else. `New-DmsMarkdown.ps1 -Write` fills in what was released before the DMS wrote them | Checked |
| REQ-P39 | The RAG is given what a citation needs | `GET /api/v1/approved-documents` answers, per released document, its Document ID, its name, its revision, the Markdown to read and the file beside it - read from the `Current_ReadOnly` folders themselves, so a document released by hand is in the list too | Built |
| REQ-P40 | The AI is never shown a document the person may not read | A question about a file is refused unless AD gives that person read on it, and the machine API answers as the key's AD account - an index built from it holds nothing that account may not see | Checked |
| REQ-P41 | Nothing in `Current_ReadOnly` is deleted | Removing a released revision is the owner's own command and it moves the file (and its Markdown) to `Obsolete_ReadOnly`; a super user cannot erase it from the page either, and the Control Audit keeps the line | Checked |
| REQ-P42 | A file becomes a document by being registered | Register gives it a Document ID, a type, an area and an owner, renames the file to the document's own name, and writes the Document Register row and the Control Audit line. Until then it is a file in a folder, and the DMS says so | Checked |
| REQ-P43 | Submitting says who has to answer | The approvers are chosen at submission, or the Approver Matrix answers for that document type: stage 1 is every mandatory approver, stage 2 the final one. The document moves to `Submitted` and the people it waits on are told | Checked |
| REQ-P44 | An approver answers once, and the answer is recorded | Approve or return with remarks, with the comment required on a return - each decision is a row in Approval Decisions and a line in the Control Audit, with the SHA-256 of the file the decision was made on | Checked |
| REQ-P45 | Remarks come back to the owner together | A return in stage 1 does not end the review: the others still answer, and when the last of them has, the document goes back to its owner with all the remarks in one notification | Checked |
| REQ-P46 | A document changed during its approval is not approved as it stands | If the copy came back changed while the approvers were answering, approval is refused and it goes back with the remarks: its owner submits the version everybody is now looking at | Checked |
| REQ-P47 | A submission can be taken back | Withdraw returns a submitted document to `Working` with its owner, ends the cycle, and says so in the audit; the approvals it had are not carried into the next cycle | Checked |
| REQ-P48 | The next revision starts from the one in force | New revision copies the approved file (or takes an uploaded one) as `<name>_RevNN_DRAFT`, on the same record: the approved revision stays current and in force until the new one is approved | Checked |
| REQ-P49 | Not everything needs a workflow | Release without workflow puts the file straight into `Current_ReadOnly`, read only, registered as approved by the DMS with its own audit line - for what a department simply publishes. A controlled document cannot be overwritten this way | Checked |
| REQ-P50 | An approver who is away does not stop the document | Delegate passes an approval to somebody else for this cycle only, with both names in the audit; a super user may do it for an approver who cannot | Checked |
| REQ-P51 | People are told, in the language they read | Submitted, returned and approved each send a notification - email and Teams through DMS Notifications - with the document, the remark and a link to the page in that person's language | Built |
| REQ-P52 | An approver is somebody who may see the document | Only people AD lets read the folder can be chosen, and the approval does not grant sight of anything: a person who may not see the folder cannot be an approver of what is in it. The people picker offers the company directory; the server checks the choice again | Checked |
| REQ-P53 | Who approves is a rule, not a habit | The Approver Matrix answers per document type - the mandatory approvers and the final one - and is what the page offers when nobody is chosen at submission. The rule in force at submission is the rule the cycle follows, whatever the matrix says later | Checked |
| REQ-P54 | A super user may answer when nobody else can, and it says so | A super user can decide any stage; the decision is recorded as made by them, marked "super user", with their own account in the Control Audit - an unblocking, not a disguise | Checked |
| REQ-P55 | Taking back and passing on are the owner's and the approver's own commands | Withdraw belongs to the document's owner (or a super user); Delegate belongs to the approver who owes the answer (or a super user acting for them), is good for this cycle only, and cannot land back on the author | Checked |
| REQ-P56 | What is waiting, and for whom, is on the screen | The Approvals page lists what waits for this person - stage, who has answered, who is still owed, how many days it has waited, and the remarks so far - and My workflows shows the owner the same from the other side | Checked |
| REQ-P57 | A file released without workflow is taken out the same way as any other | It is a released document: Delete moves it (and its Markdown) to `Obsolete_ReadOnly`, read only, with the audit line - only its owner, and never an erase. What was published without a workflow is not withdrawn without a trace either | Checked |
| REQ-P58 | Deleting is one file at a time, and says what it will do | The command takes the one file that is ticked, names it, and says where it is going - to `Obsolete_ReadOnly` for a released document, to the recycle folder for anything else. Nothing on the file server is ever erased by the page | Checked |
| REQ-P59 | Every document can account for itself | History on a row shows that document's whole life from the Control Audit - registered, submitted, each decision and its comment, returned, approved, released, revised, shared, taken out - with who did it, when, and the SHA-256 of the file each decision was made on | Checked |
| REQ-P60 | The trail is written as it happens, and is not rewritten | Control Audit and Approval Decisions are appended to at the moment of the act, never edited; a status that moved, a file that moved, a permission that changed and a share that went out each leave their own line, and what the DMS itself does is signed by the DMS, not by a person | Checked |
| REQ-P61 | What the DMS could not write down, it says | A SharePoint call that fails is kept in the DMS's own list of last errors and shown in the ⋮ diagnostics, and the file action is completed anyway - the trail is repaired by the upkeep pass rather than left half written, and nothing silently stops being traced | Built |
| REQ-P62 | Who did what on the file server is traceable too | Every change the page makes - upload, new folder, rename, delete, release, share - is written to the service log with the real account behind it, including a super user acting as somebody else | Checked |
| REQ-P63 | Opening a document is two commands, and the DMS says which one this person gets | **Open to edit** and **View** are separate lines on every row. The DMS decides from the document's state and the person's AD rights which of them is live, so nobody picks one and is refused afterwards | Checked |
| REQ-P64 | View is reading, and cannot become writing | A released document is read only on the file server, the copy the bridge makes to read is a PDF with nothing to type into, the library those copies live in gives nobody write, and a writable file opened read only in Word or Excel is accompanied by a line saying a save would go nowhere | Checked |
| REQ-P65 | One person edits a document at a time | Taking it out for editing marks it; a second person is told who has it, and is still free to read it - their own reading copy, never the one being written in. "Done editing" brings it back, and a copy forgotten in SharePoint comes back by itself | Checked |
| REQ-P66 | Editing happens where the person already works | With the bridge, in Word, Excel or PowerPoint for the web with their own Microsoft account, and what they changed is written back to the file server by the DMS; without it, in the desktop application, straight from the page. Nothing is installed on the PC either way | Checked |
| REQ-P67 | A document in work is its owner's, and a document under approval is the answer's | While it is in `Working` its owner edits it; while it is in `Submitted` the people it waits on and its owner may write in it (`DMS_SUBMITTED_EDITABLE`), so a remark is answered in the document; once it is released, nobody edits it - the next revision does | Checked |
| REQ-P68 | A remark can be a sentence or a marked-up document | Returning asks for the sentence; an approver who prefers to mark the document itself either writes in it (while it is submitted) or edits a copy on their own PC and attaches it as their remarks - both reach the owner, and neither needs rights on the file server | Checked |
| REQ-P69 | Attached remarks are kept beside the document, not in it | They live in the DMS's own area under the document's id, newest first, and the released document is never mixed with the marks somebody made on it. Who may see them: the owner, the approvers of the cycle, and a super user | Checked |
| REQ-P70 | Remarks stay readable after the decision | The approvals row shows the remarks so far, History shows each decision with its comment, and the owner gets them all in one notification when the review ends - the reason a document came back does not have to be remembered | Checked |
| REQ-P71 | A customer is sent the document, never the file server | Share copies the approved revisions to the customer's own folder on the Large File Exchange site and invites the person there as a B2B guest, view only. The repository is never reachable from outside, and the guest is on a site that holds no register | Checked |
| REQ-P72 | Only what is approved is sent, and only by the people whose document it is | Share takes released revisions only, from the owner or a super user; several documents go in one share, and every later share adds to the same customer folder rather than making another one | Checked |
| REQ-P73 | What was sent, to whom and when, is kept where the customer's work is | Every share is appended to the customer's own share log (`02_Customers\<customer>\Shared\DMS-Shared-Log.csv`), a Control Audit row is written per document, and the row on the page says who it went to and until when | Checked |
| REQ-P74 | A share does not last for ever | Files on the Exchange site are removed a set number of days after their last share (`DMS_EX_DAYS`), and the page shows a share that has expired as expired - what was sent for one quotation is not still downloadable a year later | Built |
| REQ-P75 | HR shares with a person, not with a customer | A file under `01_General\HR` is shared with a candidate the same way - their own folder on the Exchange site, a guest invitation, the same log and audit - without appearing in the customers list or making a customer folder | Checked |
| REQ-P76 | The share log is the DMS's, not somebody's spreadsheet | The `Shared` folder and its log are kept by the DMS: read only on the page, no workflow, no rename, no delete - they are the record of what left the company | Checked |
| REQ-P77 | The share log says everything a question about a share needs | One row per file shared and per share that expired: the date in UTC, the action, who shared it, who it went to (name and address), the Document ID, the title, the revision, the file, the link on the Exchange site, and the date it is available until | Checked |
| REQ-P78 | Each customer's log lives with that customer's work | `02_Customers\<customer>\Shared\DMS-Shared-Log.csv`, and HR's in `01_General\HR\Shared` - whoever may see the customer may read what was sent to them, without being given the whole company's sharing history | Checked |
| REQ-P79 | The log is appended to by the DMS and by nobody else | Written with the DMS's own account, read-only attribute set, and on Windows its own permissions: Read for users, so it cannot be renamed, deleted or edited even by the person who made the share. Appended only - a row is never changed | Checked |
| REQ-P80 | The log opens in Excel with Hebrew intact | CSV in UTF-8 with a byte-order mark, so a name in Hebrew is a name in Hebrew when somebody double-clicks it | Checked |
| REQ-P81 | A page of the repository runs, it is not downloaded | An HTML file in the repository - a dashboard, a KPI, a report - opens and runs in the browser from the DMS, in a sandbox with an origin of its own, so it cannot reach the DMS's own API or anybody's session | Checked |
| REQ-P82 | A running page can read its own folder, and nothing else | It is given a key when it is opened, good for the folder it was opened from and for a few hours (`DMS_PAGE_KEY_HOURS`): list the folder, read a file, read a file as data. Reading only - there is no way back through that key | Checked |
| REQ-P83 | A page gets a workbook as data, not as a download | `/api/kpi/data` answers a spreadsheet as its sheets and rows and a JSON as what it says, because a browser cannot open an `.xlsx` and the server may have no way out to fetch a library for it | Checked |
| REQ-P84 | A KPI's page and its data have different lives | The page stays writable so the next build replaces it; the data beside it is released into `Current_ReadOnly`, read only, in the register - the thing that draws and the thing that is measured are not the same kind of object | Checked |
| REQ-P85 | A dashboard belongs to the department, a KPI to itself | `dashboard_<something>.html` stays at the root of the department's `KPIs` folder and its data is released into that folder's own `Current_ReadOnly`; every other package makes `KPIs\<KPI>` of its own | Checked |
| REQ-P86 | The KPI Builder is its own project | It is built, versioned and opened separately, and reaches the DMS only through the API - with its own key, acting as its own AD account. The DMS offers **＋ New KPI** and **Edit KPI** where they make sense and hands over the folder it is about | Built |
| REQ-P87 | Finding a document does not need to know where it is | One search over the register and the file names - Document ID, title, type, customer, file - with an exact Document ID first; Path finder walks the blueprint; "What are you saving?" takes the kind of document and offers the folder it belongs in, creating it when it is missing | Checked |
| REQ-P88 | Files arrive the way they do in Explorer | Dragging files or a folder onto the list copies them in, up to 300 at a time, and the DMS asks once whether they are work in progress, something to send for approval, or something released as it is. The drop needs Modify in AD on that folder, as the file server would | Checked |
| REQ-P89 | A Hebrew name or a long path still opens in Office | The DMS gives Office a short (8.3) path when the real one is too long, and a WebDAV address of its own when even that will not do, so a document called by its Hebrew name opens and saves like any other | Checked |
| REQ-P90 | An old repository can be brought in as it is | First loading registers what is really on the file server - the type and the area from the blueprint, the document approved as it stands, its Markdown written - so a company starts with its history in the DMS rather than beside it | Built |
| REQ-P91 | The DMS can be asked why it answered as it did | Diagnostics in the browser: what Windows granted this person on a folder bit by bit, why a file cannot be edited, what SharePoint last refused, whether the KPI page's key can reach the DMS at all - each answering for whoever is signed in and changing nothing | Checked |
| REQ-P92 | The whole page is read in Hebrew or in English | Every label, every message and every notification is in both, right to left where it should be, and the choice lives in the address so a link opens in the language it was sent in | Checked |
| REQ-P93 | The customer skeleton is a shape, and stays one | Folders may be added to it - that is how the shape changes - but no document is ever filed in it, and a new customer is cut from it with its AD permissions copied, so the structure and the rights arrive together | Checked |
| REQ-P94 | One file says how this installation is set up | `webapi\.env`: the repository, the sites, the sign-in, the upkeep pass, the keys - with the first occurrence of a key winning, which is said out loud because a leftover line above is how a setting silently does not take | Checked |

### Asked for, and not built yet

| | What it would be | Why it is not done |
| --- | --- | --- |
| A package builder | An install set - `webapi\`, the scripts that run a DMS, `assets\`, the documents - instead of a copy of the working tree | Until it exists, `git pull` on the server installs the playground and the testing switches along with the product. The production `.env` keeps them off, but they should not be installed at all |
| An operations guide | Restart, the logs, the certificate's expiry, what the upkeep pass does, what to do when SharePoint refuses | The knowledge is in this project's history and in the scripts' own help, which is not where somebody looks at two in the morning |
| The production address | `dms.rh.tech` with its certificate and an IIS binding | Waiting on DNS and a certificate; the command that finishes it is one line (`Rename-DmsToProduction.ps1 -NewHost dms.rh.tech -Write`) |

### Known limits

| Limit | What it means |
| --- | --- |
| Formats the AI can read | `.docx`, `.xlsx`, `.pptx` and text are read by the DMS itself; `.pdf` with a text layer by pypdf; `.xls` needs `xlrd`; `.doc`, `.ppt` and `.rtf` go through the PDF SharePoint makes of them (so they need SharePoint configured). A scanned PDF with no text layer is invisible to the AI |
| Path length | Beyond about 200 characters Office cannot open a path; the DMS falls back to the Windows short (8.3) name, and Hebrew names reach that limit six times faster |
| Drag and drop | 300 files per drag, files and folders in, nothing out: a browser cannot hand a file back to Windows |
| Upload | 500 MB per file (`DMS_MAX_UPLOAD_MB`) |
| The upkeep pass | Automatic check-in, the read-only repair and the missing Markdown only run when `DMS_FILE_SERVICE_SECONDS` is set. It is `0` by default, which means never |
| Legacy Office formats | `.xls` needs `xlrd` in the DMS's environment; `.doc`, `.ppt` and `.rtf` are read through SharePoint's PDF of them, so they need SharePoint configured. A scanned PDF with no text layer cannot be read at all |

## Design decisions beyond the blueprint

1. **Two site collections** instead of one, so B2B guests are never on the site that holds the controlled register (01 §2).
2. **File Action Queue** plus an on-prem Workflow Service, which implements blueprint 4.2 "the workflow service account moves files" without the File System connector (01 §3.1).
3. **Approval Decisions** list, one row per approver per cycle, which makes AC-12 provable.
4. **UI Labels** list, so all text is translatable without republishing, and choice values stay as English keys.
5. Canvas instead of model-driven, to stay within Business Premium standard connectors (03).
