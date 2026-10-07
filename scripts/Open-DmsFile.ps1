#Requires -Version 5.1
<#
.SYNOPSIS
    The "rh-dms:" link handler on a user's PC (installed by Set-DmsDrives.ps1): opens a file from the DMS page
    exactly like a double-click in Explorer, so Word / Excel open it from its path (Protected View lets you edit).

.DESCRIPTION
    The DMS page uses rh-dms:<path> when a path with Hebrew names is too long for an ms-word: link.
    Only Office files under this PC's DMS drives / repository root (HKCU\Software\RH\DMS) are opened.
#>
param([string] $Uri)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
function Fail([string] $m) { [System.Windows.Forms.MessageBox]::Show($m, 'RH DMS') | Out-Null; exit 1 }

$path = [uri]::UnescapeDataString(($Uri -replace '^rh-dms:(//)?', '')).TrimEnd('/').Replace('/', '\')
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
Invoke-Item -LiteralPath $full
