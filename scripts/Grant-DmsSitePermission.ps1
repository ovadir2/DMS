<#
.SYNOPSIS
    Gives the DMS Entra app write on one SharePoint site (Sites.Selected), so the DMS can put files there.
.DESCRIPTION
    The DMS app holds "Sites.Selected": it can touch only the sites it was given, one by one. Approvals and
    "Open to edit" write to the Document Control site; sharing with a customer writes to the Large File
    Exchange site. An app cannot grant itself rights, so this runs as a person: sign in as a SharePoint or
    Global administrator when the browser window opens.

    It goes through Microsoft Graph, with the Microsoft.Graph.Authentication module, which runs on Windows
    PowerShell 5.1 as well as PowerShell 7 and needs no application of its own. Install it once:

        Install-Module Microsoft.Graph.Authentication -Scope CurrentUser -Force

    It is a one-off per site; running it again on a site that already has the grant changes nothing.
.EXAMPLE
    .\Grant-DmsSitePermission.ps1 -AppId b1cf02f1-bba8-4fd5-8ba5-94f2fb4a26c3 `
        -Site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST,
              https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST
.EXAMPLE
    # read what an app already has on a site, change nothing
    .\Grant-DmsSitePermission.ps1 -AppId <app id> -Site <site url> -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][guid] $AppId,
    [Parameter(Mandatory)][string[]] $Site,
    [string] $DisplayName = 'RH DMS',
    [ValidateSet('read', 'write', 'manage', 'fullcontrol')][string] $Permissions = 'write'
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Module -ListAvailable Microsoft.Graph.Authentication)) {
    throw 'Microsoft.Graph.Authentication is missing: Install-Module Microsoft.Graph.Authentication -Scope CurrentUser -Force'
}
Import-Module Microsoft.Graph.Authentication -ErrorAction Stop

if (-not (Get-MgContext)) {
    # a server has no browser to sign in with: fall back to the code you type on your own PC
    try { Connect-MgGraph -Scopes 'Sites.FullControl.All' -NoWelcome -ErrorAction Stop }
    catch {
        Write-Host 'No browser here - signing in with a device code instead.' -ForegroundColor Yellow
        Connect-MgGraph -Scopes 'Sites.FullControl.All' -NoWelcome -UseDeviceAuthentication
    }
}
Write-Host ("Signed in as {0}" -f (Get-MgContext).Account) -ForegroundColor DarkGray

foreach ($url in $Site) {
    $u = [uri] $url.TrimEnd('/')
    Write-Host "-- $($u.AbsoluteUri)" -ForegroundColor Cyan

    # the site id Graph wants is hostname,siteGuid,webGuid - never the bare GUID
    $site = Invoke-MgGraphRequest -Method GET -Uri "/v1.0/sites/$($u.Host):$($u.AbsolutePath)"
    Write-Host "   $($site.id)" -ForegroundColor DarkGray

    $have = (Invoke-MgGraphRequest -Method GET -Uri "/v1.0/sites/$($site.id)/permissions").value |
            Where-Object { $_.grantedToIdentities.application.id -contains $AppId.Guid -or
                           $_.grantedToIdentitiesV2.application.id -contains $AppId.Guid }
    if ($have) {
        if ($have.roles -contains $Permissions) { Write-Host "   already $Permissions" -ForegroundColor DarkGray; continue }
        if ($PSCmdlet.ShouldProcess($u.AbsoluteUri, "change $($have.roles) to $Permissions")) {
            Invoke-MgGraphRequest -Method PATCH -Uri "/v1.0/sites/$($site.id)/permissions/$($have.id)" `
                -Body @{ roles = @($Permissions) } | Out-Null
            Write-Host "   $($have.roles) -> $Permissions" -ForegroundColor Green
        }
        continue
    }
    if ($PSCmdlet.ShouldProcess($u.AbsoluteUri, "grant $Permissions to $AppId")) {
        Invoke-MgGraphRequest -Method POST -Uri "/v1.0/sites/$($site.id)/permissions" -Body @{
            roles = @($Permissions)
            grantedToIdentities = @(@{ application = @{ id = $AppId.Guid; displayName = $DisplayName } })
        } | Out-Null
        Write-Host "   $Permissions granted" -ForegroundColor Green
    }
}
Write-Host 'Done. The DMS picks this up at once: no restart.' -ForegroundColor Cyan
