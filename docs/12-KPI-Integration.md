# KPI integration - what the DMS already does, and what is still to build

The KPI Builder lives in its own repository (`kpi-builder`), with its own VS Code workspace, built, tested and deployed on its own. Nothing of it is in this repository: what the two applications agree on is this document, and nothing else: how the Builder is built and deployed is written in its own repository (`DEPLOY.md` there). This document is the DMS side of the contract the SRS
(`DMS_KPI_INTEGRATION_SRS`, v1.2) asks each team to write: the integration points **as they exist in this
code**, the semantics the Builder may rely on, and the requirements that are not built yet. Where the SRS
says the DMS "SHALL" do something that is already true, the endpoint or rule is named; where it is not, it
says so plainly rather than describing an intention.

Nothing here changes the DMS's own rules: AD decides who sees what, the DMS writes every file with its own
account, and a released document is read only.

## 1. The KPIs folders

Every department under `01_General` and every customer under `02_Customers` has a blueprint folder `KPIs`
(`webapi/dms_api/blueprint.py`). Being part of the blueprint is what identifies it, not its name:
`files.kpis_folder(root, path)` returns the KPIs folder a path sits in, by asking the blueprint what that
place is, so a folder somebody names "KPIs" inside their own work is not one (**DMS-002**: satisfied by
blueprint identity; there is no separate persisted classification table and none is needed while the
blueprint is the source of truth).

A KPIs folder is a blueprint folder, so it cannot be renamed or deleted, and neither can the departmental
folder above it (**SRS-002**, **DMS-001**).

## 2. Where a KPI's files live

```text
01_General/<Department>/KPIs/           <- blueprint folder
  <KPI_ID>/                             <- made by the DMS when the first file of that KPI arrives
    <KPI_ID>.html                       <- the page that runs the KPI: writable, replaced by a newer build
    Current_ReadOnly/
      <KPI_ID>.json                     <- released: read only, approved, registered, audited
      <other artifacts>
```

A dashboard reads several KPIs, so it belongs to the department rather than to one of them:

```text
01_General/<Department>/KPIs/
  Dashboard_DB.html                     <- the dashboard page: writable, replaced by a newer build
  Current_ReadOnly/
    Dashboard_DB.json                   <- what it reads: released, read only, approved
  <KPI_ID>/...                          <- one folder per KPI, as above
```

`files.kpi_place()` decides this, and `POST /api/files/upload` applies it: a file dropped **on the KPIs
folder** is placed in a subfolder named after the file (`OEE_LINE1.json` -> `OEE_LINE1/`), a file dropped on
a KPI's own subfolder stays in that one. HTML stays at the subfolder root and is overwritten by the next
drop; everything else is released into `Current_ReadOnly` through the DMS's ordinary no-workflow release -
read only, registered in the Document Register, written to Control Audit (**PKG-006**, **PKG-007**,
**PKG-008**, **PKG-009**, **PKG-011** partly - see gaps, **PKG-013**: a drop anywhere else is untouched).

## 3. Running a KPI page

`GET /api/files/dashboard?path=<file>` serves any `.html`/`.htm` of the repository with
`Content-Security-Policy: sandbox allow-scripts allow-popups allow-downloads allow-forms`,
`X-Content-Type-Options: nosniff` and `Cache-Control: no-store`. The page runs in an opaque origin: it draws
itself and runs its own scripts, and it cannot read the DMS's cookies or call the DMS as the person looking
at it (**SEC-006**). The DMS page opens it in a tab on double-click or Open (**DMS-007**, **WID-001**).

The endpoint authorizes the file itself on every request (`may_read`), so a path typed by hand grants nothing
(**SEC-004**).

## 3a. What a page may read (the page key)

A sandboxed page has no account: it cannot send the person's Windows sign-in, and the DMS would refuse it if
it could. A page that tried to call `/api/browse` therefore got "failed to fetch" on every call.

So the DMS hands the page a key when it opens it. `GET /api/files/dashboard?path=<file>` without a key
answers with a redirect to the same address plus `&t=<key>`; the page reads it from its own address:

```js
const key = new URLSearchParams(location.search).get('t');
const folder = await (await fetch('/api/kpi/files?t=' + key)).json();          // its own folder
const sub = await (await fetch('/api/kpi/files?t=' + key + '&path=' + encodeURIComponent(p))).json();
const text = await (await fetch('/api/kpi/file?t=' + key + '&path=' + encodeURIComponent(f))).text();
```

| | |
| --- | --- |
| `GET /api/kpi/files?t=&path=` | What is in that folder: `name`, `path`, `folder`, `size`, `modified`. `path` defaults to the folder the page lives in; folders under it are allowed |
| `GET /api/kpi/file?t=&path=` | One file as it is on disk (`.md` as `text/markdown`, `.json` as `application/json`, and so on) |
| `GET /api/kpi/data?t=&path=` | The same file **as data a page can draw**: a workbook as `{kind:"sheets", sheets:{<sheet>: [[cell, …], …]}}`, a JSON as `{kind:"json", json:…}`, anything else as `{kind:"text", text:…}`. A browser cannot open an `.xlsx` by itself, and the server may have no way out to fetch a library for it |

