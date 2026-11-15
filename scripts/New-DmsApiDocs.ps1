<#
.SYNOPSIS
    Write docs\10-Swagger.md from the API itself.

.DESCRIPTION
    Every endpoint of the DMS, its parameters and what it answers, taken from the routes as they are, so the
    reference cannot drift from the code. Run it after adding or changing an endpoint and commit the file
    with the change.

.EXAMPLE
    .\scripts\New-DmsApiDocs.ps1
#>
[CmdletBinding()]
param(
    [switch]$All
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root 'webapi\.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'py' }
Push-Location (Join-Path $root 'webapi')
try {
    $env:PYTHONPATH = '.'
    $out = Join-Path $root 'docs\10-Swagger.md'
    & $py -m dms_api.apidocs | Set-Content -Path $out -Encoding UTF8
    # the whole list, for whoever is working on the DMS itself: not kept in the repository, written on ask
    if ($All) { & $py -m dms_api.apidocs --all | Set-Content -Path (Join-Path $root 'docs\10-Swagger-all.md') -Encoding UTF8 }
    Write-Host "Written: $out"
    $json = Join-Path $root 'docs\dms-swagger.json'
    & $py -m dms_api.apidocs --openapi | Set-Content -Path $json -Encoding UTF8
    Write-Host "Written: $json"
} finally { Pop-Location }
