<#
.SYNOPSIS
  A released document cannot be changed by anybody but the DMS.

.DESCRIPTION
  The DMS refuses to open an approved document for editing, and marks its file read only. Neither stops
  somebody who reaches the file server directly and has write permission on the folder: the read-only
  attribute comes off with one click. This script closes that, on the file server itself.

  In every Current_ReadOnly and Obsolete_ReadOnly folder under the repository it stops inheriting
  permissions and grants:
      the DMS account      Modify   (it is the only one that writes there)
      SYSTEM, Administrators  Full  (backup, restore, IT)
      everyone else        Read     (whoever the folder above already lets in - visibility does not change)
  and it puts the read-only attribute back on every file in them.

  Who may SEE a document does not change: that is still decided by the folders above, through AD.

.EXAMPLE
  .\Protect-DmsReadOnly.ps1 -Root E:\Shares -DmsAccount RH\dms_approval -WhatIf
  Shows what it would change, and changes nothing.

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

$targets = foreach ($name in $Folders) {
    Get-ChildItem -LiteralPath $Root -Directory -Recurse -Filter $name -ErrorAction SilentlyContinue
}
if (-not $targets) { Write-Warning "No $($Folders -join ' / ') folder was found under $Root"; return }

Write-Host "$($targets.Count) folders under $Root" -ForegroundColor Cyan
$changed = 0
foreach ($folder in $targets) {
    $path = $folder.FullName
    if ($PSCmdlet.ShouldProcess($path, 'read only for everyone but the DMS')) {
        # /inheritance:r drops what the folder above gave, /grant:r replaces whatever that account had
        $out = & icacls $path /inheritance:r `
            /grant:r "$($DmsAccount):(OI)(CI)(M)" `
            "*S-1-5-18:(OI)(CI)(F)" `
            "*S-1-5-32-544:(OI)(CI)(F)" `
            "*S-1-5-11:(OI)(CI)(RX)" 2>&1
        if ($LASTEXITCODE) { Write-Warning "$path : $out"; continue }
        Get-ChildItem -LiteralPath $path -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { -not $_.IsReadOnly } |
            ForEach-Object { $_.IsReadOnly = $true; Write-Verbose "read only: $($_.FullName)" }
        $changed++
    }
}
Write-Host "Done: $changed folders" -ForegroundColor Green
Write-Host "A released document is now read only on the file server too, not only in the DMS." -ForegroundColor Green
