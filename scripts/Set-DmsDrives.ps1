#Requires -Version 5.1
<#
.SYNOPSIS
    Maps the DMS folders to drive letters on this PC: $Root\02_Customers and $Root\01_General,
    so the paths users open and copy from the DMS stay short and readable.

.DESCRIPTION
    A UNC root (\\server\share\...) is mapped with "net use" (persistent, back after every logon).
    A local root (C:\...) is mapped with "subst", and a small logon entry (HKCU Run) maps it again
    after every logon. The preferred letters are R: and G:; when a letter is busy on this PC, the next
    free one (from Z: down) is used. With -DmsUrl the DMS page is opened once with this PC's letters
    (?drives=...), and the page remembers them: Open and Copy link then use this PC's drives.
    The letters chosen are kept in HKCU\Software\RH\DMS (a second run keeps them). -Remove takes them away.

.EXAMPLE
    .\Set-DmsDrives.ps1 -Root $Root -DmsUrl http://localhost:8080

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
    [string] $DmsUrl,
    [switch] $Remove
)
$ErrorActionPreference = 'Stop'
$Root = $Root.TrimEnd('\')
$run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$keep = 'HKCU:\Software\RH\DMS'
$wanted = [ordered]@{ $CustomersFolder = $CustomersDrive.ToUpper(); $GeneralFolder = $GeneralDrive.ToUpper() }

function Get-Mapped([string] $drive) {
    # what is on this letter now: @{Kind='subst'|'net'|'disk'; Target=...} or $null
    $s = (subst) | Where-Object { $_ -like "$drive\*" }
    if ($s) { return @{ Kind = 'subst'; Target = ($s -split '=>\s*', 2)[1].Trim() } }
    $d = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$drive'" -ErrorAction SilentlyContinue
    if ($d -and $d.DriveType -eq 4) { return @{ Kind = 'net'; Target = $d.ProviderName } }
    if ($d -or (Test-Path "$drive\")) { return @{ Kind = 'disk'; Target = '' } }
    return $null
}
function Remove-Mapped([string] $drive, $m) {
    if ($m.Kind -eq 'subst') { subst $drive /D | Out-Null } elseif ($m.Kind -eq 'net') { net use $drive /delete /y | Out-Null }
    Remove-ItemProperty -Path $run -Name "DMS drive $drive" -ErrorAction SilentlyContinue
}

$used = @{}
$result = [ordered]@{}
foreach ($folder in $wanted.Keys) {
    $target = Join-Path $Root $folder
    $before = (Get-ItemProperty -Path $keep -Name $folder -ErrorAction SilentlyContinue).$folder   # letter of an earlier run
    if ($before) { $m = Get-Mapped $before; if ($m -and $m.Kind -ne 'disk' -and $m.Target -eq $target) { Remove-Mapped $before $m } }
    if ($Remove) { Remove-ItemProperty -Path $keep -Name $folder -ErrorAction SilentlyContinue; if ($before) { Write-Host "$before removed" }; continue }
    if (-not (Test-Path -LiteralPath $target)) { Write-Warning "Folder not found, no drive for it: $target"; continue }

    # the letter: the earlier one, else the preferred one, else the next free one from Z: down
    $letters = @(@($before, $wanted[$folder]) | Where-Object { $_ }) + @([char[]](90..68) | ForEach-Object { "$_" })
    $drive = $null
    foreach ($l in $letters) { $d = "$($l.TrimEnd(':')):"; if (-not $used[$d] -and -not (Get-Mapped $d)) { $drive = $d; break } }
    if (-not $drive) { throw "No free drive letter on this PC for $target" }
    $used[$drive] = $true

    if ($target.StartsWith('\\')) {
        net use $drive "$target" /persistent:yes | Out-Null
        if ($LASTEXITCODE) { throw "net use $drive $target failed ($LASTEXITCODE)" }
    } else {
        subst $drive "$target"
        if ($LASTEXITCODE) { throw "subst $drive $target failed ($LASTEXITCODE)" }
        Set-ItemProperty -Path $run -Name "DMS drive $drive" -Value "subst $drive `"$target`""   # again after every logon
    }
    if (-not (Test-Path $keep)) { New-Item -Path $keep -Force | Out-Null }
    Set-ItemProperty -Path $keep -Name $folder -Value $drive
    $result[$folder] = $drive
    Write-Host "$drive -> $target$(if ($drive -ne "$($wanted[$folder]):") { "  ($($wanted[$folder]): is busy on this PC)" })" -ForegroundColor Green
}
if (-not $Remove) {
    $drives = ($result.Keys | ForEach-Object { "$_=$($result[$_])" }) -join ';'
    if ($DmsUrl) {
        Start-Process ("$($DmsUrl.TrimEnd('/'))/dms/dms-page?drives=" + [uri]::EscapeDataString($drives))   # the page remembers this PC's letters
        Write-Host "`nThe DMS page was opened with this PC's drives ($drives)." -ForegroundColor Cyan
    } else {
        Write-Host "`nThis PC's drives: $drives. Run again with -DmsUrl <DMS address> so the page uses them." -ForegroundColor Cyan
    }
}
