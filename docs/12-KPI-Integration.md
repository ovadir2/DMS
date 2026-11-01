# KPI integration - what the DMS already does, and what is still to build

The KPI Builder lives in its own repository. This document is the DMS side of the contract the SRS
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
| **DMS-003**, **DMS-004**, **DMS-005**, **DMS-009** | The right-click menu has no *Add New KPI*, *Edit KPI*, *View KPIs* or *Refresh*. The menu is built in `dms-page.html` (the `CANON` list); adding a line is small, but it needs the Builder's launch URL and the contract for passing the folder - neither exists yet. Nothing in the DMS launches the Builder. |
| **DMS-006** | No *Edit KPI*: the DMS does not know which file is a KPI definition, only that it is a released document. |
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
