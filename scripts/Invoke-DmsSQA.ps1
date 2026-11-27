<#
.SYNOPSIS
    Software Quality Assurance (SQA-001): qualifies the build against SRS-001, before it is installed.

.DESCRIPTION
    This is the stage before IQ. It runs the whole automated suite, then answers the question the
    validation actually asks: requirement by requirement of SRS-001, what proves it, and did that pass.
    A requirement verified on the page or by inspection is marked as belonging to OQ, PQ or IQ, so the
    report accounts for every requirement and not only for the ones a test can reach.

    It also checks what would make the qualification a lie: a requirement that claims to be tested and
    names no test, a test named in the map that no longer exists, a traceability matrix that is behind,
    an uncommitted working tree.

    Nothing on the server is touched: this runs against the code, not against the installation.

.EXAMPLE
    .\scripts\Invoke-DmsSQA.ps1
.EXAMPLE
    .\scripts\Invoke-DmsSQA.ps1 -Report C:\Validation\SQA-Rev01.md
#>
[CmdletBinding()]
param(
    [string]$App = '',
    [string]$Report = ''
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $App) { $App = Get-DmsDefault App }
if (-not $Report) { $Report = Join-Path $env:TEMP ("DMS-SQA {0:yyyy-MM-dd HHmm}.md" -f (Get-Date)) }
$py = Join-Path $App 'webapi\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw "The DMS python was not found: $py" }

$checks = @()
function Check([string]$Id, [string]$What, [string]$Expected, [scriptblock]$Body) {
    $found = ''; $ok = $false
    try { $found = & $Body; if ($found -is [array]) { $found = ($found -join '; ') }; $ok = $true }
    catch { $found = "$($_.Exception.Message)" -replace '\s+', ' ' }
    $script:checks += [pscustomobject]@{ Id = $Id; What = $What; Expected = $Expected
                                          Found = "$found"; Result = $(if ($ok) { 'PASS' } else { 'FAIL' }) }
    Write-Host ("{0,-8} {1,-44} {2}" -f $Id, $What, $(if ($ok) { 'PASS' } else { 'FAIL' })) -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
    if ("$found".Trim()) { Write-Host "         $found" -ForegroundColor DarkGray }
}

