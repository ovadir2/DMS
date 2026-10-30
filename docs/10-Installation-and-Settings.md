# Installation and settings

Everything needed to put the DMS on a server, and every setting it reads. The pilot was installed this way;
`docs/Go-Live.md` is the checklist for doing it again for production.

---

## 1. What the DMS is made of

| Piece | Where it runs | What it does |
| --- | --- | --- |
| The repository | The file server (`E:\Shares`, shared as `\\RHFS02\...`) | The documents themselves. Nothing else holds content |
| The web service | IIS on the file server, `webapi/` (FastAPI behind HttpPlatformHandler) | The page and the API: what people see, and every rule |
| SharePoint | Microsoft 365, two sites | The register, Control Audit, approval decisions, the copies people read and edit, and the exchange with customers |
| The AI portal | n8n, outside the DMS | Answers questions from the Markdown the DMS writes beside each released document |

The web service is the only thing with rights on the file server. Everyone else works through it.

## 2. Before you start

- A Windows server that can see the repository, with **IIS**, **HttpPlatformHandler** and **Python 3.11+**.
- An account for the DMS to run as: a domain account or a gMSA (the pilot runs as `RH\gmsa-dms-pilot$`).
  It needs **Modify** on the repository; nobody else needs write access on `Current_ReadOnly`.
- **PowerShell 7.4+** and `Install-Module PnP.PowerShell` on the machine that provisions SharePoint.
- An **Entra app registration** for the DMS, with a certificate, and `Sites.Selected` granted on each site -
  for **SharePoint** and for **Graph** separately. They are two grants and the second is the one forgotten.
- A certificate for the site, and a DNS name (`dms.rh.tech`).

## 3. SharePoint

```powershell
cd scripts
./Provision-DMS.ps1 -TenantName rhisrael -ClientId <app id> -OwnerUpn it.admin@rh.co.il -Language he
./Grant-DmsSitePermission.ps1 -Site <site url> -AppId <app id>      # SharePoint and Graph
python new_dms_cert.py                                              # the certificate, then upload it to the app
```

Two libraries the DMS uses and cannot create itself (an app-only account may not create a list - SharePoint
answers `403 UnauthorizedAccessException`), so make them by hand on the control site:

- **`Approvals`** - the copy a person edits while a document is being approved.
- **`Views`** - was the copy people read; since the DMS fetches the PDF and deletes the copy at once, it stays
  empty. Keep it, with **no standing permissions on it at all**: a standing permission beats the "view" in a
  sharing link, which is how a reading copy became editable in the pilot.

## 4. The file server

```powershell
./New-DmsFileServerTree.ps1 -Root E:\Shares -CreateAdGroups -ApplyAcl     # the tree and its AD groups
./Set-DmsAccess.ps1 -Root E:\Shares                                        # department access from dms-access.csv
./Protect-DmsReadOnly.ps1                                                  # released folders: read only for everyone but the DMS
```

`Protect-DmsReadOnly.ps1` finds the root in `webapi\.env` and the account from the site's application pool.
It keeps the AD groups a folder already had and leaves them Read and Execute; only the DMS keeps Modify. Run
it once after installing, and again if folders were created while the service was down.

## 5. The web service

```powershell
git clone https://github.com/ovadir2/dms C:\DMS\app
cd C:\DMS\app\webapi
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install xlrd           # so a legacy .xls can be read for the AI
copy .env.example .env                                   # then fill it in (section 7)
```

IIS: a site whose physical path is `C:\DMS\app\webapi`, with **Windows Authentication** on and anonymous off,
its application pool running as the DMS account, and `web.config` pointing HttpPlatformHandler at
`.venv\Scripts\python.exe -m uvicorn dms_api.main:app`.

Start and check it:

```powershell
.\scripts\Restart-Dms.ps1          # recycles the pool and waits for /api/options to answer
```

`iisreset` is **not** the way - it leaves the site stopped.

## 6. After installing

```powershell
.\scripts\Compare-DmsTree.ps1 -Path "01_General"     # the DMS and the disk agree
.\scripts\New-DmsMarkdown.ps1                        # what has no Markdown yet
.\scripts\New-DmsMarkdown.ps1 -Write                 # write it
```

A format nothing can read on the server - a legacy `.doc`, a `.ppt` - goes through SharePoint: the pass asks
it for a PDF of the document, reads the pages (pypdf) and removes the copy at once. It needs `.env` filled in
(section 7) and `DMS_REVIEW_LIBRARY` set; without them such a file is reported as "nothing to read".

