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

## Requirement traceability

| Req | How it is met |
| --- | --- |
| REQ-01, REQ-02 | Files only on the file server. The register stores UNC and SHA-256 |
| REQ-03, REQ-16 | AGDLP groups, and SharePoint groups backed by Entra groups (02) |
| REQ-04, REQ-05 | `ControlMode`: Collaboration / Workflow Optional / Workflow Required / Read-Only Record |
| REQ-06 | Approver Matrix + Impact Routing + per-revision approver sets, validated on the server (DC-03) |
| REQ-07 | Teams Approvals + Flow-bot chat, templates in UI Labels. No attachments |
| REQ-08, REQ-09, REQ-10 | Separate Exchange site, per-request folders, native upload, verified-deletion gate |
| REQ-11, REQ-12, REQ-13 | CrowdStrike blocks acceptance (EX-06). Veeam scope and compliance points (blueprint 11). `RetentionClass` |
| REQ-14 | Indexed metadata, views, append-only audit lists, version history |
| REQ-15 | PLM/MAE/Priority reference columns, and the `ReleaseToPLMQueue` manifest (DC-10) |
| REQ-17 | Attachments disabled on every list. File moves via File Action Queue and the on-prem service |

## Design decisions beyond the blueprint

1. **Two site collections** instead of one, so B2B guests are never on the site that holds the controlled register (01 §2).
2. **File Action Queue** plus an on-prem Workflow Service, which implements blueprint 4.2 "the workflow service account moves files" without the File System connector (01 §3.1).
3. **Approval Decisions** list, one row per approver per cycle, which makes AC-12 provable.
4. **UI Labels** list, so all text is translatable without republishing, and choice values stay as English keys.
5. Canvas instead of model-driven, to stay within Business Premium standard connectors (03).
