<#
.SYNOPSIS
    Renames the installation folder (C:\DMS-Pilot -> C:\DMS) and points everything that names it at the
    new place: IIS, web.config, the scheduled tasks.

.DESCRIPTION
    The folder is the last thing that still says "pilot" once the site, the pool and the SharePoint sites
    have been renamed - and it is what VS Code shows at the top of the window. Moving it by hand means
    remembering IIS's physical path and the absolute paths inside web.config; this does both, and says what
    it could not do.

    It stops the site while it works and starts it again afterwards. Run it from a PowerShell that is NOT
    standing inside the folder (it will move to C:\ itself), and with the folder closed in VS Code - a file
    held open stops a rename.

    By default it only says what it would do. -Write does it.

.EXAMPLE
    .\scripts\Move-DmsFolder.ps1
.EXAMPLE
    .\scripts\Move-DmsFolder.ps1 -To C:\DMS -Write
#>
[CmdletBinding()]
param(
    [string]$From = '',
    [string]$To = 'C:\DMS',
    [string]$Site = '',
    [switch]$Write
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $From) { $From = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }   # ...\DMS-Pilot\app\scripts
if (-not $Site) { $Site = Get-DmsDefault Site }
$From = $From.TrimEnd('\'); $To = $To.TrimEnd('\')
if ($From -eq $To) { Write-Host "Already there: $From"; return }
if (Test-Path $To) { throw "$To exists already: give another -To, or move it out of the way." }

Import-Module WebAdministration -ErrorAction Stop
$pool = "$((Get-Website -Name $Site).applicationPool)"
$physical = "$((Get-Website -Name $Site).physicalPath)"
$web = Join-Path $From 'app\webapi\web.config'
if (-not (Test-Path $web)) { $web = Join-Path $From 'webapi\web.config' }

Write-Host "`n== What names $From"
Write-Host "   IIS site '$Site' (pool '$pool') physical path: $physical"
$inWeb = @()
if (Test-Path $web) {
    $inWeb = @(Select-String -Path $web -SimpleMatch $From -ErrorAction SilentlyContinue)
    Write-Host "   $web : $($inWeb.Count) line(s) name it"
} else { Write-Host "   (no web.config found under $From)" -ForegroundColor Yellow }
$tasks = @()
try {
    $tasks = @(Get-ScheduledTask | Where-Object {
        ($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments) $($_.WorkingDirectory)" }) -match [regex]::Escape($From)
    })
} catch { }
foreach ($t in $tasks) { Write-Host "   scheduled task: $($t.TaskName)" }

if (-not $Write) {
    Write-Host "`nWould: stop '$Site', rename $From -> $To, repoint IIS and web.config, start it again."
    Write-Host "Nothing was changed. Add -Write to do it." -ForegroundColor Yellow
    return
}

Write-Host "`n== Moving"
Stop-Website -Name $Site -ErrorAction SilentlyContinue
Stop-WebAppPool -Name $pool -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3                                   # let the uvicorn child go with its pool
Set-Location $env:SystemDrive\                            # never rename the folder you are standing in
try {
    Rename-Item -LiteralPath $From -NewName (Split-Path -Leaf $To) -ErrorAction Stop
    Write-Host "   $From -> $To" -ForegroundColor Green
} catch {
    Start-WebAppPool -Name $pool -ErrorAction SilentlyContinue
    Start-Website -Name $Site -ErrorAction SilentlyContinue
    throw "The folder could not be renamed ($($_.Exception.Message)). Close it in VS Code and in every " +
          "Explorer window, then run this again - the site has been started again."
}

$newPhysical = $physical -replace [regex]::Escape($From), $To
Set-ItemProperty "IIS:\Sites\$Site" -Name physicalPath -Value $newPhysical
Write-Host "   IIS physical path: $newPhysical" -ForegroundColor Green
foreach ($app in (Get-WebApplication -Site $Site)) {
    if ("$($app.PhysicalPath)" -like "$From*") {
        Set-ItemProperty "IIS:\Sites\$Site$($app.Path)" -Name physicalPath -Value ("$($app.PhysicalPath)" -replace [regex]::Escape($From), $To)
        Write-Host "   application $($app.Path) repointed" -ForegroundColor Green
    }
}

$newWeb = $web -replace [regex]::Escape($From), $To
if (Test-Path $newWeb) {
    (Get-Content $newWeb -Raw) -replace [regex]::Escape($From), $To | Set-Content $newWeb -Encoding UTF8
    Write-Host "   $newWeb rewritten" -ForegroundColor Green
}

Start-WebAppPool -Name $pool
Start-Website -Name $Site
Write-Host "`n== Afterwards"
if ($tasks.Count) {
    Write-Host "   These scheduled tasks still name the old folder - change them by hand:" -ForegroundColor Yellow
    foreach ($t in $tasks) { Write-Host "     $($t.TaskName)" }
}
Write-Host "   Open the new folder in VS Code: $To"
Write-Host "   Then: cd $To\app ; .\scripts\Restart-Dms.ps1 ; .\scripts\Test-DmsProductionReady.ps1"
