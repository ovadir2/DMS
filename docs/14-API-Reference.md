# 14 - API reference

Every endpoint of the DMS, written from the API itself (`python -m dms_api.apidocs`, or `scripts\New-DmsApiDocs.ps1`), so it cannot drift from the code. The machine API has a guide of its own in `13-Machine-API.md`, the KPI Builder in `15-KPI-Builder-Contract.md`, and the page key in `12-KPI-Integration.md`.

**Swagger**: the same thing to try and to generate a client from - `https://dms-pilot.rh.tech/dms/api-docs` (Swagger UI), `/dms/api-redoc` (ReDoc), and the OpenAPI document itself at `/api/openapi.json`. A copy of the document is in the repository as `dms-openapi.json`, for a client generated without reaching the server.

Written from DMS d66d92b.

## How a caller is known

| | How it signs in | What it may do |
| --- | --- | --- |
| A person on the page | Windows authentication (IIS), the browser's own sign-in | whatever AD gives that person, and nothing else |
| A page of the repository | `?t=<page key>`, minted when the page is opened | read the folder it was opened from |
| An application | `X-DMS-Api-Key: <key>` or `Authorization: Bearer <key>` | the key's scopes, as the AD account the key acts as |

## Signing in and what this person is

The page asks these as soon as it opens. Windows authentication: the DMS answers as the person at the keyboard, and AD decides what they see.

### GET /api/areas

The top of the tree the user may open: Customers and Management.

### GET /api/client-config

What the page needs to draw itself: the language, the features this DMS has turned on, the address of the Builder, the limits. The page asks for it once, when it opens.

### GET /api/customers

Customer folders the user may open (AD), optionally filtered by name.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `q` | query | no | string |  |

### GET /api/health

Is the DMS up, and which build is it? Open it in the browser after a pull and a restart.

### GET /api/levels

One selector per level of the tree, from the root down to `path`, plus the next level: [{selected, options}]. Choosing an option in one level gives the options of the next.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | no | string |  |

### GET /api/me

Who the DMS thinks you are: the account AD gave it, your name, and whether you are a super user (and, when a super user is acting as somebody, who that is).

### GET /api/options

The choices the Document Register offers - document types, areas, lifecycle states - as SharePoint holds them, so the page shows the same words the register stores.

### GET /api/people

People in the company directory, for choosing approvers (SharePoint people picker).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `q` | query | yes | string |  |

### GET /api/people/list

The list to choose approvers from: all RH Microsoft 365 users (people search); if the directory cannot be read, the people of the DocumentControl site. The DMS super users are always in it.

### GET /api/projects

Project folders of one customer that the user may open.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `customer` | query | yes | string |  |

## The repository: folders and files

Everything the file list does. The user's own AD rights decide every one of them; the DMS writes with its own account but never in place of a right the person does not have.

### GET /api/browse

One folder of the repository: its folders and its files, with what may be done to each.

Only what AD lets this person see is in the answer, and every row says how it opens (in Office, in
SharePoint, as a PDF), whether it may be edited and - when it may not - why.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | no | string |  |

### GET /api/classify

What a file saved in this folder (or this file) inherits from the blueprint.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | yes | string |  |

### POST /api/files/checkin

Done editing: the DMS writes what the person changed back to the file server and removes the copy.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### POST /api/files/checkout

Open this file in SharePoint, with the person's own Microsoft account: the DMS (the only account with rights on the file server) puts a copy there and gives that one person edit, or read only when the document is released. A released (read-only) document is never opened for editing.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### GET /api/files/dashboard

An HTML page of the repository, served so that it runs in the browser - a dashboard, a report, a page somebody saved. It is served into a sandbox: the page may run its own scripts and draw itself, and it may not read the DMS's cookies or call the DMS as the person looking at it, because a page that arrives from a shared folder is not trusted with their account.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | yes | string |  |
| `t` | query | no | string |  |

### GET /api/files/download

The file itself, for someone AD lets read it. The DMS reads it with its own account: an approver needs no rights on the file server.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | yes | string |  |

### GET /api/files/link

A link to this file or folder that means something only inside the DMS: a short token, not the path on the file server. Pasted into File Explorer it leads nowhere; opened in the DMS it goes to the file, and what the person may see is decided there, by their own AD groups, as always.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | yes | string |  |

