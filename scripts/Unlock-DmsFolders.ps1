#Requires -Version 5.1
<#
.SYNOPSIS
    Finds and removes what locks the blueprint folders on the file server, so files there can be opened
    for editing (Word "read only") before they are registered.

.DESCRIPTION
    Under 01_General and 02_Customers (not 03/04/05, not the DMS workflow folders Submitted /
    Current_ReadOnly / Obsolete_ReadOnly, whose files stay read only):
      - files with the Read-only attribute
      - folders that do not inherit permissions (protected ACL) or hold Deny rules
      - whether -Group may write (Modify) at 01_General and 02_Customers
    Without -Apply it only reports. With -Apply:
      - clears the Read-only attribute of those files
      - gives -Group Modify (inherited by everything below) on 01_General and 02_Customers, and on every
        folder that does not inherit
    The DMS page itself never offers Rename / Delete on blueprint folders (only on their content).
    -ProtectBlueprint also stops it in Explorer: Deny "Delete" on each blueprint folder itself (not its content).

    Run as a user who may change permissions on the share (IT / file server admin). Supports -WhatIf.

.EXAMPLE
    .\Unlock-DmsFolders.ps1                                    # report only (root from webapi\.env)
    .\Unlock-DmsFolders.ps1 -Apply -WhatIf                     # what would change
    .\Unlock-DmsFolders.ps1 -Apply -Group 'RH\GG_DMS_Employees' -ProtectBlueprint
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $Root,
    [string] $Group = "$env:USERDOMAIN\Domain Users",
    [switch] $Apply,
    [switch] $ProtectBlueprint
)
$ErrorActionPreference = 'Stop'

if (-not $Root) {
    $envFile = Join-Path $PSScriptRoot '..\webapi\.env'
    if (Test-Path -LiteralPath $envFile) {
        $line = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^\s*DMS_REPOSITORY_ROOT\s*=' } | Select-Object -First 1
        if ($line) { $Root = ($line -split '=', 2)[1].Split('#')[0].Trim().Trim('"') }
    }
}
if (-not $Root -or -not (Test-Path -LiteralPath $Root)) { throw "Give -Root (the DMS repository root), not found: '$Root'" }

$Workflow = @('Submitted', 'Current_ReadOnly', 'Obsolete_ReadOnly')
$Tops = @('01_General', '02_Customers') | ForEach-Object { Join-Path $Root $_ } | Where-Object { Test-Path -LiteralPath $_ }
$Modify = [Security.AccessControl.FileSystemRights]'Modify, Synchronize'
$Inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
$NoProp = [Security.AccessControl.PropagationFlags]::None

function In-Workflow([string]$Path) {
    foreach ($w in $Workflow) { if ($Path -match "[\\/]$([regex]::Escape($w))([\\/]|$)") { return $true } }
    $false
}

function Grant-Modify([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($Group, $Modify, $Inherit, $NoProp, 'Allow')))
    if ($PSCmdlet.ShouldProcess($Path, "Allow Modify for $Group")) { Set-Acl -LiteralPath $Path -AclObject $acl; Write-Host "  + Modify $Group  $Path" -ForegroundColor Green }
}

function Can-Write([string]$Path) {
    foreach ($r in (Get-Acl -LiteralPath $Path).Access) {
        if ($r.AccessControlType -eq 'Allow' -and $r.IdentityReference.Value -eq $Group -and
            ($r.FileSystemRights -band [Security.AccessControl.FileSystemRights]::Write) -eq [Security.AccessControl.FileSystemRights]::Write) { return $true }
    }
    $false
}

Write-Host "Repository: $Root   Group: $Group" -ForegroundColor Cyan
$folders = @($Tops) + @($Tops | ForEach-Object { Get-ChildItem -LiteralPath $_ -Directory -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object FullName }) |
           Where-Object { -not (In-Workflow $_) }
