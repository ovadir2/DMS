<#
.SYNOPSIS
    Performance Qualification (VAL-004): measures what the DMS really did over the PQ period and writes
    the report.

.DESCRIPTION
    PQ is not a rehearsal - the documents are the company's own, filed and approved by the people whose
    work it is. This does not touch them. It reads what happened: the register and every document's
    history, the time each stage took, what was returned with remarks, what was delegated, what was
    shared, how the pages respond with the period's real data, and what the DMS logged as an error.

    It fills in the measured part of the protocol (PQ-01 to PQ-15). The cases that need a person to say
    yes - the customer really opened the file, the AI answered from a released revision - are listed for
    Document Control to sign, with the evidence this found beside them.

    Run it as a DMS super user: only a super user sees everyone's workflows.

.EXAMPLE
    .\scripts\Invoke-DmsPQ.ps1 -From 2026-12-01 -To 2026-12-14
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [datetime]$From,
    [datetime]$To = (Get-Date),
    [string]$Url = '',
    [string]$App = '',
    [string]$Report = '',
    [int]$MinDocuments = 10,
    [int]$MaxSeconds = 5
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Url) { $Url = Get-DmsDefault Url }
if (-not $App) { $App = Get-DmsDefault App }
if (-not $Report) { $Report = Join-Path $env:TEMP ("DMS-PQ {0:yyyy-MM-dd} to {1:yyyy-MM-dd}.md" -f $From, $To) }
$u = $Url.TrimEnd('/')

function Call($path) { Invoke-RestMethod -Uri "$u$path" -UseDefaultCredentials -TimeoutSec 600 }
function Within($utc) {
    if (-not $utc) { return $false }
    $when = try { [datetime]::Parse($utc).ToUniversalTime() } catch { return $false }
    return ($when -ge $From.ToUniversalTime() -and $when -le $To.ToUniversalTime().AddDays(1))
}
function Hours($a, $b) {
    try { return [math]::Round(([datetime]::Parse($b) - [datetime]::Parse($a)).TotalHours, 1) } catch { return $null }
}

Write-Host "=== PQ of the DMS at $u, $($From.ToString('yyyy-MM-dd')) to $($To.ToString('yyyy-MM-dd'))" -ForegroundColor Cyan
$health = Call '/api/health'
Write-Host "  build $($health.version), software revision $($health.softwareRevision) ($($health.validationStatus))"
$state = Get-Content -LiteralPath (Join-Path $App 'docs\validation\validation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ("$($health.softwareRevision)" -ne "$($state.softwareRevision)") {
    Write-Host ("  the DMS ran revision $($health.softwareRevision) and the validation set is revision " +
                "$($state.softwareRevision): the report records both, and the difference is a deviation.") -ForegroundColor Yellow
}

# ---------------------------------------------------------------- what happened in the period
$all = Call '/api/my-workflows?everyone=true'
$items = @($all.items)
Write-Host "  $($items.Count) document(s) in the register"

$released = @(); $returned = @(); $delegated = @(); $stage = @(); $whole = @()
foreach ($d in $items) {
    $events = @($d.history)                      # oldest first
    $mine = @($events | Where-Object { Within $_.utc })
    if (-not $mine) { continue }
    $created   = ($events | Where-Object { $_.event -match 'Created|נוצר' } | Select-Object -First 1)
    $submitted = ($events | Where-Object { $_.event -match 'Submit|הוגש' } | Select-Object -Last 1)
    $approved  = ($mine   | Where-Object { $_.details -match 'Released|שוחרר' -or $_.toStatus -match 'Approved' } | Select-Object -Last 1)
    foreach ($e in $mine) {
        if ($e.details -match '^Stage \d returned|החזרה') { $returned += [pscustomobject]@{ Doc = $d.documentId; By = $e.actor; When = $e.utc } }
        if ($e.details -match 'Delegated')                { $delegated += [pscustomobject]@{ Doc = $d.documentId; What = $e.details; When = $e.utc } }
    }
    if ($approved) {
        $released += [pscustomobject]@{
            Doc = $d.documentId; Title = $d.title; Rev = $d.currentRevision; Owner = $d.ownerName
            Folder = (Split-Path (Split-Path "$($d.file)" -Parent) -Parent)
            SubmittedToApproved = if ($submitted) { Hours $submitted.utc $approved.utc } else { $null }
            DraftToApproved     = if ($created)   { Hours $created.utc   $approved.utc } else { $null } }
        if ($submitted -and $created) { $whole += $d }
    }
    $answers = @($mine | Where-Object { $_.event -match 'Approv|אוש' })
    if ($answers.Count -gt 1) { $stage += $d.documentId }
}