### POST /api/files/release

Selected files released without workflow, like Save file (no workflow): each goes to Current_ReadOnly in its folder, read only, registered in SharePoint (approved by DMS, Collaboration, SHA-256); can be shared.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### GET /api/files/text

A text file, to read and edit on the page itself: nothing has to be installed on the PC.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | yes | string |  |

### POST /api/files/text

Save a text file edited on the page itself.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### POST /api/files/upload

Save a file from the user's PC into a folder of the repository (the user needs write access there).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | multipart/form-data | yes | object |  |

### GET /api/files/view-pdf

The document as a PDF, served by the DMS itself. SharePoint turns it into one - nothing has to be installed on the server for that - but the copy is fetched and removed at once, so there is no copy left anywhere for a reader to annotate and save. Reading leaves nothing behind.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | yes | string |  |

### POST /api/folders

Make a folder. Workflow folders, the customer skeleton and the customer's Shared folder are not places to make one; a new folder under the customers folder is a new customer, cut from the skeleton.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### GET /api/guide

"What are you saving?" - the document kinds and where each belongs in the blueprint tree.

### POST /api/guide/create

Create the blueprint folder for a document kind when it is missing (the user needs write permission on the deepest folder that exists).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `key` | query | yes | string |  |
| `customer` | query | yes | string |  |
| `project` | query | no | string |  |

### GET /api/guide/target

The folder for one kind of document, for a customer (and project). It may not exist yet.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `key` | query | yes | string |  |
| `customer` | query | yes | string |  |
| `project` | query | no | string |  |

### POST /api/items/delete

Moves the file or folder to the recycle folder (04_Workflow_System\Recycle), never erases it.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### POST /api/items/rename

Rename a file or a folder (the user needs write access, and a registered document is renamed through its own record so the register follows).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### GET /api/pathfinder

The options for the next level under `path`: the folders that exist (AD-filtered) plus the blueprint folders that do not exist yet ("exists": false). Customers and projects (the "*" levels of the blueprint) are offered only when they exist.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | no | string |  |

### POST /api/pathfinder/create

Create the missing folders of a blueprint path. Every new folder must be one the blueprint expects at its level, and the user needs write permission on the deepest folder that exists.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | yes | string |  |

### GET /api/search

Customers, folders, registered documents (Document ID, title, type, file name) and file names the user may see, in the whole repository. Several words match in any order. An exact Document ID comes first.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `q` | query | yes | string |  |
| `scope` | query | no | string | all / customer / project / document / file / quick (customers, folders, documents) |
| `customer` | query | no | string | Customer folder path, to search inside one customer |
| `limit` | query | no | string | At most this many results (suggestions while typing) |

## Documents and the workflow

Registering a document, submitting it, approving it, revising it, sharing it. The Document Register and the Control Audit in SharePoint are written as each of these happens.

### GET /api/approvals

Documents waiting for this user's approval (DMS_APPROVALS=page).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `everyone` | query | no | boolean | Super users: every pending approval |

### POST /api/approvals/{item_id}

Approve or reject on the page (DMS_APPROVALS=page). A super user may decide any stage.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |
| _body_ | application/json | yes | object |  |

### POST /api/approvals/{item_id}/delegate

Pass a waiting approval to someone else for this cycle (the approver, or a super user for any waiting approver).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |
| _body_ | application/json | yes | object |  |

### GET /api/approver-rule

Who the Approver Matrix sends this document type to (the default when nobody is chosen).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `documentType` | query | yes | string |  |

### GET /api/documents

The Document Register, as this person may see it: the documents whose files AD lets them read.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `mine` | query | no | boolean |  |
| `status` | query | no | string | Working / Submitted / Approved_ReadOnly |

### POST /api/documents

Register a file as a controlled document (and submit it for approval with submit=true): the Document Register row, the Control Audit line, and the file renamed to the document's own name.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### GET /api/documents/{item_id}

One document of the register, by its item id.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |

### GET /api/documents/{item_id}/approvers

For a new submission: the approvers chosen last time, and the document type (for the Matrix).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |

### POST /api/documents/{item_id}/delete