Then **First loading** (super users, ⋮ menu) registers what is already on the server, and
`docs/Go-Live.md` covers the rest.

## 6a. "I may see the folder but New document and Upload are not there"

The DMS shows those commands where AD lets that person write. Open, signed in as them:

```
https://dms-pilot.rh.tech/api/diagnostics/access?path=02_Customers\Customer_A
```

It says what Windows answered for them on that folder, bit by bit, what the DMS asked for, and whether the
place is one the DMS keeps read only anyway (a workflow folder, a blueprint folder). Adding a file needs
*write data* and *append data*; `DMS_STRICT_ACCESS_CHECK=1` goes back to asking for the whole Write right
(extended attributes and attributes included), which an ACL set by hand often does not grant.

## 7. Settings (`webapi\.env`)

**The first occurrence of a key wins.** A leftover line above is the usual reason a setting "does not take".

### The essentials

| Key | Default | What it does |
| --- | --- | --- |
| `DMS_REPOSITORY_ROOT` | - | The repository root, e.g. `E:\Shares` |
| `DMS_SITE_URL` | - | The control site in SharePoint |
| `DMS_TENANT_ID`, `DMS_CLIENT_ID` | - | The Entra app the DMS signs in as |
| `DMS_CERT_PATH`, `DMS_CERT_THUMBPRINT` | - | Its certificate (the DMS warns 45 days before it expires) |
| `DMS_ADMINS` | - | The DMS super users, by email |
| `DMS_FILE_SERVICE_SECONDS` | `0` | How often the upkeep pass runs. **0 means never**: set it to `60` |

### Who the user is

| Key | Default | What it does |
| --- | --- | --- |
| `DMS_AUTH_MODE` | `windows` | `windows` (IIS signs people in), `entra` (from outside), `dev` (a named user - never in production) |
| `DMS_DEV_USER`, `DMS_DEV_USERS` | - | Testing only: who you are, and the "Acting as" list |
| `DMS_DEV_AD_CHECK` | - | Check AD rights as that user, for testing permissions |
| `DMS_REMOTE_SIGNIN` | `ntlm` | How another PC on the network signs in |
| `DMS_API_AUDIENCE`, `DMS_SPA_CLIENT_ID`, `DMS_USER_HEADER`, `DMS_ALLOWED_ORIGINS` | - | For `entra` mode |

### The repository

| Key | Default | What it does |
| --- | --- | --- |
| `DMS_CUSTOMERS_FOLDER` | `02_Customers` | The customers root |
| `DMS_PROTECTED_DEPTH` | `2` | How deep the company structure is protected from rename and delete |
| `DMS_SHORT_PATHS`, `DMS_CLIENT_ROOT`, `DMS_CLIENT_SHORT_PATHS` | - | The drive letters and UNC paths people see, so a path opens on their PC |
| `DMS_MAX_UPLOAD_MB` | `500` | The largest file that may be uploaded |
| `DMS_SEARCH_LIMIT` | `200` | How many results a search returns |
| `DMS_DOCUMENT_ID_PREFIX` | `DMS` | The document ID prefix |
| `DMS_REGISTER_CACHE_SECONDS` | `30` | How long the register is held in memory |
| `DMS_ACCESS_SCRIPT` | - | `1`: run `Set-DmsAccess.ps1` for a new customer folder |

### Approvals, reading and editing

| Key | Default | What it does |
| --- | --- | --- |
| `DMS_APPROVALS` | `flow` | `page`: approvals happen in the DMS. `flow`: Power Automate / Teams |
| `DMS_REVIEW_SITE_URL`, `DMS_REVIEW_LIBRARY` | `Approvals` | Where the editing copy lives |
| `DMS_VIEW_LIBRARY` | `Views` | Where a reading copy is made before the DMS fetches it and deletes it |
| `DMS_CHECKOUT_HOURS` | `8` | A document left open for editing comes back by itself after this |
| `DMS_VIEW_MINUTES` | `30` | How long an old-style reading copy may linger |
| `DMS_SUBMITTED_EDITABLE` | `true` | Approvers may edit the submitted copy |
| `DMS_DELEGATION_DAYS`, `DMS_WEEKEND` | `3`, `fri,sat` | How long a delegation lasts, and which days are not working days |
| `DMS_FIRST_LOAD_APPROVER` | `dms_approval@rh.co.il` | Who First loading records as the approver |
| `DMS_NOTIFY` | `1` | Send notifications |
| `DMS_PAGE_URL` | - | The address used in notifications and links |

