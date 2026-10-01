#Requires -Version 7.0
#Requires -Modules PnP.PowerShell
<#
.SYNOPSIS
    Pilot notifications: creates the "DMS Notifications" list and builds an importable Power Automate
    package for the flow "DC-P2 Pilot Notifications" (email + Teams).

.DESCRIPTION
    With approvals on the DMS page (Start-DmsPlayground.ps1 -Approvals page), the page writes one row to
    the DMS Notifications list at each step: submitted (to the stage-1 approvers), stage 1 complete (to the
    final approver), approved / rejected (to the owner), withdrawn (to the waiting approvers).
    The flow sends each row:
      - an email (Office 365 Outlook) to all recipients, with a link that opens the page on Approvals
        or My workflows;
      - a Teams message from the Flow bot to each recipient.
    The list is created if missing (Title, NotifyTo, MessageBody, LinkUrl, RefId). Every notification
    stays in the list, so who was told what and when is kept in SharePoint.

    Import the zip: make.powerautomate.com > My flows > Import > Import Package (Legacy), choose the zip,
    pick your SharePoint, Office 365 Outlook and Microsoft Teams connections, Import, then turn it On.

.EXAMPLE
    .\New-DmsNotifyFlowPackage.ps1 -TenantName rhisrael -ClientId $C -DocControlSiteAlias DocumentControl-TEST
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'Interactive admin script: coloured progress output is intended.')]
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidatePattern('^[a-zA-Z0-9-]+$')] [string] $TenantName,
    [Parameter(Mandatory)] [guid] $ClientId,
    [string] $DocControlSiteAlias = 'DocumentControl',
    [string] $OutFolder = (Join-Path $PSScriptRoot 'out')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SiteUrl = "https://$TenantName.sharepoint.com/sites/$DocControlSiteAlias"
Write-Host "Connecting to $SiteUrl" -ForegroundColor Cyan
Connect-PnPOnline -Url $SiteUrl -Interactive -ClientId $ClientId

# ------------------------------------------------------------------ the list
$listUrl = 'Lists/DmsNotifications'
$list = Get-PnPList -Identity $listUrl -ErrorAction SilentlyContinue
if (-not $list) {
    $list = New-PnPList -Title 'DMS Notifications' -Url $listUrl -Template GenericList -OnQuickLaunch:$false
    Set-PnPList -Identity $list -EnableAttachments $false -EnableVersioning $true | Out-Null
    Write-Host '  [new] list DMS Notifications' -ForegroundColor Green
}
$fields = @{ NotifyTo = 'Note'; MessageBody = 'Note'; LinkUrl = 'Text'; RefId = 'Text' }
foreach ($f in $fields.GetEnumerator()) {
    if (-not (Get-PnPField -List $list -Identity $f.Key -ErrorAction SilentlyContinue)) {
        Add-PnPField -List $list -DisplayName $f.Key -InternalName $f.Key -Type $f.Value -AddToDefaultView | Out-Null
        Write-Host "  [new] field $($f.Key)" -ForegroundColor Green
    }
}
$listId = (Get-PnPList -Identity $listUrl).Id.ToString()
Write-Host "  DMS Notifications = $listId"

