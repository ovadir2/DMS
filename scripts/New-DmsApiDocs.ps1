<#
.SYNOPSIS
    Write docs\14-API-Reference.md from the API itself.

.DESCRIPTION
    Every endpoint of the DMS, its parameters and what it answers, taken from the routes as they are, so the
    reference cannot drift from the code. Run it after adding or changing an endpoint and commit the file
    with the change.

.EXAMPLE
    .\scripts\New-DmsApiDocs.ps1
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root 'webapi\.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'py' }
Push-Location (Join-Path $root 'webapi')
try {
    $env:PYTHONPATH = '.'
    $out = Join-Path $root 'docs\14-API-Reference.md'
    & $py -m dms_api.apidocs | Set-Content -Path $out -Encoding UTF8
    Write-Host "Written: $out"
} finally { Pop-Location }