Delete a document in Working (owner or super user). The file goes to the recycle folder and the record stays for the audit trail: Archived, or for a new revision draft, back to its approved revision.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |

### GET /api/documents/{item_id}/remarks

The files approvers attached to this document (their remarks), newest name first.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |

### POST /api/documents/{item_id}/remarks

An approver edits the document on their own PC and attaches it here as their remarks. The submitted file is never touched: the attachment is kept beside the document, named after the approver, so several approvers can send remarks without overwriting each other and the approved revision stays as it was.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |
| _body_ | multipart/form-data | yes | object |  |

### GET /api/documents/{item_id}/remarks/{name}

One file an approver attached as their remarks, as it was uploaded.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |
| `name` | path | yes | string |  |

### POST /api/documents/{item_id}/rename

Rename the file of a document in Working (owner or super user). The register follows: working path, title (when it was the file name) and draft revision (from a _RevNN in the new name).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |
| _body_ | application/json | yes | object |  |

### POST /api/documents/{item_id}/revise

Start the next revision of an approved document, on the same record: from a copy of the approved version, or from a file uploaded from the user's PC. The draft is saved next to the document as <name>_RevNN_DRAFT.<ext>; on approval the file service makes it the current version and moves the previous one to Obsolete_ReadOnly.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |
| _body_ | multipart/form-data | yes | object |  |

### POST /api/documents/{item_id}/share

Share approved revisions with a customer: the files are copied straight into the customer folder on the Large File Exchange site (<library>/Outbound/<Customer>/, the name of the folder under 02_Customers) and SharePoint invites the person to that folder (view only, B2B guest). More documents can go in the same share; every later share adds to the same folder. A OneDrive shortcut DMS_<Customer> is added for the user. Only approved documents, by the owner or a DMS super user; one Control Audit row per document.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |
| _body_ | application/json | yes | object |  |

### GET /api/documents/{item_id}/share-info

For the Share dialog: the customer from the file's folder (02_Customers\<name>, preselected), the customer folders to choose from (any of them), and the other approved documents the user may add.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |

### POST /api/documents/{item_id}/submit

Send a registered document for approval: it moves to Submitted, the approvers are told, and the file goes to the Submitted folder.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |
| _body_ | application/json | yes | object | Req |

### POST /api/documents/{item_id}/withdraw

Take a submitted document back to Working (owner or super user). The approval cycle ends, the file service returns the file to its place, and it can be submitted again.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |

### GET /api/exchange/files

What is on the Large File Exchange site now for this customer / person (read only, for the Share dialog).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `name` | query | yes | string |  |

### POST /api/file-service/run

Run the file moves now: every approved document goes to Current_ReadOnly in its own folder (the previous revision to Obsolete_ReadOnly), read only, with its SHA-256 in the record. A super user can run it whenever they like, also when the DMS does not run it on a timer (DMS_FILE_SERVICE_SECONDS).

### POST /api/first-load

Load documents approved in the old repository: into Current_ReadOnly, registered as Approved, File Linker links moved. Runs in the background; follow it with GET /api/first-load/{id}.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### GET /api/first-load/{job_id}

How the first load is getting on: what it has done, what it could not, and whether it has finished.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `job_id` | path | yes | string |  |

### GET /api/my-workflows

Every document the user owns or registered/submitted, with its workflow status, the last decision and the full history from Control Audit.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `everyone` | query | no | boolean | Super users: everyone's workflows |

### GET /api/my-workflows/waiting

How many of this person's own documents are waiting for them: returned with remarks, or in work after a return. The page shows it on My workflows, the way approvals are counted.

### POST /api/playground/decide/{item_id}

Playground only (DMS_SHAREPOINT=memory): approve or reject as the approvers would in Teams.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `item_id` | path | yes | integer |  |
| `approve` | query | no | boolean |  |
| `comment` | query | no | string |  |

## AI Insights

Questions about a document or about the company's knowledge, asked of the RH AI portal. The DMS never sends a file the person may not read.

### POST /api/ai/ask

AI Insights: ask about one file (after the AD read check) or the company knowledge bases.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### POST /api/ai/chat-log

A question the page opened in the RH AI chat (when the page is not connected to its API).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### POST /api/ai/find

Find files from a free-text request, only among what the user may see. With AI Insights configured, the AI makes the search plan and ranks the matches with a reason; without it, the request's keywords are used.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### POST /api/ai/rag

