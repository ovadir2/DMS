# Enterprise Document Control - Implementation Package

Implementation of **IT-DOC-BP-001 "Enterprise Document Control and Large-File Exchange Blueprint"** (On-Premises Windows repository + Microsoft 365 control plane, about 260 Business Premium users).

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

The blueprint's own requirements, and the ones the pilot added once people used it. **Checked** means it was
tried on the pilot and behaved as written; **built** means it is in the product but nobody has put it through
its paces yet.

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
| REQ-P05 | Nothing in `Current_ReadOnly` is deleted | Delete is not offered there and the DMS refuses it, for its owner and for a super user alike; a revision leaves only by being replaced | Checked |
| REQ-P06 | View means reading, not editing | SharePoint turns the document into a PDF, the DMS fetches it and deletes the copy, and serves the PDF itself: there is nothing to type into and nothing left behind | Checked |
| REQ-P07 | Nobody approves their own document | Choosing yourself as an approver, and delegating back to the author, are both refused | Checked |
| REQ-P08 | The company AI reads the documents in force | `<document>.md` is written beside every released document, at the moment of release; the Markdown of a replaced revision is removed so nothing quotes it | Checked |
| REQ-P09 | The page works the way people already work | A folder tree and a detailed list, right-click for the commands of the row, double-click to open, drag files or a folder in from Windows | Checked |
| REQ-P10 | A document comes back by itself when it is closed | Office releases its lock when the document is closed; the DMS writes the copy back to the file server and removes it, with "Done editing" kept for when that does not happen | Built |
| REQ-P11 | A link can be shared without exposing the file server | Copy link gives a token the DMS resolves; Copy path still gives the path for whoever works that way | Built |
| REQ-P12 | What cannot be done is visible, not hidden | Every menu offers the same lines in the same order, with what does not apply greyed and the reason in its tooltip | Checked |

### Known limits

| Limit | What it means |
| --- | --- |
| Formats the AI can read | `.docx` `.xlsx` and text are read by the DMS; `.pdf` (with a text layer), `.pptx` and `.xls` need markitdown (and `xlrd` for `.xls`). `.doc`, `.ppt`, `.rtf` and scanned PDFs are not read at all and are invisible to the AI |
| Path length | Beyond about 200 characters Office cannot open a path; the DMS falls back to the Windows short (8.3) name, and Hebrew names reach that limit six times faster |
| Drag and drop | 300 files per drag, files and folders in, nothing out: a browser cannot hand a file back to Windows |
| Upload | 500 MB per file (`DMS_MAX_UPLOAD_MB`) |
| The upkeep pass | Automatic check-in, the read-only repair and the missing Markdown only run when `DMS_FILE_SERVICE_SECONDS` is set |

## Design decisions beyond the blueprint

1. **Two site collections** instead of one, so B2B guests are never on the site that holds the controlled register (01 §2).
2. **File Action Queue** plus an on-prem Workflow Service, which implements blueprint 4.2 "the workflow service account moves files" without the File System connector (01 §3.1).
3. **Approval Decisions** list, one row per approver per cycle, which makes AC-12 provable.
4. **UI Labels** list, so all text is translatable without republishing, and choice values stay as English keys.
5. Canvas instead of model-driven, to stay within Business Premium standard connectors (03).