The key reads **one folder and what is under it**, for `DMS_PAGE_KEY_HOURS` hours (8 by default), in the name
of the person who opened the page. For a page inside a `KPIs` folder that folder is the whole of it, so a
KPI's page reads its own `Current_ReadOnly` (under it) and a dashboard reads the department's (**beside**
it); anywhere else the page is given its own folder and no more - their AD rights are checked again on every call, so a page cannot show
anyone more than they may see. There is no way back through it: nothing it reaches can be written, renamed or
deleted. Both answers carry `Access-Control-Allow-Origin: *`, because the sandbox gives the page an origin of
its own; the key, not the origin, is what authorizes the call (**SEC-004**, **SEC-006**).

A page that is opened by hand - its address typed, or a link kept from yesterday - gets a fresh key the same
way, as long as the person opening it is signed in to the DMS and may see the file.

**A page written against the DMS's own addresses needs no rewriting.** The DMS puts a few lines in front of
the page it serves, which send the DMS's folder and file calls to the key endpoints instead:

| What the page asks for | Where it goes |
| --- | --- |
| `/api/browse`, `/api/list`, `/api/files`, `/api/folder(s)`, `/api/levels` (with `path=`, `folder=` or `file=`) | `/api/kpi/files?t=…&path=…` |
| `/api/files/download`, `/api/files/text`, `/api/files/raw`, `/api/file` | `/api/kpi/file?t=…&path=…` |

The bridge sends those calls without a sign-in (`credentials: 'omit'`): in the sandbox the page has an
origin of its own, and a browser throws away an answer that says "anyone may read this" when the call also
carried credentials - which is what "failed to fetch" meant. The key is what opens the door, not the sign-in.
`XMLHttpRequest` is bridged the same way.

The DMS's own marks are there for a page that draws a header: `/dms/logo.png` and `/dms/icon.png` (also
`window.DMS.logo` and `window.DMS.icon`). A page should use those rather than draw its own "rh".

`/api/kpi/files` answers in the shape `/api/browse` answers in (`path`, `parent`, `folders[]`, `files[]`),
so such a page reads it unchanged. The key is also there as `window.DMS = {key, api, folder}` for a page that
would rather call the endpoints itself. Everything else the page does is untouched.

## 3b. New KPI / Edit KPI (the launch)

Right-clicking a departmental or customer `KPIs` folder offers **＋ New KPI**; right-clicking one KPI's folder
inside it offers **Edit KPI**. Both appear only where the person may add to that folder, and only where the
Builder is configured (`DMS_KPI_BUILDER_URL`); otherwise the line is there in grey like any command that does
not apply (**DMS-003**, **DMS-004**, **DMS-006**, **DMS-008**).

The page does not build the address. It asks the DMS, which checks the folder against the blueprint and the
person against AD before answering (**DMS-005**):

```http
POST /api/kpi/open      {"folder": "<a KPIs folder, or one KPI's folder>", "kpi": "<optional>"}
  -> {"url": "...", "folder": "<the KPIs folder>", "kpi": "OEE_LINE1", "mode": "create" | "edit"}
  400 this is not a KPIs folder | 403 not allowed to add here | 503 the Builder is not set up here
```

The address handed back is `DMS_KPI_BUILDER_URL` plus, as the **interim** launch contract (to be replaced by
the versioned one when the Builder team states theirs):

| Parameter | Meaning |
| --- | --- |
| `mode` | `create` or `edit` |
| `folder`, `folderId` | the departmental (or customer) `KPIs` folder, by path |
| `owner` | the department or customer that folder belongs to |
| `kpi` | the KPI's folder name, on `edit` |
| `user` | the signed-in DMS user |
| `dms` | `DMS_PAGE_URL`, where to come back to |
| `api` | `/api/kpi` - where the page-key endpoints of §3a live |

The Builder has no publication API in the DMS yet (**PKG-003** is still open): what it produces is brought in
by dropping it into the `KPIs` folder, as §2 describes.

### The dashboard's own files

`KPIs\Current_ReadOnly` holds what a departmental dashboard reads - the weekly workbook and the dashboard's
definition - both released, approved and read only:

```js
const key = new URLSearchParams(location.search).get('t');
const at  = window.DMS.folder + '\\Current_ReadOnly';
const inside = await (await fetch(`/api/kpi/files?t=${key}&path=${encodeURIComponent(at)}`)).json();
for (const f of inside.files) {
  const d = await (await fetch(`/api/kpi/data?t=${key}&path=${encodeURIComponent(f.path)}`)).json();
  if (d.kind === 'sheets') { /* d.sheets['DB'] -> rows of cells */ }
  if (d.kind === 'json')   { /* d.json         -> the definition */ }
}
```

