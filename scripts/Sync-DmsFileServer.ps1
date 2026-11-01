<#
.SYNOPSIS
    Puts the DMS and the file server back in step after files were added or deleted by hand.
.DESCRIPTION
    Somebody copies a file into a folder, deletes a document, renames a folder - on the file server itself,
    where the DMS cannot see it happen. This looks at both sides and reports, and with -Write puts them back
    in step:

      1. a record whose file moved is pointed at it; a record whose file is gone keeps its history, stops
         claiming the file and is archived, with the reason in Control Audit
      2. a file sitting in Current_ReadOnly that the DMS does not know is reported; -Register registers it as
         released without workflow, with its audit row
      3. a released file that is not read only is made read only, and its folder is hardened
      4. a dashboard page released into Current_ReadOnly is put back in its own folder
      5. Markdown is written for what has none, and removed where it does not belong
      6. blueprint folders missing from the skeleton are listed (New-DmsFileServerTree.ps1 puts them back)

    Nothing is deleted from SharePoint, and nothing changes without -Write.
.EXAMPLE
    .\scripts\Sync-DmsFileServer.ps1                      # what it would do
.EXAMPLE
    .\scripts\Sync-DmsFileServer.ps1 -Write               # do it
.EXAMPLE
    .\scripts\Sync-DmsFileServer.ps1 -Write -Register     # and adopt what it found in Current_ReadOnly
#>
[CmdletBinding()]
param(
    [string]$App = 'C:\DMS-Pilot\app\webapi',
    [switch]$Write,
    [switch]$Register,
    [string]$Log = (Join-Path $PSScriptRoot 'out\align.log')
)

$py = Join-Path $App '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw "The DMS python was not found: $py (give -App)" }

$args = @('-m', 'dms_api.align')
if ($Write)    { $args += '--write' }
if ($Register) { $args += '--register' }

New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null
Push-Location $App
try { & $py @args 2>&1 | Tee-Object -FilePath $Log }
finally { Pop-Location }
Write-Host "`n  log: $Log" -ForegroundColor DarkGray
