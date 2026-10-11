#Requires -Version 5.1
<#
.SYNOPSIS
    Reads the DMS root and reports, for each folder down to the department level, who has access now and what
    scripts\dms-access.csv plans for it. Changes nothing.

.DESCRIPTION
    Folders: the root's folders, 01_General\*, 02_Customers\* and 02_Customers\<Customer>\* (-Depth 4 also one level
    below those). One row each, in a CSV that Excel opens (default: dms-access-report.csv next to this script):
        Folder        path from the root
        Inherits      Yes / No (No = "inheritance disabled" on that folder)
        Own           its own permissions (group: Full / Modify / Read / Open / NoDelete / Other)
        FromAbove     the permissions it inherits
        Broad         Everyone / Authenticated Users / Domain Users / Users that can open it (anyone in the company)
        PlanModify    the groups dms-access.csv gives Modify there
        PlanRead      the groups dms-access.csv gives Read there
        Note          "not in the table" for a department / customer folder no row covers, "blueprint" for the others
    Run as a user who may read the permissions (file server admin).

.EXAMPLE
    .\Get-DmsAccess.ps1                         # root from webapi\.env (DMS_REPOSITORY_ROOT)
    .\Get-DmsAccess.ps1 -Root E:\Shares -Out C:\Temp\access.csv
#>
[CmdletBinding()]
param(
    [string] $Root,
    [string] $Map = (Join-Path $PSScriptRoot 'dms-access.csv'),
    [string] $Out = (Join-Path $PSScriptRoot 'dms-access-report.csv'),
    [ValidateRange(2, 5)] [int] $Depth = 3
)
$ErrorActionPreference = 'Stop'
$envFile = Join-Path $PSScriptRoot '..\webapi\.env'
function Get-DmsSetting([string]$Name) {
    $v = [Environment]::GetEnvironmentVariable($Name)
    if ($v) { return $v.Trim() }
    if (-not (Test-Path -LiteralPath $envFile)) { return '' }
    $line = Get-Content -LiteralPath $envFile -Encoding UTF8 | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -Last 1
    if (-not $line) { return '' }
    (($line -split '=', 2)[1] -replace '\s+#.*$', '').Trim().Trim('"').Trim("'")
}
if (-not $Root) { $Root = Get-DmsSetting 'DMS_REPOSITORY_ROOT' }
if (-not $Root -or -not (Test-Path -LiteralPath $Root)) { throw "Repository root not found: '$Root'. Set DMS_REPOSITORY_ROOT in webapi\.env or give -Root." }
$Root = $Root.TrimEnd('\')
$custFolder = Get-DmsSetting 'DMS_CUSTOMERS_FOLDER'; if (-not $custFolder) { $custFolder = '02_Customers' }

function Split-List([string]$v) { @("$v" -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notlike '<*' }) }
$rows = @(Import-Csv -LiteralPath $Map -Encoding UTF8 | Where-Object { $_.Department -and (Split-List $_.Groups).Count })

# the plan for one folder (parts from the root), as Set-DmsAccess.ps1 reads the table
function Plan([string[]]$parts) {
    $m = @(); $r = @(); $rel = $parts -join '\'
    foreach ($row in $rows) {
        $hit = $false
        if ($row.Department -match '\\') { $hit = $row.Department.Trim('\') -eq $rel }
        elseif ($parts.Count -eq 2 -and $parts[0] -eq '01_General') { $hit = $parts[1] -eq $row.Department }
        elseif ($parts.Count -eq 3 -and $parts[0] -eq $custFolder) { $hit = $parts[2] -in (Split-List $row.CustomerFolders) }
        if ($hit) { $m += Split-List $row.Groups; $r += Split-List $row.ReadGroups }
    }
    @{ M = @($m | Select-Object -Unique); R = @($r | Select-Object -Unique) }
}

function Short-Rights($rule) {
    $v = [int]$rule.FileSystemRights
    if ($rule.AccessControlType -eq 'Deny') { if ($v -eq 0x10000) { return 'NoDelete' } else { return 'Deny' } }
    $open = $rule.InheritanceFlags -eq 'None'
    $name = if (($v -band 0x1F01FF) -eq 0x1F01FF) { 'Full' } elseif (($v -band 0x1301BF) -eq 0x1301BF) { 'Modify' }
            elseif (($v -band 0x1200A9) -eq 0x1200A9) { 'Read' } else { 'Other' }
    if ($open -and $name -eq 'Read') { 'Open' } else { $name }
}
function Name-Of($sid) { try { $sid.Translate([Security.Principal.NTAccount]).Value } catch { $sid.Value } }
$broad = { param($sid) $v = $sid.Value; $v -in 'S-1-1-0', 'S-1-5-11', 'S-1-5-32-545' -or $v -match '^S-1-5-21-.+-513$' }
function Rules-Text($rules) {
    (@($rules | ForEach-Object { "$(Name-Of $_.IdentityReference): $(Short-Rights $_)" } | Select-Object -Unique) -join '; ')
}
$bp = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'blueprint-folders.txt') -Encoding UTF8 | ForEach-Object { $_.Trim().ToLower() })

