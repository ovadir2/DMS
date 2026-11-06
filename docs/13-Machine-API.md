# 13 - The machine API: an application that calls the DMS

A browser signs in with Windows, and the DMS answers what AD lets that person see. An application has
neither: Priority, a report, a script on another server. It is given a **key**, and the key is an identity -
a name, what it may read, and a line in the log for every call it makes.

Nothing of the person-facing API changes. The machine API lives under `/api/v1/`, and only there.

## The key, and the account behind it

```powershell
.\scripts\New-DmsApiKey.ps1 -Name priority -Scopes customers,documents -ActsAs svc_priority@rh.co.il
# priority:kR7...:customers,documents:svc_priority@rh.co.il   <- paste after DMS_API_KEYS= in webapi\.env
.\scripts\Restart-Dms.ps1
```

Four parts: the caller's name, its key, what it may ask for, and **the AD account it acts as**.

That last part is the point. **An application is not a super user.** Every answer is filtered, folder by
folder, against that account's own AD rights - the same question the DMS asks of a person, asked through
`AuthzInitializeContextFromSid`, so no sign-in and nothing on any PC is needed. A caller is told exactly what
its account may see on the file server, and a caller whose line names no account is told **nothing** (403):
without one there is no rule to apply, and a key is not permission.

Give that account the AD groups it should read, like any other member of staff; take them away and the
caller stops seeing those folders at the next call.

Several callers are separated by `|`. Scopes are `customers`, `documents`, `files`, `kpi`; a caller with no scope
named gets `customers`. The DMS never writes a key to the log, never answers one back, and compares them so
that a wrong key says nothing about how wrong it was.

## Calling

```http
GET /api/v1/customers HTTP/1.1
Host: dms-pilot.rh.tech
X-DMS-Api-Key: kR7...
```

`Authorization: Bearer kR7...` is accepted as well, for a client that only speaks that.

| | |
| --- | --- |
| 401 | no key, or one the DMS does not know |
| 403 | a key the DMS knows, for something it may not read - or one that names no AD account |
| 503 | the repository could not be read |

IIS must let these calls through without a Windows sign-in, the same way it does for `/api/kpi`:
`scripts\Set-DmsKpiKeyAccess.ps1` and the `<location path="api/v1">` block in `webapi\web.config.example`.

## GET /api/v1/customers

The customers the DMS knows - the folders under the customers folder of the repository. The skeleton new
customers are cut from is not one of them.

| Parameter | |
| --- | --- |
| `q` | only customers whose name contains this |
| `with_projects` | also list each customer's products (`Develop\Products\<product>`) |

```json
{
  "customers": [
    { "name": "Elbit",  "path": "E:\\Shares\\02_Customers\\Elbit", "products": ["CRU 4"] },
    { "name": "Rafael", "path": "E:\\Shares\\02_Customers\\Rafael", "products": [] }
  ],
  "count": 2
}
```

## GET /api/v1/documents

Every document in force - the approved revision and the file that is it - and the Markdown beside it. This is
what the company's AI reads from: it asks the DMS which documents are current and where they are, instead of
being pointed at a folder and left to work out what in it still counts.

A document whose next revision is being written is still here, with its approved file; `nextRevision` says
which revision is coming. A document only in work is not here at all, and neither is a revision that has been
replaced.

| Parameter | |
| --- | --- |
| `customer` | only that customer's documents |
| `q` | title, Document ID or file name contains this |
| `since` | approved on or after this (`2026-01-01`, or a full UTC stamp) |
| `with_markdown` | include the `.md` beside each file (on by default) |

```json
{
  "documents": [
    {
      "documentId": "COM-QUO-00001", "title": "CRU 4 FCT Quote", "revision": "01",
      "type": "הצעת מחיר", "area": "מסחרי", "owner": "michaelr@rh.co.il",
      "customer": "Customer_A", "status": "מאושר - קריאה בלבד", "nextRevision": "",
      "approvedUtc": "2026-10-04T08:11:00Z",
      "path": "E:\\Shares\\02_Customers\\Customer_A\\Commercial\\Quotations\\Current_ReadOnly\\CRU 4 FCT Quote_Rev1.xlsx",
      "markdown": "E:\\Shares\\...\\Current_ReadOnly\\CRU 4 FCT Quote_Rev1.md",
      "folder": "E:\\Shares\\...\\Current_ReadOnly",
      "sha256": "9b2c..."
    }
  ],
  "count": 1,
  "withoutFile": 0
}
```