$protected = @(); $denies = @()
foreach ($f in $folders) {
    try { $acl = Get-Acl -LiteralPath $f } catch { Write-Warning "Cannot read the permissions of $f ($($_.Exception.Message))"; continue }
    if ($acl.AreAccessRulesProtected) { $protected += $f }
    if ($acl.Access | Where-Object { $_.AccessControlType -eq 'Deny' -and -not $_.IsInherited -and
                                     -not ($_.FileSystemRights -eq 'Delete' -and $_.IdentityReference.Value -eq $Group) }) { $denies += $f }   # not -ProtectBlueprint's
}
$readOnly = @($Tops | ForEach-Object { Get-ChildItem -LiteralPath $_ -File -Recurse -Force -ErrorAction SilentlyContinue } |
              Where-Object { $_.IsReadOnly -and -not (In-Workflow $_.FullName) })

Write-Host ""
foreach ($t in $Tops) { Write-Host ("{0,-60} {1} may write: {2}" -f $t, $Group, $(if (Can-Write $t) { 'yes' } else { 'NO' })) }
Write-Host "Folders that do not inherit permissions: $($protected.Count)"; $protected | Select-Object -First 20 | ForEach-Object { Write-Host "    $_" }
Write-Host "Folders with Deny rules: $($denies.Count)"; $denies | Select-Object -First 20 | ForEach-Object { Write-Host "    $_" }
Write-Host "Read-only files outside the workflow folders: $($readOnly.Count)"; $readOnly | Select-Object -First 20 | ForEach-Object { Write-Host "    $($_.FullName)" }

if (-not $Apply) { Write-Host "`nReport only. Run again with -Apply (and -WhatIf first) to unlock." -ForegroundColor Yellow; return }

Write-Host "`nUnlocking" -ForegroundColor Cyan
foreach ($t in $Tops) { if (-not (Can-Write $t)) { Grant-Modify $t } }
foreach ($f in $protected) { if (-not (Can-Write $f)) { Grant-Modify $f } }
foreach ($file in $readOnly) {
    if ($PSCmdlet.ShouldProcess($file.FullName, 'Clear the Read-only attribute')) { $file.IsReadOnly = $false }
}
Write-Host "  Read-only cleared on $($readOnly.Count) files" -ForegroundColor Green
if ($denies.Count) { Write-Warning "Deny rules were kept (check them by hand, a Deny wins over Allow): $($denies -join '; ')" }

if ($ProtectBlueprint) {
    # The blueprint folders (scripts\blueprint-folders.txt; <Customer> = every customer folder): Deny Delete on the
    # folder itself only, so it cannot be renamed or deleted in Explorer either. Its content stays editable.
    $bpFile = Join-Path $PSScriptRoot 'blueprint-folders.txt'
    $customers = @(Get-ChildItem -LiteralPath (Join-Path $Root '02_Customers') -Directory -ErrorAction SilentlyContinue | ForEach-Object Name)
    $paths = @('01_General', '02_Customers') + @($customers | ForEach-Object { "02_Customers\$_" })
    foreach ($l in Get-Content -LiteralPath $bpFile -Encoding UTF8 | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notlike '*<Product>*' }) {
        if ($l -like '*<Customer>*') { foreach ($c in $customers) { $paths += $l.Replace('<Customer>', $c) } } else { $paths += $l }
    }
    foreach ($p in $paths | Select-Object -Unique) {
        $full = Join-Path $Root $p
        if (-not (Test-Path -LiteralPath $full)) { continue }
        $acl = Get-Acl -LiteralPath $full
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($Group, 'Delete', 'None', 'None', 'Deny')))
        if ($PSCmdlet.ShouldProcess($full, "Deny Delete (this folder only) for $Group")) { Set-Acl -LiteralPath $full -AclObject $acl }
    }
    Write-Host "  Blueprint folders protected against rename / delete: $(@($paths | Select-Object -Unique).Count)" -ForegroundColor Green
}
Write-Host "`nDone. Open a file from the DMS page again (Word should open it for editing)." -ForegroundColor Green
