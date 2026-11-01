<#
.SYNOPSIS
    Puts the KPI Builder on this server (E:\KPI_Builder) and gives it a site of its own in IIS.
.DESCRIPTION
    The Builder is a page, nothing more: it makes the two files a KPI is - <name>.html, which the DMS runs,
    and <name>.json, which says what it reads - and they are brought into the DMS by dropping them on the
    department's KPIs folder. It needs no application pool of its own doing work, no database and no network
    beyond this server.

    The Builder is its own repository (its own VS Code workspace, built and deployed on its own, as the
    integration SRS says). This script only puts it on the server: it copies -Source to -Path, creates the IIS site (or updates it), turns
    Windows Authentication on and anonymous off so it knows who is using it, and - with -WireDms - writes
    DMS_KPI_BUILDER_URL into the DMS's own .env and lets the DMS answer the Builder's calls
    (DMS_ALLOWED_ORIGINS), so New KPI in the DMS menu opens it.

    Run it on the file server, as an administrator.
.EXAMPLE
    .\scripts\New-KpiBuilderSite.ps1 -Source C:\Dev\kpi-builder -WhatIf
.EXAMPLE
    .\scripts\New-KpiBuilderSite.ps1 -Source C:\Dev\kpi-builder -WireDms
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Path = 'E:\KPI_Builder',
    [Parameter(Mandatory)] [string]$Source,         # the Builder's own repository (it is not in this one)
    [string]$SiteName = 'KPI-Builder',
    [int]$Port = 8081,
    [string]$HostHeader = '',                       # e.g. kpi-pilot.rh.tech; empty: the port alone
    [string]$DmsApp = 'C:\DMS-Pilot\app',
    [string]$DmsUrl = 'https://dms-pilot.rh.tech',
    [switch]$WireDms
)

$ErrorActionPreference = 'Stop'
$source = $Source
if (-not (Test-Path -LiteralPath $source)) { throw "The Builder was not found: $source" }
if (-not (Test-Path -LiteralPath (Join-Path $source 'index.html'))) {
    throw "$source does not look like the Builder (no index.html). Give the folder of its repository."
}

Write-Host "=== The files" -ForegroundColor Cyan
if ($PSCmdlet.ShouldProcess($Path, 'copy the Builder')) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    Copy-Item -Path (Join-Path $source '*') -Destination $Path -Recurse -Force
    Write-Host "  [ok]   $Path" -ForegroundColor Green
}

Write-Host "=== The site" -ForegroundColor Cyan
Import-Module WebAdministration -ErrorAction Stop
$binding = if ($HostHeader) { "*:${Port}:$HostHeader" } else { "*:${Port}:" }
if ($PSCmdlet.ShouldProcess($SiteName, 'create or update the IIS site')) {
    if (-not (Test-Path "IIS:\AppPools\$SiteName")) { New-WebAppPool -Name $SiteName | Out-Null }
    Set-ItemProperty "IIS:\AppPools\$SiteName" -Name managedRuntimeVersion -Value ''      # no .NET needed
    if (Test-Path "IIS:\Sites\$SiteName") {
        Set-ItemProperty "IIS:\Sites\$SiteName" -Name physicalPath -Value $Path
    } else {
        New-Website -Name $SiteName -PhysicalPath $Path -ApplicationPool $SiteName -Port $Port `
                    -HostHeader $HostHeader -Force | Out-Null
    }
    # It should know who is using it, like the DMS does, and nobody should reach it anonymously.
    Set-WebConfigurationProperty -Filter '/system.webServer/security/authentication/windowsAuthentication' `
        -Name enabled -Value $true -PSPath 'IIS:\' -Location $SiteName
    Set-WebConfigurationProperty -Filter '/system.webServer/security/authentication/anonymousAuthentication' `
        -Name enabled -Value $false -PSPath 'IIS:\' -Location $SiteName
    Start-Website -Name $SiteName -ErrorAction SilentlyContinue
    Write-Host "  [ok]   http://$(if ($HostHeader) { $HostHeader } else { $env:COMPUTERNAME }):$Port" -ForegroundColor Green
}

if ($WireDms) {
    Write-Host "=== The DMS" -ForegroundColor Cyan
    $envFile = Join-Path $DmsApp 'webapi\.env'
    if (-not (Test-Path -LiteralPath $envFile)) { throw "The DMS .env was not found: $envFile (give -DmsApp)" }
    $url = if ($HostHeader) { "http://$HostHeader`:$Port/index.html" } else { "http://$env:COMPUTERNAME`:$Port/index.html" }
    $lines = @(Get-Content -LiteralPath $envFile -Encoding UTF8)
    function Set-Line([string[]]$text, [string]$key, [string]$value) {
        $at = ($text | Select-String -Pattern "^\s*$key\s*=" | Select-Object -First 1)
        if ($at) { $text[$at.LineNumber - 1] = "$key=$value"; return $text }
        return $text + "$key=$value"
    }
    # The Builder is a site of its own, so the DMS must be willing to answer it.
    $origin = $url -replace '/[^/]*$', ''
    $lines = Set-Line $lines 'DMS_KPI_BUILDER_URL' $url
    $cors = ($lines | Select-String -Pattern '^\s*DMS_ALLOWED_ORIGINS\s*=' | Select-Object -First 1)
    $allowed = if ($cors) { ($cors.Line -split '=', 2)[1].Trim() } else { '' }
    if ($allowed -notmatch [regex]::Escape($origin)) {
        $allowed = (@($allowed, $origin) | Where-Object { $_ }) -join ','
        $lines = Set-Line $lines 'DMS_ALLOWED_ORIGINS' $allowed
    }
    if ($PSCmdlet.ShouldProcess($envFile, "DMS_KPI_BUILDER_URL=$url")) {
        Set-Content -LiteralPath $envFile -Value $lines -Encoding UTF8
        Write-Host "  [ok]   DMS_KPI_BUILDER_URL=$url" -ForegroundColor Green
        Write-Host "  [ok]   DMS_ALLOWED_ORIGINS includes $origin" -ForegroundColor Green
        Write-Host "  next   .\scripts\Restart-Dms.ps1   (then New KPI appears on a KPIs folder)" -ForegroundColor DarkGray
    }
}
