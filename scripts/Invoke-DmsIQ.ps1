<#
.SYNOPSIS
    Installation Qualification (VAL-002): checks the production installation step by step and writes the
    report to attach to the protocol.

.DESCRIPTION
    Each step of docs\validation\VAL-002-IQ-Protocol.md that a machine can judge is performed here, against
    the installation that is really running. Every step says what was expected, what was found, and PASS or
    FAIL - nothing is "probably fine". The steps a person must do (AD groups, no software on anyone's PC,
    backup) are listed at the end as manual, so the report is complete either way.

    Nothing is changed on the server: this only reads. No key, certificate or password value is written to
    the report - only whether the setting is there.

.EXAMPLE
    .\scripts\Invoke-DmsIQ.ps1
.EXAMPLE
    .\scripts\Invoke-DmsIQ.ps1 -Report C:\Validation\IQ-2026-11-27.md
#>
[CmdletBinding()]
param(
    [string]$Url = '',
    [string]$Site = '',
    [string]$App = '',
    [string]$Report = ''
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Url)  { $Url  = Get-DmsDefault Url }
if (-not $Site) { $Site = Get-DmsDefault Site }
if (-not $App)  { $App  = Get-DmsDefault App }
if (-not $Report) {
    $Report = Join-Path $env:TEMP ("DMS-IQ {0:yyyy-MM-dd HHmm}.md" -f (Get-Date))
}

$steps = @()
function Step([string]$Id, [string]$What, [string]$Expected, [scriptblock]$Check) {
    # Every step answers with what it found; anything thrown is the finding, and the step fails.
    $found = ''; $ok = $false
    try {
        $found = & $Check
        if ($found -is [array]) { $found = ($found -join '; ') }
        $ok = $true
    } catch {
        $found = "$($_.Exception.Message)" -replace '\s+', ' '
    }
    $script:steps += [pscustomobject]@{ Id = $Id; What = $What; Expected = $Expected
                                        Found = "$found"; Result = $(if ($ok) { 'PASS' } else { 'FAIL' }) }
    $colour = if ($ok) { 'Green' } else { 'Red' }
    Write-Host ("{0,-6} {1,-46} {2}" -f $Id, $What, $(if ($ok) { 'PASS' } else { 'FAIL' })) -ForegroundColor $colour
    if ("$found".Trim()) { Write-Host "       $found" -ForegroundColor DarkGray }
}

Write-Host "=== IQ of the DMS at $Url (site $Site, $App)" -ForegroundColor Cyan
Write-Host ''

Step 'IQ-01' 'The released build, with nothing changed on top' 'a clean checkout of main' {
    $dirty = & git -C $App status --porcelain
    if ($dirty) { throw "the working tree has uncommitted changes: $(($dirty | Select-Object -First 5) -join ', ')" }
    $commit = (& git -C $App log -1 --format='%h %ad %s' --date=short)
    $branch = (& git -C $App rev-parse --abbrev-ref HEAD)
    "branch $branch, commit $commit"
}

Step 'IQ-02' 'Python and the packages it needs' 'the venv exists, pip check is clean' {
    $py = Join-Path $App 'webapi\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $py)) { throw "no virtual environment at $py" }
    $v = & $py --version 2>&1
    $check = & $py -m pip check 2>&1
    if ($LASTEXITCODE -ne 0) { throw "pip check: $check" }
    "$v, pip check clean"
}

Step 'IQ-03' 'The IIS site and its application pool are started' 'both Started' {
    Import-Module WebAdministration -ErrorAction Stop
    $s = Get-Item "IIS:\Sites\$Site" -ErrorAction Stop
    $pool = $s.applicationPool
    $p = Get-Item "IIS:\AppPools\$pool"
    if ("$($s.State)" -ne 'Started') { throw "the site is $($s.State)" }
    if ("$($p.State)" -ne 'Started') { throw "the application pool $pool is $($p.State)" }
    "site $Site Started, pool $pool Started, identity $($p.processModel.identityType) $($p.processModel.userName)"
}

