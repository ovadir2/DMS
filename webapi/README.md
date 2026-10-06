# RH - Documents Management System (Web API and page)

A small web service inside the company network that "wraps" the file server repository, in the style of File Linker. Users sign in with their Windows login (no login screen). They pick a customer and see only what AD allows them, work with files and folders like in Explorer, save files from their PC into the right folder of `$Root`, start the approval workflow and see each file's status.

Everything else stays as it is: SharePoint keeps the records, the approval flow (DC-P1) sends the approvals in Teams, the Workflow Service (`scripts/Invoke-DmsWorkflowService.ps1`) moves the files, and the Explorer right-click still works.

## Try it on your PC (playground)

```powershell
cd C:\dms\webapi; .\Start-DmsPlayground.ps1 -Root $Root
```

It opens `http://localhost:8080/dms/dms-page?lang=EN` on your real folders, with a temporary in-memory register instead of SharePoint and no AD checks (you are the only user). Approve or reject in **My workflows** (the yellow test buttons) instead of Teams. Uploads, renames and deletes are real changes in `-Root`, so use the test share. Add `-Lang HE` for Hebrew. AI Insights uses the RH AI (`chat.ai.rh-global.com`) and the QMS tool by default, when the PC can reach them; otherwise the search works by keywords.

## Live pilot on your PC (real SharePoint, real approvals)

```powershell
cd C:\dms\webapi; .\Start-DmsPlayground.ps1 -Root $Root -Live -ClientId $C
```

- Your real folders, the real Document Register and Control Audit on `DocumentControl-TEST`, and the real approval flow: submitting from the page sets the status, and DC-P1 sends the approvals to Teams.
- A browser window opens once to sign in to SharePoint, with the Entra app you use for PnP (`$C`). The token is cached in `%LOCALAPPDATA%\DMS`. You are the DMS user (no AD checks on the PC). To test other users and AD: add `-Users user1@rh.co.il,user2@rh.co.il` (an "Acting as" list on the page). In the pilot every user's AD / NTFS access to `$Root` is checked, the `-Admins` are not (`-NoAdCheck` turns it off).
- The Workflow Service file moves run inside the page service every 60 seconds (Submitted -> `Submitted`, Approved -> `Current_ReadOnly`, Rejected -> back). **My workflows > Move files now** runs them at once. Do not run `Invoke-DmsWorkflowService.ps1` at the same time.
- **Approvals on the page** (default `-Approvals page`): the header shows **Approvals** with the number waiting; approvers approve (optional comment) or reject (comment required) by the DC-P1 rules (Approver Matrix: every mandatory approver, then the final approver). Turn **DC-P1 Off** in Power Automate for the pilot. `-Approvals flow` keeps the approvals in Teams.
- **Notifications:** with page approvals, each step is written to the **DMS Notifications** list and sent by email and Teams by the DC-P2 flow (`scripts/New-DmsNotifyFlowPackage.ps1`). The links open the page on Approvals (`?view=approvals`) or My workflows (`?view=workflows`). `DMS_NOTIFY=0` turns them off.
- `-Admins` (default `roneno@rh.co.il`) are DMS super users: they may submit any document, decide any approval stage and see **All workflows** and **All pending approvals**.
- For one person to approve everything during the pilot: `..\scripts\Set-DmsTestApprover.ps1 -TenantName rhisrael -DocControlSiteAlias DocumentControl-TEST -ClientId $C -Approver roneno@rh.co.il` (it saves a backup and prints the command to restore the real approvers).


### Let the approvers try it (from their PCs)

```powershell
.\Start-DmsPlayground.ps1 -Live -Share -Users dana@rh.co.il,eli@rh.co.il
```

- The DMS listens on the network: the approvers open `http://<your PC>.rh.local:8080/dms/dms-page` (the script prints the address; the links in the email / Teams notifications point there too). Port 8080 is opened in the Windows firewall for the domain network (run PowerShell as administrator the first time, or ask IT).
- **Acting as** is in the ⋮ menu, for DMS super users only (also on the server with Windows sign-in): see and act as another user, with that user's AD rights, and back. With `-Share` in the pilot everyone reaches the DMS as you (the person who runs it) and uses **Acting as** to pick themselves - not a sign-in, pilot only. Their AD / NTFS rights are checked (`-Users` must be their emails, with Microsoft 365 accounts).
- Open on their PC uses the network path (`\\FILE-SERVER\...`), or the DMS link for long paths; your drive letters are only for you. Word opens and saves with their own Windows rights.
- Your PC must stay on with the DMS running. For real use: the server install below (IIS, Windows sign-in, no Acting as).

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
| **Search** (one box, the whole repository: 01_General, 02_Customers ...): while typing, up to 10 suggestions (customers, folders, documents with ID and status, file names); Enter or 🔎 shows the full results: smart suggestions plus folders, documents and files with their path. Several words match in any order; an exact Document ID comes first | `GET /api/search?q=&scope=quick&limit=`, `POST /api/ai/find` | Only what AD allows; system folders (`03_`, `04_Workflow_System`, `05_`) are never searched |
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

