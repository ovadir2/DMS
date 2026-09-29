#Requires -Version 5.1
<#
.SYNOPSIS
    Builds the on-premises DMS repository tree on the file server (docs/01 §4, docs/02 §3)
    and, optionally, the Domain Local groups and NTFS permissions.

.DESCRIPTION
    Two modes.

    Tree mode (default) - creates the repository root:
        01_Management\<area folders>
        02_Customers\<Customer>\{Customer_Profile, Commercial, Projects, Shared, Archive}
        03_Operations_Staging\{PLM_Release_Queue, MAE_Release_Queue, Priority_Import_Queue, Integration_Logs}
        04_Workflow_System\{Submitted_Queue, Rejected_Queue, Processing, Error_Queue}
        05_Exchange_Quarantine\{Inbound, Accepted, Rejected, Logs}

    Document mode (-DocumentId) - creates the controlled-document folder for one document:
        <Area folder>\<DocumentId>_<ShortTitle>\{Working, Submitted, Current_ReadOnly, Obsolete_ReadOnly}
    This is what the Workflow Service does for every new document; use it by hand for the pilot.

    Idempotent: existing folders are kept. Supports -WhatIf.

.PARAMETER Root
    Repository root, e.g. \\FILE-SERVER\Corporate_Data or D:\Corporate_Data. For a test use a
    separate folder, e.g. D:\Corporate_Data_TEST.

.PARAMETER Customers
    Customer folder names to create under 02_Customers (optionally with -Projects).

.PARAMETER ApplyAcl
    Break inheritance and apply the NTFS permissions from docs/02 §3.2. Run on the file server
    (or with admin rights on the share) as a member of GG_DMS_ITAdmins. The groups must exist
    in AD (use -CreateAdGroups).

.PARAMETER CreateAdGroups
    Create the DL_FS_* Domain Local groups in -GroupOU and nest the GG_* groups that exist in AD.
    Needs the ActiveDirectory module (RSAT).

.EXAMPLE
    # Pilot: tree only, on a test folder
    .\New-DmsFileServerTree.ps1 -Root 'D:\Corporate_Data_TEST' -Customers 'Customer_A'

.EXAMPLE
    # Folder for one document, with permissions
    .\New-DmsFileServerTree.ps1 -Root '\\FILE-SERVER\Corporate_Data' -DocumentId COM-QUO-00001 -ShortTitle CRU4_FCT_Quote -ApplyAcl
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'Interactive admin script: coloured progress output is intended.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
    Justification = 'Domain is read inside Resolve-Principal through script scope.')]
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)] [string] $Root,

    # Area code -> folder under the root. Change to your blueprint Appendix A tree before the first run.
    [hashtable] $AreaFolders = [ordered]@{
        MGT = '01_Management\Management'
        COM = '01_Management\Commercial'
        DEV = '01_Management\Development'
        MFG = '01_Management\Manufacturing'
        TST = '01_Management\Test_Engineering'
        QA  = '01_Management\Quality'
        CHG = '01_Management\Changes'
        IT  = '01_Management\IT'
        SEC = '01_Management\InfoSec'
    },

    [string[]] $Customers = @(),
    [string[]] $Projects = @(),

    # Document mode
    [ValidatePattern('^[A-Z]{2,3}-[A-Z]{2,3}-\d{5}$')] [string] $DocumentId,
    [ValidatePattern('^[\w\-]{1,60}$')] [string] $ShortTitle,

    [switch] $ApplyAcl,
    [switch] $CreateAdGroups,
    [string] $GroupOU,
    [string] $Domain = $env:USERDOMAIN,
    [string] $WorkflowAccount  = 'gMSA_DMS_Workflow$',
    [string] $TransferAccount  = 'gMSA_DMS_Transfer$'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step([string]$Message) { Write-Host "`n=== $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "  [ok]   $Message" -ForegroundColor Green }
function Write-Skip([string]$Message) { Write-Host "  [skip] $Message" -ForegroundColor DarkGray }
function Write-Warn2([string]$Message){ Write-Host "  [warn] $Message" -ForegroundColor Yellow }

function Add-DmsFolder {
    [CmdletBinding(SupportsShouldProcess)] param([string]$Path)
    if (Test-Path -LiteralPath $Path) { Write-Skip $Path; return }
    if ($PSCmdlet.ShouldProcess($Path, 'Create folder')) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
        Write-Ok $Path
    }
}

# ------------------------------------------------------------------ NTFS helpers
$R_Read     = [Security.AccessControl.FileSystemRights]'ReadAndExecute, Synchronize'
$R_Modify   = [Security.AccessControl.FileSystemRights]'Modify, Synchronize'
# "Controlled Modify": write and read, but no Delete and no Change Permissions (docs/02 §3.2)
$R_Control  = [Security.AccessControl.FileSystemRights]'ReadAndExecute, Write, Synchronize'
$R_Full     = [Security.AccessControl.FileSystemRights]'FullControl'

