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
| **🧭 Path finder** (folder toolbar or menu): build a path level by level from the blueprint tree, with the blueprint folders that do not exist yet marked *new*; then Go there, Create and go, Upload here or Copy path | `GET /api/pathfinder?path=`, `POST /api/pathfinder/create?path=` | Existing folders only where AD allows; new folders only where the blueprint expects them and the user may write. Customers and projects are offered only when they exist |
| **What are you saving?** Pick a document kind (quotation, RFQ, SOW, ECO, test report ...) and, when needed, a project. The page goes to the blueprint folder and opens the upload window | `GET /api/guide`, `GET /api/guide/target`, `POST /api/guide/create` | A missing blueprint folder is created only with the user's consent and write permission |
| Pick a customer | `GET /api/customers` | Only customers whose folder the user may open |
| Open folders | `GET /api/browse?path=` | Only items the user may read, each file with its DMS status |
| Search: All, Customer, Project, Document ID, File | `GET /api/search?q=&scope=` | Same filter |
| Upload file into the open folder | `POST /api/files/upload` | Needs write permission there. Saved to a temporary name, then renamed. Replacing needs the "replace" option |
| New folder | `POST /api/folders` | Needs write permission |
| Rename | `POST /api/items/rename` | Needs write permission. Not for controlled documents |
| Delete | `POST /api/items/delete` | Needs write permission. Moves the item to `04_Workflow_System\Recycle\<date>\<user>\...` so IT can restore it. Not for controlled documents |
| Open (Excel/Word from the server), Download | `GET /api/files/download` | Read permission |
| Start workflow (register and submit) | `POST /api/documents` | As before |
| **My workflows** (header): every document the user owns or registered/submitted, with counts per status (Working, Submitted, Approved, Rejected - back to you), days waiting, the last decision with the approver's comment, and the full history | `GET /api/my-workflows` | The user's own workflows only. Built from the Document Register and Control Audit |
| Submit (or resubmit after a rejection) | `POST /api/documents/{id}/submit` | Owner only |
| **Approvals** (header, pilot `DMS_APPROVALS=page`): documents waiting for the user's approval, with stage, who approved, days waiting; Approve / Reject with comment | `GET /api/approvals`, `POST /api/approvals/{id}` | Only the pending approvers of the current stage (Approver Matrix), or a super user. Each decision is a Control Audit row |
| **AI Insights** (header, or ✦ AI on a file): ask about a document (summary, key requirements, risks, dates) or the company knowledge | `GET /api/ai/status`, `POST /api/ai/ask` | See below |
| **Find a file** (AI Insights panel, or **✦ Smart** in the search): describe the file in your own words ("the latest FCT report of the CRU4 project") and get a short list of suggestions, each with where it is, its DMS status, why it was suggested, and Open / Go to folder / Ask about it | `POST /api/ai/find` | Searches only folders the user may read (AD). Superseded revisions and the approval queue are skipped. Works without the AI too, by keywords |

Protected:
- The company structure (`$Root`, `02_Customers`, each customer folder) cannot be renamed or deleted. The depth is set with `DMS_PROTECTED_DEPTH`.
- The workflow folders (`Submitted`, `Current_ReadOnly`, `Obsolete_ReadOnly`) are managed by the DMS only.
- A registered file, or a folder that holds one, cannot be renamed or deleted.

Every action is written to the service log, and registration and submission also to Control Audit. The full API is at `/docs`.

## AI Insights (RH on-prem RAG LLM)

AI Insights connects to RH's on-prem LLM, the Open WebUI at `https://chat.ai.rh-global.com`, through its API, with a service token (`DMS_AI_*` in `.env`). Without these settings, AI Insights stays hidden.

- **About a file:** the service checks that the user may read the file (AD), uploads it to Open WebUI (once per version), and asks the question with the file attached. The DMS record (ID, type, status, revision, owner) is added as context.
- **Company knowledge:** without a file, the question goes to the knowledge bases in `DMS_AI_KNOWLEDGE_IDS` (RAG), and the answer lists its sources.
- **Find a file:** the AI turns the request into a search plan (keywords, customer, project, document kind, newest or not). The service searches only the folders the user may read and scores the matches by name, blueprint folder and date. The AI then picks the best ones and says why. The AI only ever sees the names of customers and files the user is allowed to see, never file contents, and never decides on access. Without AI Insights configured, the same search runs on the request's keywords.
- Answers are in the page language (English or Hebrew). Documents go only to the on-prem LLM, and every question is written to the service log.

Setup:
1. In Open WebUI, create a service user for the DMS and get its token (Settings > Account; enable API keys in Admin > Settings if needed).
2. Pick the model id (`GET /api/models`) and, optionally, the knowledge base ids (Workspace > Knowledge).
3. The DMS server must reach `chat.ai.rh-global.com` over HTTPS.

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