## Installation guide (step by step)

Two ways to run the DMS. **A** is the pilot on one PC (what runs today). **B** is the production install on a Windows server for all users. Do the steps in order; each ends with a check.

### Before you start (both)

| What | Who | Notes |
|---|---|---|
| Git and Python 3.11+ (`py` launcher) on the PC or server | IT | `py --version` |
| PnP PowerShell 2.x and an Entra app for PnP (`$C`, its Client ID) | M365 admin | Used by the scripts in `scripts\` |
| The repository share `$Root` (e.g. `\\FILE-SERVER\Corporate_Data_TEST`) | IT | The DMS account needs **Modify** on it |
| SharePoint sites `DocumentControl-TEST` and `LargeFileExchange-TEST` | M365 admin | Created by step 2 below if missing |
| Power Automate, Standard license | each flow owner | DC-P2 uses Standard connectors only |

### A. Pilot on a PC (live, your own sign-in)

1. **Get the code**
   ```powershell
   git clone https://github.com/ovadir2/DMS.git C:\dms
   cd C:\dms\webapi; py -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt
   ```
   Check: `.\.venv\Scripts\python -c "import dms_api"` prints nothing.
2. **SharePoint lists** (once per site): `..\scripts\Provision-DMS.ps1 -TenantName rhisrael -ClientId $C -OwnerUpn <you> -Language he` creates Document Register, Control Audit, Approver Matrix, Approval Decisions and Delegations with their views. Then `..\scripts\New-DmsNotifyFlowPackage.ps1 -TenantName rhisrael -ClientId $C -DocControlSiteAlias DocumentControl-TEST` creates **DMS Notifications** and the DC-P2 flow package.
   Check: the lists appear in Site contents.
3. **Notifications flow:** Power Automate › My flows › Import › Import package (legacy) › the zip from step 2 › connect SharePoint, Outlook and Teams › Import. Open **DC-P2 Pilot Notifications** › **Turn on**. Keep only one copy. Turn **DC-P1 Off** (the pilot approves on the page).
   Check: the flow shows *On*.
4. **Folder tree:** the blueprint is the structure in `docs\root-structure.txt` (Management, and per customer: Customer_Profile, Commercial, Pricing, Develop\ATEFiles, Develop\Products\<Product> with the stages 01-10, Engineering, DFM, DFT, NPI, Manufacturing, Quality_QC, Supply_chain, Shared, Archive). List the customers and their products in a CSV (columns `CustomerName,ProductName`, one row per product; `scripts\customers.example.csv` holds Customer_A with Product_1), then `..\scripts\New-DmsFileServerTree.ps1 -Root $Root -CustomersCsv .\customers.csv -WhatIf` and again without `-WhatIf`. Existing folders are kept and existing products of a listed customer are completed; `-CompleteExisting` alone completes every customer. On the DMS page, **New folder** under `02_Customers` or under a customer's `Develop\Products` creates the same blueprint folders. The folder list the script uses is `scripts\blueprint-folders.txt`, generated from `webapi\dms_api\blueprint.py` (`py -m dms_api.blueprint > ..\scripts\blueprint-folders.txt`).

5. **Start the DMS**
   ```powershell
   cd C:\dms\webapi; .\Start-DmsPlayground.ps1 -Root $Root -Live -ClientId $C
   ```
   A browser window asks you to sign in to SharePoint once (cached in `%LOCALAPPDATA%\DMS`). The page opens at `http://localhost:8080/dms/dms-page`.
   Check: `http://localhost:8080/api/health` shows `"rootReachable": true`; ⋮ › **SharePoint check** shows every list with ✓.