### Exchange with customers

| Key | Default | What it does |
| --- | --- | --- |
| `DMS_EX_SITE_URL`, `DMS_EX_LIBRARY`, `DMS_EX_FOLDER` | `TemporaryUploads`, `Outbound` | The exchange site and where shared files go |
| `DMS_EX_DAYS` | `3` | How long a shared file stays |
| `DMS_EX_SHORTCUT`, `DMS_EX_SHORTCUT_FOLDER` | `true`, `DMS Shortcuts` | A shortcut for whoever shares |
| `DMS_SHARED_LOG` | `Shared/DMS-Shared-Log.csv` | The share log kept beside the customer's folder |

### The AI

| Key | Default | What it does |
| --- | --- | --- |
| `DMS_AI_URL`, `DMS_AI_TOKEN`, `DMS_AI_MODEL` | the RH chat | Ask the RH AI from the page |
| `DMS_AI_PATH`, `DMS_AI_UPLOAD_PATH`, `DMS_AI_MAX_TOKENS`, `DMS_AI_MAX_CHARS`, `DMS_AI_MAX_FILE_MB`, `DMS_AI_KNOWLEDGE_IDS` | | How it is called |
| `DMS_RAG_URL`, `DMS_RAG_TOOLS`, `DMS_RAG_TOKEN` | the AI portal, `qms` | The QMS knowledge the page can ask |

### File Linker (First loading)

| Key | Default | What it does |
| --- | --- | --- |
| `DMS_FL_CHECK_URL`, `DMS_FL_UPDATE_URL`, `DMS_FL_UPDATE_METHOD`, `DMS_FL_UPDATE_BODY`, `DMS_FL_REGISTERED_FIELD`, `DMS_FL_AUTH`, `DMS_FL_TOKEN` | - | Moving an old link to the document's new home |

### Testing only

| Key | What it does |
| --- | --- |
| `DMS_SHAREPOINT=memory` | The playground register: no SharePoint at all |
| `DMS_SP_AUTH=interactive` | Sign in to SharePoint with a browser instead of a certificate |
| `DMS_OFFICE_NATIVE_PATH=1` | Give Office the path instead of a `file://` link, where a PC refuses the URL form |
| `DMS_OFFICE_FILE_URL` | Kept for the same reason, the other way round |

## 8. The scripts

| Script | What it is for |
| --- | --- |
| `Provision-DMS.ps1` | Creates both SharePoint sites with everything in them |
| `Grant-DmsSitePermission.ps1` | `Sites.Selected` for the app, SharePoint and Graph |
| `Connect-DmsGroups.ps1` | The Entra groups and their SharePoint membership |
| `New-DmsFileServerTree.ps1` | The repository tree, its AD groups and NTFS permissions |
| `Set-DmsAccess.ps1`, `Get-DmsAccess.ps1` | Department access on the folders, from `dms-access.csv` |
| `Protect-DmsReadOnly.ps1` | Released folders: read only for everyone but the DMS |
| `New-DmsMarkdown.ps1` | The Markdown beside every released document, in one pass |
| `Compare-DmsTree.ps1` | What the DMS shows against what is on the disk |
| `Restart-Dms.ps1` | Reload the service (`-ComputerName` from another machine) |
| `New-DmsOwnerMail.ps1` | A short letter to each department's owners |
| `Set-DmsDrives.ps1`, `Set-DmsShortPaths.ps1` | What a user's PC needs to open a path in one click |
| `new_dms_cert.py` | A certificate for the Entra app |

## 9. When something is wrong

| What you see | Where to look |
| --- | --- |
| The page does not change after a pull | The page is served with `no-store`; Ctrl+F5, and check `git log --oneline -1` on the server |
| A document opens read-write that should not | `Protect-DmsReadOnly.ps1`, then `icacls` on the folder: your groups should have `(RX)` and only the DMS `(M)` |
| No Markdown beside a document | The log says why; `.xls`, `.doc`, `.ppt` and scanned PDFs cannot be read |
| A document stays "out for editing" | The upkeep pass is off (`DMS_FILE_SERVICE_SECONDS=0`) or Office never released its lock |
| SharePoint refuses something | ⋮ menu → **SharePoint check**: every list, the last errors, and a test notification |
| The service log | `webapi\logs\*.log` (HttpPlatformHandler names each file) |
