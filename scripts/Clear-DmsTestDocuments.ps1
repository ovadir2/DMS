<#
.SYNOPSIS
    Removes test documents from the DMS: the record, the released file, and the row in the register.

.DESCRIPTION
    Test documents left in the workflow sit in a real person's Approvals - the Approver Matrix sends a
    document nobody chose approvers for to the people the company named, and they have no way of knowing
    the document is a test. This takes them out.

    Each is taken back to where it may be removed: withdrawn if it is waiting for an approver, its released
    file taken out if it was approved, and then the record itself. What the page will not remove (the row
    of a document that was approved) is cleared from the register afterwards, by the folder it is in.

    It works by title: every document whose title starts with -Title (AI-TEST by default), and nothing
    else. The Approver Matrix, the blueprint and real documents are not touched.

    Nothing is removed without -Apply.

.EXAMPLE
    .\scripts\Clear-DmsTestDocuments.ps1
.EXAMPLE
    .\scripts\Clear-DmsTestDocuments.ps1 -Title AI-TEST -Apply
.EXAMPLE
    .\scripts\Clear-DmsTestDocuments.ps1 -Title 'DMS walk' -Apply
#>
[CmdletBinding()]
param(
    [string]$Url = '',
    [string[]]$Title = @('AI-TEST'),
    [string]$As = '',
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Url) { $Url = Get-DmsDefault Url }
$headers = @{}
if ($As) { $headers['X-DMS-Dev-User'] = $As }

function Why($err) {
    $text = "$($err.ErrorDetails.Message)"
    if (-not $text.Trim()) { return "$($err.Exception.Message)" }
    $detail = try { ($text | ConvertFrom-Json).detail } catch { $text }
    if ($detail -is [array]) { $detail = ($detail | ForEach-Object { "$($_.msg)" }) -join '; ' }
    if (-not "$detail".Trim()) { return "$($err.Exception.Message)" }
    return "$detail"
}
function Call($method, $path, $body) {
    $u = "$($Url.TrimEnd('/'))$path"
    if ($null -ne $body) {
        return Invoke-RestMethod -Uri $u -Method $method -UseDefaultCredentials -Headers $headers -TimeoutSec 180 `
                   -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 6)))
    }
    return Invoke-RestMethod -Uri $u -Method $method -UseDefaultCredentials -Headers $headers -TimeoutSec 180
}

function Test-Wanted($text) {
    foreach ($p in $Title) { if ("$text".StartsWith($p, [StringComparison]::OrdinalIgnoreCase)) { return $true } }
    return $false
}

Write-Host "=== The DMS at ${Url}: documents whose title starts with $($Title -join ', ')" -ForegroundColor Cyan
$all = @()
foreach ($d in (Call GET "/api/documents" $null)) { $all += $d }     # one by one: the register is a list
$mine = @()
foreach ($d in $all) { if ((Test-Wanted $d.title) -or (Test-Wanted $d.documentId)) { $mine += $d } }
Write-Host "  $($all.Count) document(s) in the register, $($mine.Count) of them test documents"
if ($mine.Count -eq 0) { Write-Host "Nothing to remove." -ForegroundColor Green; return }

foreach ($d in $mine) {
    $where = if ($d.currentUncPath) { "$($d.currentUncPath)" } else { "$($d.workingUncPath)" }
    Write-Host ("  {0,-12} {1,-34} {2,-10} {3}" -f "$($d.documentId)", "$($d.title)", "$($d.statusKey)", $where)
}
if (-not $Apply) {
    Write-Host ""
    Write-Host "$($mine.Count) document(s) would be removed. Nothing was changed. Add -Apply to do it." -ForegroundColor Yellow
    return
}

Write-Host ""
$left = @()
$folders = @()
foreach ($d in $mine) {
    $id = $d.documentId
    $path = if ($d.currentUncPath) { "$($d.currentUncPath)" } else { "$($d.workingUncPath)" }
    if ($path) {
        $parent = Split-Path $path -Parent
        if ($parent) { $folders += (Split-Path $parent -Leaf) }
    }
    if ($d.statusKey -eq 'Submitted') {
        try { Call POST "/api/documents/$($d.id)/withdraw" @{} | Out-Null; Write-Host "  $id taken back out of Approvals" }
        catch { Write-Host "  $id could not be taken back: $(Why $_)" -ForegroundColor Yellow }
    }
    if ($d.currentUncPath -and (Test-Path -LiteralPath $d.currentUncPath)) {
        try { Call POST "/api/items/delete" @{ path = $d.currentUncPath } | Out-Null }
        catch { Write-Host "  $id released file: $(Why $_)" -ForegroundColor Yellow }
    }
    try { Call POST "/api/documents/$($d.id)/delete" @{} | Out-Null; Write-Host "  $id removed" }
    catch { $left += $id; Write-Host "  $id record stays: $(Why $_)" -ForegroundColor DarkGray }
}

Write-Host ""
if ($left) {
    # a document that was approved keeps its row - right for a real one, clutter for a test one
    $folders = @($folders | Where-Object { $_ -and $_.Length -ge 4 } | Sort-Object -Unique)
    $py = Join-Path (Split-Path $PSScriptRoot -Parent) 'webapi\.venv\Scripts\python.exe'
    Write-Host "$($left.Count) record(s) the page cannot remove: $($left -join ', ')" -ForegroundColor Yellow
    foreach ($f in $folders) {
        if (Test-Path $py) {
            Push-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'webapi')
            try { & $py -m dms_api.spreset "--documents-under=$f" --write } finally { Pop-Location }
        } else {
            Write-Host "    cd webapi; .\.venv\Scripts\python -m dms_api.spreset --documents-under=$f --write"
        }
    }
} else {
    Write-Host "$($mine.Count) document(s) removed. The Approver Matrix and everything else stay as they are." -ForegroundColor Green
}
