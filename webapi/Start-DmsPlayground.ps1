#Requires -Version 5.1
<#
.SYNOPSIS
    Runs the RH - Documents Management System page on this PC: a playground, or the live pilot.

.DESCRIPTION
    Playground (default): your real folders (-Root), a temporary in-memory register instead of
    SharePoint, no AD checks. Approve or reject in My workflows instead of Teams.

    Live pilot (-Live): your real folders, the real Document Register and Control Audit on the
    DocumentControl site, and the real approval flow (DC-P1 sends the approvals to Teams). You sign
    in to SharePoint once in the browser with the Entra app you use for PnP (-ClientId, i.e. $C) and
    you are the DMS user. The Workflow Service file moves run inside the page service every
    -FileServiceSeconds (Submitted -> Submitted folder, Approved -> Current_ReadOnly, Rejected -> back),
    so do not also run Invoke-DmsWorkflowService.ps1 at the same time.

    -Approvals page (default): approvers approve or reject on the page (Approvals), by the same rules as
    DC-P1 (Approver Matrix: all mandatory approvers, then the final approver). Turn DC-P1 Off in Power
    Automate for the pilot, or the approvals are also sent to Teams. -Approvals flow: DC-P1 in Teams.
    -Admins are DMS super users (submit any document, decide any approval stage, see all workflows).
    The first run creates .venv and installs the packages (needs Python 3.11+: "py" or "python").
    Uploads, renames and deletes are real changes in -Root. Stop with Ctrl+C.

.EXAMPLE
    .\Start-DmsPlayground.ps1 -Root $Root

.EXAMPLE
    .\Start-DmsPlayground.ps1 -Root $Root -Live -ClientId $C

.EXAMPLE
    .\Start-DmsPlayground.ps1 -Root $Root -Live -ClientId $C -Users user1@rh.co.il,user2@rh.co.il
    "Acting as" list on the page to switch user. In the pilot (-Live) each user's AD / NTFS access to -Root
    is checked (domain PC); the -Admins are not. -NoAdCheck turns it off; -AdCheck turns it on in the playground.
#>
[CmdletBinding()]
param(
    [string] $Root,
    [switch] $Live,
    [string] $ClientId,
    [string] $TenantName = 'rhisrael',
    [string] $Site = 'DocumentControl-TEST',
    [string] $ExchangeSite = 'LargeFileExchange-TEST',
    [string[]] $Admins = @('roneno@rh.co.il'),
    [ValidateSet('page', 'flow')] [string] $Approvals = 'page',
    [int] $FileServiceSeconds = 60,
    [string] $User,
    [string[]] $Users = @(),
    [switch] $AdCheck,
    [switch] $NoAdCheck,
    [string] $GeneralFolder = '01_General',
    [switch] $NoDrives,
    [int] $Port = 8080,
    [string] $Address,      # -Share: the address the approvers use (e.g. the VPN address); default: this PC's first IPv4
    [switch] $Share,
    [ValidateSet('EN', 'HE')] [string] $Lang = 'EN',
    [string] $AiUrl, [string] $AiToken, [string] $AiModel
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
# -Root / -ClientId not given: DMS_REPOSITORY_ROOT / DMS_CLIENT_ID from .env (a <placeholder> does not count)
function Get-DotEnv([string] $key) {
    $f = Join-Path $PSScriptRoot '.env'
    if (-not (Test-Path $f)) { return '' }
    $line = Select-String -LiteralPath $f -Pattern "^\s*$key\s*=" | Select-Object -First 1
    if (-not $line) { return '' }
    $v = (($line.Line -split '=', 2)[1] -replace '\s+#.*$', '').Trim().Trim('"', "'")
    if ($v -like '<*') { return '' } else { return $v }
}
if (-not $Root) { $Root = Get-DotEnv 'DMS_REPOSITORY_ROOT' }
if (-not $ClientId) { $ClientId = Get-DotEnv 'DMS_CLIENT_ID' }
if (-not $Root) { throw 'No root: give -Root <folder>, or set DMS_REPOSITORY_ROOT in .env' }
if (-not (Test-Path -LiteralPath $Root)) { throw "Root not found: $Root" }
if ($Live -and -not $ClientId) {
    throw '-Live needs the Entra app id you use for PnP: -ClientId <app id>, or DMS_CLIENT_ID=<app id> in .env'
}

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host 'First run: creating .venv and installing packages...' -ForegroundColor Cyan
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { python -m venv .venv }
    else { throw 'Python 3.11+ is not installed. Install it: winget install -e --id Python.Python.3.12  (then open a new PowerShell window)' }
    if (-not (Test-Path $py)) { throw 'Could not create .venv. Check that Python 3.11+ is installed (python --version).' }
    & $py -m pip install --quiet --upgrade pip
}
& $py -m pip install --quiet -r requirements.txt

