<#
.SYNOPSIS
    A key for an application that calls the DMS (not a person).
.DESCRIPTION
    A browser signs in with Windows and the DMS answers what AD lets that person see. An application -
    Priority, a report, a script on another server - has no sign-in and no AD rights. It is given a key, and
    the key is an identity: a name, what it may read, and a line in the log for every call it makes.

    This prints the line to paste into webapi\.env after DMS_API_KEYS= (several callers separated by |).
    The DMS never shows a key again, and never writes one to the log or into an answer.

    Scopes: customers, documents, files, kpi (the KPI Builder: it also publishes).

    -ActsAs is the AD account the caller acts as. An application is not a super user: every answer is
    filtered against that account's own AD rights, folder by folder. A key without one is told nothing.
.EXAMPLE
    .\scripts\New-DmsApiKey.ps1 -Name priority -Scopes customers,documents -ActsAs svc_priority@rh.co.il
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Name,
    [string[]]$Scopes = @('customers'),
    [Parameter(Mandatory)] [string]$ActsAs,          # the AD account it acts as: what it may see is what that account may see
    [string]$App = ''
)
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $App) { $App = Get-DmsDefault App }

$py = Join-Path $App '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw "The DMS python was not found: $py (give -App)" }

Push-Location $App
try { & $py -m dms_api.apikeys $Name ($Scopes -join ',') $ActsAs } finally { Pop-Location }
