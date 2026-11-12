<#
.SYNOPSIS
    Opens Swagger UI for the DMS, after checking that the DMS really answers it.

.DESCRIPTION
    The whole API in one page: every endpoint, grouped by who calls it, with Try it out. The script asks the
    DMS for its OpenAPI document first with the signed-in Windows account, says how many endpoints are in it
    and which build answered, and only then opens the page - so a page that does not load is told apart from
    a DMS that is not running or a build that is behind.

    Swagger UI's own files come from jsdelivr, so the browser needs the internet. -Redoc opens ReDoc
    instead, which does not; -NoOpen only checks.

.EXAMPLE
    .\scripts\Open-DmsSwagger.ps1
.EXAMPLE
    .\scripts\Open-DmsSwagger.ps1 -Redoc
.EXAMPLE
    .\scripts\Open-DmsSwagger.ps1 -Url https://dms.rh.tech -NoOpen
#>
[CmdletBinding()]
param(
    [string]$Url = '',
    [switch]$Redoc,
    [switch]$NoOpen
)
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Url) { $Url = Get-DmsDefault Url }
$ErrorActionPreference = 'Stop'
$base = $Url.TrimEnd('/')
try {
    $doc = Invoke-RestMethod -Uri "$base/api/openapi.json" -UseDefaultCredentials -TimeoutSec 30
} catch {
    throw "The DMS did not answer $base/api/openapi.json : $($_.Exception.Message)`n" +
          "Is it running (.\scripts\Restart-Dms.ps1), and is this build pulled?"
}
$paths = @($doc.paths.PSObject.Properties).Count
$ways  = @($doc.components.securitySchemes.PSObject.Properties.Name) -join ', '
Write-Host "$($doc.info.title) $($doc.info.version): $paths endpoints, signed in with: $ways"
$page = if ($Redoc) { "$base/dms/api-redoc" } else { "$base/dms/api-docs" }
if ($NoOpen) { Write-Host "Not opened (-NoOpen): $page" } else { Write-Host "Opening $page"; Start-Process $page }