$state = Get-Content -LiteralPath (Join-Path $App 'docs\validation\validation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$commit = (& git -C $App log -1 --format='%h %ad %s' --date=short)
Write-Host "=== SQA of $App" -ForegroundColor Cyan
Write-Host "    software revision $($state.softwareRevision), commit $commit"
Write-Host ''

Check 'SQA-R1' 'The working tree is the committed build' 'clean, and pushed' {
    $dirty = & git -C $App status --porcelain
    if ($dirty) { throw "uncommitted changes: $(($dirty | Select-Object -First 5) -join ', ')" }
    $ahead = & git -C $App rev-list --count '@{u}..HEAD' 2>$null
    if ($ahead -and [int]$ahead -gt 0) { throw "$ahead commit(s) not pushed" }
    "clean, $commit"
}

$junit = Join-Path $env:TEMP ("dms-sqa-{0:yyyyMMddHHmm}.xml" -f (Get-Date))
Check 'SQA-R2' 'The automated suite' 'every test passes' {
    Push-Location (Join-Path $App 'webapi')
    try { $text = & $py -m pytest -q --junitxml=$junit 2>&1 | Out-String } finally { Pop-Location }
    $line = ($text -split "`r?`n" | Where-Object { $_ -match '\d+ (passed|failed)' } | Select-Object -Last 1)
    if ($line -match '(\d+) failed') { throw "$line" }
    "$($line.Trim())"
}

Check 'SQA-R3' 'The dependency set' 'pip check clean' {
    $out = & $py -m pip check 2>&1
    if ($LASTEXITCODE -ne 0) { throw "$out" }
    'no broken requirement'
}

Check 'SQA-R4' 'The generated documents are current' 'reference, Swagger, blueprint list, matrix' {
    Push-Location (Join-Path $App 'webapi')
    try {
        $out = & $py -m pytest -q -k 'swagger or blueprint_folder_list or traceability or reference_is_the_four_calls' 2>&1 | Out-String
    } finally { Pop-Location }
    if ($out -match '(\d+) failed') { throw ($out -split "`r?`n" | Where-Object { $_ -match 'failed' } | Select-Object -Last 1) }
    (($out -split "`r?`n" | Where-Object { $_ -match 'passed' } | Select-Object -Last 1)).Trim()
}

Check 'SQA-R5' 'The script lint tests' 'pass' {
    Push-Location (Join-Path $App 'webapi')
    try { $out = & $py -m pytest -q -k 'script' 2>&1 | Out-String } finally { Pop-Location }
    if ($out -match '(\d+) failed') { throw 'a script lint test failed' }
    (($out -split "`r?`n" | Where-Object { $_ -match 'passed' } | Select-Object -Last 1)).Trim()
}

Check 'SQA-R6' 'Traceability, both directions' 'no requirement without a test, no test named that is gone' {
    Push-Location (Join-Path $App 'webapi')
    try { $out = & $py -m dms_api.qualification --check 2>&1 | Out-String } finally { Pop-Location }
    if ($out -notmatch 'with no test named: none' -or $out -notmatch 'do not exist: none') { throw ($out -replace '\s+', ' ') }
    'every requirement verified by test names its tests, and each one exists'
}

Check 'SQA-R7' 'No secret in the repository' 'none' {
    $hits = @(& git -C $App grep -nIE '(DMS_API_KEYS=|BEGIN (RSA|PRIVATE) KEY|client_secret|password\s*=\s*["''][^"'']{6,})' -- . ':!docs' ':!*.md' 2>$null)
    if ($hits) { throw "$($hits.Count) line(s) look like a secret, first: $($hits[0])" }
    'nothing that looks like a key, a certificate or a password'
}

# ---------------------------------------------------------------- the qualification itself
Push-Location (Join-Path $App 'webapi')
try { $qualification = & $py -m dms_api.qualification $junit 2>&1 | Out-String } finally { Pop-Location }

$pass = @($checks | Where-Object { $_.Result -eq 'PASS' }).Count
$fail = @($checks | Where-Object { $_.Result -eq 'FAIL' }).Count

$out = @()
$out += "# SQA report - RH DMS (SQA-001)"
$out += ""
$out += "| | |"
$out += "|---|---|"
$out += "| Executed | $(Get-Date -Format 'yyyy-MM-dd HH:mm') |"
$out += "| By | $env:USERDOMAIN\$env:USERNAME on $env:COMPUTERNAME |"
$out += "| Commit under test | $commit |"
$out += "| Software revision | $($state.softwareRevision) ($($state.status)) |"
$out += "| Result | $pass of $($checks.Count) check(s) passed, $fail failed |"
$out += ""
$out += "## Checks"
$out += ""
$out += "| # | Check | Expected | Found | P/F |"
$out += "|---|---|---|---|---|"
foreach ($c in $checks) {
    $found = ($c.Found -replace '\|', '/') -replace '\r?\n', ' '
    $out += "| $($c.Id) | $($c.What) | $($c.Expected) | $found | **$($c.Result)** |"
}
$out += ""
$out += ($qualification -split "`r?`n")
$out += ""
$out += "## Defects found and their disposition"
$out += ""
$out += "| # | Defect | Class | Fixed in | Re-tested |"
$out += "|---|---|---|---|---|"
foreach ($c in ($checks | Where-Object { $_.Result -eq 'FAIL' })) {
    $out += "| | $($c.Id): $(($c.Found -replace '\|', '/')) | | | |"
}
$out += ""
$out += "## Conclusion"
$out += ""
$out += "The build **is / is not** fit to be installed for qualification (delete one). A requirement marked"
$out += "*at OQ*, *at PQ* or *at inspection* is qualified in that protocol, not here."
$out += ""
$out += "| Role | Name | Signature | Date |"
$out += "|---|---|---|---|"
$out += "| Prepared by (System owner) | | | |"
$out += "| Reviewed by (Document Control) | | | |"
$out += "| Approved by (Quality) | | | |"
$out | Set-Content -LiteralPath $Report -Encoding UTF8

Write-Host ''
Write-Host ($qualification -split "`r?`n" | Select-Object -First 4)
Write-Host "$pass of $($checks.Count) check(s) passed, $fail failed." -ForegroundColor $(if ($fail) { 'Yellow' } else { 'Green' })
Write-Host "Report: $Report"
if ($fail) { exit 1 }
