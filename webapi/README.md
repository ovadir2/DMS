# DMS Web API

A small web service inside the company network that "wraps" the file server repository. It can see `$Root` directly, so users browse the repository, register a file and submit it for approval from the browser. RH Navigator links to it, and the Explorer right-click can open it too.

Everything else stays as it is: SharePoint keeps the records, the approval flow (DC-P1) sends the approvals in Teams, and the Workflow Service (`scripts/Invoke-DmsWorkflowService.ps1`) moves the files.

## What it offers

| Endpoint | What it does |
| --- | --- |
| `GET /dms/dms-page?lang=EN` (or `HE`) | The built-in page: Repository, My documents, Start workflow. With `&path=<UNC>&name=<file>` it opens the Start workflow form prefilled (the right-click link) |
| `GET /api/browse?path=` | Folders and files of one folder, each file with its DMS status, an **Open** link (opens it in Excel/Word from the server) and download |
| `POST /api/documents` | Registers a file (`path`, `documentType`, `documentArea`, `controlMode`, `submit`). `submit: true` also submits it for approval |
| `POST /api/documents/{id}/submit` | Submits a registered document (owner only, status Working) |
| `GET /api/documents?mine=true&status=` | The register, optionally only mine or one status |
| `GET /api/options` | Document types, areas and control modes from the list |
| `GET /api/files/download?path=` | Downloads a file |
| `GET /api/health`, `GET /api/me` | Health check and the signed-in user |
| `GET /docs` | The full OpenAPI description, for RH Navigator developers |

Every path is checked to be inside `DMS_REPOSITORY_ROOT`. A file is registered once only, and files already in `Submitted`, `Current_ReadOnly` or `Obsolete_ReadOnly` cannot be registered again. Registration and submission write Control Audit rows.

## Install on a Windows server (IIS)

The server needs read and write access to `$Root` and outbound HTTPS to Microsoft 365.

1. Install Python 3.11+ and the IIS **HttpPlatformHandler** module.
2. Copy this `webapi` folder to `C:\DMS\webapi`, then in PowerShell:
   ```powershell
   cd C:\DMS\webapi; py -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt; Copy-Item .env.example .env; notepad .env
   ```
3. **Entra app registration "RH DMS Web"** (one app for the page and the API):
   - Expose an API: Application ID URI `api://<app id>`, scope `access_as_user`.
   - Authentication: add a **Single-page application** redirect URI `https://<server>/dms/dms-page`.
   - Put its app id in `DMS_API_AUDIENCE` and `DMS_SPA_CLIENT_ID`.
4. **SharePoint access** for the service (app-only, no user passwords): an app with `Sites.Selected` and write on the DocumentControl site, and a certificate. The `RH-DMS-Workflow-Service` app from `Provision-DMS.ps1` can be reused. Export the certificate with its private key as PEM to `DMS_CERT_PATH`.
5. IIS: create a site (or application) on `C:\DMS\webapi` with an HTTPS binding. The app pool identity (a gMSA) needs Modify on `$Root`. `web.config` starts uvicorn.
6. Open `https://<server>/api/health`. `rootReachable` must be `true`. Then open `https://<server>/dms/dms-page?lang=EN`.

To run it without IIS (testing): `.\.venv\Scripts\python -m uvicorn dms_api.main:app --port 8080`.

## Link it

- **RH Navigator:** add a menu link to `https://<server>/dms/dms-page?lang=EN`. To call the API from Navigator's own pages instead, add the Navigator address to `DMS_ALLOWED_ORIGINS` and request a token for `api://<app id>/access_as_user`.
- **Explorer right-click:**
  ```powershell
  .\scripts\Install-DmsExplorerMenu.ps1 -AppUrl 'https://<server>/dms/dms-page?lang=EN' -RepositoryRoot $Root -MenuText 'Start workflow'
  ```

## Notes

- The service reads the files with its own identity, so the page shows the whole repository to every signed-in user. Restrict the browse view later with the `DL_FS_*` groups if needed.
- `DMS_AUTH_MODE=header` is for a reverse proxy that already signs users in and passes the email in `DMS_USER_HEADER`. `dev` uses a fixed user and is for testing only.

## Tests

```powershell
cd C:\DMS\webapi; .\.venv\Scripts\pip install -r requirements-dev.txt; .\.venv\Scripts\python -m pytest -q tests
```

The tests use an in-memory SharePoint and a temporary folder, so they need no network.
