<#
.SYNOPSIS
    Clears everything the pilot was played with - SharePoint and the file server - and leaves the blueprint.

.DESCRIPTION
    Going live with the installation that already runs means the pilot's own data has to go: the documents
    that were tried, the rows they wrote in the register and the audit, the copies left in the Approvals and
    Views libraries, the files put on the Exchange site, and the folders somebody made on the file server to
    see what would happen. What stays is the shape: every folder the blueprint defines, the KPIs folders
    among them, each customer with its own tree, and the lists themselves (emptied, not deleted).

    Nothing is removed without -Write: by default it says what it would do and stops. Take a backup of
    E:\Shares and an export of the lists before the run that writes - this cannot be undone.

    What it does NOT touch: the Approver Matrix (the rules), the AD groups and the permissions on the
    folders, the customers (unless -Customers), and anything outside DMS_REPOSITORY_ROOT and the two sites.

.PARAMETER Scope
    What to clear: SharePoint, FileServer or Both (the default).

.PARAMETER Customers
    Also remove the customer folders, keeping the skeleton. Without it a customer is kept and cleared.

.EXAMPLE
    .\scripts\Reset-DmsPilotData.ps1
.EXAMPLE
    .\scripts\Reset-DmsPilotData.ps1 -Scope FileServer -Write
.EXAMPLE
    .\scripts\Reset-DmsPilotData.ps1 -Write
#>
[CmdletBinding()]
param(
    [ValidateSet('Both', 'SharePoint', 'FileServer')] [string]$Scope = 'Both',
    [string]$SiteUrl = '',
    [string]$ExSiteUrl = '',
    [string]$Root = '',
    [string]$App = '',
    [switch]$Customers,
    [switch]$Write,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $App) { $App = Get-DmsDefault App }
if (-not $SiteUrl) { $SiteUrl = Get-DmsEnvValue 'DMS_SITE_URL' }
if (-not $ExSiteUrl) { $ExSiteUrl = Get-DmsEnvValue 'DMS_EX_SITE_URL' }
if (-not $Root) { $Root = Get-DmsEnvValue 'DMS_REPOSITORY_ROOT' }

if ($Write -and -not $Force) {
    Write-Host "This removes the pilot's data from:" -ForegroundColor Yellow
    if ($Scope -ne 'FileServer') { Write-Host "  $SiteUrl"; if ($ExSiteUrl) { Write-Host "  $ExSiteUrl" } }
    if ($Scope -ne 'SharePoint') { Write-Host "  $Root" }
    $answer = Read-Host "Type RESET to go on"
    if ($answer -ne 'RESET') { Write-Host 'Nothing was changed.'; return }
}

# ---------------------------------------------------------------- the file server
if ($Scope -ne 'SharePoint') {
    Write-Host "`n== The file server" -ForegroundColor Cyan
    $py = Join-Path $App '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $py)) { $py = 'py' }
    Push-Location $App
    try {
        $argv = @('-m', 'dms_api.reset')
        if ($Root) { $argv += $Root }
        if ($Write) { $argv += '--write' }
        if ($Customers) { $argv += '--customers' }
        $env:PYTHONPATH = '.'
        & $py @argv
    } finally { Pop-Location }
}

# ---------------------------------------------------------------- SharePoint
if ($Scope -ne 'FileServer') {
    Write-Host "`n== SharePoint" -ForegroundColor Cyan
    # The DMS's own account does it: it already signs in to SharePoint with its certificate, so there is
    # nothing to install here and nobody has to be an administrator of the sites to run this.
    $py = Join-Path $App '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $py)) { $py = 'py' }
    Push-Location $App
    try {
        $argv = @('-m', 'dms_api.spreset')
        if ($Write) { $argv += '--write' }
        $env:PYTHONPATH = '.'
        & $py @argv
    } finally { Pop-Location }
}

Write-Host ""
if ($Write) {
    Write-Host 'Done. The DMS keeps the register for a minute, so restart it before looking at the page:'
    Write-Host '  .\scripts\Restart-Dms.ps1'
    Write-Host '  .\scripts\Test-DmsProductionReady.ps1' -ForegroundColor Green
}
else { Write-Host 'Nothing was changed. Add -Write to do it.' -ForegroundColor Yellow }
