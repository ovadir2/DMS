<#
.SYNOPSIS
    Takes the KPI Builder out of the DMS repository and gives it one of its own.
.DESCRIPTION
    The Builder is a separate application: its own repository, its own VS Code window, built, tested and
    deployed on its own (the integration SRS says so, and the DMS has no business carrying its source). It
    starts here only so the pilot had something to run.

    This copies kpi-builder\ to -Path, makes it a git repository with one commit, writes the VS Code
    workspace file and a README that says what it talks to. After that, give it a remote of its own, and the
    copy inside the DMS repository can go (delete kpi-builder\ there and deploy with
    New-KpiBuilderSite.ps1 -Source <the new folder>).
.EXAMPLE
    .\scripts\Split-KpiBuilder.ps1 -Path C:\Dev\kpi-builder
.EXAMPLE
    .\scripts\Split-KpiBuilder.ps1 -Path C:\Dev\kpi-builder -Remote https://github.com/ovadir2/kpi-builder
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)] [string]$Path,
    [string]$Remote = ''
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '..\kpi-builder'
if (-not (Test-Path -LiteralPath $source)) { throw "kpi-builder was not found beside the scripts folder: $source" }
if (Test-Path -LiteralPath (Join-Path $Path '.git')) { throw "$Path is already a repository" }

if ($PSCmdlet.ShouldProcess($Path, 'copy the Builder and make it a repository of its own')) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    Copy-Item -Path (Join-Path $source '*') -Destination $Path -Recurse -Force

    $ws = @{
        folders  = @(@{ path = '.' })
        settings = @{ 'files.eol' = "`n"; 'editor.formatOnSave' = $false }
    } | ConvertTo-Json -Depth 5
    Set-Content -LiteralPath (Join-Path $Path 'kpi-builder.code-workspace') -Value $ws -Encoding UTF8
    @'
.vscode/
*.zip
'@ | Set-Content -LiteralPath (Join-Path $Path '.gitignore') -Encoding UTF8

    Push-Location $Path
    try {
        git init -q
        git add -A
        git -c user.email=dms@rh.co.il -c user.name='RH DMS' commit -q -m 'The KPI Builder, out of the DMS repository'
        if ($Remote) { git remote add origin $Remote; Write-Host "  [ok]   remote: $Remote (push when you are ready)" -ForegroundColor Green }
    } finally { Pop-Location }
    Write-Host "  [ok]   $Path (open $Path\kpi-builder.code-workspace in VS Code)" -ForegroundColor Green
    Write-Host "  next   deploy it with .\scripts\New-KpiBuilderSite.ps1 -Source '$Path'" -ForegroundColor DarkGray
}
