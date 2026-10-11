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
    New groups are Global security groups in -OU (default: OU=DMS at the top of the domain, made if missing).
    Safe for the AD you have: it only creates groups and adds members, inside -OU. It never deletes or changes a
    user, an OU or a group outside -OU (a group of the same name elsewhere is reported and left as it is).
    Members are only added; -Exact also removes members that are not in the table (only in the DMS groups of -OU).
    Without -Apply it only reports. Supports -WhatIf.
    Talks to AD directly (ADSI, built into Windows): no RSAT / ActiveDirectory module and no administrator window
    needed - only an account that may create groups in -OU (a domain admin, or one IT delegated the OU to).

.EXAMPLE
    .\Set-DmsAdGroups.ps1                     # report only
    .\Set-DmsAdGroups.ps1 -Apply -WhatIf
    .\Set-DmsAdGroups.ps1 -Apply
    .\Set-DmsAdGroups.ps1 -OU 'OU=DMS,OU=Groups,DC=rh,DC=local' -Apply      # another OU
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $OU,                                            # where new groups are made (default: OU=DMS,<your domain>)
    [string] $Map = (Join-Path $PSScriptRoot 'dms-ad-groups.csv'),
    [switch] $Exact,
    [switch] $Apply
)
$ErrorActionPreference = 'Stop'
$GLOBAL_SECURITY = -2147483646                               # groupType: Global + Security

function Find-One([string]$filter) {
    $s = New-Object DirectoryServices.DirectorySearcher([ADSI]"LDAP://$domainDn", $filter)
    $s.PropertiesToLoad.AddRange(@('distinguishedName', 'sAMAccountName', 'objectClass'))
    $s.FindOne()
}
function Esc([string]$v) { $v -replace '([\\*()])', '\$1' }
function Exists([string]$dn) { try { [ADSI]::Exists("LDAP://$dn") } catch { $false } }

try { $domainDn = ([ADSI]'LDAP://RootDSE').defaultNamingContext.Value } catch { throw "No domain controller reached from this PC ($($_.Exception.Message))." }
if (-not $OU) { $OU = "OU=DMS,$domainDn" }
if (-not (Exists $OU)) {
    if ($OU -ne "OU=DMS,$domainDn") { throw "OU not found: $OU" }
    Write-Host "CREATE    OU $OU" -ForegroundColor Yellow
    if ($Apply -and $PSCmdlet.ShouldProcess($OU, 'Create OU')) {
        $o = ([ADSI]"LDAP://$domainDn").Create('organizationalUnit', 'OU=DMS')
        $o.Put('description', 'RH DMS: department groups (Set-DmsAdGroups.ps1)')
        $o.SetInfo()
    }
}

function Split-List([string]$v) { @("$v" -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notlike '<*' }) }
$rows = @(Import-Csv -LiteralPath $Map -Encoding UTF8 | Where-Object { $_.Group })
$todo = 0
Write-Host "Domain: $domainDn   OU: $OU" -ForegroundColor Cyan
foreach ($r in $rows) {
    $name = $r.Group.Trim()
    $hit = Find-One "(&(objectClass=group)(sAMAccountName=$(Esc $name)))"
    $g = $null
    if (-not $hit) {
        $todo++
        Write-Host "CREATE    $name  ($($r.Description))" -ForegroundColor Yellow
        if ($Apply -and (Exists $OU) -and $PSCmdlet.ShouldProcess($name, "Create Global security group in $OU")) {
            $g = ([ADSI]"LDAP://$OU").Create('group', "CN=$name")
            $g.Put('sAMAccountName', $name)
            $g.Put('groupType', $GLOBAL_SECURITY)
            if ($r.Description) { $g.Put('description', "$($r.Description)") }
            $g.SetInfo()
        }
    } else {
        $dn = "$($hit.Properties['distinguishedname'][0])"
        if (-not $dn.EndsWith(",$OU", [StringComparison]::OrdinalIgnoreCase)) {
            # a group of the same name that is not the DMS's: never changed (no member added or removed)
            Write-Warning "$name already exists outside $OU ($dn): left as it is. Rename the group in the tables."
            continue
        }
        Write-Host "ok        $name" -ForegroundColor Gray
        $g = [ADSI]"LDAP://$dn"
    }
    $now = @(if ($g -and $g.Properties['member']) { $g.Properties['member'] | ForEach-Object { "$_" } })
    $want = @()
    foreach ($m in Split-List $r.Members) {
        $acc = Find-One "(sAMAccountName=$(Esc (($m -split '\\')[-1])))"
        if (-not $acc) { Write-Warning "  $m not found in AD (not added to $name)"; continue }
        $mdn = "$($acc.Properties['distinguishedname'][0])"
        $want += $mdn
        if ($now -contains $mdn) { continue }
        $todo++
        Write-Host "  + $m in $name" -ForegroundColor Yellow
        if ($Apply -and $g -and $PSCmdlet.ShouldProcess($name, "Add $m")) { $g.Add("LDAP://$mdn") }
    }
    if ($Exact -and $g) {
        foreach ($mdn in $now | Where-Object { $_ -notin $want }) {
            $todo++
            Write-Host "  - $mdn from $name" -ForegroundColor Yellow
            if ($Apply -and $PSCmdlet.ShouldProcess($name, "Remove $mdn")) { $g.Remove("LDAP://$mdn") }
        }
    }
}
if (-not $Apply) { Write-Host "`nReport only: $todo change(s). Run again with -Apply (-WhatIf first)." -ForegroundColor Yellow }
else { Write-Host "`nDone: $todo change(s). Next: Set-DmsAccess.ps1 (puts the groups on the folders). People just added sign out and in again." -ForegroundColor Green }