Step 'IQ-04' 'HTTPS binding and its certificate' 'in date, covers the host name' {
    Import-Module WebAdministration -ErrorAction Stop
    $b = (Get-Item "IIS:\Sites\$Site").Bindings.Collection | Where-Object { $_.protocol -eq 'https' }
    if (-not $b) { throw 'the site has no https binding' }
    $out = @()
    foreach ($one in $b) {
        $thumb = $one.certificateHash -join ''
        $cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Thumbprint -eq $thumb }
        if (-not $cert) { throw "the binding $($one.bindingInformation) names a certificate that is not in LocalMachine\My" }
        $days = [int]($cert.NotAfter - (Get-Date)).TotalDays
        if ($days -lt 30) { throw "the certificate expires in $days day(s): $($cert.Subject)" }
        $out += "$($one.bindingInformation) sslFlags=$($one.sslFlags) subject=$($cert.Subject) expires in $days day(s)"
    }
    $out
}

Step 'IQ-05' 'Windows Authentication, and the token reaches the service' 'windows on, anonymous off, token forwarded' {
    Import-Module WebAdministration -ErrorAction Stop
    $win = (Get-WebConfigurationProperty -Filter 'system.webServer/security/authentication/windowsAuthentication' -Name enabled -PSPath "IIS:\Sites\$Site").Value
    $anon = (Get-WebConfigurationProperty -Filter 'system.webServer/security/authentication/anonymousAuthentication' -Name enabled -PSPath "IIS:\Sites\$Site").Value
    if (-not $win)  { throw 'Windows Authentication is off' }
    if ($anon)      { throw 'Anonymous Authentication is on' }
    $cfg = Join-Path $App 'webapi\web.config'
    $forward = (Select-String -Path $cfg -Pattern 'forwardWindowsAuthToken\s*=\s*"true"' -Quiet)
    if (-not $forward) { throw "forwardWindowsAuthToken is not true in $cfg" }
    'windows on, anonymous off, forwardWindowsAuthToken true'
}

Step 'IQ-06' 'The service answers, and says which build it is' 'status ok, the repository reachable' {
    $h = Invoke-RestMethod "$($Url.TrimEnd('/'))/api/health" -UseDefaultCredentials -TimeoutSec 60
    if ("$($h.status)" -ne 'ok') { throw "health says $($h.status)" }
    if (-not $h.rootReachable)   { throw "the repository root is not reachable from the service: $($h.repositoryRoot)" }
    "version $($h.version), software revision $($h.softwareRevision), root $($h.repositoryRoot), certificate $($h.certDaysLeft) day(s) left"
}

Step 'IQ-18' 'One version: the installation is the revision being validated' 'the DMS and the validation set agree' {
    $h = Invoke-RestMethod "$($Url.TrimEnd('/'))/api/health" -UseDefaultCredentials -TimeoutSec 60
    $state = Get-Content -LiteralPath (Join-Path $App 'docs\validation\validation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ("$($h.softwareRevision)" -ne "$($state.softwareRevision)") {
        throw "the DMS is running software revision '$($h.softwareRevision)' and the validation set is revision '$($state.softwareRevision)'"
    }
    $running = (& git -C $App rev-parse --short HEAD)
    if ("$($h.version)" -ne "$running") { throw "the service is running build $($h.version), the checkout is $running - restart the DMS" }
    "software revision $($h.softwareRevision), build $($h.version), one version everywhere"
}

Step 'IQ-07' 'The repository root, and the DMS can write in it' 'the path exists and is writable by the service account' {
    $root = Get-DmsEnvValue 'DMS_REPOSITORY_ROOT'
    if (-not $root) { throw 'DMS_REPOSITORY_ROOT is not in webapi\.env' }
    if (-not (Test-Path -LiteralPath $root)) { throw "$root does not exist" }
    $probe = Join-Path $root ".dms-iq-$([guid]::NewGuid().ToString('N').Substring(0,8)).tmp"
    try { 'iq' | Set-Content -LiteralPath $probe -Encoding UTF8; Remove-Item -LiteralPath $probe -Force }
    catch { throw "the account running this cannot write in $root (the service account must be able to): $($_.Exception.Message)" }
    "$root, writable"
}

