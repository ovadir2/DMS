#Requires -Version 7.4
#Requires -Modules @{ ModuleName = 'PnP.PowerShell'; ModuleVersion = '2.12.0' }
<#
.SYNOPSIS
    Builds an importable Power Automate package (.zip) for the pilot approval flow
    "DC-P1 Pilot Approval", so nothing has to be built by hand in the designer.

.DESCRIPTION
    The flow runs when a Document Register item is set to "Submitted" (Hebrew: הוגש לאישור):
      1. reads the active Approver Matrix rule for the document type
      2. approval stage 1 - all mandatory approvers must approve
      3. approval stage 2 - the final approver
      4. sets the status to Approved (read-only) or back to Working
      5. writes one row to the Control Audit list
    The script reads the list IDs from the site and writes out\DC-P1-PilotApproval.zip.

    Import: make.powerautomate.com > My flows > Import > Import Package (Legacy) >
    choose the zip > for each connection click "Select during import" and pick your
    SharePoint and Approvals connections > Import.

.NOTES
    Built for a site provisioned with -ChoiceLanguage he (Hebrew choice values).
    Use -ChoiceLanguage en for a site whose choice values are the English keys.
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'Interactive admin script: coloured progress output is intended.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPositionalParameters', '',
    Justification = 'Local JSON builder helpers are called positionally for readability.')]
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidatePattern('^[a-zA-Z0-9-]+$')] [string] $TenantName,
    [Parameter(Mandatory)] [guid] $ClientId,
    [string] $DocControlSiteAlias = 'DocumentControl',
    [ValidateSet('he', 'en')] [string] $ChoiceLanguage = 'he',
    [string] $OutFolder = (Join-Path $PSScriptRoot 'out')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SiteUrl = "https://$TenantName.sharepoint.com/sites/$DocControlSiteAlias"
$V = if ($ChoiceLanguage -eq 'he') {
    @{ Submitted = 'הוגש לאישור'; Working = 'בעבודה'; Approved = 'מאושר - קריאה בלבד'
       EvApproved = 'אושר'; EvRejected = 'נדחה'; NoRule = 'לא נמצא כלל פעיל במטריצת המאשרים לסוג המסמך'
       Title = 'אישור מסמך: '; Source = 'Power Automate' }
} else {
    @{ Submitted = 'Submitted'; Working = 'Working'; Approved = 'Approved_ReadOnly'
       EvApproved = 'Approved'; EvRejected = 'Rejected'; NoRule = 'No active approver matrix rule for this document type'
       Title = 'Document approval: '; Source = 'PowerAutomate' }
}

Write-Host "Reading list IDs from $SiteUrl" -ForegroundColor Cyan
Connect-PnPOnline -Url $SiteUrl -Interactive -ClientId $ClientId
$ids = @{}
foreach ($u in 'Lists/DocumentRegister', 'Lists/ApproverMatrix', 'Lists/ControlAudit') {
    $ids[$u] = (Get-PnPList -Identity $u).Id.ToString()
    Write-Host "  $u = $($ids[$u])"
}
$Reg = $ids['Lists/DocumentRegister']; $Matrix = $ids['Lists/ApproverMatrix']; $Audit = $ids['Lists/ControlAudit']

# ------------------------------------------------------------------ flow definition
$sp = '/providers/Microsoft.PowerApps/apis/shared_sharepointonline'
$ap = '/providers/Microsoft.PowerApps/apis/shared_approvals'
function Get-SpHost([string]$Op) { @{ apiId = $sp; connectionName = 'shared_sharepointonline'; operationId = $Op } }
function Get-ApHost([string]$Op) { @{ apiId = $ap; connectionName = 'shared_approvals'; operationId = $Op } }
function Get-SetVarAction([string]$Name, [string]$Value, [hashtable]$After) {
    @{ type = 'SetVariable'; inputs = @{ name = $Name; value = $Value }; runAfter = $After }
}
$rule = "first(outputs('Get_matrix_rule')?['body/value'])"
$approvalParams = {
    param([string]$Type, [string]$AssignedTo)
    @{
        approvalType                                     = $Type
        'WebhookApprovalCreationInput/title'             = "@{concat('$($V.Title)', triggerOutputs()?['body/Title'])}"
        'WebhookApprovalCreationInput/assignedTo'        = $AssignedTo
        'WebhookApprovalCreationInput/details'           = "@{triggerOutputs()?['body/DocumentId']} | @{triggerOutputs()?['body/DocumentType/Value']} | @{triggerOutputs()?['body/Editor/DisplayName']}"
        'WebhookApprovalCreationInput/itemLink'          = "@triggerOutputs()?['body/{Link}']"
        'WebhookApprovalCreationInput/itemLinkDescription' = "@triggerOutputs()?['body/Title']"
        'WebhookApprovalCreationInput/enableNotifications' = $true
        'WebhookApprovalCreationInput/enableReassignment'  = $true
    }
}

