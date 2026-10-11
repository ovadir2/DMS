#Requires -Version 5.1
<#
.SYNOPSIS
    Defines the DMS department groups in Active Directory from scripts\dms-ad-groups.csv: creates the groups
    that are missing and puts the listed people in them. Set-DmsAccess.ps1 then puts the groups on the folders.

.DESCRIPTION
    dms-ad-groups.csv (edit it, Excel keeps the format):
        Group        the group's name (sAMAccountName), e.g. GG_DMS_Engineering. Use the same name in dms-access.csv
        Description  shown in AD (which folders it opens)
        Members      user or group accounts (sAMAccountName), ";" between them: dms_approval;dms-lab
    New groups are Global security groups in -OU. Members are only added; -Exact also removes members that are
    not in the table (for groups the DMS owns only). Without -Apply it only reports.
    Run as a domain admin (or a user allowed to manage groups in -OU), with the ActiveDirectory module (RSAT:
    Settings > Optional features > "RSAT: Active Directory Domain Services"). Supports -WhatIf.

.EXAMPLE
    .\Set-DmsAdGroups.ps1 -OU 'OU=DMS,OU=Groups,DC=rh,DC=local'                  # report only
    .\Set-DmsAdGroups.ps1 -OU 'OU=DMS,OU=Groups,DC=rh,DC=local' -Apply -WhatIf
    .\Set-DmsAdGroups.ps1 -OU 'OU=DMS,OU=Groups,DC=rh,DC=local' -Apply
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)] [string] $OU,                     # where new groups are made: OU=DMS,OU=Groups,DC=rh,DC=local
    [string] $Map = (Join-Path $PSScriptRoot 'dms-ad-groups.csv'),
    [switch] $Exact,
    [switch] $Apply
)
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
try { Get-ADOrganizationalUnit -Identity $OU | Out-Null } catch { throw "OU not found: $OU (Get-ADOrganizationalUnit -Filter * | Select DistinguishedName lists them)" }

function Split-List([string]$v) { @("$v" -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
function Find-Account([string]$n) {
    $n = ($n -split '\\')[-1]
    Get-ADObject -Filter "sAMAccountName -eq '$n'" -Properties sAMAccountName | Where-Object { $_.ObjectClass -in 'user', 'group', 'computer' } | Select-Object -First 1
}

$rows = @(Import-Csv -LiteralPath $Map -Encoding UTF8 | Where-Object { $_.Group })
$todo = 0
foreach ($r in $rows) {
    $name = $r.Group.Trim()
    $g = Get-ADGroup -Filter "sAMAccountName -eq '$name'" -Properties Description
    if (-not $g) {
        $todo++
        Write-Host "CREATE    $name  ($($r.Description))" -ForegroundColor Yellow
        if ($Apply -and $PSCmdlet.ShouldProcess($name, "Create Global security group in $OU")) {
            New-ADGroup -Name $name -SamAccountName $name -GroupScope Global -GroupCategory Security -Path $OU -Description $r.Description
            $g = Get-ADGroup -Identity $name -Properties Description
        }
    } else {
        Write-Host "ok        $name" -ForegroundColor Gray
        if ($r.Description -and $g.Description -ne $r.Description -and $Apply -and $PSCmdlet.ShouldProcess($name, 'Update description')) {
            Set-ADGroup -Identity $g -Description $r.Description
        }
    }
    $now = if ($g) { @(Get-ADGroupMember -Identity $g | ForEach-Object { $_.SamAccountName }) } else { @() }
    $want = @()
    foreach ($m in Split-List $r.Members) {
        $a = Find-Account $m
        if (-not $a) { Write-Warning "  $m not found in AD (not added to $name)"; continue }
        $want += $a.sAMAccountName
        if ($a.sAMAccountName -in $now) { continue }
        $todo++
        Write-Host "  + $($a.sAMAccountName) in $name" -ForegroundColor Yellow
        if ($Apply -and $g -and $PSCmdlet.ShouldProcess($name, "Add $($a.sAMAccountName)")) { Add-ADGroupMember -Identity $g -Members $a.DistinguishedName }
    }
    if ($Exact) {
        foreach ($m in $now | Where-Object { $_ -notin $want }) {
            $todo++
            Write-Host "  - $m from $name" -ForegroundColor Yellow
            if ($Apply -and $PSCmdlet.ShouldProcess($name, "Remove $m")) { Remove-ADGroupMember -Identity $g -Members $m -Confirm:$false }
        }
    }
}
if (-not $Apply) { Write-Host "`nReport only: $todo change(s). Run again with -Apply (-WhatIf first)." -ForegroundColor Yellow }
else { Write-Host "`nDone: $todo change(s). Next: .\Set-DmsAccess.ps1 (puts the groups on the folders). People just added sign out and in again." -ForegroundColor Green }