`withoutFile` counts records whose file the DMS could not find - run `scripts\Sync-DmsFileServer.ps1` when
that is not zero.

**For the AI:** read `markdown` where it is there and the file itself where it is not, and re-ask this
endpoint rather than remembering paths - a new revision moves the old file to `Obsolete_ReadOnly`, and this
answer is the only place that says what is current.

## GET /api/v1/approved-documents - the list the RAG indexes

The Markdown of every approved document, as it lies in the `Current_ReadOnly` folders. Four things per file:

```json
{
  "documents": [
    { "DocID": "QP-16.1", "DocName": "Control of documents", "DocRev": "03",
      "DocDMSpath": "E:\\Shares\\01_General\\Quality and Standards\\Current_ReadOnly\\QP-16.1 Rev03.md" }
  ],
  "count": 1
}
```

| Parameter | |
| --- | --- |
| `customer` | only that customer's documents |
| `q` | the id or the name contains this |

It is taken from the folders, not only from the register: a document released by hand has its Markdown in
`Current_ReadOnly` too, and the AI should read that as well. Where the register knows the file, the id, the
name and the revision come from it; where it does not, they are read from the head the DMS wrote at the top
of the Markdown itself.

**How a RAG should use it:** ask this endpoint, index `DocDMSpath`, and carry `DocID`, `DocName` and `DocRev`
as the chunk's metadata, so an answer can say which document and which revision it came from. Ask again
before each run rather than remembering paths - a new revision removes the old Markdown and writes a new one,
and the answer to this call is the only place that says what is current. The list is already filtered by the
AD account the key acts as, so an index built from it contains nothing that account may not read; give the
AI's account the groups it should see and nothing else.

## GET /api/v1/kpi/folders

Scope `kpi`. Every KPIs folder the key's AD account may see - one per department, one per customer, as the
blueprint puts them - with the KPIs already in it.

```json
{
  "folders": [
    { "path": "E:\\Shares\\01_General\\Commercial\\KPIs", "owner": "Commercial",
      "kind": "department", "kpis": ["Orders", "Quotes"] }
  ],
  "count": 1
}
```

## POST /api/v1/kpi/publish

Scope `kpi`. The KPI Builder publishes one KPI: the built page and the data behind it, in the same call.
`multipart/form-data`:

| Field | |
| --- | --- |
| `folder` | a KPIs folder (or one KPI inside it) from `/api/v1/kpi/folders` |
| `files` | the files themselves, repeated - `<KPI>.html` and `<KPI>.json` |

```
curl -X POST https://dms-pilot.rh.tech/api/v1/kpi/publish ^
  -H "X-DMS-Api-Key: <key>" ^
  -F "folder=E:\Shares\01_General\Commercial\KPIs" ^
  -F "files=@Orders.html" -F "files=@Orders.json"
```

Each file lands where the DMS keeps that kind of thing, exactly as dropping the two onto the folder in the
page does:

| | Where it goes | |
| --- | --- | --- |
| `Orders.html` | `…\Commercial\KPIs\Orders\Orders.html` | writable: the next build replaces it |
| `Orders.json` | `…\Commercial\KPIs\Orders\Current_ReadOnly\Orders.json` | released, read only, in the Document Register and the Control Audit |

The KPI's folder is named after the files (`Orders.html` → `Orders`), and is created on the first publish.
A page named `dashboard_<something>.html` belongs to the department rather than to one KPI: it stays at the
root of the KPIs folder and what it reads is released into that folder's own `Current_ReadOnly`.

The answer is `201` with `saved` (what was written, with the register row of anything released) and
`failed` (name and reason). A call where nothing could be written answers `409` and says why for each file.

The application acts as its AD account here too: that account needs **Modify** on the folder, as a person
would, and a key that names no account is refused. Publishing is the only thing a key can write.

## What it is not, yet

The `files` scope has no endpoint yet: a caller that must fetch the bytes still uses the person-facing
`/api/files/download` with a Windows sign-in. Apart from `/api/v1/kpi/publish`, nothing under `/api/v1`
writes.
