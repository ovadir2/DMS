#Requires -Version 7.0
#Requires -Modules PnP.PowerShell
<#
.SYNOPSIS
    Pilot: makes one person the mandatory and final approver for every document type in the
    Approver Matrix, so that person can run the whole approval process end to end.

.DESCRIPTION
    For each Document Type choice of the Document Register:
      - the matrix rules of that type get MandatoryApprovers = FinalApprover = -Approver, active;
      - a type without a rule gets a new active rule ("Pilot - <type>").
    The current approvers are saved first to out\ApproverMatrix-backup-<time>.json.
    Run again with -Restore <that file> to put them back after the pilot.

.EXAMPLE
    .\Set-DmsTestApprover.ps1 -TenantName rhisrael -DocControlSiteAlias DocumentControl-TEST -ClientId $C -Approver roneno@rh.co.il

.EXAMPLE
    .\Set-DmsTestApprover.ps1 -TenantName rhisrael -DocControlSiteAlias DocumentControl-TEST -ClientId $C -Restore .\out\ApproverMatrix-backup-20261001-0900.json
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'Admin script: coloured progress output is intended.')]
[CmdletBinding(SupportsShouldProcess, DefaultParameterSetName = 'Set')]
param(
    [Parameter(Mandatory)] [ValidatePattern('^[a-zA-Z0-9-]+$')] [string] $TenantName,
    [Parameter(Mandatory)] [guid] $ClientId,
    [string] $DocControlSiteAlias = 'DocumentControl',
    [Parameter(Mandatory, ParameterSetName = 'Set')] [string] $Approver,
    [Parameter(Mandatory, ParameterSetName = 'Restore')] [string] $Restore
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SiteUrl = "https://$TenantName.sharepoint.com/sites/$DocControlSiteAlias"
Connect-PnPOnline -Url $SiteUrl -Interactive -ClientId $ClientId
$matrix = 'Lists/ApproverMatrix'
$emails = { param($v) @($v | Where-Object { $_ } | ForEach-Object { $_.Email }) }

if ($Restore) {
    $backup = Get-Content -LiteralPath $Restore -Raw -Encoding utf8 | ConvertFrom-Json
    foreach ($r in $backup) {
        if ($r.Created) {
            if ($PSCmdlet.ShouldProcess("rule $($r.Id) ($($r.DocumentType))", 'Remove pilot rule')) { Remove-PnPListItem -List $matrix -Identity $r.Id -Force }
            continue
        }
        $values = @{ MandatoryApprovers = @($r.MandatoryApprovers); FinalApprover = $r.FinalApprover; IsActive = [bool]$r.IsActive }
        if ($PSCmdlet.ShouldProcess("rule $($r.Id) ($($r.DocumentType))", 'Restore approvers')) {
            Set-PnPListItem -List $matrix -Identity $r.Id -Values $values | Out-Null
        }
    }
    Write-Host "Restored $(@($backup).Count) rules from $Restore" -ForegroundColor Green
    return
}

$types = (Get-PnPField -List 'Lists/DocumentRegister' -Identity DocumentType).Choices
$area = @((Get-PnPField -List $matrix -Identity DocumentArea).Choices)[0]
$rules = @(Get-PnPListItem -List $matrix -PageSize 500)
$backup = [System.Collections.Generic.List[object]]::new()
foreach ($r in $rules) {
    $f = $r.FieldValues
    $backup.Add([pscustomobject]@{ Id = $r.Id; DocumentType = $f.DocumentType; IsActive = $f.IsActive; Created = $false
        MandatoryApprovers = & $emails $f.MandatoryApprovers; FinalApprover = (& $emails $f.FinalApprover) | Select-Object -First 1 })
}

$out = Join-Path $PSScriptRoot 'out'
New-Item -ItemType Directory -Path $out -Force | Out-Null
$file = Join-Path $out ("ApproverMatrix-backup-{0:yyyyMMdd-HHmm}.json" -f (Get-Date))
if (-not $WhatIfPreference) { $backup | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $file -Encoding utf8 }   # before any change

foreach ($t in $types) {
    $mine = @($rules | Where-Object { $_.FieldValues.DocumentType -eq $t })
    if ($mine) {
        foreach ($r in $mine) {
            if ($PSCmdlet.ShouldProcess("$t (rule $($r.Id))", "Approver = $Approver")) {
                Set-PnPListItem -List $matrix -Identity $r.Id -Values @{ MandatoryApprovers = @($Approver); FinalApprover = $Approver; IsActive = $true } | Out-Null
            }
        }
        Write-Host "  [set] $t" -ForegroundColor Green
    } elseif ($PSCmdlet.ShouldProcess($t, "New pilot rule, approver $Approver")) {
        $new = Add-PnPListItem -List $matrix -Values @{ Title = "Pilot - $t"; DocumentType = $t; DocumentArea = $area
            MandatoryApprovers = @($Approver); FinalApprover = $Approver; IsActive = $true; SlaDays = 5 }
        $backup.Add([pscustomobject]@{ Id = $new.Id; DocumentType = $t; Created = $true })
        Write-Host "  [new] $t" -ForegroundColor Cyan
    }
}
if (-not $WhatIfPreference) {
    $backup | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $file -Encoding utf8
    Write-Host "$Approver now approves all $(@($types).Count) document types. Backup: $file" -ForegroundColor Green
    Write-Host "To undo after the pilot: .\Set-DmsTestApprover.ps1 -TenantName $TenantName -DocControlSiteAlias $DocControlSiteAlias -ClientId `$C -Restore '$file'"
}
