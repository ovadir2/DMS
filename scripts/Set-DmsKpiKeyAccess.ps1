<#
.SYNOPSIS
    Lets the key endpoints (/api/kpi) answer a page the DMS serves into a sandbox.
.DESCRIPTION
    A page served into a sandbox has an origin of its own, so it cannot send the person's Windows sign-in -
    and the DMS site has anonymous authentication off, so IIS refuses the call before the DMS sees it. The
    page then shows nothing but "failed to fetch".

    /api/kpi does not need a sign-in: the key in the address is what authorizes it, it reads one folder for
    a few hours, in the name of the person who opened the page, and their AD rights are checked again on
    every call. This unlocks the authentication sections on the server (IIS locks them by default) and turns
    anonymous on for that path alone. Everything else on the site stays as it was.

    Run on the DMS's web server, as an administrator.
.EXAMPLE
    .\scripts\Set-DmsKpiKeyAccess.ps1
.EXAMPLE
    .\scripts\Set-DmsKpiKeyAccess.ps1 -Site DMS-Pilot -Undo
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Site = 'DMS-Pilot',
    [switch]$Undo
)

$ErrorActionPreference = 'Stop'
$appcmd = Join-Path $env:windir 'system32\inetsrv\appcmd.exe'
if (-not (Test-Path -LiteralPath $appcmd)) { throw "appcmd was not found: $appcmd (is this the web server?)" }

$on = -not $Undo
foreach ($section in 'anonymousAuthentication', 'windowsAuthentication') {
    if ($PSCmdlet.ShouldProcess($section, 'unlock on the server')) {
        & $appcmd unlock config /section:$section | Out-Null
    }
}
if ($PSCmdlet.ShouldProcess("$Site/api/kpi", "anonymous $(if ($on) { 'on' } else { 'off' })")) {
    & $appcmd set config "$Site/api/kpi" /section:anonymousAuthentication /enabled:$($on.ToString().ToLower()) /commit:apphost | Out-Null
    & $appcmd set config "$Site/api/kpi" /section:windowsAuthentication  /enabled:$((-not $on).ToString().ToLower()) /commit:apphost | Out-Null
    Write-Host "  [ok]   $Site/api/kpi: anonymous $(if ($on) { 'on (the key authorizes)' } else { 'off' })" -ForegroundColor Green
}
Write-Host "  next   .\scripts\Restart-Dms.ps1, then open the page again" -ForegroundColor DarkGray
