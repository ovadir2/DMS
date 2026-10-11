#Requires -Version 5.1
<#
.SYNOPSIS
    Department access on the DMS folders, from scripts\dms-access.csv: AD groups per department folder under
    01_General, and the same groups on the parallel folders of every customer (02_Customers\<Customer>\...).

.DESCRIPTION
    dms-access.csv, one row per department folder under 01_General (edit it, Excel keeps the format):
        Department       the folder under 01_General (HR, Enginnering, Quality and Standards, ...)
        Code             short name of the department: its AD groups are named from it. Rows with the same Code
                         share the groups (Company_Profile and Company_Strategy -> Management)
        CustomerFolders  its parallel folders in every customer, ";" between them (Engineering;DFM;DFT). Empty: none
        Members          accounts put in GG_DMS_<Code> by -CreateGroups, ";" between them. Optional
        ReadGroups       Global groups that may only read there, ";" between them. Optional

    AD groups (docs\02-Security-and-Permissions.md: people -> Global group -> Domain Local group -> NTFS):
        GG_DMS_<Code>        Global, the people of the department (Members)
        DL_FS_<Code>_M       Domain Local, Modify: GG_DMS_<Code> + -ModifyAll (Document Control)
        DL_FS_<Code>_R       Domain Local, Read: ReadGroups + -ReadAll (Management, Auditors)
        DL_FS_Admin_F        Domain Local, Full control: GG_DMS_ITAdmins

    Each department folder, and its parallel folder in every customer:
      - does NOT inherit from the folder above (01_General / the customer): only what its row gives
      - SYSTEM, Administrators, DL_FS_Admin_F and the DMS account (-DmsAccount): Full control (the DMS moves the files)
      - DL_FS_<Code>_M: Modify, DL_FS_<Code>_R: Read, on the folder, its subfolders and files
      - DL_FS_<Code>_M may not rename / delete the folder itself nor the blueprint folders below it (their content it may)
    Above them (the root, 01_General, 02_Customers, each customer): the department groups may open that folder only,
    so they can browse down to their own folders. Turn on Access-Based Enumeration on the share: everyone then sees
    only the folders they may open. -RemoveBroad also takes Everyone / Authenticated Users / Domain Users / Users off
    01_General and 02_Customers (else everyone still sees and reads everything outside the department folders).

    Without -Apply it only reports. -Customer <name>: that customer only (the DMS runs it for each new customer,
    DMS_ACCESS_SCRIPT=1). Run as a domain admin / file server admin; -CreateGroups needs the ActiveDirectory
    module (RSAT). Supports -WhatIf. Run it again after changing the table: it is idempotent.

.EXAMPLE
    .\Set-DmsAccess.ps1                                                             # report only
    .\Set-DmsAccess.ps1 -CreateGroups -OU 'OU=DMS,OU=Groups,DC=rh,DC=local' -Apply -WhatIf
    .\Set-DmsAccess.ps1 -CreateGroups -OU 'OU=DMS,OU=Groups,DC=rh,DC=local' -Apply -RemoveBroad

.EXAMPLE
    .\Set-DmsAccess.ps1 -Customer Customer_B -Apply                                 # one new customer
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $Root,                                          # default: DMS_REPOSITORY_ROOT (environment, else webapi\.env)
    [string] $Map = (Join-Path $PSScriptRoot 'dms-access.csv'),
    [string] $Domain = $env:USERDOMAIN,
    [string] $DmsAccount,                                    # default: DMS_SERVICE_ACCOUNT, else you
    [string] $Customer,
    [string[]] $ModifyAll = @('GG_DMS_DocumentControl'),
    [string[]] $ReadAll = @('GG_DMS_Management', 'GG_DMS_Auditors'),
    [switch] $CreateGroups,
    [string] $OU,
    [switch] $RemoveBroad,
    [switch] $ResetChildren,                                 # subfolders / files with their own permissions inherit again
    [switch] $Apply
)
$ErrorActionPreference = 'Stop'

