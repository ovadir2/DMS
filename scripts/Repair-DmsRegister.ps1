<#
.SYNOPSIS
    The register against the file server, after files were removed outside the DMS.
.DESCRIPTION
    Files and folders deleted on the file server itself leave the DMS holding documents whose file is gone,
    Markdown beside nothing, files checked out of nowhere and blueprint folders missing. This looks, and with
    -Write puts the register straight: a record whose file merely moved is pointed at where it really is; a
    record whose file is gone keeps its history but stops claiming the file, is marked archived and the
    reason is written to Control Audit. Nothing is deleted from SharePoint.

    It says what it would change and changes nothing until -Write.
.EXAMPLE
    .\scripts\Repair-DmsRegister.ps1
.EXAMPLE
    .\scripts\Repair-DmsRegister.ps1 -Write
#>
[CmdletBinding()]
param(
    [string]$App  = 'C:\DMS-Pilot\app\webapi',
    [switch]$Write,
    [string]$Report = (Join-Path $PSScriptRoot 'out\register-check.csv')
)

$py = Join-Path $App '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw "The DMS python was not found: $py (give -App)" }

$args = @('-m', 'dms_api.reconcile')
if ($Write)  { $args += '--write' }
if ($Report) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Report) | Out-Null
    $args += @('--report', $Report)
}

Push-Location $App
try { & $py @args } finally { Pop-Location }
