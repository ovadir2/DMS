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

Several callers are separated by `|`. Scopes are `customers`, `documents`, `files`; a caller with no scope
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

## What it is not, yet

Two endpoints, read only. The `files` scope has no endpoint yet: a caller that must fetch the bytes still
uses the person-facing `/api/files/download` with a Windows sign-in. Nothing under `/api/v1` writes, and a key
cannot be used to change anything.
