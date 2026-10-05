#Requires -Version 5.1
<#
.SYNOPSIS
    Maps the DMS folders to drive letters on this PC: $Root\02_Customers and $Root\01_General,
    so the paths users open and copy from the DMS stay short and readable.

.DESCRIPTION
    A UNC root (\\server\share\...) is mapped with "net use" (persistent, back after every logon).
    A local root (C:\...) is mapped with "subst", and a small logon entry (HKCU Run) maps it again
    after every logon. Use the same letters on every PC and in the DMS .env:
        DMS_SHORT_PATHS=02_Customers=R:;01_General=G:
    For all users at once, IT can set the same drives with Group Policy (User Configuration >
    Preferences > Windows Settings > Drive Maps). -Remove takes the drives away.

.EXAMPLE
    .\Set-DmsDrives.ps1 -Root $Root

.EXAMPLE
    .\Set-DmsDrives.ps1 -Root $Root -CustomersDrive K -GeneralDrive L

.EXAMPLE
    .\Set-DmsDrives.ps1 -Root $Root -Remove
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Root,
    [ValidatePattern('^[D-Zd-z]$')] [string] $CustomersDrive = 'R',
    [ValidatePattern('^[D-Zd-z]$')] [string] $GeneralDrive = 'G',
    [string] $CustomersFolder = '02_Customers',
    [string] $GeneralFolder = '01_General',
    [switch] $Remove
)
$ErrorActionPreference = 'Stop'
$Root = $Root.TrimEnd('\')
$maps = [ordered]@{ "$($CustomersDrive.ToUpper()):" = Join-Path $Root $CustomersFolder
                    "$($GeneralDrive.ToUpper()):"   = Join-Path $Root $GeneralFolder }
$run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'

foreach ($drive in $maps.Keys) {
    $target = $maps[$drive]
    $name = "DMS drive $drive"
    # what is on this letter now: a subst, a network drive, or nothing
    $subst = (subst) | Where-Object { $_ -like "$drive\*" }
    $net = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$drive'" -ErrorAction SilentlyContinue
    if ($subst) { subst $drive /D | Out-Null }
    elseif ($net -and $net.DriveType -eq 4) { net use $drive /delete /y | Out-Null }
    elseif ($net -and -not $Remove) { throw "$drive is already used on this PC ($($net.VolumeName)). Choose another letter." }
    Remove-ItemProperty -Path $run -Name $name -ErrorAction SilentlyContinue
    if ($Remove) { Write-Host "$drive removed"; continue }

    if (-not (Test-Path -LiteralPath $target)) { throw "Folder not found: $target" }
    if ($target.StartsWith('\\')) {
        net use $drive "$target" /persistent:yes | Out-Null
        if ($LASTEXITCODE) { throw "net use $drive $target failed ($LASTEXITCODE)" }
    } else {
        subst $drive "$target"
        if ($LASTEXITCODE) { throw "subst $drive $target failed ($LASTEXITCODE)" }
        Set-ItemProperty -Path $run -Name $name -Value "subst $drive `"$target`""   # again after every logon
    }
    Write-Host "$drive -> $target" -ForegroundColor Green
}
if (-not $Remove) {
    $line = "DMS_SHORT_PATHS=$CustomersFolder=$($CustomersDrive.ToUpper()):;$GeneralFolder=$($GeneralDrive.ToUpper()):"
    Write-Host "`nIn the DMS .env (C:\dms\webapi\.env), then restart the DMS:`n  $line" -ForegroundColor Cyan
}