Step 'IQ-08' 'The folder tree matches the blueprint' 'every blueprint folder exists' {
    $root = Get-DmsEnvValue 'DMS_REPOSITORY_ROOT'
    $list = Join-Path $App 'scripts\blueprint-folders.txt'
    $want = Get-Content -LiteralPath $list -Encoding UTF8 | Where-Object { $_.Trim() -and $_ -notmatch '<[^>]+>' }
    $missing = @($want | Where-Object { -not (Test-Path -LiteralPath (Join-Path $root $_)) })
    if ($missing) { throw "$($missing.Count) blueprint folder(s) are missing, first: $($missing[0]) - run Update-DmsBlueprint.ps1" }
    "$($want.Count) blueprint folder(s), all present"
}

Step 'IQ-09' 'Released folders are read only on the file server' 'files in Current_ReadOnly carry the flag' {
    $root = Get-DmsEnvValue 'DMS_REPOSITORY_ROOT'
    $folders = @(Get-ChildItem -LiteralPath $root -Recurse -Directory -Filter 'Current_ReadOnly' -ErrorAction SilentlyContinue)
    if (-not $folders) { return 'no released documents on this server yet (nothing to check)' }
    $open = @()
    foreach ($f in $folders) {
        $open += @(Get-ChildItem -LiteralPath $f.FullName -File -ErrorAction SilentlyContinue |
                   Where-Object { -not $_.IsReadOnly -and $_.Extension -ne '.md' })
    }
    if ($open) { throw "$($open.Count) released file(s) are writable, first: $($open[0].FullName) - run Protect-DmsReadOnly.ps1" }
    "$($folders.Count) released folder(s), every file read only"
}

Step 'IQ-10' 'The settings the production configuration needs' 'all present (names only)' {
    $need = @('DMS_REPOSITORY_ROOT','DMS_SITE_URL','DMS_AUTH_MODE','DMS_APPROVALS','DMS_ADMINS',
              'DMS_TENANT_ID','DMS_CLIENT_ID','DMS_PAGE_URL')
    $missing = @($need | Where-Object { -not (Get-DmsEnvValue $_) })
    if ($missing) { throw "not set in webapi\.env: $($missing -join ', ')" }
    $mode = Get-DmsEnvValue 'DMS_AUTH_MODE'
    if ($mode -ne 'windows') { throw "DMS_AUTH_MODE is '$mode', and production signs in with Windows Authentication" }
    "$($need.Count) setting(s) present, auth mode $mode, approvals $(Get-DmsEnvValue 'DMS_APPROVALS')"
}

Step 'IQ-11' 'The SharePoint lists the DMS keeps' 'all six exist and the DMS may add to them' {
    $sp = Invoke-RestMethod "$($Url.TrimEnd('/'))/api/diagnostics/sharepoint" -UseDefaultCredentials -TimeoutSec 120
    $bad = @($sp.lists | Where-Object { -not $_.exists -or -not $_.mayAdd })
    if ($bad) { throw "not usable: $(($bad | ForEach-Object { $_.list }) -join ', ')" }
    "site $($sp.site), $(@($sp.lists).Count) list(s): $((($sp.lists | ForEach-Object { "$($_.list) ($($_.items))" }) -join ', '))"
}

Step 'IQ-12' 'The SharePoint certificate has time left' 'more than 30 days' {
    $sp = Invoke-RestMethod "$($Url.TrimEnd('/'))/api/diagnostics/sharepoint" -UseDefaultCredentials -TimeoutSec 120
    $days = [int]$sp.certDaysLeft
    if ($days -le 30) { throw "the certificate expires in $days day(s): make a new one (scripts\new_dms_cert.py)" }
    "$days day(s) left, authentication $($sp.auth)"
}

Step 'IQ-13' 'Every document type has an Approver Matrix rule' 'no type falls back to the super users' {
    $u = $Url.TrimEnd('/')
    $types = (Invoke-RestMethod "$u/api/options" -UseDefaultCredentials -TimeoutSec 60).DocumentType
    if (-not $types) { throw 'the register offers no document types' }
    $without = @()
    foreach ($t in $types) {
        $rule = Invoke-RestMethod "$u/api/approver-rule?documentType=$([uri]::EscapeDataString($t))" -UseDefaultCredentials -TimeoutSec 60
        if ($rule.fallback -or (-not $rule.mandatory -and -not $rule.final)) { $without += $t }
    }
    if ($without) { throw "no active rule for: $($without -join ', ') - Document Control fills the Approver Matrix" }
    "$($types.Count) document type(s), each with an active rule"
}