$folders = New-Object Collections.Generic.List[string]
function Walk([string]$path, [int]$level) {
    $folders.Add($path)
    if ($level -ge $Depth) { return }
    $rel = $path.Substring($Root.Length).TrimStart('\', '/') -replace '/', '\'
    $deeper = $level -lt 2 -or $rel -like '01_General*' -or $rel -like "$custFolder*"
    if (-not $deeper) { return }
    foreach ($d in Get-ChildItem -LiteralPath $path -Directory -Force -ErrorAction SilentlyContinue | Sort-Object Name) {
        if ($d.Name -in 'Submitted', 'Current_ReadOnly', 'Obsolete_ReadOnly') { continue }
        Walk $d.FullName ($level + 1)
    }
}
Walk $Root 0

$report = foreach ($f in $folders) {
    $rel = $f.Substring($Root.Length).TrimStart('\', '/') -replace '/', '\'
    $parts = @(if ($rel) { $rel -split '\\' })
    try { $acl = Get-Acl -LiteralPath $f } catch { [pscustomobject]@{ Folder = "\$rel"; Note = "cannot read: $($_.Exception.Message)" }; continue }
    $sid = [Security.Principal.SecurityIdentifier]
    $own = @($acl.GetAccessRules($true, $false, $sid)); $above = @($acl.GetAccessRules($false, $true, $sid))
    $p = Plan $parts
    $key = if ($parts.Count -ge 2 -and $parts[0] -eq $custFolder) { (@('02_customers', '<customer>') + @($parts | Select-Object -Skip 2)) -join '\' } else { $rel }
    $note = if (($parts.Count -eq 2 -and $parts[0] -eq '01_General') -or ($parts.Count -eq 3 -and $parts[0] -eq $custFolder)) {
                if ($p.M.Count) { '' } elseif ($key.ToLower() -in $bp) { 'not in the table' } else { 'not in the table (not a blueprint folder)' }
            } elseif ($parts.Count -ge 2 -and $key.ToLower() -notin $bp -and -not ($parts.Count -eq 2 -and $parts[0] -eq $custFolder)) { 'not a blueprint folder' } else { '' }
    [pscustomobject]@{
        Folder     = "\$rel"
        Inherits   = if ($acl.AreAccessRulesProtected) { 'No' } else { 'Yes' }
        Own        = Rules-Text $own
        FromAbove  = Rules-Text $above
        Broad      = (@($own + $above | Where-Object { & $broad $_.IdentityReference } | ForEach-Object { Name-Of $_.IdentityReference } | Select-Object -Unique) -join '; ')
        PlanModify = $p.M -join '; '
        PlanRead   = $p.R -join '; '
        Note       = $note
    }
}
$report | Export-Csv -LiteralPath $Out -NoTypeInformation -Encoding UTF8
$report | Format-Table Folder, Inherits, Broad, PlanModify, Note -AutoSize | Out-String -Width 220 | Write-Host
$open = @($report | Where-Object { $_.Broad }).Count
$miss = @($report | Where-Object { $_.Note -like 'not in the table*' }).Count
Write-Host "Folders: $(@($report).Count). Open to everyone: $open. Department / customer folders with no row in the table: $miss." -ForegroundColor Cyan
Write-Host "Full report (Own / FromAbove permissions too): $Out" -ForegroundColor Green
