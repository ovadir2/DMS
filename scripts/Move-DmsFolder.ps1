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

.PARAMETER Copy
    When the folder cannot be renamed because something holds it, copy it to the new place instead
    (robocopy /MIR) and leave the old one to be deleted later. The DMS runs from the new folder either way.

.EXAMPLE
    .\scripts\Move-DmsFolder.ps1
.EXAMPLE
    .\scripts\Move-DmsFolder.ps1 -To C:\DMS -Write
.EXAMPLE
    .\scripts\Move-DmsFolder.ps1 -To C:\DMS -Copy -Write
#>
[CmdletBinding()]
param(
    [string]$From = '',
    [string]$To = 'C:\DMS',
    [string]$Site = '',
    [switch]$Copy,
    [switch]$Write
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
          ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this in a PowerShell started as administrator: renaming a folder at the root of a drive " +
          "needs it, and so does changing IIS."
}
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
if ("$physical" -notlike "$From*") {
    Write-Host "   that path is not inside $From - IIS already points somewhere else" -ForegroundColor Yellow
    if (-not (Test-Path $physical)) {
        Write-Host "   ...and nothing is there: the DMS cannot be serving from it" -ForegroundColor Red
    }
}
$inWeb = @()
if (Test-Path $web) {
    $inWeb = @(Select-String -Path $web -SimpleMatch $From -ErrorAction SilentlyContinue)
    Write-Host "   $web : $($inWeb.Count) line(s) name it"
} else { Write-Host "   (no web.config found under $From)" -ForegroundColor Yellow }
# Windows refuses to rename a folder that is shared - and it says "access denied", which reads like a
# permission problem rather than what it is. The shares are taken down and put back at the new path.
$shares = @()
try {
    $shares = @(Get-SmbShare -ErrorAction Stop | Where-Object {
        $_.Path -and ($_.Path.TrimEnd('\') -eq $From -or $_.Path -like "$From\*")
    })
} catch { }
foreach ($sh in $shares) { Write-Host "   share \\$env:COMPUTERNAME\$($sh.Name) -> $($sh.Path)" }
$open = @()
try { $open = @(Get-SmbOpenFile -ErrorAction Stop | Where-Object { $_.Path -like "$From*" }) } catch { }
foreach ($f in $open) { Write-Host "   open over the network: $($f.Path) ($($f.ClientUserName))" -ForegroundColor Yellow }
if ($open.Count) {
    Write-Host ("   (these are handles over a share - C`$ counts, so a mapped drive or an Explorer window " +
                "on another PC is one. They are closed before the rename.)") -ForegroundColor DarkGray
}

$tasks = @()
try {
    $tasks = @(Get-ScheduledTask | Where-Object {
        ($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments) $($_.WorkingDirectory)" }) -match [regex]::Escape($From)
    })
} catch { }
foreach ($t in $tasks) { Write-Host "   scheduled task: $($t.TaskName)" }

if (-not $Write) {
    Write-Host ("`nWould: stop '$Site', take down the share(s), rename $From -> $To, put the share(s) back " +
                "at the new path, repoint IIS and web.config, start it again.")
    Write-Host "Nothing was changed. Add -Write to do it." -ForegroundColor Yellow
    return
}

# IIS answers "the service cannot accept control messages at this time" while a pool is still changing
# state, so every start and stop waits for the state it asked for rather than assuming it.
function Set-PoolState([string]$Name, [string]$Want) {
    for ($i = 0; $i -lt 20; $i++) {
        $state = (Get-WebAppPoolState -Name $Name -ErrorAction SilentlyContinue).Value
        if ($state -eq $Want) { return $true }
        try {
            if ($Want -eq 'Started') { Start-WebAppPool -Name $Name -ErrorAction Stop }
            else { Stop-WebAppPool -Name $Name -ErrorAction Stop }
        } catch { }                                       # mid-transition: wait and ask again
        Start-Sleep -Seconds 2
    }
    return ((Get-WebAppPoolState -Name $Name -ErrorAction SilentlyContinue).Value -eq $Want)
}

function Start-TheSite {
    [void](Set-PoolState $pool 'Started')
    Start-Website -Name $Site -ErrorAction SilentlyContinue
}

Write-Host "`n== Moving"
Stop-Website -Name $Site -ErrorAction SilentlyContinue
if (-not (Set-PoolState $pool 'Stopped')) { Start-TheSite; throw "The pool '$pool' would not stop." }
# the uvicorn child usually goes with its pool; a leftover one holds the folder open
foreach ($p in (Get-Process -Name python, python3, pythonw -ErrorAction SilentlyContinue)) {
    try { if ("$($p.Path)" -like "$From*") { Stop-Process -Id $p.Id -Force; Write-Host "   stopped a python left in the folder (pid $($p.Id))" } } catch { }
}
Set-Location $env:SystemDrive\                            # never rename the folder you are standing in
# Handles held over a share keep the folder from being renamed, and the usual one is the person doing the
# move: their own mapped drive, through C$. Closing them here only drops the network handle - nothing is
# lost, and the mapping works again as soon as the folder is back.
foreach ($f in $open) {
    try { Close-SmbOpenFile -FileId $f.FileId -Force -ErrorAction Stop; Write-Host "   closed $($f.Path) ($($f.ClientUserName))" }
    catch { Write-Host "   could not close $($f.Path): $($_.Exception.Message)" -ForegroundColor Yellow }
}
# The DMS's own scheduled tasks run a python out of this folder: one that fires mid-move holds it open.
# They are stopped and disabled here, and put back - with their paths followed - at the end.
foreach ($t in $tasks) {
    try {
        Stop-ScheduledTask -TaskName $t.TaskName -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskName $t.TaskName -ErrorAction Stop | Out-Null
        Write-Host "   scheduled task $($t.TaskName) stopped for the move"
    } catch { Write-Host "   could not stop $($t.TaskName): $($_.Exception.Message)" -ForegroundColor Yellow }
}
Start-Sleep -Seconds 2

# the shares, remembered as they are and taken down: a shared folder cannot be renamed
$kept = @()
foreach ($sh in $shares) {
    $kept += [pscustomobject]@{
        Name = $sh.Name; Path = $sh.Path; Description = $sh.Description
        Full = @(Get-SmbShareAccess -Name $sh.Name | Where-Object AccessRight -eq 'Full' | ForEach-Object AccountName)
        Change = @(Get-SmbShareAccess -Name $sh.Name | Where-Object AccessRight -eq 'Change' | ForEach-Object AccountName)
        Read = @(Get-SmbShareAccess -Name $sh.Name | Where-Object AccessRight -eq 'Read' | ForEach-Object AccountName)
    }
    Remove-SmbShare -Name $sh.Name -Force
    Write-Host "   share $($sh.Name) taken down (it goes back at the new path)"
}
$moved = $false
for ($i = 1; $i -le 5 -and -not $moved; $i++) {
    try {
        Rename-Item -LiteralPath $From -NewName (Split-Path -Leaf $To) -ErrorAction Stop
        $moved = $true
        Write-Host "   $From -> $To" -ForegroundColor Green
    } catch {
        $why = $_.Exception.Message
        if ($i -lt 5) { Start-Sleep -Seconds 3 }
        elseif ($Copy) {
            # Something holds the folder and will not let go. The contents can still be copied: the new
            # folder becomes the installation, and the old one is deleted later, when whatever holds it has.
            Write-Host "   the folder will not be renamed - copying instead (-Copy)" -ForegroundColor Yellow
            # Not captured into a variable: a copy of tens of thousands of files (the .venv) with its
            # output swallowed looks exactly like a hung command. The folder names scroll past instead.
            robocopy $From $To /MIR /R:1 /W:1 /NFL /NP
            if ($LASTEXITCODE -ge 8) { Start-TheSite; throw "robocopy failed with exit code $LASTEXITCODE." }
            $moved = $true
            Write-Host "   copied $From -> $To (the old folder stays until you remove it)" -ForegroundColor Green
        }
        else {
            foreach ($k in $kept) {       # put the shares back where they were: nothing was moved
                New-SmbShare -Name $k.Name -Path $k.Path -Description $k.Description -ErrorAction SilentlyContinue | Out-Null
                foreach ($a in $k.Full) { Grant-SmbShareAccess -Name $k.Name -AccountName $a -AccessRight Full -Force | Out-Null }
                foreach ($a in $k.Change) { Grant-SmbShareAccess -Name $k.Name -AccountName $a -AccessRight Change -Force | Out-Null }
                foreach ($a in $k.Read) { Grant-SmbShareAccess -Name $k.Name -AccountName $a -AccessRight Read -Force | Out-Null }
            }
            Start-TheSite
            throw "The folder could not be renamed after $i tries ($why).`n" +
                  "Something is holding it open - the usual suspects are VS Code, an Explorer window, a " +
                  "PowerShell standing in it, or a file open from the share. Close them and run this " +
                  "again. The site has been started again, so the DMS is up."
        }
    }
}

foreach ($k in $kept) {                 # the shares, at the new path, with the same permissions
    $path = $k.Path -replace [regex]::Escape($From), $To
    New-SmbShare -Name $k.Name -Path $path -Description $k.Description -ErrorAction Stop | Out-Null
    foreach ($a in $k.Full) { Grant-SmbShareAccess -Name $k.Name -AccountName $a -AccessRight Full -Force | Out-Null }
    foreach ($a in $k.Change) { Grant-SmbShareAccess -Name $k.Name -AccountName $a -AccessRight Change -Force | Out-Null }
    foreach ($a in $k.Read) { Grant-SmbShareAccess -Name $k.Name -AccountName $a -AccessRight Read -Force | Out-Null }
    Write-Host "   share $($k.Name) -> $path" -ForegroundColor Green
}

$newPhysical = if ("$physical" -like "$From*") { $physical -replace [regex]::Escape($From), $To }
               else { Join-Path $To 'app\webapi' }        # it pointed somewhere else: put it where the DMS is
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

Start-TheSite
$state = (Get-WebAppPoolState -Name $pool -ErrorAction SilentlyContinue).Value
Write-Host "   pool '$pool' is $state" -ForegroundColor $(if ($state -eq 'Started') { 'Green' } else { 'Yellow' })
Write-Host "`n== Afterwards"
foreach ($t in $tasks) {
    try {
        $task = Get-ScheduledTask -TaskName $t.TaskName
        $actions = foreach ($a in $task.Actions) {
            New-ScheduledTaskAction -Execute ($a.Execute -replace [regex]::Escape($From), $To) `
                -Argument ("$($a.Arguments)" -replace [regex]::Escape($From), $To) `
                -WorkingDirectory ("$($a.WorkingDirectory)" -replace [regex]::Escape($From), $To)
        }
        Set-ScheduledTask -TaskName $t.TaskName -Action $actions | Out-Null
        Enable-ScheduledTask -TaskName $t.TaskName | Out-Null
        Write-Host "   scheduled task $($t.TaskName) now runs from $To" -ForegroundColor Green
    } catch {
        Write-Host "   $($t.TaskName) still names the old folder and is disabled - change it by hand: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}
Write-Host "   Open the new folder in VS Code: $To"
Write-Host "   Then: cd $To\app ; .\scripts\Restart-Dms.ps1 ; .\scripts\Test-DmsProductionReady.ps1"