$definition = [ordered]@{
    '$schema'      = 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
    contentVersion = '1.0.0.0'
    parameters     = @{
        '$connections'   = @{ defaultValue = @{}; type = 'Object' }
        '$authentication' = @{ defaultValue = @{}; type = 'SecureObject' }
    }
    triggers       = @{
        When_an_item_is_created_or_modified = @{
            type       = 'OpenApiConnection'
            recurrence = @{ interval = 1; frequency = 'Minute' }
            splitOn    = "@triggerOutputs()?['body/value']"
            conditions = @(@{ expression = "@equals(triggerOutputs()?['body/LifecycleStatus/Value'], '$($V.Submitted)')" })
            inputs     = @{
                host = Get-SpHost 'GetOnUpdatedItems'
                parameters = @{ dataset = $SiteUrl; table = $Reg }
                authentication = "@parameters('`$authentication')"
            }
        }
    }
    actions        = [ordered]@{
        Init_NewStatus = @{ type = 'InitializeVariable'; runAfter = @{}
            inputs = @{ variables = @(@{ name = 'NewStatus'; type = 'string'; value = $V.Working }) } }
        Init_Event = @{ type = 'InitializeVariable'; runAfter = @{ Init_NewStatus = @('Succeeded') }
            inputs = @{ variables = @(@{ name = 'Event'; type = 'string'; value = $V.EvRejected }) } }
        Init_Details = @{ type = 'InitializeVariable'; runAfter = @{ Init_Event = @('Succeeded') }
            inputs = @{ variables = @(@{ name = 'Details'; type = 'string'; value = '' }) } }
        Get_matrix_rule = @{
            type = 'OpenApiConnection'; runAfter = @{ Init_Details = @('Succeeded') }
            inputs = @{
                host = Get-SpHost 'GetItems'
                parameters = @{
                    dataset = $SiteUrl; table = $Matrix; '$top' = 1
                    '$filter' = "DocumentType eq '@{triggerOutputs()?['body/DocumentType/Value']}' and IsActive eq 1"
                }
                authentication = "@parameters('`$authentication')"
            }
        }
        Rule_found = @{
            type = 'If'; runAfter = @{ Get_matrix_rule = @('Succeeded') }
            expression = @{ greater = @("@length(outputs('Get_matrix_rule')?['body/value'])", 0) }
            else = @{ actions = @{ Set_details_no_rule = Get-SetVarAction 'Details' $V.NoRule @{} } }
            actions = [ordered]@{
                Select_mandatory = @{
                    type = 'Select'; runAfter = @{}
                    inputs = @{ from = "@coalesce(${rule}?['MandatoryApprovers'], json('[]'))"; select = "@item()?['Email']" }
                }
                Approval1 = @{
                    type = 'OpenApiConnectionWebhook'; runAfter = @{ Select_mandatory = @('Succeeded') }
                    inputs = @{
                        host = Get-ApHost 'StartAndWaitForAnApproval'
                        parameters = & $approvalParams 'BasicAwaitAll' "@{join(body('Select_mandatory'), ';')}"
                        authentication = "@parameters('`$authentication')"
                    }
                }
                Stage1_approved = @{
                    type = 'If'; runAfter = @{ Approval1 = @('Succeeded') }
                    expression = @{ equals = @("@outputs('Approval1')?['body/outcome']", 'Approve') }
                    else = @{ actions = @{ Set_details_1 = Get-SetVarAction 'Details' "@{string(outputs('Approval1')?['body/responses'])}" @{} } }
                    actions = [ordered]@{
                        Approval2 = @{
                            type = 'OpenApiConnectionWebhook'; runAfter = @{}
                            inputs = @{
                                host = Get-ApHost 'StartAndWaitForAnApproval'
                                parameters = & $approvalParams 'Basic' "@{${rule}?['FinalApprover']?['Email']}"
                                authentication = "@parameters('`$authentication')"
                            }
                        }
                        Set_details_2 = Get-SetVarAction 'Details' "@{string(outputs('Approval2')?['body/responses'])}" @{ Approval2 = @('Succeeded') }
                        Stage2_approved = @{
                            type = 'If'; runAfter = @{ Set_details_2 = @('Succeeded') }
                            expression = @{ equals = @("@outputs('Approval2')?['body/outcome']", 'Approve') }
                            actions = [ordered]@{
                                Set_status_approved = Get-SetVarAction 'NewStatus' $V.Approved @{}
                                Set_event_approved  = Get-SetVarAction 'Event' $V.EvApproved @{ Set_status_approved = @('Succeeded') }
                            }
                        }
                    }
                }
            }
        }
        Update_status = @{
            type = 'OpenApiConnection'; runAfter = @{ Rule_found = @('Succeeded') }
            inputs = @{
                host = Get-SpHost 'HttpRequest'
                parameters = @{
                    dataset = $SiteUrl
                    'parameters/method' = 'POST'
                    'parameters/uri' = "_api/web/lists(guid'$Reg')/items(@{triggerOutputs()?['body/ID']})/ValidateUpdateListItem"
                    'parameters/headers' = @{ Accept = 'application/json;odata=nometadata'; 'Content-Type' = 'application/json;odata=nometadata' }
                    'parameters/body' = "{`"formValues`":[{`"FieldName`":`"LifecycleStatus`",`"FieldValue`":`"@{variables('NewStatus')}`"}]}"
                }
                authentication = "@parameters('`$authentication')"
            }
        }
        Write_audit = @{
            type = 'OpenApiConnection'; runAfter = @{ Update_status = @('Succeeded') }
            inputs = @{
                host = Get-SpHost 'PostItem'
                parameters = @{
                    dataset = $SiteUrl; table = $Audit
                    'item/Title' = "@{variables('Event')} @{triggerOutputs()?['body/DocumentId']}"
                    'item/CorrelationId' = "@{triggerOutputs()?['body/DocumentId']}"
                    'item/AuditEventType/Value' = "@variables('Event')"
                    'item/FromStatus' = $V.Submitted
                    'item/ToStatus' = "@variables('NewStatus')"
                    'item/ActorEmail' = "@triggerOutputs()?['body/Editor/Email']"
                    'item/EventUtc' = '@utcNow()'
                    'item/EventSource/Value' = $V.Source
                    'item/EventDetails' = "@variables('Details')"
                }
                authentication = "@parameters('`$authentication')"
            }
        }
    }
}

