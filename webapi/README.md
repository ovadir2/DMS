# RH - Documents Management System (Web API and page)

A small web service inside the company network that "wraps" the file server repository, in the style of File Linker. Users sign in with their Windows login (no login screen). They pick a customer and see only what AD allows them, work with files and folders like in Explorer, save files from their PC into the right folder of `$Root`, start the approval workflow and see each file's status.

Everything else stays as it is: SharePoint keeps the records, the approval flow (DC-P1) sends the approvals in Teams, the Workflow Service (`scripts/Invoke-DmsWorkflowService.ps1`) moves the files, and the Explorer right-click still works.

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
| My documents (menu), Submit | `GET /api/documents?mine=true`, `POST /api/documents/{id}/submit` | Owner only |

Protected:
- The company structure (`$Root`, `02_Customers`, each customer folder) cannot be renamed or deleted. The depth is set with `DMS_PROTECTED_DEPTH`.
- The workflow folders (`Submitted`, `Current_ReadOnly`, `Obsolete_ReadOnly`) are managed by the DMS only.
- A registered file, or a folder that holds one, cannot be renamed or deleted.

Every action is written to the service log, and registration and submission also to Control Audit. The full API is at `/docs`.

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