function Resolve-Principal([string]$Name) {
    $account = if ($Name -match '\\') { $Name } else { "$Domain\$Name" }
    try { [void](New-Object Security.Principal.NTAccount($account)).Translate([Security.Principal.SecurityIdentifier]); $account }
    catch { Write-Warn2 "Principal not found, skipped: $account"; $null }
}

# Replace the folder ACL with exactly these grants (inheritance from the parent removed).
function Grant-DmsAcl {
    [CmdletBinding(SupportsShouldProcess)] param([string]$Path, [array]$Grants)
    if (-not $ApplyAcl) { return }
    if (-not $PSCmdlet.ShouldProcess($Path, 'Set NTFS permissions')) { return }
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    $prop = [Security.AccessControl.PropagationFlags]::None
    foreach ($g in @(@{ Who = 'SYSTEM'; Rights = $R_Full }, @{ Who = 'DL_FS_Admin_F'; Rights = $R_Full }) + $Grants) {
        $who = if ($g.Who -eq 'SYSTEM') { 'NT AUTHORITY\SYSTEM' } else { Resolve-Principal $g.Who }
        if (-not $who) { continue }
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($who, $g.Rights, $inherit, $prop, 'Allow')))
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
    Write-Ok "ACL $Path"
}

# ------------------------------------------------------------------ AD groups
if ($CreateAdGroups) {
    Write-Step 'Domain Local groups'
    Import-Module ActiveDirectory
    if (-not $GroupOU) { throw 'Give -GroupOU, e.g. "OU=DMS,OU=Groups,DC=rh,DC=local".' }
    $dl = [ordered]@{
        'DL_FS_Admin_F'              = @('GG_DMS_ITAdmins')
        'DL_FS_Quarantine_M'         = @('GG_DMS_DocumentControl')
        'DL_FS_Quarantine_Inbound_M' = @()
        'DL_FS_Workflow_M'           = @()
        'DL_FS_Auditors_R'           = @('GG_DMS_Auditors')
    }
    foreach ($code in $AreaFolders.Keys) {
        $dl["DL_FS_$($code)_Working_M"]    = @('GG_DMS_Engineers', 'GG_DMS_DocumentControl')
        $dl["DL_FS_$($code)_Submitted_R"]  = @('GG_DMS_Approvers', 'GG_DMS_Engineers')
        $dl["DL_FS_$($code)_Current_R"]    = @('GG_DMS_Employees')
        $dl["DL_FS_$($code)_Controlled_M"] = @('GG_DMS_DocumentControl')
    }
    foreach ($c in $Customers) { $dl["DL_FS_Customer_$($c)_M"] = @("GG_CFT_$c", 'GG_DMS_DocumentControl') }
    foreach ($name in $dl.Keys) {
        if (Get-ADGroup -Filter "SamAccountName -eq '$name'") { Write-Skip $name }
        elseif ($PSCmdlet.ShouldProcess($name, 'Create AD group')) {
            New-ADGroup -Name $name -SamAccountName $name -GroupScope DomainLocal -GroupCategory Security -Path $GroupOU `
                -Description 'DMS file-server resource group (docs/02 §3.2)'
            Write-Ok $name
        }
        foreach ($member in $dl[$name]) {
            if (Get-ADGroup -Filter "SamAccountName -eq '$member'") {
                if ($PSCmdlet.ShouldProcess("$member -> $name", 'Add group member')) { Add-ADGroupMember -Identity $name -Members $member }
            } else { Write-Warn2 "$member not found in AD (not nested in $name)" }
        }
    }
    foreach ($pair in @(@('DL_FS_Workflow_M', $WorkflowAccount), @('DL_FS_Quarantine_Inbound_M', $TransferAccount))) {
        $acct = Get-ADServiceAccount -Filter "SamAccountName -eq '$($pair[1])'" -ErrorAction SilentlyContinue
        if ($acct) { Add-ADGroupMember -Identity $pair[0] -Members $acct } else { Write-Warn2 "$($pair[1]) not found (add it to $($pair[0]) later)" }
    }
}

# ------------------------------------------------------------------ document mode
if ($DocumentId) {
    if (-not $ShortTitle) { throw 'Give -ShortTitle together with -DocumentId (letters, digits, _ and -).' }
    $code = $DocumentId.Split('-')[0]
    if (-not $AreaFolders.Contains($code)) { throw "Unknown area code '$code'. Known: $($AreaFolders.Keys -join ', ')" }
    $docRoot = Join-Path (Join-Path $Root $AreaFolders[$code]) "$($DocumentId)_$ShortTitle"
    Write-Step "Controlled-document folder $docRoot"
    Add-DmsFolder $docRoot
    $sub = [ordered]@{
        Working           = @(@{ Who = "DL_FS_$($code)_Working_M"; Rights = $R_Modify }, @{ Who = "DL_FS_$($code)_Controlled_M"; Rights = $R_Modify })
        Submitted         = @(@{ Who = "DL_FS_$($code)_Submitted_R"; Rights = $R_Read }, @{ Who = "DL_FS_$($code)_Controlled_M"; Rights = $R_Control })
        Current_ReadOnly  = @(@{ Who = "DL_FS_$($code)_Current_R"; Rights = $R_Read }, @{ Who = "DL_FS_$($code)_Controlled_M"; Rights = $R_Control })
        Obsolete_ReadOnly = @(@{ Who = "DL_FS_$($code)_Current_R"; Rights = $R_Read }, @{ Who = "DL_FS_$($code)_Controlled_M"; Rights = $R_Control })
    }
    foreach ($name in $sub.Keys) {
        $p = Join-Path $docRoot $name
        Add-DmsFolder $p
        Grant-DmsAcl $p ($sub[$name] + @(@{ Who = 'DL_FS_Workflow_M'; Rights = $R_Modify }, @{ Who = 'DL_FS_Auditors_R'; Rights = $R_Read }))
    }
    Write-Step 'Done'
    Write-Host "  Working path for the Document Register (WorkingUncPath): $(Join-Path $docRoot 'Working')"
    return
}

# ------------------------------------------------------------------ tree mode
Write-Step "Repository tree under $Root"
Add-DmsFolder $Root
$top = [ordered]@{
    '01_Management'          = @()
    '02_Customers'           = @()
    '03_Operations_Staging'  = @('PLM_Release_Queue', 'MAE_Release_Queue', 'Priority_Import_Queue', 'Integration_Logs')
    '04_Workflow_System'     = @('Submitted_Queue', 'Rejected_Queue', 'Processing', 'Error_Queue')
    '05_Exchange_Quarantine' = @('Inbound', 'Accepted', 'Rejected', 'Logs')
}
foreach ($t in $top.Keys) {
    Add-DmsFolder (Join-Path $Root $t)
    foreach ($s in $top[$t]) { Add-DmsFolder (Join-Path (Join-Path $Root $t) $s) }
}

Write-Step 'Area folders'
foreach ($code in $AreaFolders.Keys) { Add-DmsFolder (Join-Path $Root $AreaFolders[$code]) }

if ($Customers) {
    Write-Step 'Customer folders'
    foreach ($c in $Customers) {
        $cRoot = Join-Path (Join-Path $Root '02_Customers') $c
        foreach ($s in 'Customer_Profile', 'Commercial', 'Projects', 'Shared', 'Archive') { Add-DmsFolder (Join-Path $cRoot $s) }
        foreach ($p in $Projects) { Add-DmsFolder (Join-Path (Join-Path $cRoot 'Projects') $p) }
    }
}

if ($ApplyAcl) {
    Write-Step 'NTFS permissions'
    Grant-DmsAcl $Root @(@{ Who = 'DL_FS_Auditors_R'; Rights = $R_Read })
    foreach ($code in $AreaFolders.Keys) {
        Grant-DmsAcl (Join-Path $Root $AreaFolders[$code]) @(
            @{ Who = "DL_FS_$($code)_Current_R"; Rights = $R_Read }
            @{ Who = "DL_FS_$($code)_Working_M"; Rights = $R_Read }
            @{ Who = "DL_FS_$($code)_Controlled_M"; Rights = $R_Control }
            @{ Who = 'DL_FS_Workflow_M'; Rights = $R_Modify }
            @{ Who = 'DL_FS_Auditors_R'; Rights = $R_Read })
    }
    foreach ($c in $Customers) {
        Grant-DmsAcl (Join-Path (Join-Path $Root '02_Customers') $c) @(
            @{ Who = "DL_FS_Customer_$($c)_M"; Rights = $R_Modify }
            @{ Who = 'DL_FS_Workflow_M'; Rights = $R_Modify }
            @{ Who = 'DL_FS_Auditors_R'; Rights = $R_Read })
    }
    foreach ($t in '03_Operations_Staging', '04_Workflow_System') {
        Grant-DmsAcl (Join-Path $Root $t) @(@{ Who = 'DL_FS_Workflow_M'; Rights = $R_Modify }, @{ Who = 'DL_FS_Auditors_R'; Rights = $R_Read })
    }
    $q = Join-Path $Root '05_Exchange_Quarantine'
    Grant-DmsAcl $q @(@{ Who = 'DL_FS_Quarantine_M'; Rights = $R_Modify }, @{ Who = 'DL_FS_Auditors_R'; Rights = $R_Read })
    Grant-DmsAcl (Join-Path $q 'Inbound') @(@{ Who = 'DL_FS_Quarantine_Inbound_M'; Rights = $R_Modify },
        @{ Who = 'DL_FS_Quarantine_M'; Rights = $R_Modify }, @{ Who = 'DL_FS_Auditors_R'; Rights = $R_Read })
}

Write-Step 'Done'
Write-Host "  Set the environment variable dms_RepositoryRoot to: $Root"
if (-not $ApplyAcl) { Write-Host '  Permissions were not changed. Re-run with -ApplyAcl (and -CreateAdGroups -GroupOU ...) when the AD groups are ready.' }
