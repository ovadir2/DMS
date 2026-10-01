#Requires -Version 7.0
#Requires -Modules PnP.PowerShell
<#
.SYNOPSIS
    Pilot Workflow Service: moves the files of controlled documents on the file server to match
    their status in the Document Register (Working -> Submitted -> Current_ReadOnly).

.DESCRIPTION
    Power Automate cannot reach the on-prem file server, so this script does the file side of the
    approval. Run it every few minutes (Task Scheduler) on a server that can write to the repository.
    Each run reads the Document Register and, per record:

      Status                    File found in     Action
      Submitted (הוגש לאישור)   its own place     Move to Submitted, set read-only
      Approved  (מאושר - ...)   Submitted / place Move the previous current file to Obsolete_ReadOnly,
                                                  move the file to Current_ReadOnly without "_DRAFT",
                                                  set read-only, write CurrentUncPath, CurrentSHA256,
                                                  CurrentRevision and clear WorkingUncPath
      Working   (בעבודה)        Submitted         Move back to its own place (rejected), clear read-only

    "Its own place" is the record's WorkingUncPath: wherever the user saved the file, e.g.
    ...\Commercial\Quotations\Quote.xlsx. Submitted, Current_ReadOnly and Obsolete_ReadOnly are created
    next to it (Quotations\Current_ReadOnly\Quote.xlsx), so users never handle the workflow folders.
    For a file in a Working folder (New-DmsFileServerTree.ps1 -DocumentId) they are the siblings of
    Working. Every move writes a Control Audit row (EventSource Workflow Service). Records in Submitted are never updated, so the approval flow is not re-triggered.
    Safe to re-run: a record whose file is already in the right folder is skipped.

    Pilot scope: it reads the register directly. The full design (docs/04 §5.1) reads commands from the
    File Action Queue instead.

.PARAMETER RepositoryRoot
    Only paths under this root are touched, e.g. \\FILE-SERVER\Corporate_Data_TEST.

.PARAMETER ClientId
    Entra app (client) ID used by PnP.PowerShell. Interactive sign-in unless -Thumbprint is given.

.PARAMETER Thumbprint
    Certificate thumbprint for unattended runs (scheduled task). Needs -TenantName.

.EXAMPLE
    .\Invoke-DmsWorkflowService.ps1 -TenantName rhisrael -DocControlSiteAlias DocumentControl-TEST -ClientId $C -RepositoryRoot $Root -WhatIf

.EXAMPLE
    .\Invoke-DmsWorkflowService.ps1 -TenantName rhisrael -DocControlSiteAlias DocumentControl-TEST -ClientId $C -RepositoryRoot $Root
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'Admin script: coloured progress output is intended.')]
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)] [ValidatePattern('^[a-zA-Z0-9-]+$')] [string] $TenantName,
    [Parameter(Mandatory)] [guid] $ClientId,
    [Parameter(Mandatory)] [string] $RepositoryRoot,
    [string] $DocControlSiteAlias = 'DocumentControl',
    [ValidateSet('he', 'en')] [string] $ChoiceLanguage = 'he',
    [string] $Thumbprint,
    [string] $LogFolder = (Join-Path $env:ProgramData 'DMS\logs')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SiteUrl = "https://$TenantName.sharepoint.com/sites/$DocControlSiteAlias"
