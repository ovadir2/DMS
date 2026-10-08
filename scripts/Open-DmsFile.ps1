#Requires -Version 5.1
<#
.SYNOPSIS
    The "rh-dms:" link handler on a user's PC (installed by Set-DmsDrives.ps1): opens a file from the DMS page
    exactly like a double-click in Explorer, so Word / Excel open it from its path (Protected View lets you edit).

.DESCRIPTION
    The DMS page uses rh-dms:<path> (rh-dms:ro/<path> to view only) when an ms-word: link cannot carry the path.
    Only Office files under this PC's DMS drives / repository root (HKCU\Software\RH\DMS) are opened.
#>
param([string] $Uri)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
function Fail([string] $m) { [System.Windows.Forms.MessageBox]::Show($m, 'RH DMS') | Out-Null; exit 1 }

$rest = $Uri -replace '^rh-dms:(//)?', ''
$ro = $rest -like 'ro/*'                          # rh-dms:ro/<path>: view only (an approved file in Current_ReadOnly)
if ($ro) { $rest = $rest.Substring(3) }
$path = [uri]::UnescapeDataString($rest).TrimEnd('/').Replace('/', '\')
$ext = [IO.Path]::GetExtension($path).ToLower()
if ($ext -notin '.doc', '.docx', '.docm', '.xls', '.xlsx', '.xlsm', '.ppt', '.pptx', '.pptm') { Fail "Not an Office file: $path" }

$keep = Get-ItemProperty -Path 'HKCU:\Software\RH\DMS' -ErrorAction SilentlyContinue
$allowed = @()
if ($keep) {
    foreach ($p in $keep.PSObject.Properties) {
        if ($p.Name -notlike 'PS*' -and "$($p.Value)") { $allowed += "$($p.Value)".TrimEnd('\') + '\' }
    }
}
$full = [IO.Path]::GetFullPath($path)
if (-not ($allowed | Where-Object { $full.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) })) {
    Fail "Not a DMS folder on this PC: $full"
}
if (-not (Test-Path -LiteralPath $full)) { Fail "File not found: $full" }
if (-not $ro) { Invoke-Item -LiteralPath $full; exit 0 }
try {
    Start-Process -FilePath $full -Verb OpenAsReadOnly -ErrorAction Stop       # Word / Excel / PowerPoint: Read-Only
} catch {
    # no "open read-only" for this file type: a read-only copy, so the approved file is never changed
    $copy = Join-Path $env:TEMP ("DMS view - " + [IO.Path]::GetFileName($full))
    if (Test-Path -LiteralPath $copy) { (Get-Item -LiteralPath $copy).IsReadOnly = $false }
    Copy-Item -LiteralPath $full -Destination $copy -Force
    (Get-Item -LiteralPath $copy).IsReadOnly = $true
    Invoke-Item -LiteralPath $copy
}
