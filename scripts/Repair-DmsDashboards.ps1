<#
.SYNOPSIS
    Puts dashboard pages back where they belong.
.DESCRIPTION
    A dashboard page (dashboard_DB.html) is a tool, not a document: it opens and runs, and it stays in the
    folder somebody put it in, writable. One dropped before the DMS knew that was released into
    Current_ReadOnly, read only - where nobody can move it by hand, because the DMS keeps that folder read
    only. This moves each one back up into its folder, makes it writable again and removes the Markdown that
    was written for it.

    It says what it would move and changes nothing until -Write.
.EXAMPLE
    .\scripts\Repair-DmsDashboards.ps1                # what is in the wrong place
.EXAMPLE
    .\scripts\Repair-DmsDashboards.ps1 -Write         # move them
#>
[CmdletBinding()]
param(
    [string]$App  = 'C:\DMS-Pilot\app\webapi',
    [string]$Root = '',
    [switch]$Write
)

$py = Join-Path $App '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw "The DMS python was not found: $py (give -App)" }

$args = @('-m', 'dms_api.dashboards')
if ($Root)  { $args += @('--root', $Root) }
if ($Write) { $args += '--write' }

Push-Location $App
try { & $py @args } finally { Pop-Location }
