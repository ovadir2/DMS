<#
.SYNOPSIS
    Turns this installation from the pilot into production: the .env lines, the IIS names, the restart.

.DESCRIPTION
    Everything the rename needs that can be done from PowerShell, in one command. What it does NOT do is
    the two things that are not ours: changing the SharePoint site addresses (the admin centre does that)
    and the DNS entry and certificate for the new host. It checks the first before it writes.

    By default it only says what it would change. -Write does it, after taking a copy of the .env beside it.

    In order:
      1. the new SharePoint addresses answer                 (refused if they do not, unless -Force)
      2. IIS Windows Authentication is on, anonymous off     (-EnableWindowsAuth turns it on)
      3. webapi\.env:
             DMS_AUTH_MODE      -> windows
             DMS_DEV_USER       removed      (it fixes who everybody is)
             DMS_DEV_USERS      removed      ("Acting as": a super user being somebody else)
             DMS_SITE_URL       -TEST dropped
             DMS_EX_SITE_URL    -TEST dropped
             DMS_REVIEW_SITE_URL -TEST dropped
             DMS_PAGE_URL       the new host
      4. the IIS site and pool renamed                       (-RenameSite)
      5. the DMS restarted, and the readiness check run

.PARAMETER NewHost
    The production address, e.g. dms.rh.tech. Left out, the address is not changed - the SharePoint rename
    and the sign-in settings do not wait for DNS. It is refused if the name does not resolve: a DMS_PAGE_URL
    nobody can reach sends every notification to a dead link.

.EXAMPLE
    .\scripts\Rename-DmsToProduction.ps1
.EXAMPLE
    .\scripts\Rename-DmsToProduction.ps1 -Write
.EXAMPLE
    .\scripts\Rename-DmsToProduction.ps1 -RenameSite -EnableWindowsAuth -Write
.EXAMPLE
    .\scripts\Rename-DmsToProduction.ps1 -NewHost dms.rh.tech -Write     # once DNS and the binding exist
#>
[CmdletBinding()]
param(
    [string]$NewHost = '',
    [string]$NewSite = 'DMS',
    [string]$Site = '',
    [string]$EnvFile = '',
    [switch]$RenameSite,
    [switch]$EnableWindowsAuth,
    [switch]$Write,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
$root = Split-Path -Parent $PSScriptRoot
if ($NewHost) {
    # The address is only written when it answers to DNS: notifications carry it, and a name that does not
    # resolve is a link nobody can open.
    try { [void][System.Net.Dns]::GetHostEntry($NewHost) }
    catch {
        if (-not $Force) {
            throw "$NewHost does not resolve on this machine. Make the DNS entry, the IIS binding and the " +
                  "certificate first, then run this again with -NewHost $NewHost (or -Force to write it anyway)."
        }
        Write-Host "   $NewHost does not resolve - writing it anyway (-Force)" -ForegroundColor Yellow
    }
}
if (-not $EnvFile) { $EnvFile = Join-Path $root 'webapi\.env' }
if (-not (Test-Path $EnvFile)) { throw "No .env at $EnvFile - run this on the DMS server." }
if (-not $Site) { $Site = Get-DmsDefault Site }

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Good($text) { Write-Host "   $text" -ForegroundColor Green }
function Warn($text) { Write-Host "   $text" -ForegroundColor Yellow }

# ---- 1. have the SharePoint sites been renamed?
Step 'SharePoint'
$sites = @{}
foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $k, $v = $line -split '=', 2
    $k = $k.Trim(); $v = ($v -replace '\s+#.*$', '').Trim().Trim("'", '"')
    if (-not $sites.ContainsKey($k)) { $sites[$k] = $v }
}
$renamed = $true
foreach ($key in 'DMS_SITE_URL', 'DMS_EX_SITE_URL', 'DMS_REVIEW_SITE_URL') {
    $old = $sites[$key]
    if (-not $old -or $old -notmatch '-TEST') { continue }
    $new = $old -replace '-TEST', ''
    # Anonymous: SharePoint answers 401/403 for a site that is there and 404 for one that is not, which is
    # all this needs to know. (Windows PowerShell throws on both, so the code comes off the exception.)
    $code = 0
    try {
        $code = (Invoke-WebRequest -Uri "$new/_api/web" -TimeoutSec 30 -UseBasicParsing -ErrorAction Stop).StatusCode
    } catch {
        $r = $_.Exception.Response
        if ($r -and $r.StatusCode) { $code = [int]$r.StatusCode }
    }
    if ($code -eq 0 -or $code -eq 404) {
        Warn "$new does not answer yet (HTTP $code) - change the site address in the SharePoint admin centre first"
        $renamed = $false
    } else {
        Good "$new is there (HTTP $code)"
    }
}
if (-not $renamed -and -not $Force) {
    Write-Host "`nStopping: rename the sites first (admin centre, Active sites, Change site address), or -Force." -ForegroundColor Yellow
    return
}

