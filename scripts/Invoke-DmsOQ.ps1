<#
.SYNOPSIS
    Operational Qualification (VAL-003): runs the evidence the OQ protocol asks for and writes the report.

.DESCRIPTION
    Two runs, both against this installation:

      the automated suite  - webapi\tests, the code's own 250 tests
      the end-to-end walk  - scripts\Test-DmsSmoke.ps1, with real Word, Excel, PDF and text files, which
                             prints a requirement id (REQ-Pnn) on every line it proves

    The report pairs each OQ step with the requirement ids behind it and says PASS, FAIL or WITNESS (a step
    a person judges on the page, left for the executor to sign). The walk runs with the DMS test accounts
    only, so no real approver is sent a test document, and -Clean removes what it made afterwards.

.EXAMPLE
    .\scripts\Invoke-DmsOQ.ps1 -As RH\dms-lab -Approver roneno@rh.co.il
#>
[CmdletBinding()]
param(
    [string]$Url = '',
    [string]$App = '',
    [string]$As = 'RH\dms-lab',
    [string]$Approver = 'roneno@rh.co.il',
    [string]$Report = '',
    [switch]$SkipTests,
    [switch]$KeepData
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Url) { $Url = Get-DmsDefault Url }
if (-not $App) { $App = Get-DmsDefault App }
if (-not $Report) { $Report = Join-Path $env:TEMP ("DMS-OQ {0:yyyy-MM-dd HHmm}.md" -f (Get-Date)) }

$protocol = Join-Path $App 'docs\validation\VAL-003-OQ-Protocol.md'
if (-not (Test-Path -LiteralPath $protocol)) { throw "The OQ protocol is not here: $protocol" }

# One version for the whole validation: qualify the revision the set is written for, or say so and stop.
$state = Get-Content -LiteralPath (Join-Path $App 'docs\validation\validation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$health = Invoke-RestMethod "$($Url.TrimEnd('/'))/api/health" -UseDefaultCredentials -TimeoutSec 60
if ("$($health.softwareRevision)" -ne "$($state.softwareRevision)") {
    throw ("The DMS is running software revision '$($health.softwareRevision)' and the validation set is " +
           "revision '$($state.softwareRevision)'. One version for the whole validation: deploy the " +
           "revision being validated, or raise the set (py -m dms_api.validation --bump NN).")
}

# ---------------------------------------------------------------- the automated suite
$suite = [pscustomobject]@{ Ran = $false; Passed = 0; Failed = 0; Line = 'not run' }
if (-not $SkipTests) {
    $py = Join-Path $App 'webapi\.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $py) {
        Write-Host '=== The automated suite' -ForegroundColor Cyan
        Push-Location (Join-Path $App 'webapi')
        try {
            $text = & $py -m pytest -q 2>&1 | Out-String
            $last = ($text -split "`r?`n" | Where-Object { $_ -match '\d+ (passed|failed)' } | Select-Object -Last 1)
            $suite.Ran = $true
            $suite.Line = "$last".Trim()
            if ($last -match '(\d+) passed') { $suite.Passed = [int]$Matches[1] }
            if ($last -match '(\d+) failed') { $suite.Failed = [int]$Matches[1] }
        } finally { Pop-Location }
        Write-Host $suite.Line
    } else {
        $suite.Line = "no virtual environment at $py"
    }
}

# ---------------------------------------------------------------- the walk
Write-Host ''
Write-Host '=== The end-to-end walk' -ForegroundColor Cyan
$walkReport = Join-Path $env:TEMP ("DMS-OQ-walk {0:yyyy-MM-dd HHmm}.txt" -f (Get-Date))
$walk = & (Join-Path $PSScriptRoot 'Test-DmsSmoke.ps1') -Url $Url -As $As -Approver $Approver -Report $walkReport 2>&1 | Out-String
Write-Host $walk
if (-not $KeepData) {
    & (Join-Path $PSScriptRoot 'Test-DmsSmoke.ps1') -Url $Url -Clean | Out-Null
}

# Which requirements the walk proved, and which it did not: its own lines say so.
$proved = @{}
foreach ($line in ($walk -split "`r?`n")) {
    if ($line -match '(REQ-P\d+)') {
        $id = $Matches[1]
        $state = if ($line -match 'FAIL') { 'FAIL' } elseif ($line -match 'SKIP') { 'SKIP' } else { 'PASS' }
        if (-not $proved.ContainsKey($id) -or $state -eq 'FAIL') { $proved[$id] = $state }
    }
}

