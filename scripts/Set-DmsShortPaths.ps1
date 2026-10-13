#Requires -Version 5.1
<#
.SYNOPSIS
    Keeps the paths users open short enough for Office, on the file server only: nothing is installed or
    changed on a user's PC.

.DESCRIPTION
    Office cannot open a file whose path, as a URL, is longer than about 218 characters, and a Hebrew letter
    counts 6 of them. Three things together keep every path under that limit:
      1. 8.3 name creation on the volume (new files get a short ASCII alias the DMS can use);
      2. a short name for the folders that already exist (fsutil file setshortname), Hebrew ones above all;
      3. a share of its own for 01_General and 02_Customers, so the path users open starts at \\server\General
         instead of \\server\Shares\01_General.
    It ends with the longest paths it found, so you can see what is still over the limit.
    Run it on the file server, as administrator. -WhatIf shows what it would do and changes nothing.

.EXAMPLE
    .\Set-DmsShortPaths.ps1 -Root E:\Shares -WhatIf
    .\Set-DmsShortPaths.ps1 -Root E:\Shares                    # the three steps, then the report
    .\Set-DmsShortPaths.ps1 -Root E:\Shares -Shares:$false     # without creating the extra shares
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)] [string] $Root,
    [string] $GeneralFolder = '01_General',
    [string] $CustomersFolder = '02_Customers',
    [string] $GeneralShare = 'General',
    [string] $CustomersShare = 'Customers',
    [bool] $Shares = $true,
    [int] $Limit = 200                      # the length the DMS itself treats as too long (DMS_... LONG_PATH)
)
$ErrorActionPreference = 'Stop'
$Root = $Root.TrimEnd('\')
if (-not (Test-Path -LiteralPath $Root)) { throw "Not found: $Root" }
$volume = (Split-Path -Qualifier $Root)

function UrlLength([string]$p) {
    # what Office counts: the path as a URL (a Hebrew letter is %D7%xx = 6 characters, a space %20 = 3)
    $u = $p -replace '\\', '/'                  # the comma of -replace must not be read as a second argument
    ([System.Uri]::EscapeDataString($u) -replace '%2F', '/').Length
}

# ---------------------------------------------------------------- 1. short names for new files
$state = (fsutil 8dot3name query $volume) -join ' '
if ($state -match 'DISABLED') {
    if ($PSCmdlet.ShouldProcess($volume, 'enable 8.3 name creation (new files only)')) {
        fsutil 8dot3name set $volume 0 | Out-Null
        Write-Host "8.3 names are now created on $volume (for files and folders made from now on)." -ForegroundColor Green
    }
} else {
    Write-Host "8.3 names are already created on $volume." -ForegroundColor Green
}

# ---------------------------------------------------------------- 2. short names for the folders already there
$made = 0; $had = 0; $failed = 0
foreach ($d in Get-ChildItem -LiteralPath $Root -Directory -Recurse -Force -ErrorAction SilentlyContinue) {
    $out = (fsutil file queryshortname "$($d.FullName)") -join ' '
    if ($out -notmatch 'Short Name\s*:\s*$' -and $out -match 'Short Name\s*:\s*\S') { $had++; continue }
    # a name that needs one: not plain ASCII, or longer than 8.3 can hold
    if ($d.Name -match '^[\x20-\x7E]{1,8}(\.[\x20-\x7E]{1,3})?$') { continue }
    $base = (($d.Name -replace '[^A-Za-z0-9]', '') + 'DMSFLDR').Substring(0, 5).ToUpper()
    for ($n = 1; $n -le 999; $n++) {
        $try = "$base~$n"
        if ($PSCmdlet.ShouldProcess($d.FullName, "short name $try")) {
            fsutil file setshortname "$($d.FullName)" $try 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $made++; break }
        } else { break }
        if ($n -eq 999) { $failed++ }
    }
}
Write-Host "Folders: $made short names added, $had had one already$(if ($failed) { ", $failed could not be set" })." -ForegroundColor Green

# ---------------------------------------------------------------- 3. a share of its own for the two big folders
if ($Shares) {
    foreach ($pair in @(@($GeneralShare, $GeneralFolder), @($CustomersShare, $CustomersFolder))) {
        $name, $folder = $pair
        $path = Join-Path $Root $folder
        if (-not (Test-Path -LiteralPath $path)) { continue }
        if (Get-SmbShare -Name $name -ErrorAction SilentlyContinue) {
            Write-Host "Share $name exists." -ForegroundColor Green
        } elseif ($PSCmdlet.ShouldProcess($path, "share as \\$env:COMPUTERNAME\$name")) {
            New-SmbShare -Name $name -Path $path -FullAccess 'Everyone' | Out-Null   # NTFS decides who sees what
            Write-Host "\\$env:COMPUTERNAME\$name -> $path" -ForegroundColor Green
        }
    }
    Write-Host "`nPut this line in webapi\.env (it is what users open and copy):" -ForegroundColor Cyan
    Write-Host "DMS_CLIENT_SHORT_PATHS=$GeneralFolder=\\$env:COMPUTERNAME\$GeneralShare;$CustomersFolder=\\$env:COMPUTERNAME\$CustomersShare" -ForegroundColor Yellow
    Write-Host "then: Restart-WebAppPool DMS-Pilot" -ForegroundColor Cyan
}

# ---------------------------------------------------------------- the report: what is still too long
$client = "\\$env:COMPUTERNAME\$GeneralShare"
$long = Get-ChildItem -LiteralPath $Root -File -Recurse -Force -ErrorAction SilentlyContinue |
    ForEach-Object {
        $rel = $_.FullName.Substring($Root.Length).TrimStart('\')
        $asUser = if ($Shares -and $rel -like "$GeneralFolder\*") { Join-Path $client $rel.Substring($GeneralFolder.Length + 1) } else { $_.FullName }
        [pscustomobject]@{ Length = UrlLength $asUser; Path = $asUser }
    } | Where-Object { $_.Length -gt $Limit } | Sort-Object Length -Descending
if ($long) {
    Write-Host "`nStill longer than $Limit characters as a URL ($(@($long).Count) files):" -ForegroundColor Yellow
    $long | Select-Object -First 15 | Format-Table Length, Path -AutoSize | Out-String -Width 220 | Write-Host
    Write-Host "Shorten a folder name on those paths, or let the DMS open them through itself." -ForegroundColor Yellow
} else {
    Write-Host "`nNo file is over $Limit characters: every file opens straight from the share." -ForegroundColor Green
}
