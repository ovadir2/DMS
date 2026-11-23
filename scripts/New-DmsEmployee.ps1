<#
.SYNOPSIS
    An employee file in the DMS: the folders of Employee_Skeleton and the AD permissions on them, for one
    employee or for a list of them.

.DESCRIPTION
    HRPortal asks the DMS for these one at a time (POST /api/v1/employees/<id>/folder). This is the same
    thing from the server: for loading a whole company at once, or where the DMS is not running.

    One folder under HR\Employees is the skeleton (DMS_EMPLOYEE_SKELETON, Employee_Skeleton by default; a
    folder named Employee_Skelton answers to it too). An employee file is its folder tree and its
    permissions, copied - and never its documents, which is what keeps the restricted folders restricted.

    Nothing is written without -Apply.

.PARAMETER SynelId
    One or more Synel employee ids. They are folder names: letters, digits, - and _ , leading zeros kept.

.PARAMETER FromCsv
    A CSV instead, with the ids in -Column (default SynelId).

.EXAMPLE
    .\scripts\New-DmsEmployee.ps1 -SynelId 000123,000124
.EXAMPLE
    .\scripts\New-DmsEmployee.ps1 -FromCsv .\employees.csv -Column EmployeeId -Apply
#>
[CmdletBinding()]
param(
    [string[]]$SynelId = @(),
    [string]$FromCsv = '',
    [string]$Column = 'SynelId',
    [string]$Root = '',
    [string]$Employees = '',
    [string]$Skeleton = '',
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Root)      { $Root = Get-DmsEnvValue 'DMS_REPOSITORY_ROOT' }
if (-not $Root)      { throw "DMS_REPOSITORY_ROOT is not in webapi\.env - run this on the DMS server, or give -Root." }
if (-not $Employees) { $Employees = (Get-DmsEnvValue 'DMS_EMPLOYEES_FOLDER'); if (-not $Employees) { $Employees = '01_General/HR/Employees' } }
if (-not $Skeleton)  { $Skeleton  = (Get-DmsEnvValue 'DMS_EMPLOYEE_SKELETON'); if (-not $Skeleton)  { $Skeleton  = 'Employee_Skeleton' } }

$base = Join-Path $Root ($Employees -replace '/', '\')
if (-not (Test-Path -LiteralPath $base)) {
    throw "There is no employee folder yet: $base - run .\scripts\Update-DmsBlueprint.ps1 first."
}
$shape = Join-Path $base $Skeleton
if (-not (Test-Path -LiteralPath $shape)) {
    $shape = Get-ChildItem -LiteralPath $base -Directory |
             Where-Object { $_.Name -match '^employees?[ _-]?skel(e)?ton$' } |
             Select-Object -First 1 -ExpandProperty FullName
}
if (-not $shape) { Write-Host "  [warn] no $Skeleton under $base - the folders will be made without permissions" -ForegroundColor Yellow }

if ($FromCsv) {
    if (-not (Test-Path -LiteralPath $FromCsv)) { throw "The CSV was not found: $FromCsv" }
    $SynelId += (Import-Csv -LiteralPath $FromCsv | ForEach-Object { "$($_.$Column)".Trim() } | Where-Object { $_ })
}
$SynelId = @($SynelId | Where-Object { $_ } | Select-Object -Unique)
if (-not $SynelId.Count) { throw "Give -SynelId, or -FromCsv with the ids in -Column." }

Write-Host ""
Write-Host "=== $($SynelId.Count) employee file(s) under $base" -ForegroundColor Cyan
Write-Host "    skeleton: $(if ($shape) { $shape } else { '(none - the blueprint folders only)' })"
Write-Host "    mode    : $(if ($Apply) { 'writing' } else { 'showing what would be done (-Apply writes)' })"
Write-Host ""

$made = 0; $there = 0; $bad = 0
foreach ($one in $SynelId) {
    if ($one -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$' -or $one -match '^employees?[ _-]?skel(e)?ton$') {
        Write-Host "  [skip] $one is not a Synel employee id" -ForegroundColor Yellow; $bad++; continue
    }
    $target = Join-Path $base $one
    if (Test-Path -LiteralPath $target) { Write-Host "  [--]   $one is already there" -ForegroundColor DarkGray; $there++; continue }
    if (-not $Apply) { Write-Host "  [--]   $one would be cut from $(Split-Path $shape -Leaf)"; continue }
    if ($shape) {
        # /E every folder, /XF * none of the files in them, /COPYALL the permissions and the owner with each
        $out = robocopy $shape $target /E /XF * /COPYALL /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
        if ($LASTEXITCODE -ge 8) {
            Write-Host "  [warn] $one : robocopy $LASTEXITCODE - the folders may be there without their permissions" -ForegroundColor Yellow
            Write-Host ($out | Select-Object -Last 3) -ForegroundColor DarkGray
        } else {
            $n = (Get-ChildItem -LiteralPath $target -Recurse -Directory -ErrorAction SilentlyContinue).Count
            Write-Host ("  [ok]   {0} : {1} folders, with their permissions" -f $one, $n) -ForegroundColor Green
        }
    } else {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        foreach ($f in @('01_Personal','02_Employment','03_Contracts','04_Compensation','05_Attendance_Leave',
                         '06_Onboarding','07_Training','08_Performance','09_Equipment','10_Correspondence',
                         '11_Acknowledgments','12_Disciplinary','13_Medical','14_Offboarding')) {
            New-Item -ItemType Directory -Path (Join-Path $target $f) -Force | Out-Null
        }
        Write-Host "  [ok]   $one : 14 folders (no permissions were copied)" -ForegroundColor Green
    }
    $made++
}
Write-Host ""
Write-Host ("{0} made, {1} already there, {2} not an id." -f $made, $there, $bad) -ForegroundColor $(if ($bad) { 'Yellow' } else { 'Green' })
if (-not $Apply) { Write-Host "Nothing was changed. Add -Apply to write them." -ForegroundColor Yellow }
