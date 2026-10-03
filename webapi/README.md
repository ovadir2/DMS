# RH - Documents Management System (Web API and page)

A small web service inside the company network that "wraps" the file server repository, in the style of File Linker. Users sign in with their Windows login (no login screen). They pick a customer and see only what AD allows them, work with files and folders like in Explorer, save files from their PC into the right folder of `$Root`, start the approval workflow and see each file's status.

Everything else stays as it is: SharePoint keeps the records, the approval flow (DC-P1) sends the approvals in Teams, the Workflow Service (`scripts/Invoke-DmsWorkflowService.ps1`) moves the files, and the Explorer right-click still works.

## Try it on your PC (playground)

```powershell
cd C:\dms\webapi; .\Start-DmsPlayground.ps1 -Root $Root
```

It opens `http://localhost:8080/dms/dms-page?lang=EN` on your real folders, with a temporary in-memory register instead of SharePoint and no AD checks (you are the only user). Approve or reject in **My workflows** (the yellow test buttons) instead of Teams. Uploads, renames and deletes are real changes in `-Root`, so use the test share. Add `-Lang HE` for Hebrew, and `-AiUrl https://chat.ai.rh-global.com -AiToken <token> -AiModel <model>` to try AI Insights against the on-prem LLM. Without them, Find a file works by keywords.

## Live pilot on your PC (real SharePoint, real approvals)

```powershell
cd C:\dms\webapi; .\Start-DmsPlayground.ps1 -Root $Root -Live -ClientId $C
```

- Your real folders, the real Document Register and Control Audit on `DocumentControl-TEST`, and the real approval flow: submitting from the page sets the status, and DC-P1 sends the approvals to Teams.
- A browser window opens once to sign in to SharePoint, with the Entra app you use for PnP (`$C`). The token is cached in `%LOCALAPPDATA%\DMS`. You are the DMS user (no AD checks on the PC).
- The Workflow Service file moves run inside the page service every 60 seconds (Submitted -> `Submitted`, Approved -> `Current_ReadOnly`, Rejected -> back). **My workflows > Move files now** runs them at once. Do not run `Invoke-DmsWorkflowService.ps1` at the same time.
- **Approvals on the page** (default `-Approvals page`): the header shows **Approvals** with the number waiting; approvers approve (optional comment) or reject (comment required) by the DC-P1 rules (Approver Matrix: every mandatory approver, then the final approver). Turn **DC-P1 Off** in Power Automate for the pilot. `-Approvals flow` keeps the approvals in Teams.
- **Notifications:** with page approvals, each step is written to the **DMS Notifications** list and sent by email and Teams by the DC-P2 flow (`scripts/New-DmsNotifyFlowPackage.ps1`). The links open the page on Approvals (`?view=approvals`) or My workflows (`?view=workflows`). `DMS_NOTIFY=0` turns them off.
- `-Admins` (default `roneno@rh.co.il`) are DMS super users: they may submit any document, decide any approval stage and see **All workflows** and **All pending approvals**.
- For one person to approve everything during the pilot: `..\scripts\Set-DmsTestApprover.ps1 -TenantName rhisrael -DocControlSiteAlias DocumentControl-TEST -ClientId $C -Approver roneno@rh.co.il` (it saves a backup and prints the command to restore the real approvers).

## How it knows the AD permissions

