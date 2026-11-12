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

.PARAMETER ClientId
    The Entra app registration PnP signs in with (the same one Provision-DMS.ps1 uses).

.EXAMPLE
    .\scripts\Reset-DmsPilotData.ps1
.EXAMPLE
    .\scripts\Reset-DmsPilotData.ps1 -Scope FileServer -Write
.EXAMPLE
    .\scripts\Reset-DmsPilotData.ps1 -ClientId <guid> -Write
#>
[CmdletBinding()]
param(
    [ValidateSet('Both', 'SharePoint', 'FileServer')] [string]$Scope = 'Both',
    [string]$SiteUrl = '',
    [string]$ExSiteUrl = '',
    [string]$Root = '',
    [string]$App = '',
    [string]$ClientId = '',
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
if (-not $ClientId) { $ClientId = Get-DmsEnvValue 'DMS_CLIENT_ID' }

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
    if (-not (Get-Module -ListAvailable -Name PnP.PowerShell)) {
        throw 'PnP.PowerShell is not installed: Install-Module PnP.PowerShell -Scope CurrentUser'
    }
    Import-Module PnP.PowerShell -ErrorAction Stop

    # The lists that hold what the pilot did. The Approver Matrix is not here: those are the rules.
    $lists = @('DocumentRegister', 'ControlAudit', 'ApprovalDecisions', 'Delegations', 'DmsNotifications')
    $libraries = @('Approvals', 'Views')          # the copies the DMS makes for approving and for reading

    function Clear-DmsList([string]$Title) {
        $list = Get-PnPList -Identity $Title -ErrorAction SilentlyContinue
        if (-not $list) { Write-Host "  (no list $Title)" -ForegroundColor DarkGray; return }
        $items = Get-PnPListItem -List $Title -PageSize 500 -Fields Id
        Write-Host ("  {0,-20} {1} item(s)" -f $Title, $items.Count)
        if (-not $Write) { return }
        foreach ($item in $items) { Remove-PnPListItem -List $Title -Identity $item.Id -Force | Out-Null }
        Write-Host ("  {0,-20} emptied" -f $Title) -ForegroundColor Green
    }

    foreach ($url in @($SiteUrl, $ExSiteUrl | Where-Object { $_ })) {
        Write-Host "`n-- $url"
        if ($ClientId) { Connect-PnPOnline -Url $url -Interactive -ClientId $ClientId }
        else { Connect-PnPOnline -Url $url -Interactive }
        if ($url -eq $SiteUrl) { foreach ($l in $lists) { Clear-DmsList $l } }
        foreach ($lib in $libraries) { Clear-DmsList $lib }
        # The Exchange site holds what was shared with customers: its document libraries, emptied.
        if ($url -eq $ExSiteUrl) {
            foreach ($lib in (Get-PnPList | Where-Object { $_.BaseTemplate -eq 101 -and -not $_.Hidden })) {
                Clear-DmsList $lib.Title
            }
        }
        Disconnect-PnPOnline
    }
}

Write-Host ""
if ($Write) { Write-Host 'Done. Run .\scripts\Test-DmsProductionReady.ps1 to see what is left.' -ForegroundColor Green }
else { Write-Host 'Nothing was changed. Add -Write to do it.' -ForegroundColor Yellow }
