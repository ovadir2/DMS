<#
.SYNOPSIS
    Writes the Markdown copy (.md) beside every file in Current_ReadOnly, in one pass.
.DESCRIPTION
    The DMS writes <document>.md when a document is approved. Anything released before that existed, or
    released by hand, has none - and the AI cannot read it at all. This is the one-time catch-up.

    It says what it would write and changes nothing until -Write.
.EXAMPLE
    .\scripts\New-DmsMarkdown.ps1                     # what is missing
.EXAMPLE
    .\scripts\New-DmsMarkdown.ps1 -Write              # write it
.EXAMPLE
    .\scripts\New-DmsMarkdown.ps1 -Write -Rewrite     # write it again for everything, after a change to
                                                      # how a format is read (sheet names, a new reader)
#>
[CmdletBinding()]
param(
    [string]$App  = 'C:\DMS-Pilot\app\webapi',
    [string]$Root = '',
    [switch]$Write,
    [switch]$Rewrite,                                                      # also redo the ones that have one
    [string]$Report = (Join-Path $PSScriptRoot 'out\markdown-run.csv')      # what happened, file by file
)

$py = Join-Path $App '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw "The DMS python was not found: $py (give -App)" }

$args = @('-m', 'dms_api.backfill')
if ($Root)  { $args += @('--root', $Root) }
if ($Write)   { $args += '--write' }
if ($Rewrite) { $args += '--rewrite' }
if ($Report) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Report) | Out-Null
    $args += @('--report', $Report)
}

Push-Location $App
try { & $py @args } finally { Pop-Location }
