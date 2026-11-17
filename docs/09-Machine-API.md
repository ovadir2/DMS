# 09 - The machine API: an application, and the company's AI

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

## Three questions, and one thing it may write

An application does not need an endpoint per screen: it needs to know what is released, and where the work
is kept. AD does the rest - a key acts as an account, and an account that may not see a folder is not told
about it, exactly as a person is not.

| | |
| --- | --- |
| `GET /api/v1/approved-documents` | everything released: `Current_ReadOnly` everywhere, with the document id, the name, the revision, the Markdown the AI reads and the file itself |
| `GET /api/v1/departments` | the departments under General, with the KPIs folder of each |
| `GET /api/v1/customers` | the customers, with the KPIs folder of each |
| `POST /api/v1/kpi/publish` | the WidgetBuilder's page and data (the only thing a key may write) |

`GET /api/v1/documents` answers the same released documents from the register rather than from the folders;
it is kept for callers that already ask it.

## Swagger, and a page to try it

`https://dms.rh.tech/dms/api-try` makes the four calls for you - it asks the DMS for a ticket and uses it
exactly as an application would, and shows the answer, how long it took and how many bytes it was. Nothing
to install, and it runs with your own AD rights, so what you see is what that application would get.

Beside every answer it writes **the call itself**: the whole address with every parameter, and the same
call as `curl` (ticket in the address, or as the `X-DMS-Index-Ticket` header), as PowerShell with your
Windows sign-in, and as an application would make it with `X-DMS-Api-Key` and no ticket - with a Copy
button, so it goes straight into a terminal or into whatever the other system is written in.

The page is not part of the DMS page: its own address, its own file, and nothing in the DMS links to it.
It uses only what the published API gives anybody else.

`https://dms.rh.tech/dms/api-docs` shows exactly what is on this page and nothing more: the machine API, the
indexing ticket and the page key. The document itself is `/api/openapi.json`, and a copy travels with the
repository as `docs/dms-swagger.json` - enough to generate a client without reaching the server. The DMS has
many more endpoints for its own page; they are not part of what an outside system talks to, and live in
`/api/openapi-all.json` and `docs/10-Swagger.md`.

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

Each customer carries `path`, and `kpis` / `kpisExists` - the customer's KPIs folder, and whether it has
been made yet.

## GET /api/v1/departments

Scope `customers` or `kpi`. The departments of the company: the folders under `01_General`, with the name
the page shows (English and Hebrew), the folder's own name, and the KPIs folder of each.

```json
{
  "departments": [
    { "name": "Commercial", "folderName": "Commercial", "he": "מסחרי",
      "path": "E:\\Shares\\01_General\\Commercial",
      "kpis": "E:\\Shares\\01_General\\Commercial\\KPIs", "kpisExists": true }
  ],
  "count": 1
}
```

| Parameter | |
| --- | --- |
| `q` | the name contains this, in either language |

A department the key's account may not see is not in the answer.

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

Everything released, read from the `Current_ReadOnly` folders themselves - every department, every
customer, every project. **One entry per released file**: its id, its name, its revision, **the Markdown the
RAG reads**, and the released file itself beside it. Two documents that share a folder and a base name
(`Procedure.docx` and `Procedure.xlsx`) are two entries, each with the Markdown written for that file - the
second one's is `Procedure.xlsx.md`. A Markdown with no file beside it is listed on its own, with
`DocFileName` empty.

```json
{
  "documents": [
    { "DocID": "QP-16.1", "DocName": "Control of documents", "DocRev": "03",
      "DocDMSpath": "E:\\Shares\\01_General\\Quality and Standards\\Current_ReadOnly\\QP-16.1 Rev03.md",
      "DocFile":    "E:\\Shares\\01_General\\Quality and Standards\\Current_ReadOnly\\QP-16.1 Rev03.docx",
      "DocFileName": "QP-16.1 Rev03.docx",
      "files": [ { "name": "QP-16.1 Rev03.docx", "path": "E:\\Shares\\...", "size": 182144 },
                 { "name": "QP-16.1 Rev03.md",   "path": "E:\\Shares\\...", "size": 7431 } ],
      "folder": "E:\\Shares\\01_General\\Quality and Standards\\Current_ReadOnly",
      "customer": "", "hasMarkdown": true }
  ],
  "count": 1
}
```