# ------------------------------------------------------------------ flow definition
$sp = '/providers/Microsoft.PowerApps/apis/shared_sharepointonline'
$ol = '/providers/Microsoft.PowerApps/apis/shared_office365'
$tm = '/providers/Microsoft.PowerApps/apis/shared_teams'
function Get-Host([string]$Api, [string]$Conn, [string]$Op) { @{ apiId = $Api; connectionName = $Conn; operationId = $Op } }
$t = "triggerOutputs()?['body"
$html = "<p>@{$t/MessageBody']}</p><p><a href=`"@{$t/LinkUrl']}`">Open the DMS page / פתיחת דף ה-DMS</a></p><p style=`"color:#888`">RH - Documents Management System</p>"

$definition = [ordered]@{
    '$schema'      = 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
    contentVersion = '1.0.0.0'
    parameters     = @{
        '$connections'    = @{ defaultValue = @{}; type = 'Object' }
        '$authentication' = @{ defaultValue = @{}; type = 'SecureObject' }
    }
    triggers       = @{
        When_a_notification_is_created = @{
            type       = 'OpenApiConnection'
            recurrence = @{ interval = 1; frequency = 'Minute' }
            splitOn    = "@triggerOutputs()?['body/value']"
            inputs     = @{
                host = Get-Host $sp 'shared_sharepointonline' 'GetOnNewItems'
                parameters = @{ dataset = $SiteUrl; table = $listId }
                authentication = "@parameters('`$authentication')"
            }
        }
    }
    actions        = [ordered]@{
        Send_email = @{
            type = 'OpenApiConnection'; runAfter = @{}
            inputs = @{
                host = Get-Host $ol 'shared_office365' 'SendEmailV2'
                parameters = @{
                    'emailMessage/To'      = "@{$t/NotifyTo']}"
                    'emailMessage/Subject' = "@{$t/Title']}"
                    'emailMessage/Body'    = $html
                    'emailMessage/Importance' = 'Normal'
                }
                authentication = "@parameters('`$authentication')"
            }
        }
        For_each_recipient = @{
            type = 'Foreach'; foreach = "@split($t/NotifyTo'], ';')"
            runAfter = @{ Send_email = @('Succeeded', 'Failed', 'Skipped', 'TimedOut') }
            actions = @{
                Post_in_Teams = @{
                    type = 'OpenApiConnection'; runAfter = @{}
                    inputs = @{
                        host = Get-Host $tm 'shared_teams' 'PostMessageToConversation'
                        parameters = @{
                            poster = 'Flow bot'; location = 'Chat with Flow bot'
                            'body/recipient'   = "@{trim(item())}"
                            'body/messageBody' = "<p><b>@{$t/Title']}</b></p>$html"
                        }
                        authentication = "@parameters('`$authentication')"
                    }
                }
            }
        }
    }
}

# ------------------------------------------------------------------ legacy package
$flowId = [guid]::NewGuid().ToString()
$apis = [ordered]@{
    shared_sharepointonline = @{ Api = $sp; Display = 'SharePoint' }
    shared_office365        = @{ Api = $ol; Display = 'Office 365 Outlook' }
    shared_teams            = @{ Api = $tm; Display = 'Microsoft Teams' }
}
foreach ($k in @($apis.Keys)) { $apis[$k].ApiRes = [guid]::NewGuid().ToString(); $apis[$k].ConnRes = [guid]::NewGuid().ToString() }

$connectionReferences = @{}
foreach ($k in $apis.Keys) {
    $connectionReferences[$k] = @{ connectionName = ($k.Replace('_', '-').Substring(0, [Math]::Min(20, $k.Length)) + '-' + [guid]::NewGuid())
                                   source = 'Embedded'; id = $apis[$k].Api; tier = 'NotSpecified' }
}
$flow = [ordered]@{
    name = $flowId; id = "/providers/Microsoft.Flow/flows/$flowId"; type = 'Microsoft.Flow/flows'
    properties = [ordered]@{
        apiId = '/providers/Microsoft.PowerApps/apis/shared_logicflows'
        displayName = 'DC-P2 Pilot Notifications'
        definition = $definition
        connectionReferences = $connectionReferences
        flowFailureAlertSubscribed = $false
    }
}
$resources = [ordered]@{
    $flowId = @{ id = "/providers/Microsoft.Flow/flows/$flowId"; name = $flowId; type = 'Microsoft.Flow/flows'
                 suggestedCreationType = 'New'; creationType = 'Existing, New, Update'
                 details = @{ displayName = 'DC-P2 Pilot Notifications' }; configurableBy = 'User'; hierarchy = 'Root'
                 dependsOn = @($apis.Values | ForEach-Object { $_.ApiRes; $_.ConnRes }) }
}
foreach ($k in $apis.Keys) {
    $a = $apis[$k]
    $resources[$a.ApiRes] = @{ id = $a.Api; name = $k; type = 'Microsoft.PowerApps/apis'; suggestedCreationType = 'Existing'
        details = @{ displayName = $a.Display; iconUri = '' }; configurableBy = 'System'; hierarchy = 'Child'; dependsOn = @() }
    $resources[$a.ConnRes] = @{ type = 'Microsoft.PowerApps/apis/connections'; suggestedCreationType = 'Existing'; creationType = 'Existing'
        details = @{ displayName = $a.Display; iconUri = '' }; configurableBy = 'User'; hierarchy = 'Child'; dependsOn = @($a.ApiRes) }
}
$manifest = [ordered]@{
    schema = '1.0'
    details = @{ displayName = 'DC-P2 Pilot Notifications'; description = 'DMS pilot notifications (email + Teams)'
                 createdTime = (Get-Date).ToUniversalTime().ToString('o'); packageTelemetryId = [guid]::NewGuid().ToString()
                 creator = 'DMS'; sourceEnvironment = '' }
    resources = $resources
}

$stage = Join-Path ([IO.Path]::GetTempPath()) "dms-flow-$flowId"
$flowDir = Join-Path $stage "Microsoft.Flow/flows/$flowId"
New-Item -ItemType Directory -Path $flowDir -Force | Out-Null
$manifest | ConvertTo-Json -Depth 60 | Set-Content (Join-Path $stage 'manifest.json') -Encoding utf8NoBOM
$flow | ConvertTo-Json -Depth 60 | Set-Content (Join-Path $flowDir 'definition.json') -Encoding utf8NoBOM
$apiMap = [ordered]@{}; $connMap = [ordered]@{}
foreach ($k in $apis.Keys) { $apiMap[$k] = $apis[$k].ApiRes; $connMap[$k] = $apis[$k].ConnRes }
$apiMap | ConvertTo-Json | Set-Content (Join-Path $flowDir 'apisMap.json') -Encoding utf8NoBOM
$connMap | ConvertTo-Json | Set-Content (Join-Path $flowDir 'connectionsMap.json') -Encoding utf8NoBOM
[ordered]@{ packageSchemaVersion = '1.0'; flowAssets = @{ assetPaths = @($flowId) } } | ConvertTo-Json -Depth 5 |
    Set-Content (Join-Path $stage 'Microsoft.Flow/flows/manifest.json') -Encoding utf8NoBOM

New-Item -ItemType Directory -Path $OutFolder -Force | Out-Null
$zip = Join-Path $OutFolder 'DC-P2-PilotNotifications.zip'
Remove-Item $zip -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($zip, 'Create')
try {
    foreach ($file in Get-ChildItem $stage -Recurse -File) {
        $entry = [IO.Path]::GetRelativePath($stage, $file.FullName).Replace('\', '/')   # the import service rejects '\'
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $entry) | Out-Null
    }
} finally { $archive.Dispose() }
Remove-Item $stage -Recurse -Force

Write-Host "`nPackage written: $zip" -ForegroundColor Green
Write-Host 'Import: make.powerautomate.com > My flows > Import > Import Package (Legacy). Pick the SharePoint, Office 365 Outlook and Teams connections, Import, then turn the flow On.'