AI Insights: a question to an RH RAG tool on the AI portal (e.g. QMS).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### GET /api/ai/status

Is AI Insights set up here, and which knowledge bases and RAG tools the portal offers.

## Diagnostics

Why the DMS answered as it did: open them in the browser. They answer for whoever is signed in and change nothing.

### GET /api/diagnostics/access

Why may this person not save here? What Windows answered for them on that folder, bit by bit, beside what the DMS asked for - and what the DMS itself forbids there whatever AD says (a workflow folder, a blueprint folder). Open it in the browser: /api/diagnostics/access?path=<folder>. It answers for whoever is signed in and reads nothing else.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | yes | string |  |

### POST /api/diagnostics/clear-errors

Super users: empty the list of last SharePoint errors (it also empties at every restart).

### GET /api/diagnostics/dashboard

Does this DMS know what a dashboard page is, and does it see this name as one? A name that comes back false is released into Current_ReadOnly like any other file - and a DMS that answers 404 here is running a build from before the rule. Open /api/diagnostics/dashboard?name=<the file name>.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `name` | query | no | string |  |

### GET /api/diagnostics/file

Why can this person not edit this file? Every answer the row is drawn from, in one place: what the DMS knows about the file, what AD gives this person on it, what the register says, and whether a copy of it is out in SharePoint. Open it in the browser: /api/diagnostics/file?path=<the file>. It answers for whoever is signed in.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | yes | string |  |

### POST /api/diagnostics/notify-test

Super users: write one test row to DMS Notifications, addressed to themselves (the DC-P2 flow sends it).

### GET /api/diagnostics/sharepoint

Super users: the DMS lists in SharePoint (exists, items, may this account add), and the last errors.

## Pages of the repository (the page key)

A dashboard or a KPI page runs in a sandbox with an opaque origin: it cannot sign in, so the DMS gives the page a key of its own, good for the folder it was opened from and for a few hours. Reading only.

### GET /api/kpi/data

A file of that folder as data a page can draw: a workbook as its sheets and rows, a JSON as what it says, anything else as its text. A browser cannot open an .xlsx by itself and the server may have no way out to fetch a library for it - the DMS reads workbooks anyway, for the AI.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `t` | query | yes | string |  |
| `path` | query | yes | string |  |

### GET /api/kpi/file

One file of that folder, as it is on disk. Reading only: there is no way back through this key.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `t` | query | yes | string |  |
| `path` | query | yes | string |  |

### GET /api/kpi/files

What is in the folder this page was opened from (and in the folders under it): name, size, when it was last written. The page asks for this instead of the DMS's own folder API, which answers only to a signed-in browser.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `t` | query | yes | string |  |
| `path` | query | no | string |  |

### POST /api/kpi/open

Where to send this person to make a KPI, or to change one. The page asks for this rather than building the address itself: the folder is checked here - that it is a KPIs folder of the skeleton, and that this person may add to it - so a folder named in a browser grants nothing (DMS-005).

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | application/json | yes | object |  |

### GET /api/kpi/ping

Can a page reach the DMS at all? This one answers without a key and without a sign-in, so it says which of the two is in the way: open it in the browser (/api/kpi/ping). A sign-in prompt or 401 means IIS is still asking for one on /api/kpi (scripts/Set-DmsKpiKeyAccess.ps1); an answer means the way is open and anything still failing is the key or the address.

## The machine API

An application, not a person: a key (X-DMS-Api-Key, or Authorization: Bearer) that names what it may read and the AD account it acts as. The DMS answers it exactly what that account may see.

### GET /api/v1/approved-documents

The Markdown of every approved document, as it lies in the Current_ReadOnly folders.

Four things per file: the document's id, its name, its revision and where the Markdown is. This is
the AI's list - it reads these files - so it is taken from the folders themselves and not only from
the register: a document released by hand is in Current_ReadOnly with its Markdown beside it, and the
AI should read that too. What the register knows fills in the id and the revision; what it does not
know is read from the Markdown's own first lines, which the DMS wrote when it made the file.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `customer` | query | no | string |  |
| `q` | query | no | string |  |
| `all` | query | no | boolean | Also the released files that have no Markdown of their own (a drawing, a picture) |

