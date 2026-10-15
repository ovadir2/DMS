<#
.SYNOPSIS
    Gives the DMS Entra app write on one SharePoint site (Sites.Selected), so the DMS can put files there.
.DESCRIPTION
    The DMS app holds Graph/SharePoint "Sites.Selected": it can touch only the sites it was given, one by one.
    Sharing with a customer writes to the Large File Exchange site, so that site needs the Write grant; the
    Document Control site needs it for approvals and for opening a document for editing.

    An app cannot grant itself rights: run this signed in as a SharePoint or Global administrator. It is a
    one-off per site, and running it again on a site that already has the grant changes nothing.
.EXAMPLE
    # in PowerShell 7 (pwsh), with the tenant's PnP app for the sign-in
    .\Grant-DmsSitePermission.ps1 -AppId b1cf02f1-bba8-4fd5-8ba5-94f2fb4a26c3 -ClientId <PnP app id> `
        -Site https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST
.EXAMPLE
    # both sites at once
    .\Grant-DmsSitePermission.ps1 -AppId <app id> -Site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST,
        https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][guid] $AppId,
    [Parameter(Mandatory)][string[]] $Site,
    [string] $DisplayName = 'RH DMS',
    [guid] $ClientId = $(if ($env:DMS_PNP_CLIENT_ID) { $env:DMS_PNP_CLIENT_ID } else { [guid]::Empty }),
    [ValidateSet('Read', 'Write', 'Manage', 'FullControl')][string] $Permissions = 'Write'
)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'Run this in PowerShell 7 (pwsh), not Windows PowerShell 5.1: PnP.PowerShell needs it.'
}
if (-not (Get-Module -ListAvailable PnP.PowerShell)) {
    throw 'PnP.PowerShell is missing. In pwsh: Install-Module PnP.PowerShell -Scope CurrentUser -Force'
}
Import-Module PnP.PowerShell -ErrorAction Stop

# PnP renamed these cmdlets (AzureAD -> EntraID): use whichever this version has.
function Get-Cmd([string[]] $names) {
    foreach ($n in $names) { if (Get-Command $n -ErrorAction SilentlyContinue) { return $n } }
    throw "None of these cmdlets exist in PnP.PowerShell: $($names -join ', '). Update the module."
}

foreach ($url in $Site) {
    $url = $url.TrimEnd('/')
    Write-Host "-- $url" -ForegroundColor Cyan
    # PnP no longer has an app of its own: the sign-in goes through the tenant's PnP app (the one
    # Provision-DMS.ps1 uses), given as -ClientId or in DMS_PNP_CLIENT_ID.
    if ($ClientId -ne [guid]::Empty) { Connect-PnPOnline -Url $url -Interactive -ClientId $ClientId }
    else { Connect-PnPOnline -Url $url -Interactive }      # older PnP versions: sign in as an administrator
    $get   = Get-Cmd 'Get-PnPEntraIDAppSitePermission', 'Get-PnPAzureADAppSitePermission'
    $grant = Get-Cmd 'Grant-PnPEntraIDAppSitePermission', 'Grant-PnPAzureADAppSitePermission'
    $set   = Get-Cmd 'Set-PnPEntraIDAppSitePermission', 'Set-PnPAzureADAppSitePermission'
    $have = & $get -ErrorAction SilentlyContinue |
            Where-Object { $_.Apps.Id -contains $AppId.Guid }
    if ($have) {
        if ($have.Roles -contains $Permissions) { Write-Host "   already $Permissions" -ForegroundColor DarkGray; continue }
        & $set -PermissionId $have.Id -Permissions $Permissions | Out-Null
        Write-Host "   $($have.Roles) -> $Permissions" -ForegroundColor Green
        continue
    }
    & $grant -AppId $AppId -DisplayName $DisplayName -Site $url -Permissions $Permissions | Out-Null
    Write-Host "   $Permissions granted" -ForegroundColor Green
}
Write-Host 'Done. The DMS picks this up at once: no restart.' -ForegroundColor Cyan
