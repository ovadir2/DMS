<#
.SYNOPSIS
    Reloads the DMS after a git pull: the site's own application pool only.
.DESCRIPTION
    iisreset is not the way here - it leaves the pilot stopped. This recycles the DMS pool (and starts it
    when it is stopped, which is what makes Restart-WebAppPool refuse), makes sure the site is running,
    and then asks the DMS for /api/options so the answer says whether it really came back.

    IIS lives on the DMS server. From a PC that only maps the drive (Z:\app), give -ComputerName and the
    whole thing runs there instead.
.EXAMPLE
    .\scripts\Restart-Dms.ps1
.EXAMPLE
    .\scripts\Restart-Dms.ps1 -ComputerName RHFS02
#>
[CmdletBinding()]
param(
    [string]$Site = '',
    [string]$Pool = '',
    [string]$Url  = '',
    [string]$ComputerName = ''
)
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Site) { $Site = Get-DmsDefault Site }
if (-not $Url) { $Url = Get-DmsDefault Url }

$work = {
    param($Site, $Pool, $Url)

    if (-not (Get-Module -ListAvailable -Name WebAdministration)) {
        throw "$env:COMPUTERNAME has no IIS (the WebAdministration module is missing): run this on the DMS server, or from here with -ComputerName RHFS02"
    }
    Import-Module WebAdministration -ErrorAction Stop

    if (-not $Site) {
        $there = (Get-Website | ForEach-Object { $_.Name }) -join ', '
        throw "Which IIS site? This machine has: $there. Give -Site <name>, or set DMS_IIS_SITE in webapi\.env."
    }
    if (-not (Test-Path "IIS:\Sites\$Site")) {
        $there = (Get-ChildItem IIS:\Sites | ForEach-Object { $_.Name }) -join ', '
        throw "There is no IIS site called '$Site' on $env:COMPUTERNAME. The sites here are: $there. " +
              "Give -Site <name>, or set DMS_IIS_SITE in webapi\.env."
    }
    if (-not $Pool) {
        $Pool = "$((Get-Website -Name $Site).applicationPool)"
        if (-not $Pool) { $Pool = "$((Get-Item "IIS:\Sites\$Site" -ErrorAction Stop).applicationPool)" }
    }
    if (-not $Pool) { throw "The site '$Site' names no application pool: give -Pool <name>." }

    $state = (Get-WebAppPoolState -Name $Pool).Value
    Write-Host "Application pool '$Pool' is $state"
    if ($state -ne 'Started') {
        Start-WebAppPool -Name $Pool                 # Restart-WebAppPool refuses a stopped pool
        Write-Host "  started"
    } else {
        Restart-WebAppPool -Name $Pool               # the uvicorn child is started again by HttpPlatformHandler
        Write-Host "  recycled"
    }

    if ((Get-WebsiteState -Name $Site).Value -ne 'Started') {
        Start-Website -Name $Site
        Write-Host "Site '$Site' started"
    }

    for ($i = 1; $i -le 10; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "$Url/api/options" -UseDefaultCredentials -UseBasicParsing -TimeoutSec 20
            Write-Host "DMS answers: $($r.StatusCode) $($r.StatusDescription)" -ForegroundColor Green
            return
        } catch {
            Start-Sleep -Seconds 2                   # the first request is the one that starts the app
        }
    }
    Write-Warning "The DMS did not answer on $Url/api/options - look at the uvicorn log beside the site (webapi\logs)"
}

if ($ComputerName) {
    Invoke-Command -ComputerName $ComputerName -ScriptBlock $work -ArgumentList $Site, $Pool, $Url -ErrorAction Stop
} else {
    & $work $Site $Pool $Url
}
