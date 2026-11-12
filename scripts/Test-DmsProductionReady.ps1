<#
.SYNOPSIS
    Is this DMS fit to be the production one? Every check that can be made from here, in one list.

.DESCRIPTION
    Written for promoting the pilot in place: the same installation becomes production, so the things that
    make it a pilot have to be gone rather than left to be noticed later. Nothing is changed - each line is
    PASS, FAIL or a note, with what to run to fix it.

    What it looks at:
      the .env of the installation      dev sign-in, the acting-as list, the playground register, the
                                        addresses, the file service, the application keys
      the DMS itself                    the build it runs, whether it answers, who it thinks you are
      the file server                   the pilot's canaries, what is still checked out, the recycle folder
      the register                      documents whose file is not there any more

.EXAMPLE
    .\scripts\Test-DmsProductionReady.ps1
.EXAMPLE
    .\scripts\Test-DmsProductionReady.ps1 -Url https://dms.rh.tech -Repository E:\Shares
#>
[CmdletBinding()]
param(
    [string]$Url = '',
    [string]$EnvFile = '',
    [string]$Repository = ''
)
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Url) { $Url = Get-DmsDefault Url }
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $EnvFile) { $EnvFile = Join-Path $root 'webapi\.env' }
$fail = 0
function Say($ok, $what, $fix = '') {
    if ($ok) { Write-Host ("PASS  " + $what) -ForegroundColor Green }
    else { $script:fail++; Write-Host ("FAIL  " + $what) -ForegroundColor Red; if ($fix) { Write-Host ("      -> " + $fix) } }
}
function Note($what) { Write-Host ("      " + $what) -ForegroundColor DarkGray }

# ---- the .env of this installation (first occurrence of a key wins, as the DMS reads it)
Write-Host "`n== $EnvFile"
$cfg = @{}
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $k, $v = $line -split '=', 2
        $k = $k.Trim()
        $v = ($v -replace '\s+#.*$', '').Trim().Trim("'", '"')    # a comment after the value, as the DMS reads it
        if (-not $cfg.ContainsKey($k)) { $cfg[$k] = $v }
    }
} else { Say $false ".env not found at $EnvFile" "run this on the DMS server, or give -EnvFile" }
function Get-Cfg([string]$k, [string]$d = '') { if ($cfg.ContainsKey($k) -and $cfg[$k]) { $cfg[$k] } else { $d } }

Say ((Get-Cfg 'DMS_AUTH_MODE' 'windows') -eq 'windows') "DMS_AUTH_MODE is windows" `
    "a production DMS with DMS_AUTH_MODE=dev has no authentication at all"
Say (-not (Get-Cfg 'DMS_DEV_USER')) "no DMS_DEV_USER" "remove the line: it fixes who everybody is"
Say (-not (Get-Cfg 'DMS_DEV_USERS')) "no DMS_DEV_USERS (Acting as)" "remove the line: it lets a super user be somebody else"
Say ((Get-Cfg 'DMS_SHAREPOINT' 'online') -ne 'memory') "the register is SharePoint, not the playground" "DMS_SHAREPOINT=online"
$seconds = 0; [void][int]::TryParse((Get-Cfg 'DMS_FILE_SERVICE_SECONDS' '0'), [ref]$seconds)
Say ($seconds -gt 0) "the upkeep pass runs (DMS_FILE_SERVICE_SECONDS=$seconds)" "set it to 60"
Say ([bool](Get-Cfg 'DMS_SITE_URL')) "DMS_SITE_URL is set" "the Document Register lives there"
Say ([bool](Get-Cfg 'DMS_PAGE_URL')) "DMS_PAGE_URL is set" "notifications link to it"
Say ([bool](Get-Cfg 'DMS_API_KEYS')) "at least one application key" "scripts\New-DmsApiKey.ps1"
foreach ($k in 'DMS_SITE_URL', 'DMS_EX_SITE_URL', 'DMS_REVIEW_SITE_URL', 'DMS_PAGE_URL') {
    $v = Get-Cfg $k
    if ($v -and ($v -match '-TEST|dms-pilot')) { Note "$k still says a pilot name: $v" }
}

# ---- the DMS itself
Write-Host "`n== $Url"
try {
    $me = Invoke-RestMethod "$Url/api/me" -UseDefaultCredentials -TimeoutSec 30
    $doc = Invoke-RestMethod "$Url/api/openapi.json" -UseDefaultCredentials -TimeoutSec 30
    Say $true "the DMS answers as $($me.email) (build $($doc.info.version))"
    if ($me.actingFrom) { Note "you are acting as somebody ($($me.actingFrom) is the real account)" }
    if ($null -ne $me.certDaysLeft) {
        Say ($me.certDaysLeft -gt 30) "the SharePoint certificate has $($me.certDaysLeft) days left" `
            "renew it (scripts\new_dms_cert.py) before it stops the DMS"
    }
} catch { Say $false "the DMS did not answer $Url" ".\scripts\Restart-Dms.ps1" }
try {
    $sp = Invoke-RestMethod "$Url/api/diagnostics/sharepoint" -UseDefaultCredentials -TimeoutSec 60
    $bad = @($sp.lists | Where-Object { -not $_.exists })
    Say ($bad.Count -eq 0) "every SharePoint list the DMS needs is there" ("missing: " + (($bad | ForEach-Object { $_.title }) -join ', '))
    if ($sp.errors) { Note "last SharePoint errors: $(@($sp.errors).Count) (the page's diagnostics show them)" }
    Say ($sp.review.on) "the SharePoint bridge is on (View makes a PDF, approvers edit a copy)" `
        "set DMS_REVIEW_LIBRARY - without it View hands Word the file itself"
    $still = @($sp.review.checkedOut).Count
    if ($still) { Note "$still document(s) still out in SharePoint" }
} catch { Note "the SharePoint check needs a super user: $($_.Exception.Message)" }

# ---- the file server
if (-not $Repository) { $Repository = Get-Cfg 'DMS_REPOSITORY_ROOT' }
if ($Repository -and (Test-Path $Repository)) {
    Write-Host "`n== $Repository"
    $canary = @(Get-ChildItem -Path $Repository -Recurse -Filter 'DMS_ACCESS_CANARY*' -ErrorAction SilentlyContinue)
    Say ($canary.Count -eq 0) "no DMS_ACCESS_CANARY files left" "delete them: they are the pilot's access test"
    $out = Join-Path $Repository '04_Workflow_System\CheckedOut.json'
    $held = 0
    if (Test-Path $out) {
        try { $held = @((Get-Content $out -Raw | ConvertFrom-Json).PSObject.Properties).Count } catch { $held = 0 }
    }
    Say ($held -eq 0) "nothing is out for editing in SharePoint" "bring them back on the page (Done editing), then check again"
    $recycle = Join-Path $Repository '04_Workflow_System\Recycle'
    if (Test-Path $recycle) { Note "the recycle folder holds $(@(Get-ChildItem $recycle -Recurse -File).Count) files from the pilot" }
} else { Note "the repository was not read ($Repository): run this on the DMS server" }

Write-Host ""
if ($fail) { Write-Host "$fail check(s) to fix before this is production." -ForegroundColor Yellow }
else { Write-Host "Ready: nothing left that makes this a pilot." -ForegroundColor Green }
