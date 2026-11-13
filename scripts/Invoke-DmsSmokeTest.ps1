<#
.SYNOPSIS
    Runs a real document through this DMS - register, submit, remark, approve, release, revise - and leaves
    everything in place so it can be traced on the page.

.DESCRIPTION
    The same walk the automated tests do, but against the DMS that is really running, with your Windows
    sign-in, so what it does appears in Approvals, My workflows, the Document Register and the Control
    Audit. Nothing is cleaned up: -Clean removes what it made, when you say so.

    It works in a folder of its own (`01_General\IT\DMS-Selftest` by default) so nothing real is touched.

.PARAMETER Approver
    Who to send it to. It cannot be you: nobody approves their own document. The approval itself is then
    made by you as a super user, which is how a document is unblocked when an approver is away.

.EXAMPLE
    .\scripts\Invoke-DmsSmokeTest.ps1 -Approver dms-lab@rh.co.il
.EXAMPLE
    .\scripts\Invoke-DmsSmokeTest.ps1 -Clean
#>
[CmdletBinding()]
param(
    [string]$Url = '',
    [string]$Approver = '',
    [string]$Folder = '01_General\IT\DMS-Selftest',
    [switch]$Clean
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Url) { $Url = Get-DmsDefault Url }
$root = Get-DmsEnvValue 'DMS_REPOSITORY_ROOT'
if (-not $root) { throw "DMS_REPOSITORY_ROOT is not in webapi\.env - run this on the DMS server." }
$here = Join-Path $root $Folder
$step = 0
function Call($method, $path, $body, $fields) {
    # Windows PowerShell 5.1 has no -Form, so a form is written out by hand; it is two fields at most here.
    $u = "$($Url.TrimEnd('/'))$path"
    if ($fields) {
        $pairs = ($fields.GetEnumerator() | ForEach-Object { "$($_.Key)=$([uri]::EscapeDataString("$($_.Value)"))" }) -join '&'
        return Invoke-RestMethod -Uri $u -Method $method -UseDefaultCredentials -TimeoutSec 120 `
                   -ContentType 'application/x-www-form-urlencoded' -Body $pairs
    }
    if ($body) { return Invoke-RestMethod -Uri $u -Method $method -UseDefaultCredentials -TimeoutSec 120 `
                     -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 5))) }
    return Invoke-RestMethod -Uri $u -Method $method -UseDefaultCredentials -TimeoutSec 120
}
function Say($what, $detail = '') {
    $script:step++
    Write-Host ("{0,2}. {1}" -f $script:step, $what) -ForegroundColor Green
    if ($detail) { Write-Host "    $detail" -ForegroundColor DarkGray }
}

if ($Clean) {
    Write-Host "Removing what the self-test made in $here" -ForegroundColor Yellow
    $mine = (Call GET "/api/documents" $null $null) | Where-Object { "$($_.workingUncPath)$($_.currentUncPath)" -like "*$Folder*" }
    foreach ($d in $mine) {
        try { Call POST "/api/documents/$($d.id)/delete" @{} $null | Out-Null; Write-Host "    $($d.documentId) removed" }
        catch { Write-Host "    $($d.documentId): $($_.Exception.Message)" -ForegroundColor Yellow }
    }
    if (Test-Path $here) { Get-ChildItem $here -Recurse -File | ForEach-Object { $_.IsReadOnly = $false } ; Remove-Item $here -Recurse -Force }
    Write-Host "Done. The Control Audit keeps the lines - that is the point of it." -ForegroundColor Green
    return
}
if (-not $Approver) { throw "Give -Approver <someone@rh.co.il> - it cannot be you." }
# The approver has to be able to read the folder before the document can be sent to them. A folder made a
# moment ago may not have reached them yet, and the DMS then refuses the submission - which is the rule
# working, not a fault: the folder is made first, and the walk waits for AD to catch up.


# ---- a folder of its own, and a real file in it
$fresh = -not (Test-Path $here)
New-Item -ItemType Directory -Path $here -Force | Out-Null
if ($fresh) {
    Write-Host "    (the folder was just made: giving AD a moment to pass its permissions down)" -ForegroundColor DarkGray
    Start-Sleep -Seconds 5
}
$name = "DMS self-test $(Get-Date -Format 'yyyy-MM-dd HHmm').txt"
$file = Join-Path $here $name
@("DMS self-test", "", "Written by scripts\Invoke-DmsSmokeTest.ps1 on $(Get-Date -Format u).",
  "This document is here to be traced: register, submit, remark, approve, release, revise.") |
    Set-Content -Path $file -Encoding UTF8
Say "a file was written into the repository" $file

# ---- register and submit
$doc = Call POST "/api/documents" @{ path = $file; documentType = 'נוהל'; documentArea = 'מערכות מידע';
                                     submit = $true; approvers = @($Approver) } $null
Say "registered and submitted" "$($doc.documentId) - waiting for $Approver"

# ---- approve it as a super user (the approver is away; this is the unblocking path, and it says so)
$after = Call POST "/api/approvals/$($doc.id)" @{ approve = $true; comment = 'self-test: approved' } $null
Say "approved" "status now: $($after.statusKey)"

Start-Sleep -Seconds 3
$cur = Join-Path $here 'Current_ReadOnly'
Say "released" ((Get-ChildItem $cur -File -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }) -join ', ')

# ---- the next revision, left in work so it can be seen in My workflows
$rev = Call POST "/api/documents/$($doc.id)/revise" $null @{ submit = 'false' }   # a form, as the endpoint takes
Say "a second revision was started and left in work" (Split-Path -Leaf $rev.draft)

Write-Host ""
Write-Host "Trace it on the page:" -ForegroundColor Cyan
Write-Host "  $Url/dms/dms-page   ->  $Folder"
Write-Host "  My workflows        ->  $($doc.documentId), revision 02 in work"
Write-Host "  History on the row  ->  registered, submitted, approved, released, revised"
Write-Host "  $cur"
Write-Host ""
Write-Host "When you have seen enough:  .\scripts\Invoke-DmsSmokeTest.ps1 -Clean" -ForegroundColor Yellow