$env:DMS_REPOSITORY_ROOT = (Resolve-Path -LiteralPath $Root).ProviderPath
$env:DMS_AUTH_MODE = 'dev'
$dotenv = Join-Path $PSScriptRoot '.env'
$adminsInEnv = (Test-Path $dotenv) -and (Select-String -LiteralPath $dotenv -Pattern '^\s*DMS_ADMINS\s*=' -Quiet)
if ($PSBoundParameters.ContainsKey('Admins') -or -not $adminsInEnv) { $env:DMS_ADMINS = ($Admins -join ',').ToLower() }   # else DMS_ADMINS in .env
$env:DMS_APPROVALS = $Approvals
if ($Users) { $env:DMS_DEV_USERS = ($Users -join ',').ToLower() }   # "Acting as" list (testing); else DMS_DEV_USERS in .env
$env:DMS_DEV_AD_CHECK = if (($Live -or $AdCheck) -and -not $NoAdCheck) { '1' } else { '' }   # AD / NTFS checks (on in the pilot), not for -Admins
$env:DMS_DEV_USER = if ($User) { $User.ToLower() } elseif ($Live) { '' } else { "$env:USERNAME@rh.co.il".ToLower() }
if ($Live) {
    $env:DMS_SHAREPOINT = 'online'
    $env:DMS_SP_AUTH = 'interactive'
    $env:DMS_SITE_URL = "https://$TenantName.sharepoint.com/sites/$Site"
    $env:DMS_EX_SITE_URL = "https://$TenantName.sharepoint.com/sites/$ExchangeSite"
    $env:DMS_TENANT_ID = "$TenantName.onmicrosoft.com"
    $env:DMS_CLIENT_ID = $ClientId
    $env:DMS_FILE_SERVICE_SECONDS = "$FileServiceSeconds"
    Write-Host "Live pilot: $env:DMS_SITE_URL. Sign in to SharePoint in the browser window that opens." -ForegroundColor Yellow
    if ($Approvals -eq 'page') { Write-Host 'Approvals on the page: turn the DC-P1 flow Off in Power Automate for the pilot.' -ForegroundColor Yellow }
} else {
    $env:DMS_SHAREPOINT = 'memory'
}
if ($AiUrl) { $env:DMS_AI_URL = $AiUrl }
if ($AiToken) { $env:DMS_AI_TOKEN = $AiToken }
if ($AiModel) { $env:DMS_AI_MODEL = $AiModel }

# Drive letters for the customers and general folders on this PC (a free letter when R: / G: is busy),
# so Open and Copy link give short paths. -NoDrives skips it.
if (-not $NoDrives) {
    $drv = Join-Path $PSScriptRoot '..\scripts\Set-DmsDrives.ps1'
    $cust = if ($env:DMS_CUSTOMERS_FOLDER) { $env:DMS_CUSTOMERS_FOLDER } else { '02_Customers' }
    if (Test-Path $drv) {
        try {
            & $drv -Root $env:DMS_REPOSITORY_ROOT -CustomersFolder $cust -GeneralFolder $GeneralFolder
            $k = Get-ItemProperty -Path 'HKCU:\Software\RH\DMS' -ErrorAction SilentlyContinue
            $pairs = @($cust, $GeneralFolder | Where-Object { $k -and $k.$_ } | ForEach-Object { "$_=$($k.$_)" })
            if ($pairs) { $env:DMS_SHORT_PATHS = $pairs -join ';' }
        } catch { Write-Warning "Drive letters were not set: $_" }
    }
}

# An older DMS still running (another window, or left behind) would keep answering on the port: stop it first
$old = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -like '*uvicorn*dms_api.main:app*' } | ForEach-Object { $_.ProcessId })
$old += @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $_.OwningProcess })
foreach ($id in ($old | Where-Object { $_ -and $_ -ne $PID } | Select-Object -Unique)) {
    try { Stop-Process -Id $id -Force -ErrorAction Stop; Write-Host "Stopped an older DMS (process $id)." -ForegroundColor Yellow }
    catch { Write-Warning "Could not stop process $id that holds port ${Port}: $_" }
}
if ($old) { Start-Sleep -Seconds 1 }