# ---------------------------------------------------------------- the protocol's own steps
$rows = @()
foreach ($line in (Get-Content -LiteralPath $protocol -Encoding UTF8)) {
    if ($line -notmatch '^\|\s*(OQ-\d+)\s*\|') { continue }
    $cells = ($line.Trim().Trim('|') -split '\|') | ForEach-Object { $_.Trim() }
    $ids = [regex]::Matches($cells[3], 'REQ-P\d+') | ForEach-Object { $_.Value }
    $state = 'WITNESS'                      # a step a person judges, unless a requirement answers for it
    $saw = @()
    foreach ($id in $ids) {
        $one = if ($proved.ContainsKey($id)) { $proved[$id] } else { 'NOT RUN' }
        $saw += "$id $one"
        if ($one -eq 'FAIL' -or $state -eq 'FAIL') { $state = 'FAIL' }
        elseif ($one -eq 'PASS' -and $state -ne 'FAIL') { $state = 'PASS' }
        elseif ($one -eq 'SKIP' -and $state -notin @('PASS','FAIL')) { $state = 'SKIPPED' }
    }
    if ($cells[3] -match 'automated' -and $suite.Ran -and $suite.Failed -eq 0 -and $state -eq 'WITNESS') {
        $state = 'PASS'; $saw += 'automated suite'
    }
    $rows += [pscustomobject]@{ Id = $cells[0]; What = $cells[1]; Expected = $cells[2]
                                Evidence = (($saw -join ', ')); Result = $state }
}

$pass    = @($rows | Where-Object { $_.Result -eq 'PASS' }).Count
$fail    = @($rows | Where-Object { $_.Result -eq 'FAIL' }).Count
$witness = @($rows | Where-Object { $_.Result -eq 'WITNESS' }).Count

$out = @()
$out += "# OQ report - RH DMS (VAL-003)"
$out += ""
$out += "| | |"
$out += "|---|---|"
$out += "| Executed | $(Get-Date -Format 'yyyy-MM-dd HH:mm') |"
$out += "| By | $env:USERDOMAIN\$env:USERNAME on $env:COMPUTERNAME |"
$out += "| System | $Url |"
$out += "| Build | $($health.version) |"
$out += "| Software revision | $($state.softwareRevision) ($($state.status)) |"
$out += "| Automated suite | $($suite.Line) |"
$out += "| Walk | as $As, approver $Approver - full output in $walkReport |"
$out += "| Result | $pass passed, $fail failed, $witness awaiting a witness |"
$out += ""
$out += "## Steps"
$out += ""
$out += "| # | Function | Expected result | Evidence | P/F |"
$out += "|---|---|---|---|---|"
foreach ($r in $rows) {
    $mark = switch ($r.Result) { 'PASS' { '**PASS**' } 'FAIL' { '**FAIL**' } 'SKIPPED' { 'SKIPPED' } default { 'witness: ____' } }
    $out += "| $($r.Id) | $($r.What) | $($r.Expected) | $($r.Evidence) | $mark |"
}
$out += ""
$out += "## Requirements the walk reported"
$out += ""
$out += "| Requirement | Result |"
$out += "|---|---|"
foreach ($id in ($proved.Keys | Sort-Object { [int]($_ -replace 'REQ-P', '') })) {
    $out += "| $id | $($proved[$id]) |"
}
$out += ""
$out += "## Deviations"
$out += ""
$out += "| # | Step | What happened | Class | Disposition | Closed |"
$out += "|---|---|---|---|---|---|"
foreach ($r in ($rows | Where-Object { $_.Result -in @('FAIL','SKIPPED') })) {
    $out += "| | $($r.Id) | $($r.Evidence) | | | |"
}
$out += ""
$out += "## Signatures"
$out += ""
$out += "| Role | Name | Signature | Date |"
$out += "|---|---|---|---|"
$out += "| Executed by | | | |"
$out += "| Witnessed by (Document Control) | | | |"
$out += "| Approved by (Quality) | | | |"
$out | Set-Content -LiteralPath $Report -Encoding UTF8

Write-Host ''
Write-Host "$pass passed, $fail failed, $witness awaiting a witness." -ForegroundColor $(if ($fail) { 'Yellow' } else { 'Green' })
Write-Host "Report: $Report"
Write-Host "Walk  : $walkReport"
if ($fail) { exit 1 }