| Parameter | |
| --- | --- |
| `customer` | only that customer's documents |
| `q` | the id, the name or the file name contains this |
| `all` | also the released files that have no Markdown of their own - a drawing, a picture, a page (off by default: the RAG reads Markdown) |

It is taken from the folders, not only from the register: a document released by hand has its Markdown in
`Current_ReadOnly` too, and the AI should read that as well. Where the register knows the file, the id, the
name and the revision come from it; where it does not, they are read from the head the DMS wrote at the top
of the Markdown itself.

The Markdown of a document is `<document>.md` - `QP-16.1 Rev03.docx` -> `QP-16.1 Rev03.md`. Where that name
is already another document's, the file carries its extension too (`Procedure.xlsx.md`), so a procedure and
its workbook under one base name each keep their own. Never derive the name yourself: read `DocDMSpath`.

**How a RAG should use it:** ask this endpoint, index `DocDMSpath`, and carry `DocID`, `DocName` and `DocRev`
as the chunk's metadata, so an answer can say which document and which revision it came from. Ask again
before each run rather than remembering paths - a new revision removes the old Markdown and writes a new one,
and the answer to this call is the only place that says what is current. The list is already filtered by the
AD account the key acts as, so an index built from it contains nothing that account may not read; give the
AI's account the groups it should see and nothing else.

## Indexing in the name of the person asking (AI Insights, JIT)

A RAG that indexes with a service account answers everybody the same, which is exactly what must not
happen with documents: two people asking the same question must get answers from different documents,
because AD gives them different rights. So the DMS mints a **ticket** for the person at the keyboard, and
the AI uses that.

```
GET /api/ai/index-ticket                     (Windows sign-in: the person, from the DMS page)
-> { "ticket": "x7...", "hours": 8,
     "documents": "https://dms.rh.tech/api/v1/approved-documents?ticket=x7...",
     "search":    "https://dms.rh.tech/api/v1/search?ticket=x7...&q=",
     "header":    "X-DMS-Index-Ticket" }
```

The ticket **does not say whose it is**. The DMS keeps that; the AI cannot read the person out of it, name
another one, or build a list of who asked what. It is good for `DMS_PAGE_KEY_HOURS`, reads only, and the
rights of that person are asked again on every folder and every file, on every call.

With a ticket (`?ticket=` or the header) these answer as that person:

| | |
| --- | --- |
| `GET /api/v1/approved-documents` | what is released, with a URL to fetch each file from |
| `GET /api/v1/search` | the same search the page does |
| `GET /api/v1/customers`, `GET /api/v1/departments` | the structure, as that person sees it |
| `GET /api/v1/file` | the file itself - **the content, not a path** |

### Where the file goes

Nowhere, unless the caller puts it somewhere. `/api/v1/file` answers with the bytes themselves
(`Content-Disposition: inline`); the DMS writes no copy and keeps nothing. Where it lands is the caller's
own doing: `curl -o`, PowerShell's `-OutFile`, or - for a RAG - straight into the index without ever
touching a disk. The Markdown is text and is normally kept in the index; the document itself is fetched
only when somebody asks to see it.

### The paths in the answer are handles, not something to open

`DocFile` and `DocDMSpath` are the file server's own paths (`E:\Shares\...`). They are there so a person
can be told where a document lives and so two answers can be compared - **not for the AI to open**. The AI
has no account there, and it does not need one: every row also carries `url` and `markdownUrl`, which are
ready to fetch, and the path is simply what goes back in the `path` parameter.