$url = "http://localhost:$Port/dms/dms-page?lang=$Lang"
$bind = '127.0.0.1'
if ($Share) {
    # -Share: other PCs in the network open the DMS at http://<this PC>:<Port> and sign in with their own Windows
    # account (dms_api\ntlm.py; their AD rights are checked). Needs the port open in the Windows firewall (once, as admin).
    $bind = '0.0.0.0'
    # the IPv4 address (the DMS listens on IPv4; the PC name can also resolve to IPv6 addresses that time out)
    $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
          Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
          Sort-Object InterfaceMetric | Select-Object -First 1 -ExpandProperty IPAddress
    $all = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' })
    Write-Host "This PC's addresses: $(($all | ForEach-Object { "$($_.IPAddress) ($($_.InterfaceAlias))" }) -join ', ')   (choose one with -Address)" -ForegroundColor Cyan
    if ($Address) { $ip = $Address }
    $hostName = if ($ip) { $ip } else { try { [System.Net.Dns]::GetHostEntry($env:COMPUTERNAME).HostName } catch { $env:COMPUTERNAME } }
    $shared = "http://$($hostName):$Port/dms/dms-page?lang=$Lang"
    $env:DMS_PAGE_URL = $shared                                   # the links in the emails / Teams
    if (-not (Get-NetFirewallRule -DisplayName "RH DMS $Port" -ErrorAction SilentlyContinue)) {
        try { New-NetFirewallRule -DisplayName "RH DMS $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Any -ErrorAction Stop | Out-Null
              Write-Host "Firewall: port $Port opened." -ForegroundColor Green }
        catch { Write-Warning "Port $Port is not open in the firewall. Once, in PowerShell as administrator: New-NetFirewallRule -DisplayName 'RH DMS $Port' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Any" }
    }
    Write-Host "Shared: the approvers open $shared" -ForegroundColor Green
    # Setup for the approvers' PCs (no git / VS Code there): the scripts and a ready Setup-DMS.cmd on the share.
    # Double-click it once: drive letters + the Open handler (rh-dms:) + the DMS page.
    try {
        $setup = Join-Path $env:DMS_REPOSITORY_ROOT '04_Workflow_System\Setup'
        $cust = if ($env:DMS_CUSTOMERS_FOLDER) { $env:DMS_CUSTOMERS_FOLDER } else { '02_Customers' }
        New-Item -ItemType Directory -Path $setup -Force | Out-Null
        foreach ($f in 'Set-DmsDrives.ps1', 'Open-DmsFile.ps1') { Copy-Item -LiteralPath (Join-Path $PSScriptRoot "..\scripts\$f") -Destination $setup -Force }
        # the root as the approvers reach it: DMS_CLIENT_ROOT (an admin share like \\server\e$ is closed to them)
        $clientRoot = if ($env:DMS_CLIENT_ROOT) { $env:DMS_CLIENT_ROOT } else { Get-DotEnv 'DMS_CLIENT_ROOT' }
        if (-not $clientRoot) {
            $clientRoot = $env:DMS_REPOSITORY_ROOT
            if ($clientRoot -match '^\\\\[^\\]+\\[a-z]\$') { Write-Warning "The root $clientRoot is an admin share: the approvers cannot open it. Set DMS_CLIENT_ROOT=\\<server>\<share> in .env (the same folder as they reach it)." }
        }
        $cmd = "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0Set-DmsDrives.ps1`" -Root `"$clientRoot`" -CustomersFolder `"$cust`" -GeneralFolder `"$GeneralFolder`" -DmsUrl `"http://$($hostName):$Port`"`r`npause`r`n"
        [IO.File]::WriteAllText((Join-Path $setup 'Setup-DMS.cmd'), $cmd, [Text.Encoding]::Default)
        Write-Host "  Approvers' PCs: double-click once $(Join-Path $clientRoot '04_Workflow_System\Setup\Setup-DMS.cmd')" -ForegroundColor Green
    } catch { Write-Warning "Setup for the approvers' PCs not written: $_" }
    Write-Host ("  Each one signs in with their own Windows account (asked once: RH\name + password; no question when " +
                "http://$hostName is in Local intranet sites). This PC stays you.") -ForegroundColor Green
} else {
    $env:DMS_PAGE_URL = $url   # notification links (DC-P2) open the page here
}
Write-Host "DMS page on $url  (root: $env:DMS_REPOSITORY_ROOT). Ctrl+C to stop." -ForegroundColor Green
Start-Job -ScriptBlock { param($u, $p) for ($i = 0; $i -lt 120; $i++) { Start-Sleep 2; try { Invoke-WebRequest "http://localhost:$p/api/health" -UseBasicParsing | Out-Null; Start-Process $u; break } catch {} } } -ArgumentList $(if ($NoDrives) { $url } else { "$url&opener=1" }), $Port | Out-Null   # opener: Set-DmsDrives installed rh-dms:
& $py -m uvicorn dms_api.main:app --host $bind --port $Port
