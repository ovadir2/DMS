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
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Root,
    [switch] $Live,
    [string] $ClientId,
    [string] $TenantName = 'rhisrael',
    [string] $Site = 'DocumentControl-TEST',
    [string[]] $Admins = @('roneno@rh.co.il'),
    [ValidateSet('page', 'flow')] [string] $Approvals = 'page',
    [int] $FileServiceSeconds = 60,
    [string] $User,
    [int] $Port = 8080,
    [ValidateSet('EN', 'HE')] [string] $Lang = 'EN',
    [string] $AiUrl, [string] $AiToken, [string] $AiModel
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath $Root)) { throw "Root not found: $Root" }
if ($Live -and -not $ClientId) { throw '-Live needs -ClientId (the Entra app you use for PnP, $C)' }

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host 'First run: creating .venv and installing packages...' -ForegroundColor Cyan
    $base = if (Get-Command py -ErrorAction SilentlyContinue) { @('py', '-3') }
            elseif (Get-Command python -ErrorAction SilentlyContinue) { @('python') }
            else { throw 'Python 3.11+ is not installed. Install it: winget install -e --id Python.Python.3.12  (then open a new PowerShell window)' }
    & $base[0] @($base | Select-Object -Skip 1) -m venv .venv
    if (-not (Test-Path $py)) { throw 'Could not create .venv. Check that Python 3.11+ is installed (python --version).' }
    & $py -m pip install --quiet --upgrade pip
}
& $py -m pip install --quiet -r requirements.txt

$env:DMS_REPOSITORY_ROOT = (Resolve-Path -LiteralPath $Root).ProviderPath
$env:DMS_AUTH_MODE = 'dev'
$env:DMS_ADMINS = ($Admins -join ',').ToLower()
$env:DMS_APPROVALS = $Approvals
$env:DMS_DEV_USER = if ($User) { $User.ToLower() } elseif ($Live) { '' } else { "$env:USERNAME@rh.co.il".ToLower() }
if ($Live) {
    $env:DMS_SHAREPOINT = 'online'
    $env:DMS_SP_AUTH = 'interactive'
    $env:DMS_SITE_URL = "https://$TenantName.sharepoint.com/sites/$Site"
    $env:DMS_TENANT_ID = "$TenantName.onmicrosoft.com"
    $env:DMS_CLIENT_ID = $ClientId
    $env:DMS_FILE_SERVICE_SECONDS = "$FileServiceSeconds"
    Write-Host "Live pilot: $env:DMS_SITE_URL. Sign in to SharePoint in the browser window that opens." -ForegroundColor Yellow
    if ($Approvals -eq 'page') { Write-Host 'Approvals on the page: turn the DC-P1 flow Off in Power Automate for the pilot.' -ForegroundColor Yellow }
} else {
    $env:DMS_SHAREPOINT = 'memory'
}
if ($AiUrl) { $env:DMS_AI_URL = $AiUrl; $env:DMS_AI_TOKEN = $AiToken; $env:DMS_AI_MODEL = $AiModel }

$url = "http://localhost:$Port/dms/dms-page?lang=$Lang"
Write-Host "DMS page on $url  (root: $env:DMS_REPOSITORY_ROOT). Ctrl+C to stop." -ForegroundColor Green
Start-Job -ScriptBlock { param($u, $p) for ($i = 0; $i -lt 120; $i++) { Start-Sleep 2; try { Invoke-WebRequest "http://localhost:$p/api/health" -UseBasicParsing | Out-Null; Start-Process $u; break } catch {} } } -ArgumentList $url, $Port | Out-Null
& $py -m uvicorn dms_api.main:app --host 127.0.0.1 --port $Port