# Settings: the parameter, else the environment variable, else webapi\.env (same file the DMS reads)
$envFile = Join-Path $PSScriptRoot '..\webapi\.env'
function Get-DmsSetting([string]$Name) {
    $v = [Environment]::GetEnvironmentVariable($Name)
    if ($v) { return $v.Trim() }
    if (-not (Test-Path -LiteralPath $envFile)) { return '' }
    $line = Get-Content -LiteralPath $envFile -Encoding UTF8 | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -Last 1
    if (-not $line) { return '' }
    (($line -split '=', 2)[1] -replace '\s+#.*$', '').Trim().Trim('"').Trim("'")
}
if (-not $Root) { $Root = Get-DmsSetting 'DMS_REPOSITORY_ROOT' }
if (-not $Root -or -not (Test-Path -LiteralPath $Root)) { throw "Repository root not found: '$Root'. Set DMS_REPOSITORY_ROOT in webapi\.env or give -Root." }
$Root = $Root.TrimEnd('\')
if (-not $DmsAccount) { $DmsAccount = Get-DmsSetting 'DMS_SERVICE_ACCOUNT' }
if (-not $DmsAccount) { $DmsAccount = "$env:USERDOMAIN\$env:USERNAME"; Write-Warning "No DMS_SERVICE_ACCOUNT: the DMS account is taken to be you ($DmsAccount)." }
$custFolder = Get-DmsSetting 'DMS_CUSTOMERS_FOLDER'; if (-not $custFolder) { $custFolder = '02_Customers' }
if ($CreateGroups -and $Apply -and -not $OU) { throw '-CreateGroups needs -OU (where the groups are created), e.g. OU=DMS,OU=Groups,DC=rh,DC=local' }

function Split-List([string]$v) { @("$v" -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
function Q([string]$name) { if ($name -match '\\') { $name } else { "$Domain\$name" } }
function Get-Sid([string]$name) { try { (New-Object Security.Principal.NTAccount (Q $name)).Translate([Security.Principal.SecurityIdentifier]) } catch { $null } }
function GG([string]$c) { "GG_DMS_$c" }
function DLM([string]$c) { "DL_FS_$($c)_M" }
function DLR([string]$c) { "DL_FS_$($c)_R" }

$rows = @(Import-Csv -LiteralPath $Map -Encoding UTF8 | Where-Object { $_.Department -and $_.Code })
foreach ($r in $rows) { if ($r.Code -notmatch '^[A-Za-z0-9_-]+$') { throw "Code '$($r.Code)' ($($r.Department)): letters, digits, _ and - only" } }
$codes = @($rows | ForEach-Object { $_.Code } | Select-Object -Unique)

# ---- AD groups --------------------------------------------------------------------------------------------------
if ($CreateGroups) {
    Import-Module ActiveDirectory
    function Find-Group([string]$n) { Get-ADGroup -Filter "SamAccountName -eq '$n'" -ErrorAction SilentlyContinue }
    function Ensure-Group([string]$n, [string]$scope, [string]$desc) {
        if (Find-Group $n) { return }
        if ($Apply -and $PSCmdlet.ShouldProcess($n, "Create AD group ($scope) in $OU")) {
            New-ADGroup -Name $n -SamAccountName $n -GroupScope $scope -GroupCategory Security -Path $OU -Description $desc
            Write-Host "  + group $n ($scope)" -ForegroundColor Green
        } elseif (-not $Apply) { Write-Host "  group to create: $n ($scope)" -ForegroundColor Yellow }
    }
    function Ensure-Member([string]$group, [string]$member) {
        $g = Find-Group $group
        $has = $g -and (Get-ADGroupMember -Identity $group | Where-Object { $_.SamAccountName -eq $member })
        if ($has) { return }
        if ($Apply -and $PSCmdlet.ShouldProcess($group, "Add $member")) {
            Add-ADGroupMember -Identity $group -Members $member; Write-Host "  + $member in $group" -ForegroundColor Green
        } elseif (-not $Apply) { Write-Host "  to add: $member in $group" -ForegroundColor Yellow }
    }
    Write-Host "AD groups ($OU)" -ForegroundColor Cyan
    $globals = @($ModifyAll + $ReadAll + 'GG_DMS_ITAdmins' + @($rows | ForEach-Object { Split-List $_.ReadGroups }) | Select-Object -Unique)
    foreach ($c in $codes) { Ensure-Group (GG $c) Global "DMS: people of $c" }
    foreach ($n in $globals) { if ($n -notin @($codes | ForEach-Object { GG $_ })) { Ensure-Group $n Global "DMS role group" } }
    Ensure-Group 'DL_FS_Admin_F' DomainLocal 'DMS folders: Full control'
    Ensure-Member 'DL_FS_Admin_F' 'GG_DMS_ITAdmins'
    foreach ($c in $codes) {
        $deps = ($rows | Where-Object { $_.Code -eq $c } | ForEach-Object { $_.Department }) -join ', '
        Ensure-Group (DLM $c) DomainLocal "DMS folders of $deps (and in every customer): Modify"
        Ensure-Group (DLR $c) DomainLocal "DMS folders of $deps (and in every customer): Read"
        Ensure-Member (DLM $c) (GG $c)
        foreach ($m in $ModifyAll) { Ensure-Member (DLM $c) $m }
        foreach ($m in @($ReadAll + @($rows | Where-Object { $_.Code -eq $c } | ForEach-Object { Split-List $_.ReadGroups })) | Select-Object -Unique) { Ensure-Member (DLR $c) $m }
        foreach ($m in @($rows | Where-Object { $_.Code -eq $c } | ForEach-Object { Split-List $_.Members }) | Select-Object -Unique) { Ensure-Member (GG $c) $m }
    }
}

# ---- which folders --------------------------------------------------------------------------------------------
$bp = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'blueprint-folders.txt') -Encoding UTF8 | ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and $_ -notlike '*<Product>*' })
$targets = [ordered]@{}     # department folder -> @{ Key = its blueprint line; Codes }
$parents = [ordered]@{}     # folder above -> codes that may open it
$absent = @()
function Add-Parent([string]$p, [string]$c) {
    if (-not $parents.Contains($p)) { $parents[$p] = New-Object Collections.Generic.List[string] }
    if (-not $parents[$p].Contains($c)) { $parents[$p].Add($c) }
}
function Add-Target([string]$full, [string]$key, [string]$c, [string[]]$above) {
    if (-not (Test-Path -LiteralPath $full -PathType Container)) { $script:absent += $full; return }
    if (-not $targets.Contains($full)) { $targets[$full] = @{ Key = $key; Codes = (New-Object Collections.Generic.List[string]) } }
    if (-not $targets[$full].Codes.Contains($c)) { $targets[$full].Codes.Add($c) }
    foreach ($p in $above) { Add-Parent $p $c }
}
$custRoot = Join-Path $Root $custFolder
if ($Customer) {
    if (-not (Test-Path -LiteralPath (Join-Path $custRoot $Customer) -PathType Container)) { throw "Customer folder not found: $(Join-Path $custRoot $Customer)" }
    $customers = @($Customer)
} else {
    $customers = @(Get-ChildItem -LiteralPath $custRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object Name)
}
foreach ($r in $rows) {
    if (-not $Customer) {
        Add-Target (Join-Path $Root "01_General\$($r.Department)") "01_General\$($r.Department)" $r.Code @($Root, (Join-Path $Root '01_General'))
    }
    foreach ($f in Split-List $r.CustomerFolders) {
        foreach ($c in $customers) {
            Add-Target (Join-Path $custRoot "$c\$f") "02_Customers\<Customer>\$f" $r.Code @($Root, $custRoot, (Join-Path $custRoot $c))
        }
    }
}