$Root = $RepositoryRoot.TrimEnd('\')
$V = if ($ChoiceLanguage -eq 'he') {
    @{ Working = 'בעבודה'; Submitted = 'הוגש לאישור'; Approved = 'מאושר - קריאה בלבד'
       EvDone = 'פעולת קובץ הושלמה'; EvFailed = 'פעולת קובץ נכשלה'; Source = 'שירות תהליכים' }
} else {
    @{ Working = 'Working'; Submitted = 'Submitted'; Approved = 'Approved_ReadOnly'
       EvDone = 'FileActionCompleted'; EvFailed = 'FileActionFailed'; Source = 'WorkflowService' }
}

New-Item -ItemType Directory -Path $LogFolder -Force | Out-Null
$logFile = Join-Path $LogFolder ('WorkflowService_{0:yyyyMMdd}.log' -f (Get-Date))
function Write-Log([string]$Message, [string]$Color = 'Gray') {
    Write-Host $Message -ForegroundColor $Color
    Add-Content -LiteralPath $logFile -Value ('{0:u} {1}' -f (Get-Date).ToUniversalTime(), $Message) -Encoding utf8
}

function Test-UnderRoot([string]$Path) {
    $Path -and $Path -notmatch '\.\.' -and $Path.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Set-ReadOnly([string]$Path, [bool]$On) {
    (Get-Item -LiteralPath $Path).IsReadOnly = $On
}

function Move-DmsFile([string]$Source, [string]$Target, [switch]$Replace) {
    # Moves never overwrite (an existing target gets a timestamp suffix), unless -Replace: then an older
    # copy of the same document is replaced, so the file keeps its name.
    if ($Replace -and (Test-Path -LiteralPath $Target -PathType Leaf)) {
        Set-ReadOnly $Target $false
        Remove-Item -LiteralPath $Target -Force
    }
    if (Test-Path -LiteralPath $Target) {
        $Target = Join-Path (Split-Path $Target) ('{0}_{1:yyyyMMddHHmmss}{2}' -f
            [IO.Path]::GetFileNameWithoutExtension($Target), (Get-Date), [IO.Path]::GetExtension($Target))
    }
    New-Item -ItemType Directory -Path (Split-Path $Target) -Force | Out-Null
    $ro = (Get-Item -LiteralPath $Source).IsReadOnly
    if ($ro) { Set-ReadOnly $Source $false }
    Move-Item -LiteralPath $Source -Destination $Target
    if ($ro) { Set-ReadOnly $Target $true }
    $Target
}

function Write-Audit([string]$DocumentId, [string]$Status, [string]$Event, [string]$Details) {
    $values = @{
        Title = "$Event $DocumentId"; CorrelationId = $DocumentId; AuditEventType = $Event
        FromStatus = $Status; ToStatus = $Status; ActorEmail = $actor; EventUtc = (Get-Date).ToUniversalTime()
        EventSource = $V.Source; EventDetails = $Details
    }
    Add-PnPListItem -List 'Lists/ControlAudit' -Values $values | Out-Null
}

if ($Thumbprint) {
    Connect-PnPOnline -Url $SiteUrl -ClientId $ClientId -Thumbprint $Thumbprint -Tenant "$TenantName.onmicrosoft.com"
} else {
    Connect-PnPOnline -Url $SiteUrl -Interactive -ClientId $ClientId
}
$actor = if ($Thumbprint) { 'RH-DMS-Workflow-Service' } else { try { (Get-PnPCurrentUser).Email } catch { $env:USERNAME } }
Write-Log "Run started on $SiteUrl, root $Root$(if ($WhatIfPreference) { ' (WhatIf)' })" 'Cyan'

$fields = 'ID', 'Title', 'DocumentId', 'LifecycleStatus', 'WorkingUncPath', 'CurrentUncPath', 'DraftRevision'
$items = Get-PnPListItem -List 'Lists/DocumentRegister' -PageSize 500 -Fields $fields
$done = 0; $failed = 0

foreach ($item in $items) {
    $f = $item.FieldValues
    $docId = if ($f.DocumentId) { $f.DocumentId } else { "ID $($f.ID)" }
    $status = [string]$f.LifecycleStatus
    $working = [string]$f.WorkingUncPath
    if (-not $working -or $status -notin $V.Working, $V.Submitted, $V.Approved) { continue }
    if (-not (Test-UnderRoot $working)) {
        Write-Log "  [skip] $docId - WorkingUncPath is not under the root: $working" 'DarkGray'; continue
    }

    $name = Split-Path $working -Leaf
    # The file stays where the user saved it (or in a Working folder). The workflow folders are
    # created next to it, or next to Working for a document created with New-DmsFileServerTree.ps1.
    $parent = Split-Path $working
    $docFolder = if ((Split-Path $parent -Leaf) -in 'Working', 'Submitted', 'Current_ReadOnly', 'Obsolete_ReadOnly') { Split-Path $parent } else { $parent }
    $inWorking = $working
    $inSubmitted = Join-Path $docFolder "Submitted\$name"
    if (-not (Test-Path -LiteralPath $inSubmitted)) {
        # Older runs renamed it with a timestamp suffix: take the newest one, it goes back under its own name
        $base = [IO.Path]::GetFileNameWithoutExtension($name); $ext = [IO.Path]::GetExtension($name)
        $old = Get-ChildItem -LiteralPath (Join-Path $docFolder 'Submitted') -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match ('^' + [regex]::Escape($base) + '_\d{14}' + [regex]::Escape($ext) + '$') } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($old) { $inSubmitted = $old.FullName }
    }
    $action = $null; $details = $null

    try {
        switch ($status) {
            $V.Submitted {
                if (-not (Test-Path -LiteralPath $inWorking)) { continue }
                $action = 'MoveToSubmitted'
                if ($PSCmdlet.ShouldProcess($inWorking, $action)) {
                    $target = Move-DmsFile $inWorking (Join-Path $docFolder "Submitted\$name") -Replace
                    Set-ReadOnly $target $true
                    $sha = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
                    $details = "${action}: $inWorking -> $target. SHA-256 $sha"
                }
            }
            $V.Working {
                if (-not (Test-Path -LiteralPath $inSubmitted) -or (Test-Path -LiteralPath $inWorking)) { continue }
                $action = 'ReturnToWorking'
                if ($PSCmdlet.ShouldProcess($inSubmitted, $action)) {
                    Set-ReadOnly $inSubmitted $false
                    $target = Move-DmsFile $inSubmitted $inWorking
                    $details = "${action}: $inSubmitted -> $target"
                }
            }
            $V.Approved {
                $source = @($inSubmitted, $inWorking) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
                if (-not $source) { Write-Log "  [warn] $docId - approved, but the file is not in Working or Submitted: $name" 'Yellow'; continue }
                $action = 'PromoteToCurrent'
                if ($PSCmdlet.ShouldProcess($source, $action)) {
                    $obsolete = $null
                    $old = [string]$f.CurrentUncPath
                    if ((Test-UnderRoot $old) -and (Test-Path -LiteralPath $old)) {
                        $obsolete = Move-DmsFile $old (Join-Path $docFolder ('Obsolete_ReadOnly\' + (Split-Path $old -Leaf)))
                        Set-ReadOnly $obsolete $true
                    }
                    $currentName = $name -replace '_DRAFT(?=\.[^.]+$|$)', ''
                    $target = Move-DmsFile $source (Join-Path $docFolder "Current_ReadOnly\$currentName")
                    Set-ReadOnly $target $true
                    $sha = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
                    $values = @{ CurrentUncPath = $target; CurrentSHA256 = $sha; WorkingUncPath = $null }
                    if ($f.DraftRevision) { $values.CurrentRevision = $f.DraftRevision; $values.DraftRevision = $null }
                    Set-PnPListItem -List 'Lists/DocumentRegister' -Identity $f.ID -Values $values -UpdateType SystemUpdate | Out-Null
                    $details = "${action}: $source -> $target. SHA-256 $sha" + $(if ($obsolete) { ". Previous revision -> $obsolete" })
                }
            }
        }
        if ($details) {
            Write-Audit $docId $status $V.EvDone $details
            Write-Log "  [ok]   $docId - $details" 'Green'; $done++
        }
    } catch {
        $failed++
        $msg = "${action} failed for ${name}: $($_.Exception.Message)"
        Write-Log "  [fail] $docId - $msg" 'Red'
        try { Write-Audit $docId $status $V.EvFailed $msg } catch { Write-Log "  [fail] audit row not written: $($_.Exception.Message)" 'Red' }
    }
}

Write-Log "Run finished: $done moved, $failed failed. Log: $logFile" $(if ($failed) { 'Red' } else { 'Cyan' })
if ($failed) { exit 1 }
