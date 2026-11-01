# Putting the Builder on the server

The Builder is a page and nothing else: copy it where IIS can serve it.

```powershell
# on the file server, as an administrator
$src = 'C:\Dev\kpi-builder'                     # this repository
robocopy $src 'E:\KPI_Builder' /MIR /XD .git .vscode
```

The site itself (once): `.\New-KpiBuilderSite.ps1`, here in this repository, creates it - IIS site on port 8081, Windows Authentication on, anonymous off - and with `-WireDms` writes
`DMS_KPI_BUILDER_URL` into the DMS's `.env` and adds this address to `DMS_ALLOWED_ORIGINS`, so **＋ New KPI**
in the DMS opens it.

What the two applications agree on is written in the DMS repository: `docs/12-KPI-Integration.md`.
