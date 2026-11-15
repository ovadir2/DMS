<#
.SYNOPSIS
    Give every customer the skeleton's permissions: the AD groups set on Customer_Skeleton, folder by
    folder, applied to the customers that already exist.

.DESCRIPTION
    A new customer is cut from `Customer_Skeleton` and carries its permissions with it. Customers made
    before the skeleton's groups were set do not - and setting them by hand, folder by folder, on twenty
    customers, is how a repository ends up with twenty different answers.

    This reads the skeleton as the one truth: for every folder of it, the rules that were set on that
    folder (the inherited ones belong to the parent and are left alone), and writes the same rules onto the
    same folder of each customer. Where a group is named after the skeleton - RH-DMS-Customer_Skeleton-RW -
    the customer's own group is used instead (RH-DMS-Elbit-RW) when AD has one; when it does not, the
    folder is left as it is and the missing group is named in the report, because a folder that quietly
    keeps the skeleton's group is worse than one that was not touched.

    Nothing is written without -Apply. Without it every line is what would be done.

.PARAMETER Customer
    One or more customers. Left out: every folder under the customers folder, except the skeleton itself.

.PARAMETER CreateMissing
    Also make the folders of the skeleton that a customer does not have yet.

.EXAMPLE
    .\scripts\Sync-DmsCustomerAccess.ps1
.EXAMPLE
    .\scripts\Sync-DmsCustomerAccess.ps1 -Customer Elbit -Apply
.EXAMPLE
    .\scripts\Sync-DmsCustomerAccess.ps1 -Apply -CreateMissing
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [string[]]$Customer = @(),
    [string]$Skeleton = 'Customer_Skeleton',
    [switch]$CreateMissing,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Root) { $Root = Get-DmsEnvValue 'DMS_REPOSITORY_ROOT' }
if (-not $Root) { throw "DMS_REPOSITORY_ROOT is not in webapi\.env - run this on the DMS server, or give -Root." }
$folder = Get-DmsEnvValue 'DMS_CUSTOMERS_FOLDER'
if (-not $folder) { $folder = '02_Customers' }
$customers = Join-Path $Root $folder
$shape = Join-Path $customers $Skeleton
if (-not (Test-Path -LiteralPath $shape)) { throw "The skeleton was not found: $shape" }

function Known($name) {
    # Is this an account AD knows? No RSAT needed: the name is translated to a SID, or it is not.
    try { ([Security.Principal.NTAccount]$name).Translate([Security.Principal.SecurityIdentifier]) | Out-Null; $true }
    catch { $false }
}

$mapped = @{}
function For-Customer($identity, $who) {
    # RH-DMS-Customer_Skeleton-RW on the skeleton is RH-DMS-<customer>-RW on a customer. A name that does
    # not carry the skeleton's is the same everywhere (Domain Admins, the DMS's own account) and is kept.
    if ($identity -notlike "*$Skeleton*") { return @{ name = $identity; ok = $true } }
    $want = $identity -replace [regex]::Escape($Skeleton), $who
    if (-not $mapped.ContainsKey($want)) { $mapped[$want] = Known $want }
    return @{ name = $want; ok = $mapped[$want] }
}

$names = if ($Customer.Count) { $Customer } else {
    Get-ChildItem -LiteralPath $customers -Directory | Where-Object { $_.Name -ne $Skeleton } |
        Select-Object -ExpandProperty Name
}
Write-Host ""
Write-Host "=== The skeleton's permissions -> $($names.Count) customer(s)" -ForegroundColor Cyan
Write-Host "    skeleton: $shape"
Write-Host "    mode    : $(if ($Apply) { 'writing' } else { 'showing what would be done (-Apply writes)' })"
Write-Host ""

$shapeFolders = @(Get-ChildItem -LiteralPath $shape -Recurse -Directory -ErrorAction SilentlyContinue)
$rows = @()
foreach ($who in $names) {
    $target = Join-Path $customers $who
    if (-not (Test-Path -LiteralPath $target)) {
        Write-Host "  [skip] $who is not a folder under $folder" -ForegroundColor DarkGray
        continue
    }
    $set = 0; $made = 0; $missingFolders = @(); $missingGroups = @()
    foreach ($src in @(Get-Item -LiteralPath $shape) + $shapeFolders) {
        $rel = $src.FullName.Substring($shape.Length).TrimStart('\')
        $dst = if ($rel) { Join-Path $target $rel } else { $target }
        if (-not (Test-Path -LiteralPath $dst)) {
            if (-not $CreateMissing) { $missingFolders += $rel; continue }
            if ($Apply) { New-Item -ItemType Directory -Path $dst -Force | Out-Null }
            $made++
        }
        $acl = Get-Acl -LiteralPath $src.FullName
        $own = @($acl.Access | Where-Object { -not $_.IsInherited })
        if (-not $own.Count) { continue }              # nothing of its own here: the parent decides
        $new = New-Object Security.AccessControl.DirectorySecurity
        $new.SetAccessRuleProtection($acl.AreAccessRulesProtected, $false)
        $skip = $false
        foreach ($rule in $own) {
            $to = For-Customer $rule.IdentityReference.Value $who
            if (-not $to.ok) { $missingGroups += $to.name; $skip = $true; continue }
            $new.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
                $to.name, $rule.FileSystemRights, $rule.InheritanceFlags, $rule.PropagationFlags, $rule.AccessControlType)))
        }
        if ($skip) { continue }                        # a folder is never left with half of its rules
        if ($Apply) { Set-Acl -LiteralPath $dst -AclObject $new }
        $set++
    }
    $missingGroups = @($missingGroups | Select-Object -Unique)
    $colour = if ($missingGroups.Count) { 'Yellow' } else { 'Green' }
    Write-Host ("  [{0}] {1,-22} {2} folder(s){3}{4}" -f $(if ($Apply) { 'ok' } else { '--' }), $who, $set,
                $(if ($made) { ", $made made" } else { '' }),
                $(if ($missingGroups.Count) { ", $($missingGroups.Count) group(s) AD does not have" } else { '' })) -ForegroundColor $colour
    foreach ($g in $missingGroups) { Write-Host "         no such group: $g" -ForegroundColor DarkGray }
    foreach ($f in @($missingFolders | Select-Object -First 5)) { Write-Host "         not there: $f" -ForegroundColor DarkGray }
    if ($missingFolders.Count -gt 5) { Write-Host "         ... and $($missingFolders.Count - 5) more (-CreateMissing makes them)" -ForegroundColor DarkGray }
    $rows += [pscustomobject]@{ Customer = $who; Folders = $set; Made = $made
                                MissingGroups = $missingGroups.Count; MissingFolders = $missingFolders.Count }
}
Write-Host ""
if (-not $Apply) { Write-Host "Nothing was changed. Add -Apply to write the permissions." -ForegroundColor Yellow }
$rows