### When a page will not run

`https://<the DMS>/dms/page-test` is a page of the DMS's own, served exactly as any HTML of the repository
is - into the sandbox, with a key in its address and the bridge in front of it. It asks the DMS the three
things such a page asks and says which one failed:

1. **the page was given a key** - no key means the DMS serving it is older than the bridge, or the address
   lost its `?t=`;
2. **the key endpoint answers** - a 401 here is IIS asking for a sign-in the page cannot give
   (`scripts\Set-DmsKpiKeyAccess.ps1`), and "failed to fetch" means the call never reached the DMS at all;
3. **a call written for the DMS** (`/api/browse`) - if 2 works and 3 does not, the bridge is missing.

If that page works and yours does not, the fault is in the page.

## 4. Identity, rights and audit

| What the Builder needs | Where it is |
| --- | --- |
| Who is signed in | `GET /api/me` - email, name, whether a DMS super user |
| May this person write here | `POST /api/files/upload` and `POST /api/folders` refuse with 403; `GET /api/diagnostics/access?path=` says which right is missing and why |
| Repository root, language, settings a client needs | `GET /api/client-config` |
| Folder contents with per-file DMS state | `GET /api/browse?path=` |
| Release a file as approved without a workflow | `POST /api/files/release` |
| A link to a file that works for anyone allowed to see it | `POST /api/files/link` -> `/dms/go/<token>` |

Rights come from AD through the user's Windows token or their AD groups (`webapi/dms_api/security.py`); the
DMS has no users, groups or ACLs of its own (**SEC-001**). Every write endpoint checks the DMS object again,
server side, whatever the client claims (**SEC-002**, **SEC-004**). Releases, approvals, deletions and
no-workflow releases are written to Control Audit with the person's email (**SEC-007**).

## 5. What is not built yet

| Requirement | What is missing |
| --- | --- |
| **DMS-009** | The `KPIs` folder menu has no *View KPIs* or *Refresh* (New KPI and Edit KPI are built - see §3b). |
| **DMS-006** (part) | *Edit KPI* opens the Builder on a KPI's folder, but the DMS does not know which file inside it is the definition - only that it is a released document. |
| **ART-005** | A package is dropped file by file. There is no "one logical release" of the HTML and the JSON together, so a half-finished drop leaves the page without its definition. |
| **ART-006** | KPI IDs are folder names; there is no collision detection beyond a file of the same name, and no rollback of a KPI as a unit. Revisions of the released artifacts work as for any document. |
| **ART-008** | There is no derived index of KPIs. The Builder would have to walk `KPIs` folders through `/api/browse`. |
| **PKG-003**, **PKG-005** | Direct publication by the Builder is not implemented: the only route in is the DMS's own drag and drop (which does work, see §2). |
| **PKG-011** | Package validation is not done: file types and collisions are checked per file, but the package as a whole, its KPI ID and its manifest are not. |
| **XINT-001..005** | No versioned contract, no contract tests. Nothing is agreed with the Builder repository yet. |

## 6. What the DMS needs from the Builder before any of that is built

1. A **package format**: what a KPI's files are, which is the definition, what the manifest says, and how the
   KPI ID is carried (today the DMS takes it from the file name).
2. A **launch contract**: the URL to open for "create" and for "edit", what the DMS passes (folder, KPI ID,
   who is signed in) and how the Builder comes back.
3. A statement of what the Builder will call on the DMS, so those endpoints can be given a stable shape and
   contract tests. The endpoints in §4 are the DMS's own page API: they are not versioned, and they will
   change if nobody is depending on them.

Until 1 and 2 exist, the DMS side stops at: the KPIs folders are part of the skeleton, a KPI package dropped
into one lands as one KPI, its page runs in a sandbox, and everything beside the page follows the ordinary
rules of a released document.

## The Builder publishes without a browser

The Builder sends the two files of a KPI to the DMS itself, with a key of its own
(`.\scripts\New-DmsApiKey.ps1 -Name kpi-builder -Scopes kpi -ActsAs svc_kpi@rh.co.il`):

1. `GET /api/v1/kpi/folders` - every KPIs folder that account may see, by department and by customer.
2. `POST /api/v1/kpi/publish` - `folder` plus the files themselves (`files=@Orders.html`,
   `files=@Orders.json`) in one `multipart/form-data` call.

The page lands writable at the root of the KPI's own folder, so the next build replaces it; the JSON is
released into `Current_ReadOnly` beside it, read only and traced in the Document Register and the Control
Audit. It is the same rule as dropping the two files onto the folder in the page - see
`docs/13-Machine-API.md` for the exact fields and answers. The account the key acts as needs **Modify** on
the folder, like a person.