# ------------------------------------------------------------------ legacy package
$flowId = [guid]::NewGuid().ToString()
$res = @{ SpApi = [guid]::NewGuid().ToString(); SpConn = [guid]::NewGuid().ToString()
          ApApi = [guid]::NewGuid().ToString(); ApConn = [guid]::NewGuid().ToString() }
$connNames = @{ Sp = 'shared-sharepointonl-' + [guid]::NewGuid().ToString(); Ap = 'shared-approvals-' + [guid]::NewGuid().ToString() }

$flow = [ordered]@{
    name = $flowId; id = "/providers/Microsoft.Flow/flows/$flowId"; type = 'Microsoft.Flow/flows'
    properties = [ordered]@{
        apiId = '/providers/Microsoft.PowerApps/apis/shared_logicflows'
        displayName = 'DC-P1 Pilot Approval'
        definition = $definition
        connectionReferences = @{
            shared_sharepointonline = @{ connectionName = $connNames.Sp; source = 'Embedded'; id = $sp; tier = 'NotSpecified' }
            shared_approvals        = @{ connectionName = $connNames.Ap; source = 'Embedded'; id = $ap; tier = 'NotSpecified' }
        }
        flowFailureAlertSubscribed = $false
    }
}
function Get-ApiResource([string]$Api, [string]$Name, [string]$Display) {
    @{ id = $Api; name = $Name; type = 'Microsoft.PowerApps/apis'; suggestedCreationType = 'Existing'
       details = @{ displayName = $Display; iconUri = '' }; configurableBy = 'System'; hierarchy = 'Child'; dependsOn = @() }
}
function Get-ConnectionResource([string]$ApiRes, [string]$Display) {
    @{ type = 'Microsoft.PowerApps/apis/connections'; suggestedCreationType = 'Existing'; creationType = 'Existing'
       details = @{ displayName = $Display; iconUri = '' }; configurableBy = 'User'; hierarchy = 'Child'; dependsOn = @($ApiRes) }
}
$manifest = [ordered]@{
    schema = '1.0'
    details = @{ displayName = 'DC-P1 Pilot Approval'; description = 'DMS pilot approval flow'; createdTime = (Get-Date).ToUniversalTime().ToString('o')
                 packageTelemetryId = [guid]::NewGuid().ToString(); creator = 'DMS'; sourceEnvironment = '' }
    resources = [ordered]@{
        $flowId = @{ id = "/providers/Microsoft.Flow/flows/$flowId"; name = $flowId; type = 'Microsoft.Flow/flows'
                     suggestedCreationType = 'New'; creationType = 'Existing, New, Update'
                     details = @{ displayName = 'DC-P1 Pilot Approval' }; configurableBy = 'User'; hierarchy = 'Root'
                     dependsOn = @($res.SpApi, $res.SpConn, $res.ApApi, $res.ApConn) }
        $res.SpApi  = Get-ApiResource $sp 'shared_sharepointonline' 'SharePoint'
        $res.SpConn = Get-ConnectionResource $res.SpApi 'SharePoint'
        $res.ApApi  = Get-ApiResource $ap 'shared_approvals' 'Approvals'
        $res.ApConn = Get-ConnectionResource $res.ApApi 'Approvals'
    }
}

