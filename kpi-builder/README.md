# RH KPI Builder

> **This is a separate application.** It lives here only so the pilot had something to run.
> `scripts\Split-KpiBuilder.ps1 -Path <folder>` makes it a repository and a VS Code workspace of its own,
> after which this copy is deleted and the site is deployed with `New-KpiBuilderSite.ps1 -Source <folder>`.
> The DMS and the Builder are built, tested and deployed independently; what they agree on is written in the
> DMS repository's `docs/12-KPI-Integration.md`.

A page that makes a KPI. It is deliberately small: the DMS already knows what a KPI's files are and where
they go, so the Builder's whole job is to write those two files.

```text
<name>.html    the page the DMS runs (double-click in the DMS)
<name>.json    what it reads: which files, which column, how to draw it
```

Drop both on a department's (or customer's) `KPIs` folder in the DMS. The DMS makes `KPIs\<name>\`, keeps the
page at its root - writable, so a newer build replaces it - and releases the definition into
`KPIs\<name>\Current_ReadOnly`, read only and approved, with the audit trail of any released document.

## How it is opened

The DMS opens it from the right-click menu of a `KPIs` folder (**New KPI**) or of one KPI's folder
(**Edit KPI**), with the context in the address: `mode`, `folder`, `folderId`, `owner`, `kpi`, `user`, `dms`,
`api` (see `docs/12-KPI-Integration.md` §3b). Opened on its own it still works; it just does not know which
folder the KPI is for.

## What the KPI page does when the DMS runs it

The DMS serves an HTML page into a sandbox and hands it a key for the folder it lives in. The generated page
uses it:

```text
GET /api/kpi/files?t=<key>&path=<folder>\Current_ReadOnly
GET /api/kpi/file?t=<key>&path=<file>
```

It reads every file matching the pattern, takes the column it was told to take out of each Markdown table (or
a field of a JSON), and draws them in order. Nothing is fetched from anywhere else, so it opens on any PC
with no internet and nothing installed.

## Installing

On the file server, as an administrator:

```powershell
.\scripts\New-KpiBuilderSite.ps1 -WhatIf      # what it would do
.\scripts\New-KpiBuilderSite.ps1 -WireDms     # copy, make the IIS site, tell the DMS where it is
.\scripts\Restart-Dms.ps1
```

It goes to `E:\KPI_Builder` and gets an IIS site of its own on port 8081, with Windows Authentication on and
anonymous off. `-WireDms` writes `DMS_KPI_BUILDER_URL` into the DMS's `.env` and adds the Builder's address to
`DMS_ALLOWED_ORIGINS`, so the DMS answers the Builder when it lists a folder.

## What it does not do

It does not publish into the DMS - the DMS has no publication API yet (`docs/12-KPI-Integration.md` §5), and
dropping the package does the same job. It does not calculate anything server side, keep a KPI index, or
version a KPI as a unit: the artifacts are versioned by the DMS, like any document.
