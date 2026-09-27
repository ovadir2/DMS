#Requires -Version 7.4
#Requires -Modules @{ ModuleName = 'PnP.PowerShell'; ModuleVersion = '2.12.0' }
<#
.SYNOPSIS
    Creates the DMS Entra security groups and connects them to the SharePoint groups
    of both DMS sites (docs/02-Security-and-Permissions.md, section 3 and 5).

.DESCRIPTION
    Idempotent. For each role it:
      1. finds or creates the Entra security group (GG_DMS_*)
      2. adds the people you pass on the command line (optional)
      3. adds the Entra group to the matching SharePoint group(s) on both sites

    GG_DMS_Employees is created as a DYNAMIC group (all enabled internal users, no guests)
    unless -NoDynamicEmployees is given. Dynamic groups need Entra ID P1, which is part
    of Microsoft 365 Business Premium.

    With -PilotMode the SharePoint "members / employees" groups get GG_DMS_PilotUsers
    instead of GG_DMS_Employees, so only the pilot users can open the sites.

.PARAMETER ServiceAccountUpn
    The Power Automate service account (e.g. svc-dms-flows@company.co.il). It is added
    directly to the two "service accounts" SharePoint groups.

.EXAMPLE
    ./Connect-DmsGroups.ps1 -TenantName contoso -ClientId <pnp-app-id> `
        -DocumentControl dana@contoso.com, avi@contoso.com -ITAdmins it.admin@contoso.com `
        -PilotUsers user1@contoso.com, user2@contoso.com -PilotMode `
        -DocControlSiteAlias DocumentControl-TEST -ExchangeSiteAlias LargeFileExchange-TEST

.NOTES
    The PnP login app needs Microsoft Graph delegated permissions Group.ReadWrite.All and
    User.Read.All (admin consent). Your account needs Groups Administrator (or Global
    Administrator) in Entra and SharePoint Administrator.
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'Interactive admin script: coloured progress output is intended.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
    Justification = 'NoDynamicEmployees is read inside Get-EntraGroupId through script scope.')]
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidatePattern('^[a-zA-Z0-9-]+$')] [string] $TenantName,
    [Parameter(Mandatory)] [guid] $ClientId,
    [string] $DocControlSiteAlias = 'DocumentControl',
    [string] $ExchangeSiteAlias   = 'LargeFileExchange',
    [string[]] $ITAdmins = @(),
    [string[]] $DocumentControl = @(),
    [string[]] $Approvers = @(),
    [string[]] $Auditors = @(),
    [string[]] $PilotUsers = @(),
    [string] $ServiceAccountUpn,
    [switch] $PilotMode,
    [switch] $NoDynamicEmployees
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TenantRoot = "https://$TenantName.sharepoint.com"
$Sites = @{ DC = "$TenantRoot/sites/$DocControlSiteAlias"; EX = "$TenantRoot/sites/$ExchangeSiteAlias" }

function Write-Step([string]$Message) { Write-Host "`n=== $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "  [ok]   $Message" -ForegroundColor Green }
function Write-Skip([string]$Message) { Write-Host "  [skip] $Message" -ForegroundColor DarkGray }
function Write-Warn2([string]$Message){ Write-Host "  [warn] $Message" -ForegroundColor Yellow }

# SharePoint group names exactly as Provision-DMS.ps1 creates them (English / Hebrew).
$SpGroups = @{
    DcOwners      = @('DMS Owners', 'DMS - בעלים')
    DcControllers = @('DMS Document Controllers', 'DMS - בקרי מסמכים')
    DcApprovers   = @('DMS Approvers', 'DMS - מאשרים')
    DcMembers     = @('DMS Members', 'DMS - עובדים')
    DcAuditors    = @('DMS Auditors', 'DMS - מבקרים')
    DcService     = @('DMS Service Accounts', 'DMS - חשבונות שירות')
    ExOwners      = @('Exchange Owners', 'העברת קבצים - בעלים')
    ExControllers = @('Exchange Document Control', 'העברת קבצים - בקרת מסמכים')
    ExEmployees   = @('Exchange Employees', 'העברת קבצים - עובדים')
    ExAuditors    = @('Exchange Auditors', 'העברת קבצים - מבקרים')
    ExService     = @('Exchange Service Accounts', 'העברת קבצים - חשבונות שירות')
}

$membersKey = if ($PilotMode) { 'GG_DMS_PilotUsers' } else { 'GG_DMS_Employees' }
$EntraGroups = @(
    @{ Name = 'GG_DMS_ITAdmins';        Desc = 'DMS - IT / SharePoint administrators';           People = $ITAdmins;        SharePoint = @('DcOwners', 'ExOwners') }
    @{ Name = 'GG_DMS_DocumentControl'; Desc = 'DMS - Document Control team';                    People = $DocumentControl; SharePoint = @('DcControllers', 'ExControllers') }
    @{ Name = 'GG_DMS_Approvers';       Desc = 'DMS - everyone who can appear in the approver matrix'; People = $Approvers; SharePoint = @('DcApprovers') }
    @{ Name = 'GG_DMS_Auditors';        Desc = 'DMS - Quality / InfoSec / internal audit (read)'; People = $Auditors;       SharePoint = @('DcAuditors', 'ExAuditors') }
    @{ Name = 'GG_DMS_PilotUsers';      Desc = 'DMS - pilot users';                              People = $PilotUsers;      SharePoint = @() }
    @{ Name = 'GG_DMS_Employees';       Desc = 'DMS - all internal employees (dynamic, no guests)'; People = @();           SharePoint = @()
       Rule = '(user.accountEnabled -eq true) and (user.userType -eq "Member")' }
)
($EntraGroups | Where-Object Name -eq $membersKey).SharePoint = @('DcMembers', 'ExEmployees')