$stage = Join-Path ([IO.Path]::GetTempPath()) "dms-flow-$flowId"
$flowDir = Join-Path $stage "Microsoft.Flow/flows/$flowId"
New-Item -ItemType Directory -Path $flowDir -Force | Out-Null
$manifest | ConvertTo-Json -Depth 60 | Set-Content (Join-Path $stage 'manifest.json') -Encoding utf8NoBOM
$flow | ConvertTo-Json -Depth 60 | Set-Content (Join-Path $flowDir 'definition.json') -Encoding utf8NoBOM
@{ shared_sharepointonline = $res.SpApi; shared_approvals = $res.ApApi } | ConvertTo-Json | Set-Content (Join-Path $flowDir 'apisMap.json') -Encoding utf8NoBOM
@{ shared_sharepointonline = $res.SpConn; shared_approvals = $res.ApConn } | ConvertTo-Json | Set-Content (Join-Path $flowDir 'connectionsMap.json') -Encoding utf8NoBOM
[ordered]@{ packageSchemaVersion = '1.0'; flowAssets = @{ assetPaths = @($flowId) } } | ConvertTo-Json -Depth 5 |
    Set-Content (Join-Path $stage 'Microsoft.Flow/flows/manifest.json') -Encoding utf8NoBOM

New-Item -ItemType Directory -Path $OutFolder -Force | Out-Null
$zip = Join-Path $OutFolder 'DC-P1-PilotApproval.zip'
Remove-Item $zip -ErrorAction SilentlyContinue
# Build the zip entry by entry so every path uses '/' (the import service rejects '\').
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($zip, 'Create')
try {
    foreach ($file in Get-ChildItem $stage -Recurse -File) {
        $entry = [IO.Path]::GetRelativePath($stage, $file.FullName).Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $entry) | Out-Null
    }
} finally { $archive.Dispose() }
Remove-Item $stage -Recurse -Force

Write-Host "`nPackage written: $zip" -ForegroundColor Green
Write-Host 'Import: make.powerautomate.com > My flows > Import > Import Package (Legacy).'
