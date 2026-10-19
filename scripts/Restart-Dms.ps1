<#
.SYNOPSIS
    Reloads the DMS after a git pull: the site's own application pool only.
.DESCRIPTION
    iisreset is not the way here - it leaves the pilot stopped. This recycles the DMS pool (and starts it
    when it is stopped, which is what makes Restart-WebAppPool refuse), makes sure the site is running,
    and then asks the DMS for /api/options so the answer says whether it really came back.
.EXAMPLE
    .\scripts\Restart-Dms.ps1
#>
[CmdletBinding()]
param(
    [string]$Site = 'DMS-Pilot',
    [string]$Pool = '',
    [string]$Url  = 'https://dms-pilot.rh.tech'
)

Import-Module WebAdministration -ErrorAction Stop

if (-not $Pool) {
    $Pool = (Get-Item "IIS:\Sites\$Site" -ErrorAction Stop).applicationPool
}

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
Write-Warning "The DMS did not answer on $Url/api/options - look at the HttpPlatformHandler log under C:\DMS-Pilot\logs"