1. IIS signs the user in with **Windows Authentication**, using the login of the person at the PC. Browsers on domain PCs do this silently.
2. IIS passes the user's Windows token to the service (`forwardWindowsAuthToken` in `web.config`). The token holds the user and all of their AD groups.
3. Before showing or changing anything, the service asks Windows: "may this token read (or write) this folder or file?" (Win32 `AccessCheck` against the item's NTFS permissions). Items the user may not read are not shown, and actions they may not do are refused.

So the NTFS permissions on the file server (the `DL_FS_*` groups, docs/02 §3.2) are the only place access is managed. The service account (gMSA) does the actual reading and writing, and needs Modify on `$Root`. No Kerberos delegation is needed.

## Following the blueprint tree

`dms_api/blueprint.py` holds the Appendix A tree (the same tree `scripts/New-DmsFileServerTree.ps1` creates) with English and Hebrew names and short hints. Folder tiles show those names and hints, folders are listed in blueprint order, and the page guides users to the right folder. Folders that are not in the blueprint still show with their own names.

## What users can do

| On the page | API | Rules |
| --- | --- | --- |
| **Location** lists along the blueprint tree (Customers › Customer › Commercial / Projects › Project › Engineering, Development 01-10, Test engineering ...). Choosing a folder in one list fills the next list with its subfolders | `GET /api/levels?path=` | Only folders the user may open, in blueprint order, with English/Hebrew names. System and workflow folders are not offered |
| **⟳ New revision** on an approved document: from a copy of the approved revision or a file from the PC; saved as `<name>_RevNN_DRAFT.<ext>` on the same record; optional submit | `POST /api/documents/{id}/revise` (multipart: optional `file`, `submit`) | Only Approved documents; the user must see the approved file and may write in its folder. On approval the previous revision moves to `Obsolete_ReadOnly` |
| **＋ New document**: a file from the PC saved into the open folder and registered (and submitted) in one step | `POST /api/files/upload` + `POST /api/documents` | Write permission in the folder |
| Workflow folders (`Submitted`, `Current_ReadOnly`, `Obsolete_ReadOnly`, `Working`) | | Read only on the page: no upload, new folder, rename or delete in them, and a folder holding them cannot be renamed or deleted |
| **⇪ DMS First loading** (super users, ⋮ menu): load documents approved in the old repository - source + target folder, dry run, then each file into `Current_ReadOnly`, registered as Approved, File Linker link moved (WebAPI#1 check, WebAPI#2 replace), CSV report | `POST /api/first-load`, `GET /api/first-load/{id}` | Target under the root and not a workflow folder; repeatable (loaded files are skipped). File Linker in `.env` (`DMS_FL_*`) |
| **Search** (one box, the whole repository: 01_Management, 02_Customers ...): while typing, up to 10 suggestions (customers, folders, documents with ID and status, file names); Enter or 🔎 shows the full results: smart suggestions plus folders, documents and files with their path. Several words match in any order; an exact Document ID comes first | `GET /api/search?q=&scope=quick&limit=`, `POST /api/ai/find` | Only what AD allows; system folders (`03_`, `04_Workflow_System`, `05_`) are never searched |
| **🧭 Path finder** (folder toolbar or menu): build a path level by level from the blueprint tree, with the blueprint folders that do not exist yet marked *new*; then Go there, Create and go, Upload here or Copy path | `GET /api/pathfinder?path=`, `POST /api/pathfinder/create?path=` | Existing folders only where AD allows; new folders only where the blueprint expects them and the user may write. Customers and projects are offered only when they exist |
| **What are you saving?** Pick a document kind (quotation, RFQ, SOW, ECO, test report ...) and, when needed, a project. The page goes to the blueprint folder and opens the upload window | `GET /api/guide`, `GET /api/guide/target`, `POST /api/guide/create` | A missing blueprint folder is created only with the user's consent and write permission |
| Pick a customer | `GET /api/customers` | Only customers whose folder the user may open |
| Open folders | `GET /api/browse?path=` | Only items the user may read, each file with its DMS status |
| Upload file into the open folder | `POST /api/files/upload` | Needs write permission there. Saved to a temporary name, then renamed. Replacing needs the "replace" option |
| New folder | `POST /api/folders` | Needs write permission |
| Rename | `POST /api/items/rename` | Needs write permission. Not for controlled documents |
| Delete | `POST /api/items/delete` | Needs write permission. Moves the item to `04_Workflow_System\Recycle\<date>\<user>\...` so IT can restore it. Not for controlled documents |
| **Rename / Delete a document in Working** (folder view, My workflows) | `POST /api/documents/{id}/rename`, `POST /api/documents/{id}/delete` | Owner or super user, Working only. Rename: the register follows (working path, title, `_RevNN` draft revision). Delete: the file to the recycle folder, the record stays as Archived (hidden); a new revision draft is deleted and the approved revision stays current. Both in Control Audit |
| Open (Excel/Word from the server), Download | `GET /api/files/download` | Read permission. A path over 200 characters opens through its Windows short (8.3) form |
| **🔗 Copy link** (folder toolbar, each file; My workflows: current and working path) | | Copies the full path (also on http intranet addresses) |
| Start workflow (register and submit) | `POST /api/documents` | Type, area and control mode are preselected from the blueprint folder (`GET /api/classify`). **Choose the approvers myself**: a checkbox list of all RH Microsoft 365 users (filter, and typing searches the whole directory); all of them must approve, in one stage. Default: the Approver Matrix, shown in the dialog |
| **My workflows** (header): every document the user owns or registered/submitted, with counts per status (Working, Submitted, Approved, Rejected - back to you), days waiting, the last decision with the approver's comment, and the full history | `GET /api/my-workflows` | The user's own workflows only. Built from the Document Register and Control Audit |
| Submit (or resubmit after a rejection or a withdraw) | `POST /api/documents/{id}/submit` | Owner or super user. The dialog preselects the approvers chosen last time (`GET /api/documents/{id}/approvers`); untick to go back to the Approver Matrix |
| Withdraw | `POST /api/documents/{id}/withdraw` | The file returns from `Submitted` to its place at once, under its own name |
| **Approvals** (header, pilot `DMS_APPROVALS=page`): documents waiting for the user's approval, with stage, who approved, days waiting; Approve / Reject with comment | `GET /api/approvals`, `POST /api/approvals/{id}` | Only the pending approvers of the current stage (Approver Matrix or chosen approvers), or a super user, who sees every pending approval by default. A type with no Matrix rule goes to the super users. Each decision is a Control Audit row |
| **⇄ Delegate** (Approvals): someone else approves instead, chosen from the RH users, with a note | `POST /api/approvals/{id}/delegate` | The approver, or a super user for any waiting approver. Valid `DMS_DELEGATION_DAYS` working days (default 3, weekend `DMS_WEEKEND=fri,sat`), then it returns to the approver. Logged in the Delegations list and in Control Audit; the delegate is notified |
| **AI Insights** (header): **Ask** the RH AI, or **📚 QMS** (the QMS RAG of the AI portal) | `POST /api/ai/ask`, `POST /api/ai/rag` | See below |
| **🩺 SharePoint check** (super users, ⋮ menu): each DMS list (exists, items, may this account add), notifications status, the last notifications, **Send me a test notification**, the last SharePoint errors | `GET /api/diagnostics/sharepoint`, `POST /api/diagnostics/notify-test` | Read only, except the test row |
| The **RH logo** / system name | | Back to a fresh home screen |

Protected:
- The company structure (`$Root`, `02_Customers`, each customer folder) cannot be renamed or deleted. The depth is set with `DMS_PROTECTED_DEPTH`.
- The workflow folders (`Submitted`, `Current_ReadOnly`, `Obsolete_ReadOnly`) are managed by the DMS only.
- A registered file, or a folder that holds one, cannot be renamed or deleted.

Every action is written to the service log, and registration and submission also to Control Audit. The full API is at `/docs`.

## AI Insights (RH on-prem AI)

The panel has two tabs. Answers appear in the panel, in the language of the question (a Hebrew question gets a Hebrew answer). Every question and answer is written to Control Audit (CorrelationId `AI`).

- **Ask** - the RH AI chat (`https://chat.ai.rh-global.com`). The DMS sends what the chat page sends: `POST <DMS_AI_URL><DMS_AI_PATH>` (default `/stream`) with `{"model": "org-chat", "messages": [...]}`; the answer is read from JSON, from streamed `data:` lines or from plain text. A question about a file (the quick questions: summary, requirements, risks, dates) first checks that the user may read it (AD), uploads it like the chat's 📎 (`POST /upload`, once per file version) and attaches its id; if the upload fails, the file's text (Word, Excel, PowerPoint, PDF, text; up to `DMS_AI_MAX_CHARS`) goes with the question.
- **📚 QMS** - the QMS RAG tool of the AI portal: `POST https://aiportal.ai.rh-global.com/webhook/qms-chat` with `{question, sessionId, history}`; the answer comes with its sources (procedure, section, file). Follow-up questions keep the last turns. More tools: `DMS_RAG_TOOLS=qms,...` (each `<tool>-chat`).
- **Smart search** (the main search box) uses the RH AI to turn a request into a search plan and to rank the matches; the AI sees only names the user may see, never file contents, and never decides on access. Without the AI, the same search runs on keywords.

Settings (`.env`, on-prem, no token): `DMS_AI_URL`, `DMS_AI_PATH`, `DMS_AI_UPLOAD_PATH`, `DMS_AI_MODEL`, `DMS_AI_MAX_CHARS`; `DMS_RAG_URL`, `DMS_RAG_TOOLS`. `DMS_AI_TOKEN` / `DMS_RAG_TOKEN` only if the portal ever asks for sign-in (a service token, never a personal one).

## Install on a Windows server (IIS)

The server must be joined to the domain, reach `$Root`, and have outbound HTTPS to Microsoft 365.

1. Install Python 3.11+, the IIS **Windows Authentication** feature, and the **HttpPlatformHandler** module.
2. Copy this `webapi` folder to `C:\DMS\webapi`, then in PowerShell:
   ```powershell
   cd C:\DMS\webapi; py -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt; Copy-Item .env.example .env; notepad .env
   ```
3. **SharePoint access** for the service (app-only, no user passwords): an app with `Sites.Selected` and write on the DocumentControl site, and a certificate. The `RH-DMS-Workflow-Service` app can be reused. Export the certificate with its private key as PEM to `DMS_CERT_PATH`.
4. IIS: create a site on `C:\DMS\webapi` with an HTTPS binding. Run its app pool as a gMSA with Modify on `$Root`. If IIS reports a locked `authentication` section, set **Windows Authentication = Enabled** and **Anonymous = Disabled** in IIS Manager instead of in `web.config`.
5. Put the company logo at `dms_api\static\logo.png` (optional, a drawn "rh" is used without it).
6. Open `https://<server>/api/health` (`rootReachable` must be `true`), then `https://<server>/dms/dms-page?lang=EN` (or `HE`).

To run it without IIS (testing): set `DMS_AUTH_MODE=dev` and `DMS_DEV_USER`, then `.\.venv\Scripts\python -m uvicorn dms_api.main:app --port 8080`. In dev mode there are no AD checks.

## Link it

- **RH Navigator:** a menu link to `https://<server>/dms/dms-page?lang=EN`.
- **Explorer right-click:**
  ```powershell
  .\scripts\Install-DmsExplorerMenu.ps1 -AppUrl 'https://<server>/dms/dms-page?lang=EN' -RepositoryRoot $Root -MenuText 'Start workflow'
  ```
- From outside the network: `DMS_AUTH_MODE=entra` behind Entra Application Proxy (an Entra app registration with an `access_as_user` scope and a SPA redirect URI). In that mode the AD file checks do not apply.

## Tests

```powershell
cd C:\DMS\webapi; .\.venv\Scripts\pip install -r requirements-dev.txt; .\.venv\Scripts\python -m pytest -q tests
```

The tests use an in-memory SharePoint and a temporary folder. The Windows token and `AccessCheck` code (`dms_api/security.py`) runs only on Windows, so verify it on the server: a user without access to a customer folder must not see that customer.
