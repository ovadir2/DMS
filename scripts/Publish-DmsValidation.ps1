<#
.SYNOPSIS
    Publishes the DMS validation set into the DMS itself, as controlled documents with a formal revision.

.DESCRIPTION
    The validation of the DMS is a controlled document set like any other, and it belongs where the quality
    documents are: 01_General\Quality and Standards\DMS_Validation. This builds the documents from their
    source (docs\validation\*.md) as Word files carrying the rh logo, the document number and the software
    revision, puts them in that folder and releases them, so the revision in force is the one in
    Current_ReadOnly.

    Run again after a change: the software revision in docs\validation\validation.json is the revision of
    the documents, each one becomes the next revision of its own record, and the DMS moves the revision it
    replaces to Obsolete_ReadOnly - the same path every controlled document takes.

    Nothing is written without -Apply.

.PARAMETER Approver
    Release through the normal approval workflow, to these approvers, instead of releasing as approved.
    Use it when Quality signs the revision inside the DMS rather than on the document.

.EXAMPLE
    .\scripts\Publish-DmsValidation.ps1
.EXAMPLE
    .\scripts\Publish-DmsValidation.ps1 -Apply
.EXAMPLE
    .\scripts\Publish-DmsValidation.ps1 -Apply -Approver quality@rh.co.il
#>
[CmdletBinding()]
param(
    [string]$Url = '',
    [string]$App = '',
    [string]$Folder = '01_General\Quality and Standards\DMS_Validation',
    [string]$Revision = '',
    [string[]]$Approver = @(),
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Url) { $Url = Get-DmsDefault Url }
if (-not $App) { $App = Get-DmsDefault App }
$root = Get-DmsEnvValue 'DMS_REPOSITORY_ROOT'
if (-not $root) { throw 'DMS_REPOSITORY_ROOT is not in webapi\.env - run this on the DMS server.' }
$py = Join-Path $App 'webapi\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw "The DMS python was not found: $py" }

$state = Get-Content -LiteralPath (Join-Path $App 'docs\validation\validation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Revision) { $Revision = $state.softwareRevision }
if (-not $Revision) { throw 'No software revision in docs\validation\validation.json' }

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
        return Invoke-RestMethod -Uri $u -Method $method -UseDefaultCredentials -TimeoutSec 300 `
                   -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 6)))
    }
    return Invoke-RestMethod -Uri $u -Method $method -UseDefaultCredentials -TimeoutSec 300
}
function Send-File($path, $where, $extra) {
    # multipart by hand: Windows PowerShell 5.1 has no -Form
    $name = Split-Path -Leaf $path
    $b = [guid]::NewGuid().ToString()
    $nl = "`r`n"
    $head = ''
    $all = @{ folder = $where } + $(if ($extra) { $extra } else { @{} })
    foreach ($k in $all.Keys) { $head += "--$b$nl" + "Content-Disposition: form-data; name=`"$k`"$nl$nl" + "$($all[$k])$nl" }
    $head += ("--$b$nl" + "Content-Disposition: form-data; name=`"file`"; filename=`"$name`"$nl" +
              "Content-Type: application/octet-stream$nl$nl")
    $enc = [Text.Encoding]::UTF8
    $bytes = $enc.GetBytes($head) + [IO.File]::ReadAllBytes($path) + $enc.GetBytes("$nl--$b--$nl")
    return Invoke-RestMethod -Uri "$($Url.TrimEnd('/'))/api/files" -Method POST -UseDefaultCredentials `
               -ContentType "multipart/form-data; boundary=$b" -Body $bytes -TimeoutSec 300
}

Write-Host "=== The DMS validation set, revision $Revision" -ForegroundColor Cyan
$here = Join-Path $root $Folder
if (-not (Test-Path -LiteralPath $here)) {
    throw "The folder $here does not exist. Run .\scripts\Update-DmsBlueprint.ps1 first."
}

$build = Join-Path $env:TEMP ("DMS-Validation-Rev{0}-{1:yyyyMMddHHmm}" -f $Revision, (Get-Date))
Push-Location (Join-Path $App 'webapi')
try { $made = & $py -m dms_api.validation_docs $build --revision $Revision } finally { Pop-Location }
$files = @(Get-ChildItem -LiteralPath $build -File | Sort-Object Name)
Write-Host "  $($files.Count) document(s) built in $build"
foreach ($f in $files) { Write-Host "    $($f.Name)" }

$known = @(Call GET '/api/documents' $null)
$plan = @()
foreach ($f in $files) {
    $id = ($f.BaseName -split '_')[0]                       # VAL-001
    $existing = $known | Where-Object {
        ("$($_.title)" -like "$id*" -or "$($_.workingUncPath)$($_.currentUncPath)" -like "*\$id`_*") -and
        "$($_.workingUncPath)$($_.currentUncPath)" -like "*$([regex]::Escape($Folder))*" } | Select-Object -First 1
    $plan += [pscustomobject]@{
        File = $f; Id = $id
        Action = if ($existing) { "new revision of $($existing.documentId) (rev $($existing.currentRevision) -> $Revision)" }
                 else { "first release, revision $Revision" }
        Record = $existing }
}
Write-Host ''
foreach ($p in $plan) { Write-Host ("  {0,-12} {1}" -f $p.Id, $p.Action) }

if (-not $Apply) {
    Write-Host ''
    Write-Host "Nothing was published. Add -Apply to put these in $here." -ForegroundColor Yellow
    Write-Host "Built documents: $build"
    return
}

Write-Host ''
$done = 0; $failed = @()
foreach ($p in $plan) {
    $name = $p.File.Name
    try {
        if ($p.Record) {
            # the next revision of the same record: the DMS makes the draft, and releasing it moves the
            # revision it replaces to Obsolete_ReadOnly
            $rev = Invoke-RestMethod -Uri "$($Url.TrimEnd('/'))/api/documents/$($p.Record.id)/revise" -Method POST `
                       -UseDefaultCredentials -TimeoutSec 300 -ContentType 'application/x-www-form-urlencoded' `
                       -Body "submit=false"
            $draft = $rev.draft
            Copy-Item -LiteralPath $p.File.FullName -Destination $draft -Force
            $released = Call POST '/api/files/release' @{ paths = @($draft) }
        } else {
            $up = Send-File $p.File.FullName $here @{}
            if ($Approver) {
                Call POST '/api/documents' @{ path = $up.path; title = "$($p.Id) $($p.File.BaseName -replace '^[^_]+_', '' -replace '_Rev\d+$', '' -replace '_', ' ')"
                                              submit = $true; approvers = $Approver } | Out-Null
                Write-Host "  $name submitted to $($Approver -join ', ')"
                $done++
                continue
            }
            $released = Call POST '/api/files/release' @{ paths = @($up.path) }
        }
        $result = @($released.results)[0]
        if (-not $result.ok) { throw "$($result.error)" }
        Write-Host "  $name released as $($result.documentId)" -ForegroundColor Green
        $done++
    } catch {
        $failed += "$name - $(Why $_)"
        Write-Host "  $name - $(Why $_)" -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host "$done of $($plan.Count) document(s) published to $here (revision $Revision)." -ForegroundColor $(if ($failed) { 'Yellow' } else { 'Green' })
if ($failed) { $failed | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }; exit 1 }