# ---- 2. IIS authentication
Step "IIS authentication on '$Site'"
Import-Module WebAdministration -ErrorAction Stop
$path = "IIS:\Sites\$Site"
if (-not (Test-Path $path)) { throw "There is no IIS site called '$Site'. Give -Site <name>." }
$win = Get-WebConfigurationProperty -Filter '/system.webServer/security/authentication/windowsAuthentication' -Name enabled -PSPath $path
$anon = Get-WebConfigurationProperty -Filter '/system.webServer/security/authentication/anonymousAuthentication' -Name enabled -PSPath $path
Write-Host "   Windows: $($win.Value)   Anonymous: $($anon.Value)"
if (-not $win.Value) {
    if ($EnableWindowsAuth -and $Write) {
        Set-WebConfigurationProperty -Filter '/system.webServer/security/authentication/windowsAuthentication' -Name enabled -Value $true -PSPath $path
        Good 'Windows Authentication turned on'
    } else {
        Warn 'Windows Authentication is OFF: with DMS_AUTH_MODE=windows nobody can sign in. Add -EnableWindowsAuth.'
        if (-not $Force) { Write-Host "`nStopping." -ForegroundColor Yellow; return }
    }
}
if ($anon.Value) {
    Warn 'Anonymous Authentication is ON for the whole site: turn it off in IIS Manager (leave it on for /api/kpi only).'
}

# ---- 3. the .env
Step $EnvFile
$lines = Get-Content $EnvFile
$out = New-Object System.Collections.Generic.List[string]
$changes = New-Object System.Collections.Generic.List[string]
$seen = @{}
foreach ($line in $lines) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { $out.Add($line); continue }
    $k = ($line -split '=', 2)[0].Trim()
    $rest = ($line -split '=', 2)[1]
    $comment = if ($rest -match '(\s+#.*)$') { $Matches[1] } else { '' }
    $value = ($rest -replace '\s+#.*$', '').Trim().Trim("'", '"')
    $new = $value
    switch ($k) {
        'DMS_AUTH_MODE' { $new = 'windows' }
        'DMS_SITE_URL' { $new = $value -replace '-TEST', '' }
        'DMS_EX_SITE_URL' { $new = $value -replace '-TEST', '' }
        'DMS_REVIEW_SITE_URL' { $new = $value -replace '-TEST', '' }
        'DMS_PAGE_URL' { if ($NewHost) { $new = $value -replace '://[^/]+', "://$NewHost" } }
    }
    if ($k -eq 'DMS_DEV_USER' -or $k -eq 'DMS_DEV_USERS') {
        $changes.Add("  - $k=$value   (removed)")
        continue
    }
    if ($new -ne $value) {
        $changes.Add("  - $k : $value  ->  $new")
        $out.Add("$k=$new$comment")
    } else { $out.Add($line) }
    $seen[$k] = $true
}
if (-not $seen['DMS_AUTH_MODE']) { $out.Add('DMS_AUTH_MODE=windows'); $changes.Add('  - DMS_AUTH_MODE=windows   (added)') }
if ($changes.Count -eq 0) { Good 'nothing to change' } else { $changes | ForEach-Object { Write-Host $_ } }
if ($Write -and $changes.Count) {
    $backup = "$EnvFile.before-rename-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Copy-Item $EnvFile $backup
    $out | Set-Content -Path $EnvFile -Encoding UTF8
    Good "written (the old one is $backup)"
}

# ---- 4. the IIS names
if ($RenameSite -and $Site -ne $NewSite) {
    Step "IIS site '$Site' -> '$NewSite'"
    if ($Write) {
        $pool = (Get-Website -Name $Site).applicationPool
        Rename-Item "IIS:\Sites\$Site" $NewSite
        if ($pool -eq $Site -and (Test-Path "IIS:\AppPools\$Site")) {
            Rename-Item "IIS:\AppPools\$Site" $NewSite
            Set-ItemProperty "IIS:\Sites\$NewSite" -Name applicationPool -Value $NewSite
        }
        Good "renamed (pool: $((Get-Website -Name $NewSite).applicationPool))"
        $Site = $NewSite
    } else { Write-Host "   would rename the site and its pool" }
}

# ---- 5. restart and look
Step 'Restart and check'
$where = if ($NewHost) { "https://$NewHost" } else { Get-DmsDefault Url }
if ($Write) {
    & (Join-Path $PSScriptRoot 'Restart-Dms.ps1') -Site $Site -Url $where
    & (Join-Path $PSScriptRoot 'Test-DmsProductionReady.ps1') -Url $where
} else {
    Write-Host "   would run Restart-Dms.ps1 and Test-DmsProductionReady.ps1"
    Write-Host "`nNothing was changed. Add -Write to do it." -ForegroundColor Yellow
}
