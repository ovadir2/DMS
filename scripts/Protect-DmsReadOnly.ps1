<#
.SYNOPSIS
  A released document can be read by whoever could read it before, and changed by nobody but the DMS.

.DESCRIPTION
  The DMS refuses to open an approved document for editing, and marks its file read only. Neither stops
  somebody who reaches the file server directly and may write in the folder: the read-only attribute comes
  off with one click. This closes that, on the file server itself.

  In every Current_ReadOnly and Obsolete_ReadOnly folder under the repository it keeps the permissions the
  folder already had - the AD groups that may see those documents, exactly as they are - and only takes the
  writing away from them: each of them is left with Read and Execute. The DMS account keeps Modify, SYSTEM
  and the administrators keep Full. Nobody is given access who did not have it, and nobody loses sight of a
  document they could see: an HR folder stays as closed as it was.

  The read-only attribute is put back on every file in those folders as well.

.EXAMPLE
  .\Protect-DmsReadOnly.ps1 -Root E:\Shares -DmsAccount RH\dms_approval -WhatIf
  Shows the folders and, for each, who is left with what. Changes nothing.

.EXAMPLE
  .\Protect-DmsReadOnly.ps1 -Root E:\Shares -DmsAccount RH\dms_approval
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$DmsAccount,              # the account the DMS runs under, e.g. RH\dms_approval
    [string[]]$Folders = @('Current_ReadOnly', 'Obsolete_ReadOnly')
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Root)) { throw "The repository root $Root was not found" }

# These keep what they have; everybody else is left with Read and Execute
$keep = @($DmsAccount, 'NT AUTHORITY\SYSTEM', 'BUILTIN\Administrators')
$read = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
$both = @([System.Security.AccessControl.InheritanceFlags]::ContainerInherit,
          [System.Security.AccessControl.InheritanceFlags]::ObjectInherit)

$targets = foreach ($name in $Folders) {
    Get-ChildItem -LiteralPath $Root -Directory -Recurse -Filter $name -ErrorAction SilentlyContinue
}
if (-not $targets) { Write-Warning "No $($Folders -join ' / ') folder was found under $Root"; return }

Write-Host "$($targets.Count) folders under $Root" -ForegroundColor Cyan
$changed = 0
foreach ($folder in $targets) {
    $path = $folder.FullName
    $acl = Get-Acl -LiteralPath $path
    $acl.SetAccessRuleProtection($true, $true)        # stop inheriting, but keep a copy of what was inherited
    $who = @()
    foreach ($rule in @($acl.Access)) {
        $name = $rule.IdentityReference.Value
        if ($keep -contains $name) { continue }
        if ($rule.AccessControlType -ne 'Allow') { continue }        # a Deny stays exactly as it is
        $null = $acl.RemoveAccessRule($rule)
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $name, $read, $both, 'None', 'Allow')))
        $who += $name
    }
    $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        $DmsAccount, 'Modify', $both, 'None', 'Allow')))
    Write-Verbose "$path : read only for $($who -join ', ')"
    if ($PSCmdlet.ShouldProcess($path, "read only for $($who -join ', '); $DmsAccount keeps Modify")) {
        Set-Acl -LiteralPath $path -AclObject $acl
        Get-ChildItem -LiteralPath $path -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { -not $_.IsReadOnly } |
            ForEach-Object { $_.IsReadOnly = $true }
        $changed++
    }
}
Write-Host "Done: $changed folders" -ForegroundColor Green
Write-Host "Whoever could see these documents still can; only the DMS can change them." -ForegroundColor Green