```
GET /api/v1/approved-documents?ticket=x7...&all=true
  -> { "DocID": "QP-16.1", "DocRev": "03",
       "DocFile":      "E:\\Shares\\01_General\\Quality\\Current_ReadOnly\\QP-16.1 Rev03.docx",
       "DocDMSpath":   "E:\\Shares\\01_General\\Quality\\Current_ReadOnly\\QP-16.1 Rev03.md",
       "url":          "https://dms.rh.tech/api/v1/file?path=E%3A%5CShares%5C...docx&ticket=x7...",
       "markdownUrl":  "https://dms.rh.tech/api/v1/file?path=E%3A%5CShares%5C...md&ticket=x7...",
       "etag": "\"9f2c...\"", "modifiedUtc": "2026-11-15T07:12:04Z", "size": 7431 }

GET <markdownUrl>                      -> the Markdown, text/markdown, which is what the RAG indexes
GET <url>                              -> the document itself (Word, Excel, a PDF, a picture)
GET <url> with If-None-Match: <etag>   -> 304, nothing read, nothing sent
```

Either call can be written by hand as
`GET /api/v1/file?path=<DocFile>&ticket=...` (add `&markdown=true` for the Markdown of that document),
and both answer only if the AD account behind the ticket may see that file.

### The AI never touches the file server

`GET /api/v1/file?path=<the path from the list>&ticket=...` returns the bytes, and
`&markdown=true` returns the Markdown written beside the document. Only `Current_ReadOnly` is served, so an
index built this way holds the revisions in force and nothing in work. The AI needs no account on the file
server, no share, no drive - which is the standing rule of this installation, and the reason the rights are
real rather than copied.

### Read the Markdown, not the documents

A RAG that downloads every Word and Excel file costs the server its morning and the index its disk, for
nothing: the Markdown beside each document is what it should read - a few KB of text against megabytes of
binary, with the headings, the lists and the tables kept. So:

- `GET /api/v1/approved-documents?ticket=...` (without `all=true`) lists only documents that **have**
  Markdown. That is the index's list.
- `&inline=true` carries the Markdown **in the answer itself**, so a folder's worth of documents is one
  call and no file is downloaded at all. `&budget=` caps how much text one answer may carry (two million
  characters by default); anything cut off says `markdownTruncated: true` and can be fetched on its own.
- the document itself (`url`) is for a person who asks to open it, or for a format with no Markdown - a
  drawing, a scan - and then only when `all=true` said it is there.

### A file that cannot be Markdown

A drawing, a scan, a picture, a CAD file - there is nothing to convert. The DMS writes a **card** beside it
all the same: the document's id, its revision, its type, where it lives, and the line
`- Content: not readable (no text in this format)`. So the AI can say *"QP-21 Rev02 is a drawing, here it
is"* and point a person at it, and it never quotes text it does not have. `New-DmsMarkdown.ps1 -Write`
fills in the cards for files released before this.

An index of embeddings can do nothing with a card, so every row says `readable`, and **`readable=true`**
leaves the cards out of the answer altogether:

```
GET /api/v1/approved-documents?ticket=...&format=ndjson&inline=true&readable=true
```

That is the call for the on-prem LLM. Ask without it when the answer is for a person, so the AI can still
say a drawing exists and link to it.

### The container the RAG indexes

There is no folder of copies anywhere, and there should not be: copies of 260 people's documents go stale
the moment a revision is approved, cost the disk twice, and move the AD decision from the DMS into a
folder's permissions. The container is **the answer itself**, built for the person asking at the moment
they ask:

```
GET /api/v1/approved-documents?ticket=...&format=ndjson&inline=true
```

- **one document per line** (`application/x-ndjson`), written as it is read. The first line reaches the
  index in milliseconds whether the person may see ten documents or ten thousand, and neither side ever
  holds the repository in memory.
- **the Markdown is in the line** (`inline=true`), so nothing is fetched afterwards and no binary is
  downloaded at all.
- **what the person may see, and only that** - their AD rights decide the walk, so the container is theirs:
  two people asking the same question are given different sets, which is the whole point.
- **a tag for the whole set**: `ETag: "set-…"`. Send it back as `If-None-Match` and an unchanged
  repository answers `304` with nothing read - which is most runs.
- **`manifest=true`** answers `{count, bytes, etag, newestUtc}` and nothing else: one cheap call to decide
  whether to index at all, and to show a person "1,842 documents, 11 MB" before the work starts.
- **`since=`** narrows it to what changed, for an index that keeps its own high-water mark.