function Get-EntraGroupId([hashtable]$G) {
    $filter = [uri]::EscapeDataString("displayName eq '$($G.Name)'")
    $found = Invoke-PnPGraphMethod -Url "v1.0/groups?`$filter=$filter&`$select=id,displayName"
    if ($found.value -and @($found.value).Count -gt 0) { Write-Skip "Entra group $($G.Name)"; return @($found.value)[0].id }

    $body = @{
        displayName     = $G.Name
        description     = $G.Desc
        mailEnabled     = $false
        mailNickname    = ($G.Name -replace '[^A-Za-z0-9]', '')
        securityEnabled = $true
    }
    if ($G.ContainsKey('Rule') -and -not $NoDynamicEmployees) {
        $body.groupTypes = @('DynamicMembership')
        $body.membershipRule = $G.Rule
        $body.membershipRuleProcessingState = 'On'
    }
    $new = Invoke-PnPGraphMethod -Url 'v1.0/groups' -Method Post -Content $body
    Write-Ok "Entra group $($G.Name) created$(if ($body.ContainsKey('groupTypes')) { ' (dynamic)' })"
    $new.id
}

function Add-EntraMember([string]$GroupId, [string]$GroupName, [string]$Upn) {
    try {
        $user = Invoke-PnPGraphMethod -Url "v1.0/users/$([uri]::EscapeDataString($Upn))?`$select=id"
        $ref = @{ '@odata.id' = "https://graph.microsoft.com/v1.0/directoryObjects/$($user.id)" }
        Invoke-PnPGraphMethod -Url "v1.0/groups/$GroupId/members/`$ref" -Method Post -Content $ref | Out-Null
        Write-Ok "  $Upn -> $GroupName"
    } catch {
        if ($_.Exception.Message -match 'already exist') { Write-Skip "  $Upn already in $GroupName" }
        else { Write-Warn2 "  $Upn : $($_.Exception.Message)" }
    }
}

function Add-SpMember([string]$SpKey, [string]$LoginName, [string]$Label) {
    $existing = @(Get-PnPGroup | ForEach-Object Title)
    $title = $SpGroups[$SpKey] | Where-Object { $existing -contains $_ } | Select-Object -First 1
    if (-not $title) { Write-Warn2 "SharePoint group for $SpKey not found (run Provision-DMS.ps1 first)"; return }
    try { Add-PnPGroupMember -Group $title -LoginName $LoginName; Write-Ok "$Label -> $title" }
    catch {
        if ($_.Exception.Message -match 'already') { Write-Skip "$Label already in $title" }
        else { Write-Warn2 "$Label -> $title : $($_.Exception.Message)" }
    }
}

# ------------------------------------------------------------------ 1. Entra groups
Write-Step 'Entra security groups'
Connect-PnPOnline -Url "https://$TenantName-admin.sharepoint.com" -Interactive -ClientId $ClientId
$ids = @{}
try {
    foreach ($g in $EntraGroups) {
        $ids[$g.Name] = Get-EntraGroupId $g
        foreach ($p in $g.People) { Add-EntraMember -GroupId $ids[$g.Name] -GroupName $g.Name -Upn $p }
    }
} catch {
    Write-Warn2 $_.Exception.Message
    Write-Warn2 'If this is 403 / Authorization_RequestDenied: give the PnP app Microsoft Graph delegated permissions'
    Write-Warn2 'Group.ReadWrite.All and User.Read.All with admin consent, and make sure you are Groups Administrator.'
    throw
}

# ------------------------------------------------------------------ 2. SharePoint groups on both sites
foreach ($siteKey in 'DC', 'EX') {
    Write-Step "SharePoint groups on $($Sites[$siteKey])"
    Connect-PnPOnline -Url $Sites[$siteKey] -Interactive -ClientId $ClientId
    foreach ($g in $EntraGroups) {
        foreach ($sp in $g.SharePoint | Where-Object { $_.StartsWith($(if ($siteKey -eq 'DC') { 'Dc' } else { 'Ex' })) }) {
            Add-SpMember -SpKey $sp -LoginName "c:0t.c|tenant|$($ids[$g.Name])" -Label $g.Name
        }
    }
    if ($ServiceAccountUpn) {
        $svcKey = if ($siteKey -eq 'DC') { 'DcService' } else { 'ExService' }
        Add-SpMember -SpKey $svcKey -LoginName "i:0#.f|membership|$ServiceAccountUpn" -Label $ServiceAccountUpn
    }
}

Write-Step 'Done'
Write-Host '  Add or remove people later in Entra (entra.microsoft.com > Groups). SharePoint follows automatically.'
if ($PilotMode) { Write-Host '  Pilot mode: only GG_DMS_PilotUsers can open the sites. Re-run without -PilotMode to open to all employees.' }
