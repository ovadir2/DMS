#Requires -Version 5.1
<#
.SYNOPSIS
    Runs the RH - Documents Management System page on this PC to try it out (playground).

.DESCRIPTION
    Uses your real repository folders (-Root), a temporary in-memory register instead of SharePoint,
    and no AD checks (you are -User). Approve or reject in My workflows instead of Teams.
    The first run creates .venv and installs the packages (needs Python 3.11+, "py" launcher).
    Optional: -AiUrl/-AiToken/-AiModel to try AI Insights against RH's on-prem LLM.
    Stop with Ctrl+C. Everything in the register is lost when it stops; files you upload, rename or
    delete are real changes in -Root, so point it at a test copy.

.EXAMPLE
    .\Start-DmsPlayground.ps1 -Root $Root
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Root,
    [string] $User = "$env:USERNAME@rh.co.il",
    [int] $Port = 8080,
    [ValidateSet('EN', 'HE')] [string] $Lang = 'EN',
    [string] $AiUrl, [string] $AiToken, [string] $AiModel
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath $Root)) { throw "Root not found: $Root" }

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host 'First run: creating .venv and installing packages...' -ForegroundColor Cyan
    py -m venv .venv
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet -r requirements.txt
}

$env:DMS_REPOSITORY_ROOT = (Resolve-Path -LiteralPath $Root).ProviderPath
$env:DMS_SHAREPOINT = 'memory'
$env:DMS_AUTH_MODE = 'dev'
$env:DMS_DEV_USER = $User.ToLower()
if ($AiUrl) { $env:DMS_AI_URL = $AiUrl; $env:DMS_AI_TOKEN = $AiToken; $env:DMS_AI_MODEL = $AiModel }

$url = "http://localhost:$Port/dms/dms-page?lang=$Lang"
Write-Host "Playground on $url  (root: $env:DMS_REPOSITORY_ROOT, user: $env:DMS_DEV_USER). Ctrl+C to stop." -ForegroundColor Green
Start-Job -ScriptBlock { param($u) Start-Sleep 3; Start-Process $u } -ArgumentList $url | Out-Null
& $py -m uvicorn dms_api.main:app --host 127.0.0.1 --port $Port