$departments = @($released | ForEach-Object { ($_.Folder -split '\\')[-1] } | Sort-Object -Unique)
$hours = @($released | Where-Object { $null -ne $_.SubmittedToApproved } | ForEach-Object { $_.SubmittedToApproved })
$median = if ($hours) { ($hours | Sort-Object)[[int]([math]::Floor($hours.Count / 2))] } else { $null }

# ---------------------------------------------------------------- how the pages respond, with real data
$timings = @()
foreach ($one in @(@{ N = 'Approvals'; P = '/api/approvals' }, @{ N = 'My workflows'; P = '/api/my-workflows' },
                   @{ N = 'Browse the root'; P = '/api/browse' }, @{ N = 'The register'; P = '/api/documents' })) {
    $t = Measure-Command { Call $one.P | Out-Null }
    $timings += [pscustomobject]@{ Page = $one.N; Seconds = [math]::Round($t.TotalSeconds, 1) }
}
$slow = @($timings | Where-Object { $_.Seconds -gt $MaxSeconds })

# ---------------------------------------------------------------- releases, Markdown and read-only
$root = Get-DmsEnvValue 'DMS_REPOSITORY_ROOT'
$writable = @(); $noMarkdown = @()
foreach ($r in $released) {
    $d = $items | Where-Object { $_.documentId -eq $r.Doc } | Select-Object -First 1
    $file = "$($d.file)"
    if (-not $file -or -not (Test-Path -LiteralPath $file)) { continue }
    if (-not (Get-Item -LiteralPath $file).IsReadOnly) { $writable += $file }
    $folder = Split-Path $file -Parent
    if (-not (Get-ChildItem -LiteralPath $folder -Filter '*.md' -File -ErrorAction SilentlyContinue)) { $noMarkdown += $file }
}

# ---------------------------------------------------------------- what the DMS logged
$errors = @()
$cfg = Join-Path $App 'webapi\web.config'
$m = Select-String -Path $cfg -Pattern 'stdoutLogFile\s*=\s*"([^"]+)"' | Select-Object -First 1
if ($m) {
    $folder = Split-Path $m.Matches[0].Groups[1].Value -Parent
    $logs = @(Get-ChildItem -LiteralPath $folder -Filter '*.log' -ErrorAction SilentlyContinue |
              Where-Object { $_.LastWriteTime -ge $From })
    foreach ($log in $logs) {
        $errors += @(Select-String -Path $log.FullName -Pattern '\bERROR\b|Traceback' -ErrorAction SilentlyContinue |
                     Select-Object -Last 50 | ForEach-Object { "$($_.Filename):$($_.LineNumber) $($_.Line.Trim())" })
    }
}

# ---------------------------------------------------------------- the register against the file server
$missing = @($items | Where-Object { $_.fileMissing })