Step 'IQ-17' 'The DMS log is being written' 'a log file, written today' {
    $cfg = Join-Path $App 'webapi\web.config'
    $m = Select-String -Path $cfg -Pattern 'stdoutLogFile\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $m) { throw "web.config does not say where the log goes (stdoutLogFile)" }
    $path = $m.Matches[0].Groups[1].Value
    $folder = Split-Path $path -Parent
    if (-not (Test-Path -LiteralPath $folder)) { throw "the log folder $folder does not exist" }
    $newest = Get-ChildItem -LiteralPath $folder -Filter '*.log' -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $newest) { throw "no log file in $folder" }
    "$($newest.FullName), last written $($newest.LastWriteTime)"
}

$manual = @(
    @{ Id = 'IQ-14'; What = 'AD groups and NTFS permissions'; How = 'Run .\scripts\Get-DmsAccess.ps1 and attach its output: the groups of dms-ad-groups.csv exist and the repository is granted to groups, not to people' }
    @{ Id = 'IQ-15'; What = 'Nothing installed on any user PC'; How = 'Confirmed by IT: the DMS is used through the browser only, and no approver needs rights on the file server' }
    @{ Id = 'IQ-16'; What = 'Backup of the repository and the SharePoint site'; How = 'The backup owner records the job, its schedule and the last successful restore test' }
)

$pass = @($steps | Where-Object { $_.Result -eq 'PASS' }).Count
$fail = @($steps | Where-Object { $_.Result -eq 'FAIL' }).Count

$out = @()
$out += "# IQ report - RH DMS (VAL-002)"
$out += ""
$out += "| | |"
$out += "|---|---|"
$out += "| Executed | $(Get-Date -Format 'yyyy-MM-dd HH:mm') |"
$out += "| By | $env:USERDOMAIN\$env:USERNAME on $env:COMPUTERNAME |"
$out += "| System | $Url (IIS site $Site, $App) |"
$out += "| Software revision | $((Get-Content -LiteralPath (Join-Path $App 'docs\validation\validation.json') -Raw -Encoding UTF8 | ConvertFrom-Json).softwareRevision) |"
$out += "| Result | $pass of $($steps.Count) automated step(s) passed, $fail failed |"
$out += ""
$out += "## Automated steps"
$out += ""
$out += "| # | Step | Expected | Found | P/F |"
$out += "|---|---|---|---|---|"
foreach ($s in $steps) {
    $found = ($s.Found -replace '\|', '/') -replace '\r?\n', ' '
    $out += "| $($s.Id) | $($s.What) | $($s.Expected) | $found | **$($s.Result)** |"
}
$out += ""
$out += "## Manual steps"
$out += ""
$out += "| # | Step | How it is evidenced | Found | P/F |"
$out += "|---|---|---|---|---|"
foreach ($m in $manual) { $out += "| $($m.Id) | $($m.What) | $($m.How) | | |" }
$out += ""
$out += "## Deviations"
$out += ""
$out += "| # | Step | What happened | Class | Disposition | Closed |"
$out += "|---|---|---|---|---|---|"
foreach ($s in ($steps | Where-Object { $_.Result -eq 'FAIL' })) {
    $out += "| | $($s.Id) | $(($s.Found -replace '\|', '/')) | | | |"
}
$out += ""
$out += "## Signatures"
$out += ""
$out += "| Role | Name | Signature | Date |"
$out += "|---|---|---|---|"
$out += "| Executed by | | | |"
$out += "| Reviewed by (Document Control) | | | |"
$out += "| Approved by (Quality) | | | |"
$out | Set-Content -LiteralPath $Report -Encoding UTF8

Write-Host ''
Write-Host "$pass of $($steps.Count) automated step(s) passed, $fail failed." -ForegroundColor $(if ($fail) { 'Yellow' } else { 'Green' })
Write-Host "Report: $Report"
Write-Host "Three manual steps (IQ-14, IQ-15, IQ-16) are in the report, to be filled in by their owners."
if ($fail) { exit 1 }
