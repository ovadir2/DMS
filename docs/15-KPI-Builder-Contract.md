# 15 - What the KPI Builder sends the DMS

The contract between the KPI Builder (its own repository, its own VS Code) and the DMS. Everything the
Builder needs is here; the full reference is `13-Machine-API.md` and `14-API-Reference.md`.

## What the Builder produces

Per KPI, two files with the same name:

| | |
| --- | --- |
| `<KPI>.html` | the widget: one page that runs on its own in a browser, reading its data through the DMS |
| `<KPI>.json` | the approved data behind it, or the definition it was built from |

A page that shows several KPIs of a department is named `dashboard_<something>.html` (with its
`dashboard_<something>.json`). The DMS treats that one as the department's dashboard, not as a KPI.

## How it signs in

One key, made once on the DMS server:

```powershell
.\scripts\New-DmsApiKey.ps1 -Name kpi-builder -Scopes kpi -ActsAs svc_kpi@rh.co.il
# -> kpi-builder:<key>:kpi:svc_kpi@rh.co.il   pasted after DMS_API_KEYS= in webapi\.env
```

Every call carries it:

```
X-DMS-Api-Key: <key>
```

The key is an identity, not a pass: the DMS acts as `svc_kpi@rh.co.il` and AD decides. That account needs
**Modify** on the KPIs folders it publishes into, and sees nothing it is not in the groups for. The key is
never written to a log and never comes back in an answer.

## Where the departments are

```
GET /api/v1/departments
{"departments":[{"name":"Commercial","folderName":"Commercial","he":"מסחרי",
                 "path":"E:\\Shares\\01_General\\Commercial",
                 "kpis":"E:\\Shares\\01_General\\Commercial\\KPIs","kpisExists":true}],"count":1}
```

`GET /api/v1/customers` answers the same for a customer. `kpisExists:false` is not a problem: publishing
makes the folder.

## Publishing a KPI

```
POST /api/v1/kpi/publish          multipart/form-data
  department = Production         (or customer = Elbit)
  kpi        = Yield              (optional: taken from the .html name)
  files      = @Yield.html
  files      = @Yield.json
```

`department` is matched as the folder is named, as the page shows it in English, or in Hebrew -
`Supply chain`, `Supply_chain` and `שרשרת אספקה` are one department.

What the DMS makes of it:

```
01_General\Production\KPIs\
    Yield\
        Yield.html                      writable - the next build replaces it
        Current_ReadOnly\Yield.json     released: read only, Document Register + Control Audit
```

and for the department's dashboard:

```
01_General\Commercial\KPIs\
    dashboard_Commercial.html
    Current_ReadOnly\dashboard_Commercial.json
```

Answer `201`:

```json
{ "folder": "E:\\Shares\\01_General\\Production\\KPIs\\Yield", "kpi": "Yield",
  "created": ["E:\\Shares\\01_General\\Production\\KPIs", "E:\\...\\Yield"],
  "saved": [ { "name": "Yield.html", "path": "...", "document": null },
             { "name": "Yield.json", "path": "...", "document": { "documentId": "DMS-00123", "...": "" } } ],
  "failed": [] }
```

| | |
| --- | --- |
| `400` | no department named, or a folder that is not a KPIs folder of the blueprint |
| `401` | no key, or one the DMS does not know |
| `403` | the key may not publish, or `svc_kpi@rh.co.il` has no Modify there |
| `404` | no such department or customer - ask `/api/v1/departments` |
| `409` | nothing could be written; the message says why for each file |

Publishing the same KPI again replaces the page and releases the JSON as a new revision. The JSON that was
there is not deleted: it moves to `Obsolete_ReadOnly`, as every replaced revision does.

## What the page may do at runtime

The DMS serves a KPI page sandboxed, with an origin of its own, so it cannot sign in and cannot reach the
DMS's ordinary API. It is given a key of its own when it is opened, and `window.DMS` holds it:

```js
const { key, api, file, folder } = window.DMS;        // api === '/api/kpi'
const data = await fetch(`${api}/data?t=${encodeURIComponent(key)}&path=${encodeURIComponent(p)}`,
                         { credentials: 'omit', mode: 'cors' }).then(r => r.json());
```

| | |
| --- | --- |
| `GET /api/kpi/files?t=&path=` | what is in the folder the page was opened from |
| `GET /api/kpi/file?t=&path=` | one file, as it is on disk |
| `GET /api/kpi/data?t=&path=` | a file as data: a workbook as sheets and rows, a JSON as what it says |
| `GET /api/kpi/ping` | is the DMS reachable at all (no key needed) |

Reading only, only inside the folder the page was opened from, and only for a few hours
(`DMS_PAGE_KEY_HOURS`). The page should read its JSON from `Current_ReadOnly` beside it - that is the
approved copy - and never assume a path outside its own folder.

## Generating a client

`https://dms-pilot.rh.tech/api/openapi.json` is the OpenAPI document of the whole DMS, and
`docs/dms-openapi.json` in the DMS repository is the same thing offline. `/dms/api-docs` shows it in Swagger
UI - put the key in the Authorize box (`X-DMS-Api-Key`) and the publish call can be tried from the page.

## Rules that do not move

- The page is a tool and stays writable; the data is a document and is released read only.
- One KPI, one folder, named after the KPI.
- The Builder writes nothing on the file server itself: it posts to the DMS, and the DMS writes with its own
  account, by the AD rights of the account the key acts as.
- Nothing is installed on anybody's PC.