# ---- permissions ------------------------------------------------------------------------------------------------
$CIOI = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
$NONE = [Security.AccessControl.InheritanceFlags]::None
$FULL = [Security.AccessControl.FileSystemRights]::FullControl
$MODIFY = [Security.AccessControl.FileSystemRights]'Modify, Synchronize'
$READ = [Security.AccessControl.FileSystemRights]'ReadAndExecute, Synchronize'
$DELETE = [Security.AccessControl.FileSystemRights]::Delete
$SID_TYPE = [Security.Principal.SecurityIdentifier]
function Rule($sid, $rights, $inherit, [string]$type = 'Allow') {
    New-Object Security.AccessControl.FileSystemAccessRule($sid, $rights, $inherit, [Security.AccessControl.PropagationFlags]::None, $type)
}
function Key-Of($r) { "$($r.IdentityReference.Value)|$([int]$r.FileSystemRights)|$([int]$r.InheritanceFlags)|$($r.AccessControlType)" }
function Explicit($acl) { @($acl.GetAccessRules($true, $false, $SID_TYPE)) }
# folder permissions (the Access part only: owner untouched), in Windows PowerShell and PowerShell 7
function Read-Acl([string]$p) {
    $i = Get-Item -LiteralPath $p
    if ($i.PSObject.Methods['GetAccessControl']) { $i.GetAccessControl('Access') } else { [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]$i, 'Access') }
}
function Write-Acl([string]$p, $acl) {
    $i = Get-Item -LiteralPath $p
    if ($i.PSObject.Methods['SetAccessControl']) { $i.SetAccessControl($acl) } else { [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]$i, $acl) }
}

