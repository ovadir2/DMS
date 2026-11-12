<#
.SYNOPSIS
    Learns the structure this company really has - its departments and the folders in them - and keeps it
    beside the blueprint.

.DESCRIPTION
    The blueprint the DMS ships with is a starting shape. The departments somebody really made under
    General, and the folders inside them, are the structure too: they should be grey in the page, not
    renamed or deleted from a row, and each department should have its KPIs folder. This reads the file
    server and writes what it finds to 04_Workflow_System\Blueprint.json, which the DMS merges at startup.

    The shape of a customer is read from the customer skeleton, so every customer - and every customer made
    later - is described the same way.

    Says what it would add and changes nothing without -Write.

.EXAMPLE
    .\scripts\Update-DmsBlueprint.ps1
.EXAMPLE
    .\scripts\Update-DmsBlueprint.ps1 -Write
.EXAMPLE
    .\scripts\Update-DmsBlueprint.ps1 -Depth 3 -Write
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [string]$App = '',
    [int]$Depth = 6,
    [switch]$Write
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $App) { $App = Get-DmsDefault App }
$py = Join-Path $App '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { $py = 'py' }
Push-Location $App
try {
    $argv = @('-m', 'dms_api.learn')
    if ($Root) { $argv += $Root }
    $argv += @('--depth', "$Depth")
    if ($Write) { $argv += '--write' }
    $env:PYTHONPATH = '.'
    & $py @argv
} finally { Pop-Location }
if ($Write) { & (Join-Path $PSScriptRoot 'Restart-Dms.ps1') }