### GET /api/v1/customers

The customers the DMS knows: what is under the customers folder of the repository, by name.

For an application, not for a person - see /api/customers for the signed-in page. The skeleton that
new customers are cut from is not one of them.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `q` | query | no | string |  |
| `with_projects` | query | no | boolean |  |

### GET /api/v1/departments

The departments of the company: the folders under General, with the name the page shows and the KPIs folder of each.

For an application, not for a person. AD decides here as everywhere: a department the key's account
may not see is not in the answer.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `q` | query | no | string |  |

### GET /api/v1/documents

Every approved document the DMS holds, with the file that is in force and the Markdown beside it.

This is what the company's AI reads from: it asks the DMS which documents are approved and where
their files are, instead of being pointed at a folder and left to guess what in it is current. A
revision that has been replaced is not here; nor is anything still in work.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `customer` | query | no | string |  |
| `q` | query | no | string |  |
| `since` | query | no | string |  |
| `with_markdown` | query | no | boolean |  |

### POST /api/v1/kpi/publish

The KPI Builder publishes one KPI of one department: its page and the data behind it, together.

POST /api/v1/kpi/publish   department=Production  kpi=Yield
                               files=@Yield.html  files=@Yield.json

What it makes, under that department's KPIs folder:

    KPIs\Yield\Yield.html                      the page, writable - the next build replaces it
    KPIs\Yield\Current_ReadOnly\Yield.json    the data, released: read only, in the register

One KPI, one folder named after it, made on the first publish - and the KPIs folder itself made if
the department has none yet. A page named dashboard_<something>.html is the department's dashboard
rather than one KPI: it stays at the root of KPIs and its data is released into the KPIs folder's
own Current_ReadOnly, which is where a dashboard layout belongs.

The application acts as its AD account: that account needs Modify there, as a person would.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| _body_ | multipart/form-data | yes | object |  |

## Office and links

What Office opens and what a DMS link points at. The token is the address; the path on the file server is never in it.

### PROPFIND /api/o/{token}/

Office asks about the "folder" of the DMS link too.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `token` | path | yes | string |  |

### GET /api/o/{token}/{name}

Open for a path too long for Office (Hebrew names): Word / Excel / PowerPoint open and save the file here.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `token` | path | yes | string |  |
| `name` | path | yes | string |  |

### PUT /api/o/{token}/{name}

Open for a path too long for Office (Hebrew names): Word / Excel / PowerPoint open and save the file here.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `token` | path | yes | string |  |
| `name` | path | yes | string |  |

### PROPFIND /api/o/{token}/{name}

Open for a path too long for Office (Hebrew names): Word / Excel / PowerPoint open and save the file here.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `token` | path | yes | string |  |
| `name` | path | yes | string |  |

### LOCK /api/o/{token}/{name}

Open for a path too long for Office (Hebrew names): Word / Excel / PowerPoint open and save the file here.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `token` | path | yes | string |  |
| `name` | path | yes | string |  |

### UNLOCK /api/o/{token}/{name}

Open for a path too long for Office (Hebrew names): Word / Excel / PowerPoint open and save the file here.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `token` | path | yes | string |  |
| `name` | path | yes | string |  |

### GET /dms/go/{token}

The other end of that link: the DMS page, standing at the file the token names.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `token` | path | yes | string |  |
| `lang` | query | no | string |  |

## The page itself

The DMS page, its logo and its icon.

### GET /dms/dms-page

The DMS page itself: one HTML file, served to the signed-in browser.

### GET /dms/icon.png

The tab's icon: the logo on a white square that it fills, the shape a tab icon is drawn in. The wide logo itself is shrunk into a corner of the tab instead. Without any icon the browser shows whatever it likes - often the icon of the site that tab held before.

### GET /dms/logo.png

The company logo: put logo.png in dms_api/static (a drawn "rh" is shown without it).

### GET /dms/page-test

A page of the DMS's own, served exactly as any HTML in the repository is: into the sandbox, with a key in its address and the bridge in front of it. It then asks the DMS three things and says what came back. If this page works and yours does not, the fault is in the page; if this one fails, it says which of the three steps failed and that is the DMS's side to fix.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `t` | query | no | string |  |