6. **Test notification:** SharePoint check › **Send me a test notification**. An email and a Teams message arrive within a few minutes (else open the flow's Run history).
7. **Customer sharing (optional):** set `DMS_EX_SITE_URL` (the Start script does it from `-ExchangeSite`). For the OneDrive shortcut, add the Microsoft Graph delegated permission **Files.ReadWrite.All** to the Entra app `$C` and grant admin consent.
   Check: share an approved test file with your own external address; the invitation arrives and `02_Customers\<Customer>\Shared\DMS-Shared-Log.csv` gets a row.
8. **Bookmarks for users:** Chrome › Bookmarks › Import › `docs\RH-DMS-Bookmarks.html`.

**Update the pilot:** `cd C:\dms; git pull`, then stop the DMS (Ctrl+C) and start it again (step 5). A change in the page only needs Ctrl+F5 in the browser.

### B. Production on a Windows server (IIS, all users)

The server must be joined to the domain, reach `$Root`, and have outbound HTTPS to Microsoft 365 and to the RH AI portal.

1. **Server features:** install Python 3.11+ (all users), IIS with **Windows Authentication**, and the **HttpPlatformHandler** module.
   Check: IIS Manager shows *Windows Authentication* under Authentication.
2. **Code and packages**
   ```powershell
   git clone https://github.com/ovadir2/DMS.git C:\DMS
   cd C:\DMS\webapi; py -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt
   mkdir logs; Copy-Item .env.example .env
   ```
3. **Service account:** create a gMSA (e.g. `RH\gmsa-dms$`), install it on the server, and give it **Modify** on `$Root`. It does all reading and writing; users keep their own NTFS rights, checked per request.
4. **Entra app (app-only, no passwords):** reuse `RH-DMS-Workflow-Service` or create an app with a certificate.
   - SharePoint: **Sites.Selected** with *write* on `DocumentControl` and on `LargeFileExchange`.
   - Microsoft Graph (for the OneDrive shortcut): **Files.ReadWrite.All** application permission, admin consent. Without it sharing still works and the shortcut is skipped.
   - Export the certificate with its private key as PEM to `C:\DMS\webapi\cert.pem` (readable by the gMSA only).
5. **Settings:** edit `C:\DMS\webapi\.env` (all keys are explained in `.env.example`). The minimum:
   ```ini
   DMS_REPOSITORY_ROOT=\\FILE-SERVER\Corporate_Data
   DMS_SITE_URL=https://rhisrael.sharepoint.com/sites/DocumentControl
   DMS_TENANT_ID=<tenant id>
   DMS_CLIENT_ID=<app id>
   DMS_CERT_PATH=C:\DMS\webapi\cert.pem
   DMS_CERT_THUMBPRINT=<thumbprint>
   DMS_SP_AUTH=certificate
   DMS_AUTH_MODE=windows
   DMS_APPROVALS=page            # or flow: approvals in Teams with DC-P1 On
   DMS_FILE_SERVICE_SECONDS=60   # file moves inside the service; do not also run Invoke-DmsWorkflowService.ps1
   DMS_PAGE_URL=https://<server>/dms/dms-page
   DMS_ADMINS=<super user emails, comma separated>
   DMS_EX_SITE_URL=https://rhisrael.sharepoint.com/sites/LargeFileExchange
   ```
   Optional: `DMS_EX_DAYS` (30), `DMS_SHARED_LOG`, `DMS_EX_SHORTCUT`, `DMS_DELEGATION_DAYS` (3), `DMS_WEEKEND` (fri,sat), the AI and File Linker keys.
6. **SharePoint lists and flows** on the production site: as in A2 and A3, with the production site alias.
   **Folder tree** on the production `$Root`: as in A4, adding `-ApplyAcl` (and `-CreateAdGroups -GroupOU <OU>` the first time) for the NTFS permissions per customer.
7. **IIS site:** new site on `C:\DMS\webapi`, HTTPS binding with the company certificate, app pool *No Managed Code*, identity = the gMSA. `web.config` is already in the folder (Windows Authentication on, Anonymous off). If IIS reports a locked `authentication` section, set the same in IIS Manager.
8. **Logo (optional):** `dms_api\static\logo.png`.
9. **Smoke test:**
   - `https://<server>/api/health`: `"rootReachable": true`.
   - `https://<server>/dms/dms-page?lang=HE` opens without a login screen and shows your name.
   - A user without access to a customer folder does not see that customer (AD check).
   - A super user: ⋮ › **SharePoint check**, all ✓, and a test notification arrives.
   - Register and submit a test file, approve it, and see it move to `Current_ReadOnly` within a minute.
10. **Link it** (next section) and run the user training (`docs\presentations\DMS-Approval-Flow.pptx`).

**Update production:** `cd C:\DMS; git pull; webapi\.venv\Scripts\pip install -r webapi\requirements.txt`, then recycle the app pool. **Roll back:** `git checkout <previous commit>` and recycle.

**Testing without IIS:** set `DMS_AUTH_MODE=dev` and `DMS_DEV_USER` (optional `DMS_DEV_USERS=a@rh.co.il,b@rh.co.il`: an "Acting as" list at the top of the page to switch user, e.g. owner and approver; add `DMS_DEV_AD_CHECK=1` on a domain PC to check each acting user's AD / NTFS access to `$Root` - the `DMS_ADMINS` are not checked), then `.\.venv\Scripts\python -m uvicorn dms_api.main:app --port 8080`. In dev mode there are no AD checks.

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