$missingGroups = @{}
function Sid-Or-Note([string]$name) {
    $s = Get-Sid $name
    if (-not $s) { $missingGroups[(Q $name)] = $true }
    $s
}
$fixed = @(
    (New-Object Security.Principal.SecurityIdentifier 'S-1-5-18'),        # SYSTEM
    (New-Object Security.Principal.SecurityIdentifier 'S-1-5-32-544'),    # Administrators
    (Sid-Or-Note 'DL_FS_Admin_F'),
    (Sid-Or-Note $DmsAccount)
) | Where-Object { $_ }

function Desired-Rules($codesHere) {
    $rules = @($fixed | ForEach-Object { Rule $_ $FULL $CIOI })
    foreach ($c in $codesHere) {
        $m = Sid-Or-Note (DLM $c); $r = Sid-Or-Note (DLR $c)
        if ($m) { $rules += Rule $m $MODIFY $CIOI; $rules += Rule $m $DELETE $NONE 'Deny' }   # no rename / delete of the folder
        if ($r) { $rules += Rule $r $READ $CIOI }
    }
    $rules
}

Write-Host "`nRepository: $Root   DMS account: $DmsAccount$(if ($Customer) { "   Customer: $Customer" })" -ForegroundColor Cyan
$changes = 0
foreach ($path in $targets.Keys) {
    $t = $targets[$path]
    $acl = Read-Acl $path
    $want = Desired-Rules $t.Codes
    $same = $acl.AreAccessRulesProtected -and
            (@($want | ForEach-Object { Key-Of $_ } | Sort-Object -Unique) -join ';') -eq (@(Explicit $acl | ForEach-Object { Key-Of $_ } | Sort-Object -Unique) -join ';')
    Write-Host ("{0,-9} {1}  [{2}]" -f $(if ($same) { 'ok' } else { 'CHANGE' }), $path, ($t.Codes -join ', ')) -ForegroundColor $(if ($same) { 'Gray' } else { 'Yellow' })
    if (-not $Apply) { if (-not $same) { $changes++ }; continue }
    if (-not $same -and $PSCmdlet.ShouldProcess($path, "No inheritance; Full: SYSTEM, Administrators, DL_FS_Admin_F, DMS account; Modify / Read: $($t.Codes -join ', ')")) {
        $new = New-Object Security.AccessControl.DirectorySecurity
        $new.SetAccessRuleProtection($true, $false)               # nothing from 01_General / the customer above
        foreach ($r in $want) { $new.AddAccessRule($r) }
        Write-Acl $path $new
        $changes++
    }
    if ($ResetChildren -and $PSCmdlet.ShouldProcess("$path\*", 'Subfolders and files inherit again (own permissions removed)')) {
        icacls "$path\*" /reset /T /C /Q | Out-Null
    }
    # the blueprint folders below: the department may not rename / delete them either
    $below = @($bp | Where-Object { $_.StartsWith("$($t.Key)\", [StringComparison]::OrdinalIgnoreCase) })
    foreach ($line in $below) {
        $rel = $line.Substring($t.Key.Length + 1)
        $sub = Join-Path $path $rel
        if (-not (Test-Path -LiteralPath $sub -PathType Container)) { continue }
        $sa = Read-Acl $sub
        $keys = @(Explicit $sa | ForEach-Object { Key-Of $_ })
        $add = @($t.Codes | ForEach-Object { Get-Sid (DLM $_) } | Where-Object { $_ } | ForEach-Object { Rule $_ $DELETE $NONE 'Deny' } |
                 Where-Object { (Key-Of $_) -notin $keys })
        if ($add.Count -and $PSCmdlet.ShouldProcess($sub, 'No rename / delete (blueprint folder)')) {
            foreach ($r in $add) { $sa.AddAccessRule($r) }
            Write-Acl $sub $sa
        }
    }
}

# the folders above: open (this folder only), so a department can browse down to its folders
foreach ($p in $parents.Keys) {
    $acl = Read-Acl $p
    $keys = @(Explicit $acl | ForEach-Object { Key-Of $_ })
    $add = @($parents[$p] | ForEach-Object { (Get-Sid (DLM $_)), (Get-Sid (DLR $_)) } | Where-Object { $_ } |
             ForEach-Object { Rule $_ $READ $NONE } | Where-Object { (Key-Of $_) -notin $keys })
    if (-not $add.Count) { continue }
    Write-Host ("{0,-9} {1}  (open only: {2})" -f 'CHANGE', $p, ($parents[$p] -join ', ')) -ForegroundColor Yellow
    if ($Apply -and $PSCmdlet.ShouldProcess($p, "Open this folder only: $($parents[$p] -join ', ')")) {
        foreach ($r in $add) { $acl.AddAccessRule($r) }
        Write-Acl $p $acl
    }
    $changes++
}

# broad groups that let everyone see / read outside the department folders
$broad = { param($sid) $v = $sid.Value; $v -in 'S-1-1-0', 'S-1-5-11', 'S-1-5-32-545' -or $v -match '^S-1-5-21-.+-513$' }
if (-not $Customer) {
    foreach ($top in @((Join-Path $Root '01_General'), $custRoot) | Where-Object { Test-Path -LiteralPath $_ }) {
        $acl = Read-Acl $top
        $hits = @($acl.GetAccessRules($true, $true, $SID_TYPE) | Where-Object { & $broad $_.IdentityReference })
        if (-not $hits.Count) { continue }
        $names = ($hits | ForEach-Object { try { $_.IdentityReference.Translate([Security.Principal.NTAccount]).Value } catch { $_.IdentityReference.Value } } | Select-Object -Unique) -join ', '
        if (-not ($Apply -and $RemoveBroad)) { Write-Warning "$top is open to ${names}: everyone sees it. -RemoveBroad takes them off."; continue }
        if ($PSCmdlet.ShouldProcess($top, "Remove $names (keep the other permissions)")) {
            $acl.SetAccessRuleProtection($true, $true)                # keep what came from above as own rules
            Write-Acl $top $acl
            $acl = Read-Acl $top
            foreach ($r in @($acl.GetAccessRules($true, $false, $SID_TYPE) | Where-Object { & $broad $_.IdentityReference })) { [void]$acl.RemoveAccessRuleSpecific($r) }
            Write-Acl $top $acl
            Write-Host "  - $names on $top" -ForegroundColor Green
        }
    }
}

if ($absent.Count) { Write-Host "`nNot found (no folder, nothing done): $($absent.Count)"; $absent | Select-Object -First 20 | ForEach-Object { Write-Host "    $_" } }
if ($missingGroups.Count) { Write-Warning "Not in AD (left out): $(@($missingGroups.Keys) -join ', '). Create them with -CreateGroups -OU <OU> -Apply." }
if (-not $Apply) { Write-Host "`nReport only: $changes folder(s) to change. Run again with -Apply (-WhatIf first)." -ForegroundColor Yellow }
else { Write-Host "`nDone: $changes folder(s). Members of a new group must sign out and in again." -ForegroundColor Green }