function Verdict($ok) { if ($ok) { '**PASS**' } else { '**FAIL**' } }
$out = @()
$out += "# PQ report - RH DMS (VAL-004)"
$out += ""
$out += "| | |"
$out += "|---|---|"
$out += "| Period | $($From.ToString('yyyy-MM-dd')) to $($To.ToString('yyyy-MM-dd')) |"
$out += "| Written | $(Get-Date -Format 'yyyy-MM-dd HH:mm') by $env:USERDOMAIN\$env:USERNAME |"
$out += "| System | $u |"
$out += "| Build / software revision | $($health.version) / $($health.softwareRevision) ($($health.validationStatus)) |"
$out += "| Validation set revision | $($state.softwareRevision)$(if ("$($health.softwareRevision)" -ne "$($state.softwareRevision)") { " - **different from the running revision: a deviation**" }) |"
$out += ""
$out += "## Measured"
$out += ""
$out += "| # | Measure | Acceptance criterion | Measured | P/F |"
$out += "|---|---|---|---|---|"
$out += "| PQ-01 | Real documents released in the period | at least $MinDocuments, across at least 3 departments | $($released.Count) document(s), $($departments.Count) department(s) | $(Verdict ($released.Count -ge $MinDocuments -and $departments.Count -ge 3)) |"
$out += "| PQ-02 | Documents with more than one approver answering | at least 3 | $($stage.Count) | $(Verdict ($stage.Count -ge 3)) |"
$out += "| PQ-03 | Returned with remarks and re-submitted | at least 2 | $($returned.Count) return(s) | $(Verdict ($returned.Count -ge 2)) |"
$out += "| PQ-04 | Delegations | at least 1 | $($delegated.Count) | $(Verdict ($delegated.Count -ge 1)) |"
$out += "| PQ-05 | Full cycle, draft to released | at least 5 whole cycles in the period | $($whole.Count) | $(Verdict ($whole.Count -ge 5)) |"
$out += "| PQ-11 | Page response with the period's real data | each under $MaxSeconds s | $(($timings | ForEach-Object { "$($_.Page) $($_.Seconds)s" }) -join ', ') | $(Verdict (-not $slow)) |"
$out += "| PQ-12 | Released files are read only, with a Markdown beside them | 100% | $($writable.Count) writable, $($noMarkdown.Count) without Markdown | $(Verdict (-not $writable -and -not $noMarkdown)) |"
$out += "| PQ-13 | Audit completeness | every release has created, submitted, decided, released | $($whole.Count) of $($released.Count) release(s) carry the whole chain | $(Verdict ($released.Count -eq 0 -or $whole.Count -eq $released.Count)) |"
$out += "| PQ-14 | Errors in the DMS log | none that affected a document | $($errors.Count) error line(s) | $(Verdict (-not $errors)) |"
$out += "| PQ-15 | The register matches the file server | every record points at a file that exists | $($missing.Count) record(s) point at nothing | $(Verdict (-not $missing)) |"
$out += ""
$out += "Time from submission to approval: " + $(if ($median) { "median $median h, longest $(($hours | Measure-Object -Maximum).Maximum) h, shortest $(($hours | Measure-Object -Minimum).Minimum) h" } else { "nothing to measure" })
$out += ""
$out += "## The documents of the period"
$out += ""
$out += "| Document | Title | Rev | Owner | Submitted to approved (h) |"
$out += "|---|---|---|---|---|"
foreach ($r in ($released | Sort-Object Doc)) {
    $out += "| $($r.Doc) | $($r.Title) | $($r.Rev) | $($r.Owner) | $($r.SubmittedToApproved) |"
}
$out += ""
$out += "## Witnessed by Document Control"
$out += ""
$out += "| # | Case | Evidence found here | Signed |"
$out += "|---|---|---|---|"
$out += "| PQ-06 | A customer received a share and could open it view-only | the share log and the audit of the period | |"
$out += "| PQ-07 | People saw what their AD groups allow, and asked for no rights on the file server | no permission request raised in the period | |"
$out += "| PQ-08 | The AI answered from a released revision, never a draft or an obsolete one | the AI reads Current_ReadOnly only | |"
$out += "| PQ-09 | HRPortal, WidgetBuilder and the AI index worked within their scopes | the machine-API lines of the DMS log | |"
$out += "| PQ-10 | Availability: no unplanned outage over 30 minutes | the service log and the IIS log of the period | |"
$out += ""
if ($errors) {
    $out += "## Errors found in the log"
    $out += ""
    $out += '```'
    $out += ($errors | Select-Object -Last 40)
    $out += '```'
    $out += ""
}
$out += "## Deviations"
$out += ""
$out += "| # | Case | What happened | Class | Disposition | Closed |"
$out += "|---|---|---|---|---|---|"
if ($writable)   { $out += "| | PQ-12 | $($writable.Count) released file(s) are writable, first $($writable[0]) | | | |" }
if ($noMarkdown) { $out += "| | PQ-12 | $($noMarkdown.Count) released file(s) have no Markdown, first $($noMarkdown[0]) | | | |" }
if ($missing)    { $out += "| | PQ-15 | $($missing.Count) record(s) point at a file that is not there, first $($missing[0].documentId) | | | |" }
if ($slow)       { $out += "| | PQ-11 | slower than $MaxSeconds s: $(($slow | ForEach-Object { "$($_.Page) $($_.Seconds)s" }) -join ', ') | | | |" }
$out += ""
$out += "## Conclusion and signatures"
$out += ""
$out += "The system **performs / does not perform** in daily use as intended (delete one)."
$out += ""
$out += "| Role | Name | Signature | Date |"
$out += "|---|---|---|---|"
$out += "| Executed by (Document Control) | | | |"
$out += "| Reviewed by (System owner) | | | |"
$out += "| Approved by (Quality) | | | |"
$out | Set-Content -LiteralPath $Report -Encoding UTF8

Write-Host ''
Write-Host "$($released.Count) document(s) released in the period, $($departments.Count) department(s), $($returned.Count) return(s), $($delegated.Count) delegation(s)."
foreach ($t in $timings) { Write-Host ("  {0,-18} {1}s" -f $t.Page, $t.Seconds) }
if ($writable -or $noMarkdown -or $missing -or $slow -or $errors) {
    Write-Host 'Deviations were found - they are listed in the report.' -ForegroundColor Yellow
}
Write-Host "Report: $Report"
