# KPI Builder - Software Requirements Specification
Version: 1.0 | Date: 1 November 2026 | Derived from: DMS KPI Integration SRS v1.2 (31 October 2026)

**Owner / repository:** KPI Builder (this repository). The DMS is a separate application in a separate
repository; what the two agree on is the DMS repository's `docs/12-KPI-Integration.md`.

## 0. What this application is

The Builder authors a KPI and writes the two files a KPI consists of. It does not store them, does not
decide who may see them and does not run a workflow: that is the DMS's work, and the DMS already does it
for every document in the company.

```text
<KPI_ID>.html    the page that runs the KPI (the DMS runs it on double-click)
<KPI_ID>.json    what it reads: which files, which column, how to draw it, its goal
```

## 1. Boundary (normative, from the shared SRS)

- **BLD-000 [MUST]** This application SHALL be independently buildable, testable and deployable, in its own
  repository and VS Code workspace.
- **BLD-001 [MUST]** It SHALL own KPI authoring, source inspection, calculation configuration, validation,
  preview, local package generation, the JSON and HTML templates and the widget runtime.
- **BLD-002 [MUST]** It SHALL NOT create departmental or customer `KPIs` containers, implement a user,
  group, role or permission system of its own, or change the DMS's folder hierarchy or data model.
- **BLD-003 [MUST]** It SHALL NOT assume any DMS endpoint that is not written down in
  `docs/12-KPI-Integration.md`; what it depends on there SHALL be agreed as a versioned contract before
  either side ships (**XINT-005** of the shared SRS).

## 2. Being opened by the DMS

- **BLD-010 [MUST]** The Builder SHALL be opened from the DMS with the context in its address and SHALL work
  from that alone: `mode` (`create` | `edit`), `folder` and `folderId` (the `KPIs` folder), `owner` (the
  department or customer), `kpi` (on edit), `user` (the signed-in DMS user), `dms` (where to go back to),
  `api` (`/api/kpi`).
- **BLD-011 [MUST]** It SHALL treat that context as a statement of where the KPI belongs, never as
  permission: the DMS decides what the person may do, and refuses the launch itself when they may not
  (`POST /api/kpi/open` answers 400, 403 or 503).
- **BLD-012 [SHOULD]** Opened on its own (no context) it SHALL still author a KPI, saying only that it does
  not know which folder the KPI is for.
- **BLD-013 [MUST]** It SHALL show the person only what the DMS lets them see: when it lists a folder it
  SHALL do so through the DMS with their sign-in, and SHALL show the DMS's refusal rather than working
  around it.

## 3. Authoring

- **BLD-020 [MUST]** A KPI SHALL have a stable identifier (its name), a title, a source (which files in the
  KPI's `Current_ReadOnly`), what to take from them, how to draw it and, optionally, a goal.
- **BLD-021 [MUST]** The Builder SHALL refuse a name that is not a legal folder and file name, and SHALL warn
  when a KPI of that name already exists in the destination folder (collision detection, **ART-006**).
- **BLD-022 [MUST]** It SHALL validate a definition before a package is written: a source that matches
  nothing, a column that is not in the data, a drawing that needs a value it has not been given.
- **BLD-023 [SHOULD]** It SHOULD inspect the source files it is pointed at and offer what it finds (sheet
  names, column headings) rather than asking the person to type them.
- **BLD-024 [SHOULD]** It SHOULD preview the KPI before it is written, with the real data where it can read
  it and with made-up numbers where it cannot, saying which it is showing.
- **BLD-025 [MUST]** On `mode=edit` it SHALL read the KPI's existing definition and write back a definition
  of the same identifier, with its version raised.

## 4. The package

- **BLD-030 [MUST]** A package SHALL be exactly the two files above, named after the KPI.
- **BLD-031 [MUST]** The definition SHALL carry: `kpi`, `title`, `owner`, `source`, `match`, `column`,
  `kind`, `goal`, `madeBy`, `madeUtc`, `version`. New fields SHALL be added without changing the meaning of
  an existing one; a page SHALL ignore a field it does not know.
- **BLD-032 [MUST]** The page SHALL carry its KPI's identifier and the version of the definition it was
  written for, so the two can be traced to each other (**ART-006**).
- **BLD-033 [MUST]** The package SHALL be downloadable as the two files, for the person to drop on the
  department's `KPIs` folder in the DMS - which is the publication (**PKG-005**, **PKG-006**).
- **BLD-034 [SHOULD]** When the DMS gains a publication API (**PKG-003**, open at the time of writing), the
  Builder SHOULD publish through it and SHALL treat the two files as one release: a partial publication
  SHALL NOT leave a page without its definition (**ART-005**).

## 5. The page the Builder writes (the widget runtime)

- **BLD-040 [MUST]** The page SHALL run in the DMS: served into a sandbox, with a key in its address for the
  folder it lives in. It SHALL read its data through `GET /api/kpi/files`, `GET /api/kpi/file` and
  `GET /api/kpi/data` with that key, and SHALL say plainly when it was opened without one.
- **BLD-041 [MUST]** It SHALL read the workbook the DMS answers with (`/api/kpi/data` -> sheets and rows)
  rather than requiring a Markdown export or a library of its own.
- **BLD-042 [MUST]** It SHALL fetch nothing from outside the DMS: no CDN, no font, no analytics. The DMS's
  policy forbids it, and a KPI must open on a PC with no way out to the internet.
- **BLD-043 [MUST]** It SHALL draw itself - a KPI is a page, not an application - and SHALL show what it
  could not read instead of an empty chart.
- **BLD-044 [MUST]** It SHALL use the DMS's own marks when it draws a header (`/dms/logo.png`,
  `/dms/icon.png`), and SHALL NOT imitate them.
- **BLD-045 [MUST]** It SHALL execute no script that came from the data it read.

## 6. Acceptance

- **BACC-001** Opened from the DMS on a `KPIs` folder with create rights, the Builder names that folder and
  can write a package for it.
- **BACC-002** A name that collides with an existing KPI is refused, or carried through as an explicit
  replacement, never silently.
- **BACC-003** The two files of a package, dropped on the department's `KPIs` folder, produce
  `KPIs\<KPI_ID>\<KPI_ID>.html` and `KPIs\<KPI_ID>\Current_ReadOnly\<KPI_ID>.json` (approved) - the layout of
  the shared SRS §"Logical artifact layout".
- **BACC-004** Double-clicking that page in the DMS draws the KPI from the files in its `Current_ReadOnly`,
  with no local paths, no credentials and no network beyond the DMS.
- **BACC-005** The same page opened without a key says so and draws nothing.
- **BACC-006** A definition that is invalid produces no package.
- **BACC-007** Editing an existing KPI writes back the same identifier with a higher version, and the page
  resolves the new definition.
- **BACC-008** Nothing the Builder writes reaches a host other than the DMS (checked with the network log).

## 7. Not in this application

KPI storage, approval, versioning of the artifacts, permissions, the audit trail, the `KPIs` folders
themselves, the right-click menu, drag-and-drop ingestion and running the page - all of that is the DMS's,
and is described in its `docs/12-KPI-Integration.md`.
