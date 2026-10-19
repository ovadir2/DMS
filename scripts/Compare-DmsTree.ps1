<#
.SYNOPSIS
  What the DMS shows against what is on the file server, folder by folder.

.DESCRIPTION
  The DMS browses the repository through the file server, with the rights of whoever is signed in, and it
  leaves some things out on purpose: Office lock files (~$...), Windows system files, hidden and system items,
  the Markdown it writes beside a released document, and anything the person's AD groups do not open. Anything
  else that differs is worth looking at, and this is how to see it.

  It walks the DMS (its browse API, as the account running this script) and the same folders on disk, and
  prints what only one of them has. A line is one of:
      DMS only        the DMS shows it and it is not on disk - a record or a listing out of date
      server only     it is on disk and the DMS does not show it - a rule above, or a right the person lacks

.EXAMPLE
  .\Compare-DmsTree.ps1 -DmsUrl https://dms-pilot.rh.tech -Path "01_General\Quality and Standards"

.EXAMPLE
  .\Compare-DmsTree.ps1 -DmsUrl https://dms-pilot.rh.tech -Path "02_Customers\Customer_A" -Root E:\Shares -All
  Also lists what the DMS leaves out on purpose, so nothing is taken on trust.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DmsUrl,
    [Parameter(Mandatory = $true)][string]$Path,              # under the repository root, e.g. 02_Customers\Customer_A
    [string]$Root,                                            # the repository root on disk; read from the DMS if not given
    [switch]$All,                                             # also show what the DMS leaves out on purpose
    [int]$Depth = 20
)

$ErrorActionPreference = 'Stop'
$base = $DmsUrl.TrimEnd('/')

function Get-Dms([string]$url) {
    # Windows PowerShell reads a JSON answer as Latin-1 unless it says charset=utf-8, and then every Hebrew
    # name differs from the one on disk by its spelling alone. The bytes are decoded here instead.
    $r = Invoke-WebRequest -Uri $url -UseDefaultCredentials -Headers @{ Accept = 'application/json' } -UseBasicParsing
    [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()) | ConvertFrom-Json
}

if (-not $Root) {
    try { $Root = (Get-Dms "$base/api/options").root } catch { }
    if (-not $Root) {        # the DMS did not say: read it where it is configured, on this server
        $env = Join-Path $PSScriptRoot '..\webapi\.env'
        if (Test-Path -LiteralPath $env) {
            $line = Select-String -Path $env -Pattern '^\s*DMS_REPOSITORY_ROOT\s*=' | Select-Object -First 1
            if ($line) { $Root = ($line.Line -split '=', 2)[1].Trim().Trim('"') }
        }
    }
    if (-not $Root) {
        throw "The repository root could not be read from the DMS or from webapi\.env. Pass it: -Root E:\Shares"
    }
    Write-Host "Repository root: $Root" -ForegroundColor Cyan
}

# What the DMS leaves out on purpose - not a difference, unless -All asks to see it
function Is-OnPurpose([System.IO.FileSystemInfo]$item) {
    if ($item.Name -like '~$*' -or $item.Name -like '.*') { return $true }
    if ($item.Name -in @('Thumbs.db', 'desktop.ini', 'ehthumbs.db', '.DS_Store')) { return $true }
    if ($item.Attributes -band [IO.FileAttributes]::Hidden) { return $true }
    if ($item.Attributes -band [IO.FileAttributes]::System) { return $true }
    if ($item.Extension -eq '.md' -and -not $item.PSIsContainer) {        # the Markdown of a document beside it
        $stem = [IO.Path]::GetFileNameWithoutExtension($item.Name)
        if (Get-ChildItem -LiteralPath $item.DirectoryName -File -Filter "$stem.*" |
                Where-Object { $_.Extension -ne '.md' }) { return $true }
    }
    return $false
}

$differences = 0

function Compare-Folder([string]$relative, [int]$left) {
    $onDisk = Join-Path $Root $relative
    $url = "$base/api/browse?path=" + [uri]::EscapeDataString($relative)
    try { $shown = Get-Dms $url } catch {
        Write-Host "DMS refused $relative : $($_.Exception.Message)" -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path -LiteralPath $onDisk)) {
        Write-Host "DMS only   (folder) $relative" -ForegroundColor Red
        $script:differences++
        return
    }
    $here = Get-ChildItem -LiteralPath $onDisk -Force -ErrorAction SilentlyContinue

    $dmsFiles = @($shown.files   | ForEach-Object { $_.name })
    $dmsDirs  = @($shown.folders | ForEach-Object { $_.name })
    $diskFiles = @($here | Where-Object { -not $_.PSIsContainer -and ($All -or -not (Is-OnPurpose $_)) } | ForEach-Object { $_.Name })
    $diskDirs  = @($here | Where-Object {      $_.PSIsContainer -and ($All -or -not (Is-OnPurpose $_)) } | ForEach-Object { $_.Name })

    foreach ($name in $dmsFiles  | Where-Object { $_ -notin $diskFiles }) {
        Write-Host "DMS only    $relative\$name" -ForegroundColor Red; $script:differences++ }
    foreach ($name in $diskFiles | Where-Object { $_ -notin $dmsFiles }) {
        Write-Host "server only $relative\$name" -ForegroundColor Yellow; $script:differences++ }
    foreach ($name in $dmsDirs   | Where-Object { $_ -notin $diskDirs }) {
        Write-Host "DMS only   (folder) $relative\$name" -ForegroundColor Red; $script:differences++ }
    foreach ($name in $diskDirs  | Where-Object { $_ -notin $dmsDirs }) {
        Write-Host "server only (folder) $relative\$name" -ForegroundColor Yellow; $script:differences++ }

    if ($left -gt 0) {
        foreach ($name in $dmsDirs | Where-Object { $_ -in $diskDirs }) {
            Compare-Folder (Join-Path $relative $name) ($left - 1)
        }
    }
}

Write-Host "Comparing $Path" -ForegroundColor Cyan
Compare-Folder $Path.Trim('\') $Depth
if ($differences -eq 0) {
    Write-Host "No difference: the DMS shows exactly what is on the file server." -ForegroundColor Green
} else {
    Write-Host "$differences differences. 'server only' is usually a right this account does not have, or a rule above; 'DMS only' is worth a closer look." -ForegroundColor Cyan
}
