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
#>
[CmdletBinding()]
param(
    [string]$App  = 'C:\DMS-Pilot\app\webapi',
    [string]$Root = '',
    [switch]$Write
)

$py = Join-Path $App '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw "The DMS python was not found: $py (give -App)" }

$args = @('-m', 'dms_api.backfill')
if ($Root)  { $args += @('--root', $Root) }
if ($Write) { $args += '--write' }

Push-Location $App
try { & $py @args } finally { Pop-Location }
