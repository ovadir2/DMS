#Requires -Version 5.1
<#
.SYNOPSIS
    Department access on the DMS folders: puts your existing AD groups (from scripts\dms-access.csv) on each
    department folder under 01_General, and on its parallel folders in every customer (02_Customers\<Customer>\...).
    Groups and members stay managed in AD: this script creates no group and adds no member.

.DESCRIPTION
    dms-access.csv, one row per department folder (edit it, Excel keeps the format):
        Department       the folder under 01_General (HR, Enginnering, Quality and Standards, ...), or a path from the
                         root for one folder only (02_Customers\Customer_A\Engineering: that customer's, not the others;
                         02_Customers\Customer_A: the whole customer, all its folders)
        Groups           the AD groups that work there (Modify), ";" between them (RH\HR_Team). A <placeholder>: row skipped
        CustomerFolders  its parallel folders in every customer, ";" between them (Engineering;DFM;DFT). Empty: none
        ReadGroups       AD groups that may only read there, ";" between them. Optional
        Inherit          No: the folder takes nothing from the folder above (HR: closed to whoever has rights on
                         01_General). Empty / Yes: it keeps what it inherits. A row "01_General" (or "02_Customers") gives
                         its groups rights on that whole level: managers on 01_General

    Each department folder, and its parallel folder in every customer:
      - keeps what it inherits from above (unless Inherit = No): a group on an upper folder (01_General, 02_Customers,
        a customer) has the same rights in every folder below it - an upper folder never gives less than its subfolders
      - SYSTEM, Administrators and the DMS account (-DmsAccount): Full control (the DMS moves the files)
      - Groups: Modify, ReadGroups: Read, on the folder, its subfolders and files
      - Groups may not rename / delete the folder itself nor the blueprint folders below it (their content they may)
    Above them (the root, 01_General, 02_Customers, each customer): those groups may open that folder only, so they
    can browse down to their own folders. Turn on Access-Based Enumeration on the share: everyone then sees only the
    folders they may open. -RemoveBroad also takes Everyone / Authenticated Users / Domain Users / Users off
    01_General and 02_Customers (else everyone still sees and reads everything outside the department folders).

    Without -Apply it only reports. -Customer <name>: that customer only (the DMS runs it for each new customer,
    DMS_ACCESS_SCRIPT=1). Run as a file server admin. Supports -WhatIf. Run it again after changing the table or
    adding customers: it is idempotent (changes only what differs).

.EXAMPLE
    .\Set-DmsAccess.ps1                                  # report only
    .\Set-DmsAccess.ps1 -Apply -WhatIf
    .\Set-DmsAccess.ps1 -Apply -RemoveBroad

.EXAMPLE
    .\Set-DmsAccess.ps1 -Customer Customer_B -Apply      # one new customer
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $Root,                                      # default: DMS_REPOSITORY_ROOT (environment, else webapi\.env)
    [string] $Map = (Join-Path $PSScriptRoot 'dms-access.csv'),
    [string] $Domain = $env:USERDOMAIN,                  # for group names written without "DOMAIN\"
    [string] $DmsAccount,                                # default: DMS_SERVICE_ACCOUNT, else you
    [string] $Customer,
    [switch] $RemoveBroad,
    [switch] $ResetChildren,                             # subfolders / files with their own permissions inherit again
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

function Split-List([string]$v) { @("$v" -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notlike '<*' }) }
function Q([string]$name) { if ($name -match '\\') { $name } else { "$Domain\$name" } }
function Get-Sid([string]$name) { try { (New-Object Security.Principal.NTAccount (Q $name)).Translate([Security.Principal.SecurityIdentifier]) } catch { $null } }

$rows = @(Import-Csv -LiteralPath $Map -Encoding UTF8 | Where-Object { $_.Department })
$skipped = @($rows | Where-Object { -not (Split-List $_.Groups).Count } | ForEach-Object Department)
$rows = @($rows | Where-Object { (Split-List $_.Groups).Count })
# what a row gives: "M|group" (Modify) and "R|group" (Read)
function Grants($r) { @(Split-List $r.Groups | ForEach-Object { "M|$(Q $_)" }) + @(Split-List $r.ReadGroups | ForEach-Object { "R|$(Q $_)" }) }