A sensible RAG run is therefore: `manifest` (cheap), compare the tag with the one it kept, and if it moved,
stream `ndjson&inline=true&since=<its mark>`. A repository of ten thousand documents costs one call and the
few that changed.

The ticket expires with the person's session, so the container cannot outlive their right to it - and
nothing was written to disk that would have to be cleaned up afterwards.

### Just in time, without re-reading the repository

Every row of the list carries `url`, `markdownUrl`, `size`, `modifiedUtc` and `etag`:

- **first run**: fetch what the list names.
- **every run after**: ask `?since=<the newest modifiedUtc you kept>` - only what changed is listed; and
  fetch with `If-None-Match: <etag>`, which answers `304` with no body for a file you already hold. A
  repository of ten thousand documents then costs one list call and the few files that moved.
- a revision that was replaced disappears from the list by itself: the Markdown of a retired revision is
  removed when it leaves `Current_ReadOnly`, so an index that follows the list cannot quote an old one.

The ticket expires with the person's session; ask for a new one from the page rather than storing it.

## POST /api/v1/kpi/publish

Scope `kpi`. One call, one KPI of one department: the built page and the data behind it, together.
`multipart/form-data`:

| Field | |
| --- | --- |
| `department` | the department these KPIs belong to - `Production`, `Supply chain`, `שרשרת אספקה`; the folder name, the English name or the Hebrew one, spaces or underscores |
| `customer` | ...or a customer, measured the same way (instead of `department`) |
| `kpi` | the KPI's name. Left out, it is taken from the page's file name (`Yield.html` → `Yield`) |
| `folder` | a path from `/api/v1/departments` or `/api/v1/customers`, instead of a name |
| `files` | the files themselves, repeated - the page and its data |

```
curl -X POST https://dms-pilot.rh.tech/api/v1/kpi/publish ^
  -H "X-DMS-Api-Key: <key>" ^
  -F "department=Production" -F "kpi=Yield" ^
  -F "files=@Yield.html" -F "files=@Yield.json"
```

What it makes, under that department's KPIs folder:

```
01_General\Production\KPIs\
    Yield\
        Yield.html                      the page, writable - the next build replaces it
        Current_ReadOnly\Yield.json     the data, released: read only, Document Register + Control Audit
```

One KPI, one folder named after it, made on the first publish - and the KPIs folder itself made if that
department has none yet.

**The department's dashboard** is not one KPI: a page named `dashboard_<something>.html` stays at the root
of the KPIs folder and its data is released into the KPIs folder's own `Current_ReadOnly`, which is where a
dashboard's layout and the numbers it reads across the department's KPIs belong.

```
01_General\Commercial\KPIs\
    dashboard_Commercial.html
    Current_ReadOnly\dashboard_Commercial.json
    Orders\  Quotes\  ...
```

The answer is `201` with `folder`, `kpi`, `created` (folders the call made), `saved` (what was written, with
the register row of anything released) and `failed` (name and reason). Nothing written at all answers `409`
and says why for each file; an unknown department answers `404` and points at `/api/v1/departments`.

The application acts as its AD account here too: that account needs **Modify** on the folder, as a person
would, and a key that names no account is refused. Publishing is the only thing a key can write.

## Swagger

`https://dms-pilot.rh.tech/dms/api-docs` is the whole API to read and to try, grouped by who calls it, with
the three ways in (Windows, the page key, an application key) in its Authorize box. `/dms/api-redoc` reads
the same document, and `/api/openapi.json` is the document itself - generate a client from it, or from the
copy in the repository, `docs/dms-swagger.json`. Swagger UI's own files come from jsdelivr, so the browser
showing it needs the internet; the document and ReDoc do not.

## Why so few

Because AD is the rule, not the API. A key names an account; the DMS answers that account exactly what it
may see, and refuses what it may not - the same answer the person would get. So an application does not need
an endpoint per question: three reads cover what is released and where the work is kept, and the only thing
a key may write is a KPI the Builder built.

## What it is not, yet

The `files` scope has no endpoint yet: a caller that must fetch the bytes still uses the person-facing
`/api/files/download` with a Windows sign-in. Apart from `/api/v1/kpi/publish`, nothing under `/api/v1`
writes.