# ---- which folders --------------------------------------------------------------------------------------------
$bp = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'blueprint-folders.txt') -Encoding UTF8 | ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and $_ -notlike '*<Product>*' })
$targets = [ordered]@{}     # department folder -> @{ Key = its blueprint line; Codes = its grants (M|group, R|group) }
$parents = [ordered]@{}     # folder above -> groups that may open it
$absent = @()
function Add-Parent([string]$p, [string]$c) {
    if (-not $parents.Contains($p)) { $parents[$p] = New-Object Collections.Generic.List[string] }
    if (-not $parents[$p].Contains($c)) { $parents[$p].Add($c) }
}
function Add-Target([string]$full, [string]$key, [string[]]$grants, [string[]]$above, [bool]$protect) {
    if (-not (Test-Path -LiteralPath $full -PathType Container)) { $script:absent += $full; return }
    if (-not $targets.Contains($full)) { $targets[$full] = @{ Key = $key; Codes = (New-Object Collections.Generic.List[string]); Protect = $false } }
    if ($protect) { $targets[$full].Protect = $true }
    foreach ($c in $grants) {
        if (-not $targets[$full].Codes.Contains($c)) { $targets[$full].Codes.Add($c) }
        foreach ($p in $above) { Add-Parent $p $c.Substring(2) }
    }
}
$custRoot = Join-Path $Root $custFolder
if ($Customer) {
    if (-not (Test-Path -LiteralPath (Join-Path $custRoot $Customer) -PathType Container)) { throw "Customer folder not found: $(Join-Path $custRoot $Customer)" }
    $customers = @($Customer)
} else {
    $customers = @(Get-ChildItem -LiteralPath $custRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object Name)
}
foreach ($r in $rows) {
    $protect = "$($r.Inherit)".Trim() -match '^(no|n|false|0)$'      # Inherit = No: nothing from the folder above
    if ($r.Department -match '\\' -or $r.Department -in '01_General', $custFolder) {   # a path from the root: that one folder
        $parts = @($r.Department.Trim('\') -split '\\')
        $isCust = $parts.Count -gt 2 -and $parts[0] -eq $custFolder
        if ($Customer -and -not ($isCust -and $parts[1] -eq $Customer)) { continue }
        $key = if ($isCust) { (@('02_Customers', '<Customer>') + $parts[2..($parts.Count - 1)]) -join '\' } else { $parts -join '\' }
        $above = @($Root) + @(for ($i = 1; $i -lt $parts.Count; $i++) { Join-Path $Root ($parts[0..($i - 1)] -join '\') })
        Add-Target (Join-Path $Root ($parts -join '\')) $key (Grants $r) $above $protect
        continue
    }
    if (-not $Customer) {
        Add-Target (Join-Path $Root "01_General\$($r.Department)") "01_General\$($r.Department)" (Grants $r) @($Root, (Join-Path $Root '01_General')) $protect
    }
    foreach ($f in Split-List $r.CustomerFolders) {
        foreach ($c in $customers) {
            Add-Target (Join-Path $custRoot "$c\$f") "02_Customers\<Customer>\$f" (Grants $r) @($Root, $custRoot, (Join-Path $custRoot $c)) $protect
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
    (Sid-Or-Note $DmsAccount)
) | Where-Object { $_ }

function Desired-Rules($grants, [string]$path) {
    $rules = @($fixed | ForEach-Object { Rule $_ $FULL $CIOI })
    if ($parents.Contains($path)) {                        # also above other department folders: they may open it
        foreach ($g in $parents[$path]) { $sid = Get-Sid $g; if ($sid) { $rules += Rule $sid $READ $NONE } }
    }
    foreach ($c in $grants) {
        $sid = Sid-Or-Note $c.Substring(2)
        if (-not $sid) { continue }
        if ($c.StartsWith('M|')) { $rules += Rule $sid $MODIFY $CIOI; $rules += Rule $sid $DELETE $NONE 'Deny' }   # no rename / delete of the folder
        else { $rules += Rule $sid $READ $CIOI }
    }
    $rules
}

Write-Host "`nRepository: $Root   DMS account: $DmsAccount$(if ($Customer) { "   Customer: $Customer" })" -ForegroundColor Cyan
$changes = 0
foreach ($path in $targets.Keys) {
    $t = $targets[$path]
    $acl = Read-Acl $path
    $want = Desired-Rules $t.Codes $path
    $same = $acl.AreAccessRulesProtected -eq $t.Protect -and
            (@($want | ForEach-Object { Key-Of $_ } | Sort-Object -Unique) -join ';') -eq (@(Explicit $acl | ForEach-Object { Key-Of $_ } | Sort-Object -Unique) -join ';')
    Write-Host ("{0,-9} {1}  [{2}]" -f $(if ($same) { 'ok' } else { 'CHANGE' }), $path, ($t.Codes -join ', ')) -ForegroundColor $(if ($same) { 'Gray' } else { 'Yellow' })
    if (-not $Apply) { if (-not $same) { $changes++ }; continue }
    if (-not $same -and $PSCmdlet.ShouldProcess($path, "$(if ($t.Protect) { 'No inheritance' } else { 'Inherits from above' }), Full: SYSTEM, Administrators, DMS account; $($t.Codes -join ', ')")) {
        $new = New-Object Security.AccessControl.DirectorySecurity
        $new.SetAccessRuleProtection($t.Protect, $false)          # Inherit = No: nothing from above; else inherits (its own rules are these)
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
        $add = @($t.Codes | Where-Object { $_.StartsWith('M|') } | ForEach-Object { Get-Sid $_.Substring(2) } | Where-Object { $_ } | ForEach-Object { Rule $_ $DELETE $NONE 'Deny' } |
                 Where-Object { (Key-Of $_) -notin $keys })
        if ($add.Count -and $PSCmdlet.ShouldProcess($sub, 'No rename / delete (blueprint folder)')) {
            foreach ($r in $add) { $sa.AddAccessRule($r) }
            Write-Acl $sub $sa
        }
    }
}

# the folders above: open (this folder only), so a department can browse down to its folders
foreach ($p in $parents.Keys) {
    if ($targets.Contains($p)) { continue }                # set with its own row above
    $acl = Read-Acl $p
    $keys = @(Explicit $acl | ForEach-Object { Key-Of $_ })
    $add = @($parents[$p] | ForEach-Object { Get-Sid $_ } | Where-Object { $_ } |
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
if ($skipped.Count) { Write-Host "`nNo group filled in yet (skipped): $($skipped -join ', ')" }
if ($missingGroups.Count) { Write-Warning "Not found in AD (left out): $(@($missingGroups.Keys) -join ', '). Check the names in $Map." }
if (-not $Apply) { Write-Host "`nReport only: $changes folder(s) to change. Run again with -Apply (-WhatIf first)." -ForegroundColor Yellow }
else { Write-Host "`nDone: $changes folder(s). Someone just added to a group must sign out and in again." -ForegroundColor Green }
