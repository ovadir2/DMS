#Requires -Version 7.4
#Requires -Modules @{ ModuleName = 'PnP.PowerShell'; ModuleVersion = '2.12.0' }
<#
.SYNOPSIS
    Provisions the Enterprise Document Control (DMS) SharePoint control plane
    defined in IT-DOC-BP-001 (Enterprise Document Control and Large-File Exchange Blueprint).

.DESCRIPTION
    Creates / updates (idempotent) two SharePoint Online sites:

      1. Document Control site  (internal only, no external sharing)
         Document Register, Workflow History, Approval Decisions, Approver Matrix,
         Impact Routing, Delegations, File Action Queue, Control Audit, UI Labels

      2. Large File Exchange site (authenticated B2B guests, per-request folders)
         Temporary Uploads (library), Upload Requests, Exchange Audit, Routing Catalog

    For each site it provisions site columns (deterministic GUIDs), content types,
    lists/libraries, list settings (versioning, attachments, unique permissions),
    views, custom permission levels, SharePoint groups and seed data
    (approver matrix, impact routing, bilingual UI labels and notification templates).

    Files are NEVER stored in SharePoint except the temporary exchange copy.
    Internal names and choice keys are always English (stable keys for Power Fx
    and Power Automate). Display names, view names, content-type names, group
    descriptions and UI labels follow -Language (en | he).

.PARAMETER TenantName
    Tenant short name. "contoso" for https://contoso.sharepoint.com

.PARAMETER ClientId
    Entra application (client) ID registered for PnP PowerShell interactive login.
    Required for site creation / tenant settings: SharePoint > Sites.FullControl.All (delegated).

.PARAMETER Language
    en (default) or he. Language of the DMS content: column, list, view, content-type
    and group names. Also the site locale unless -SiteLanguage is given.

.PARAMETER SiteLanguage
    Optional. en or he. Language of the SharePoint interface itself (site locale
    1033 / 1037). Example: -SiteLanguage he -Language en gives Hebrew SharePoint menus
    with English DMS content. Can only be set when the site is created.

.PARAMETER OwnerUpn
    Primary site collection administrator (UPN).

.PARAMETER GroupMembers
    Optional hashtable: SharePoint group key -> array of members.
    Member = Entra group object ID (GUID) or user UPN.
    Keys: DcOwners, DcControllers, DcApprovers, DcMembers, DcAuditors, DcService,
          ExOwners, ExControllers, ExEmployees, ExAuditors, ExService

.PARAMETER AllowedGuestDomains
    Optional list of external domains allowed to be invited to the Exchange site.

.PARAMETER LogoPath
    Optional site logo (PNG/JPG, ideally square, at least 64x64). Default: ..\assets\logo.png
    next to this script. Skipped if the file does not exist.

.PARAMETER TransferWorkerAppId / WorkflowServiceAppId
    Optional Entra app IDs. When supplied, the script grants Sites.Selected "Write"
    on only the matching site (Exchange / Document Control).

.EXAMPLE
    ./Provision-DMS.ps1 -TenantName contoso -ClientId 00000000-0000-0000-0000-000000000000 `
        -OwnerUpn it.admin@contoso.com -Language he `
        -GroupMembers @{ DcMembers = @('3f1c...guid'); DcControllers = @('doc.control@contoso.com') }

.NOTES
    Document ID : IT-DOC-BP-001 / Implementation package
    Encoding    : UTF-8 with BOM (Hebrew literals; safe for Windows PowerShell hosts and editors)
    Re-runnable : yes. Existing objects are detected and left in place / updated.
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'Interactive provisioning script: coloured progress output is intended and is captured by the transcript.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
    Justification = 'ClientId and GroupMembers are read inside helper functions (Connect-Site, Install-DmsGroup) through script scope.')]
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidatePattern('^[a-zA-Z0-9-]+$')] [string] $TenantName,
    [Parameter(Mandatory)] [guid]   $ClientId,
    [Parameter(Mandatory)] [string] $OwnerUpn,
    [ValidateSet('en', 'he')] [string] $Language = 'en',
    [ValidateSet('en', 'he')] [string] $SiteLanguage,
    [string] $DocControlSiteAlias = 'DocumentControl',
    [string] $ExchangeSiteAlias   = 'LargeFileExchange',
    [hashtable] $GroupMembers = @{},
    [string[]] $AllowedGuestDomains = @(),
    [guid] $TransferWorkerAppId,
    [guid] $WorkflowServiceAppId,
    [switch] $SkipSiteCreation,
    [switch] $SkipSeedData,
    [string] $LogoPath = (Join-Path $PSScriptRoot '..\assets\logo.png')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Script:He        = ($Language -eq 'he')
$siteLang         = if ($SiteLanguage) { $SiteLanguage } else { $Language }
$Script:Lcid      = if ($siteLang -eq 'he') { 1037 } else { 1033 }
$Script:FieldGrp  = 'DMS Columns'
$Script:CtGrp     = 'DMS Content Types'
$TenantRoot       = "https://$TenantName.sharepoint.com"
$AdminUrl         = "https://$TenantName-admin.sharepoint.com"
$DcUrl            = "$TenantRoot/sites/$DocControlSiteAlias"
$ExUrl            = "$TenantRoot/sites/$ExchangeSiteAlias"

$logDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Start-Transcript -Path (Join-Path $logDir ("Provision-DMS_{0:yyyyMMdd_HHmmss}.log" -f (Get-Date))) | Out-Null

#region ---------------------------------------------------------------- helpers
function Write-Step([string]$Message) { Write-Host "`n=== $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "  [ok]   $Message" -ForegroundColor Green }
function Write-Skip([string]$Message) { Write-Host "  [skip] $Message" -ForegroundColor DarkGray }
function Write-Warn2([string]$Message){ Write-Host "  [warn] $Message" -ForegroundColor Yellow }

function T([string]$En, [string]$HeText) { if ($Script:He -and $HeText) { $HeText } else { $En } }

function Get-StableGuid([string]$Seed) {
    # Deterministic GUID so the same column/content type has the same ID in DEV/TEST/PROD.
    $md5  = [System.Security.Cryptography.MD5]::Create()
    $hash = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes("RH.DMS::$Seed"))
    [guid]::new($hash)
}

function ConvertTo-XmlText([string]$Value) { [System.Security.SecurityElement]::Escape($Value) }

function Connect-Site([string]$Url) {
    for ($i = 1; $i -le 10; $i++) {
        try {
            Connect-PnPOnline -Url $Url -Interactive -ClientId $ClientId
            Get-PnPWeb | Out-Null
            return
        } catch {
            if ($i -eq 10) { throw }
            Write-Warn2 "Site not reachable yet ($Url). Retry $i/10 in 15s..."
            Start-Sleep -Seconds 15
        }
    }
}

function Resolve-LoginName([string]$Member) {
    $g = [guid]::Empty
    if ([guid]::TryParse($Member, [ref]$g)) { return "c:0t.c|tenant|$g" }   # Entra security group
    return "i:0#.f|membership|$Member"                                     # user UPN
}
#endregion

#region ---------------------------------------------------------------- choice sets (key = stored value, he = Hebrew label)
$Choices = [ordered]@{
    DocumentArea = @(
        @('Management','ניהול'), @('Commercial','מסחרי'), @('Development','פיתוח'),
        @('Manufacturing','ייצור'), @('Test Engineering','הנדסת בדיקות'), @('Quality','איכות'),
        @('Changes','שינויים'), @('IT','מערכות מידע'), @('InfoSec','אבטחת מידע'))
    DocumentType = @(
        @('Company Profile','פרופיל חברה'), @('Strategy','אסטרטגיה'), @('Policy','מדיניות'),
        @('Procedure','נוהל'), @('Quotation','הצעת מחיר'), @('Contract / NDA','חוזה / NDA'),
        @('SOW','SOW - הגדרת עבודה'), @('SRS','SRS - דרישות מערכת'), @('PDR / CDR','PDR / CDR - סקר תכן'),
        @('FAT / SAT / FDR','FAT / SAT / FDR - בדיקות קבלה'), @('Work Instruction','הוראת עבודה'),
        @('Test Procedure','נוהל בדיקה'), @('PFMEA / Control Plan','PFMEA / תוכנית בקרה'),
        @('ECO / ECN','ECO / ECN - הודעת שינוי'), @('IT Procedure','נוהל מערכות מידע'),
        @('Security Policy','מדיניות אבטחת מידע'))
    ControlMode = @(
        @('Collaboration','שיתופי ללא תהליך'), @('Workflow Optional','תהליך אישור רשות'),
        @('Workflow Required','תהליך אישור חובה'), @('Read-Only Record','רשומה לקריאה בלבד'))
    LifecycleStatus = @(
        @('Working','בעבודה'), @('Submitted','הוגש לאישור'), @('Approved_ReadOnly','מאושר - קריאה בלבד'),
        @('Released_PLM','שוחרר ל-PLM'), @('Obsolete_ReadOnly','מבוטל - קריאה בלבד'), @('Archived','בארכיון'))
    Classification = @(
        @('Public','ציבורי'), @('Internal','פנימי'), @('Confidential','סודי'), @('Restricted','מוגבל'))
    RetentionClass = @(
        @('Temporary','זמני'), @('Record-7Y','רשומה - 7 שנים'), @('Legal Hold','הקפאה משפטית'))
    DocumentLanguage = @(@('English','אנגלית'), @('Hebrew','עברית'), @('Bilingual','דו-לשוני'))
    WorkflowStatus = @(
        @('Pending','ממתין'), @('InReview','בבדיקה'), @('Approved','אושר'), @('Rejected','נדחה'),
        @('Cancelled','בוטל'), @('Restarted','הופעל מחדש'))
    RoutingMode = @(
        @('Hybrid','מקבילי ואז מאשר סופי'), @('Sequential','סדרתי'), @('Parallel','מקבילי'))
    ChangeImpact = @(
        @('Financial or pricing','כספי / תמחור'), @('Contractual/customer commitment','חוזי / התחייבות ללקוח'),
        @('Product design','תכן מוצר'), @('Manufacturing process','תהליך ייצור'),
        @('Test/acceptance','בדיקות / קבלה'), @('Cybersecurity/data','סייבר / מידע'),
        @('Employee/organization','עובדים / ארגון'), @('Supplier/BOM','ספקים / BOM'),
        @('PLM/MAE/Priority integration','ממשק PLM/MAE/Priority'))
    ApproverRole = @(@('Mandatory','חובה'), @('Conditional','מותנה'), @('Reviewer','סוקר'), @('Final','מאשר סופי'))
    Decision = @(
        @('Pending','ממתין'), @('Approved','אושר'), @('Rejected','נדחה'), @('Delegated','הואצל'),
        @('Cancelled','בוטל'), @('Expired','פג תוקף'))
    DelegationStatus = @(@('Active','פעיל'), @('Expired','פג תוקף'), @('Revoked','בוטל'))
    ActionType = @(
        @('VerifyWorkingFile','אימות קובץ עבודה'), @('CreateDraftCopy','יצירת טיוטת גרסה'),
        @('MoveToSubmitted','העברה להגשה'), @('ReturnToWorking','החזרה לעבודה'),
        @('PromoteToCurrent','קידום לגרסה נוכחית'), @('MakeObsolete','העברה לבוטל'),
        @('ReleaseToPLMQueue','שחרור לתור PLM'), @('ArchiveRevision','העברה לארכיון'))
    ActionStatus = @(
        @('Queued','בתור'), @('Processing','בעיבוד'), @('Completed','הושלם'), @('Failed','נכשל'), @('Cancelled','בוטל'))
    ExchangeStatus = @(
        @('Draft','טיוטה'), @('AwaitingUpload','ממתין להעלאה'), @('Uploaded','הועלה'),
        @('ReadyForTransfer','מוכן להעברה'), @('Transferring','בהעברה'), @('Transferred','הועבר'),
        @('Accepted','התקבל'), @('Rejected','נדחה'), @('TransferFailed','העברה נכשלה'),
        @('Cancelled','בוטל'), @('Expired','פג תוקף'))
    Direction = @(@('Inbound','נכנס'), @('Outbound','יוצא'))
    EventType = @(
        @('Created','נוצר'), @('StatusChanged','שינוי סטטוס'), @('Submitted','הוגש'), @('Approved','אושר'),
        @('Rejected','נדחה'), @('Delegated','הואצל'), @('FileActionQueued','פעולת קובץ בתור'),
        @('FileActionCompleted','פעולת קובץ הושלמה'), @('FileActionFailed','פעולת קובץ נכשלה'),
        @('TransferCompleted','העברה הושלמה'), @('TransferFailed','העברה נכשלה'),
        @('CloudCopyDeleted','העותק בענן נמחק'), @('PermissionChanged','שינוי הרשאות'),
        @('Cancelled','בוטל'), @('Expired','פג תוקף'))
    EventSource = @(
        @('PowerApps','Power Apps'), @('PowerAutomate','Power Automate'), @('TransferWorker','Transfer Worker'),
        @('WorkflowService','שירות תהליכים'), @('Manual','ידני'))
    LabelArea = @(@('App','אפליקציה'), @('Field','שדה'), @('Choice','ערך בחירה'), @('List','רשימה'), @('Message','הודעה'))
}
#endregion

#region ---------------------------------------------------------------- site columns
# N internal name | T type | En / He display | Req | Idx | Def default | Set choice set | Max | Min
$Fields = @(
    # --- Document Register
    @{N='DocumentId';        T='Text';      En='Document ID';          He='מזהה מסמך';            Req=$true; Idx=$true; Max=40}
    @{N='DocumentArea';      T='Choice';    En='Document Area';        He='תחום';                 Req=$true; Idx=$true; Set='DocumentArea'}
    @{N='DocumentType';      T='Choice';    En='Document Type';        He='סוג מסמך';             Req=$true; Idx=$true; Set='DocumentType'}
    @{N='ControlMode';       T='Choice';    En='Control Mode';         He='מצב בקרה';             Req=$true; Set='ControlMode'; Def='Workflow Optional'}
    @{N='LifecycleStatus';   T='Choice';    En='Lifecycle Status';     He='סטטוס מחזור חיים';     Req=$true; Idx=$true; Set='LifecycleStatus'; Def='Working'}
    @{N='CurrentRevision';   T='Text';      En='Current Revision';     He='גרסה נוכחית';          Max=20}
    @{N='DraftRevision';     T='Text';      En='Draft Revision';       He='גרסת טיוטה';           Max=20}
    @{N='DocumentOwner';     T='User';      En='Document Owner';       He='בעל המסמך';            Req=$true; Idx=$true}
    @{N='OwnerDepartment';   T='Text';      En='Owner Department';     He='מחלקה אחראית';         Max=100}
    @{N='CustomerCode';      T='Text';      En='Customer Code';        He='קוד לקוח';             Idx=$true; Max=40}
    @{N='ProjectCode';       T='Text';      En='Project Code';         He='קוד פרויקט';           Idx=$true; Max=60}
    @{N='CurrentUncPath';    T='Note';      En='Current UNC Path';     He='נתיב UNC - גרסה נוכחית'}
    @{N='WorkingUncPath';    T='Note';      En='Working UNC Path';     He='נתיב UNC - עבודה'}
    @{N='CurrentSHA256';     T='Text';      En='Current SHA-256';      He='SHA-256 גרסה נוכחית';  Max=64}
    @{N='Classification';    T='Choice';    En='Classification';       He='סיווג';                Req=$true; Set='Classification'; Def='Internal'}
    @{N='RetentionClass';    T='Choice';    En='Retention Class';      He='סיווג שימור';          Req=$true; Set='RetentionClass'; Def='Record-7Y'}
    @{N='DocumentLanguage';  T='Choice';    En='Document Language';    He='שפת המסמך';            Set='DocumentLanguage'; Def='English'}
    @{N='PLMReference';      T='Text';      En='PLM Reference';        He='הפניה ל-PLM';          Max=100}
    @{N='MAEReference';      T='Text';      En='MAE Reference';        He='הפניה ל-MAE';          Max=100}
    @{N='PriorityReference'; T='Text';      En='Priority Reference';   He='הפניה ל-Priority';     Max=100}
    @{N='ReviewCycleMonths'; T='Number';    En='Review Cycle (Months)'; He='מחזור סקירה (חודשים)'; Def='12'; Min=1; MaxN=60}
    @{N='NextReviewDate';    T='DateOnly';  En='Next Review Date';     He='תאריך סקירה הבא';      Idx=$true}
    @{N='EffectiveDate';     T='DateOnly';  En='Effective Date';       He='תאריך תחילת תוקף'}
    @{N='LastApprovedUtc';   T='DateTime';  En='Last Approved (UTC)';  He='אושר לאחרונה (UTC)'}
    @{N='ActiveWorkflowId';  T='Text';      En='Active Workflow ID';   He='מזהה תהליך פעיל';      Max=40}
    # --- Workflow History / Approval Decisions
    @{N='WorkflowId';        T='Text';      En='Workflow ID';          He='מזהה תהליך';           Req=$true; Idx=$true; Max=40}
    @{N='Revision';          T='Text';      En='Revision';             He='גרסה';                 Req=$true; Max=20}
    @{N='SubmittedBy';       T='User';      En='Submitted By';         He='הוגש על ידי'}
    @{N='SubmittedUtc';      T='DateTime';  En='Submitted (UTC)';      He='הוגש (UTC)'}
    @{N='WorkflowStatus';    T='Choice';    En='Workflow Status';      He='סטטוס תהליך';          Req=$true; Idx=$true; Set='WorkflowStatus'; Def='Pending'}
    @{N='RoutingMode';       T='Choice';    En='Routing Mode';         He='אופן ניתוב';           Set='RoutingMode'; Def='Hybrid'}
    @{N='MandatoryApprovers';T='UserMulti'; En='Mandatory Approvers';  He='מאשרי חובה'}
    @{N='ConditionalApprovers';T='UserMulti';En='Conditional Approvers';He='מאשרים מותנים'}
    @{N='AdditionalReviewers';T='UserMulti';En='Additional Reviewers'; He='סוקרים נוספים'}
    @{N='FinalApprover';     T='User';      En='Final Approver';       He='מאשר סופי'}
    @{N='ChangeImpact';      T='MultiChoice'; En='Change Impact';      He='השפעת השינוי';         Set='ChangeImpact'}
    @{N='ChangeSummary';     T='Note';      En='Change Summary';       He='תקציר השינוי';         Req=$true}
    @{N='SubmittedSHA256';   T='Text';      En='Submitted SHA-256';    He='SHA-256 בהגשה';        Max=64}
    @{N='SubmittedUncPath';  T='Note';      En='Submitted UNC Path';   He='נתיב UNC - הגשה'}
    @{N='DecisionDueDate';           T='DateOnly';  En='Due Date';             He='תאריך יעד'}
    @{N='CompletedUtc';      T='DateTime';  En='Completed (UTC)';      He='הושלם (UTC)'}
    @{N='FinalComment';      T='Note';      En='Final Comment';        He='הערת סיכום'}
    @{N='CycleNumber';       T='Number';    En='Cycle Number';         He='מספר מחזור';           Def='1'; Min=1}
    @{N='Approver';          T='User';      En='Approver';             He='מאשר';                 Req=$true; Idx=$true}
    @{N='ApproverRole';      T='Choice';    En='Approver Role';        He='תפקיד המאשר';          Req=$true; Set='ApproverRole'}
    @{N='ApprovalStage';             T='Number';    En='Approval Stage'; He='שלב';                  Def='1'; Min=1}
    @{N='Decision';          T='Choice';    En='Decision';             He='החלטה';                Req=$true; Idx=$true; Set='Decision'; Def='Pending'}
    @{N='DecisionComment';   T='Note';      En='Decision Comment';     He='הערת החלטה'}
    @{N='DecisionUtc';       T='DateTime';  En='Decision (UTC)';       He='מועד החלטה (UTC)'}
    @{N='DelegatedFrom';     T='User';      En='Delegated From';       He='הואצל מאת'}
    @{N='ApprovalRef';       T='Text';      En='Approval Reference';   He='מזהה אישור Teams';     Max=100}
    # --- Approver Matrix / Impact Routing / Delegations
    @{N='MandatoryRoles';    T='Text';      En='Mandatory Role(s)';    He='תפקידי חובה';          Max=255}
    @{N='ConditionalRoles';  T='Text';      En='Conditional Role(s)';  He='תפקידים מותנים';       Max=255}
    @{N='FinalRole';         T='Text';      En='Final Role';           He='תפקיד מאשר סופי';      Max=255}
    @{N='SlaDays';           T='Number';    En='Approval SLA (Days)';  He='SLA לאישור (ימים)';    Def='5'; Min=1; MaxN=60}
    @{N='IsActive';          T='Boolean';   En='Active';               He='פעיל';                 Def='1'}
    @{N='IncludeRoles';      T='Text';      En='Include Role(s)';      He='תפקידים לצירוף';       Max=255}
    @{N='IncludeApprovers';  T='UserMulti'; En='Include Approvers';    He='מאשרים לצירוף'}
    @{N='Delegator';         T='User';      En='Delegator';            He='מאציל';                Req=$true; Idx=$true}
    @{N='DelegateTo';          T='User';      En='Delegate'; He='ממלא מקום';            Req=$true}
    @{N='ValidFrom';         T='DateOnly';  En='Valid From';           He='בתוקף מתאריך';         Req=$true}
    @{N='ValidTo';           T='DateOnly';  En='Valid To';             He='בתוקף עד תאריך';       Req=$true; Idx=$true}
    @{N='DelegationReason';  T='Note';      En='Delegation Reason';    He='סיבת האצלה'}
    @{N='DelegationStatus';  T='Choice';    En='Delegation Status';    He='סטטוס האצלה';          Req=$true; Set='DelegationStatus'; Def='Active'}
    @{N='DelegationApprovedBy'; T='User';   En='Delegation Approved By'; He='האצלה אושרה על ידי'}
    # --- File Action Queue (commands for the on-premises Workflow Service)
    @{N='ActionType';        T='Choice';    En='Action Type';          He='סוג פעולה';            Req=$true; Set='ActionType'}
    @{N='ActionStatus';      T='Choice';    En='Action Status';        He='סטטוס פעולה';          Req=$true; Idx=$true; Set='ActionStatus'; Def='Queued'}
    @{N='SourceUncPath';     T='Note';      En='Source UNC Path';      He='נתיב UNC מקור'}
    @{N='TargetUncPath';     T='Note';      En='Target UNC Path';      He='נתיב UNC יעד'}
    @{N='ResultSHA256';      T='Text';      En='Result SHA-256';       He='SHA-256 תוצאה';        Max=64}
    @{N='ResultSizeBytes';   T='Number';    En='Result Size (Bytes)';  He='גודל תוצאה (בתים)';    Min=0}
    @{N='FailureDetail';     T='Note';      En='Failure Detail';       He='פירוט כשל'}
    @{N='RequestedUtc';      T='DateTime';  En='Requested (UTC)';      He='נדרש (UTC)';           Idx=$true}
    @{N='ProcessedUtc';      T='DateTime';  En='Processed (UTC)';      He='עובד (UTC)'}
    @{N='Attempts';          T='Number';    En='Attempts';             He='ניסיונות';             Def='0'; Min=0}
    @{N='RequestedBy';       T='User';      En='Requested By';         He='התבקש על ידי'}
    # --- Audit (Control Audit + Exchange Audit)
    @{N='CorrelationId';     T='Text';      En='Correlation ID';       He='מזהה קישור';           Req=$true; Idx=$true; Max=60}
    @{N='AuditEventType';         T='Choice';    En='Event Type';           He='סוג אירוע';            Req=$true; Idx=$true; Set='EventType'}
    @{N='FromStatus';        T='Text';      En='From Status';          He='מסטטוס';               Max=40}
    @{N='ToStatus';          T='Text';      En='To Status';            He='לסטטוס';               Max=40}
    @{N='ActorEmail';        T='Text';      En='Actor';                He='מבצע';                 Max=255}
    @{N='EventUtc';          T='DateTime';  En='Event Time (UTC)';     He='מועד אירוע (UTC)';     Req=$true; Idx=$true}
    @{N='EventDetails';      T='Note';      En='Event Details';        He='פרטי אירוע'}
    @{N='EventSource';       T='Choice';    En='Event Source';         He='מקור אירוע';           Req=$true; Set='EventSource'}
    # --- UI Labels (localization catalog)
    @{N='LabelEN';           T='Note';      En='English Text';         He='טקסט באנגלית';         Req=$true}
    @{N='LabelHE';           T='Note';      En='Hebrew Text';          He='טקסט בעברית';          Req=$true}
    @{N='LabelArea';         T='Choice';    En='Label Area';           He='אזור תווית';           Req=$true; Idx=$true; Set='LabelArea'; Def='App'}
    # --- Large File Exchange (blueprint section 9.2)
    @{N='RequestId';         T='Text';      En='Request ID';           He='מזהה בקשה';            Req=$true; Idx=$true; Max=40}
    @{N='UploaderEmail';     T='Text';      En='Uploader Email';       He='דוא"ל המעלה';          Idx=$true; Max=255}
    @{N='GuestEmail';        T='Text';      En='Customer Guest Email'; He='דוא"ל אורח הלקוח';     Max=255}
    @{N='TransferDirection';         T='Choice';    En='Direction'; He='כיוון';                Req=$true; Set='Direction'; Def='Inbound'}
    @{N='PackageDescription';T='Note';      En='Package Description';  He='תיאור החבילה';         Req=$true}
    @{N='DestinationRelativePath'; T='Note';En='Destination Relative Path'; He='נתיב יעד יחסי'}
    @{N='ExchangeStatus';    T='Choice';    En='Exchange Status';      He='סטטוס העברה';          Req=$true; Idx=$true; Set='ExchangeStatus'; Def='Draft'}
    @{N='DriveItemId';       T='Text';      En='Drive Item ID';        He='מזהה פריט בענן';       Max=255}
    @{N='ExchangeFileName';  T='Text';      En='File Name';            He='שם קובץ';              Max=255}
    @{N='ExpectedSizeBytes'; T='Number';    En='Expected Size (Bytes)'; He='גודל צפוי (בתים)';    Min=0}
    @{N='DestinationSizeBytes'; T='Number'; En='Destination Size (Bytes)'; He='גודל ביעד (בתים)'; Min=0}
    @{N='SHA256';            T='Text';      En='SHA-256';              He='SHA-256';              Max=64}
    @{N='UploadFolderUrl';   T='URL';       En='Upload Folder';        He='תיקיית העלאה'}
    @{N='TransferStartedUtc';T='DateTime';  En='Transfer Started (UTC)';   He='תחילת העברה (UTC)'}
    @{N='TransferCompletedUtc'; T='DateTime'; En='Transfer Completed (UTC)'; He='סיום העברה (UTC)'}
    @{N='CloudCopyDeleted';  T='Boolean';   En='Cloud Copy Deleted';   He='העותק בענן נמחק';      Def='0'}
    @{N='ExpiryDate';        T='DateOnly';  En='Expiry Date';          He='תאריך תפוגה';          Idx=$true}
    @{N='ReviewedBy';        T='User';      En='Reviewed By';          He='נבדק על ידי'}
    @{N='CustomerName';      T='Text';      En='Customer Name';        He='שם לקוח';              Max=255}
    @{N='ProjectName';       T='Text';      En='Project Name';         He='שם פרויקט';            Max=255}
    @{N='AllowedGuestDomains'; T='Text';    En='Allowed Guest Domains'; He='דומיינים מורשים לאורחים'; Max=255}
)
$FieldMap = @{}; foreach ($f in $Fields) { $FieldMap[$f.N] = $f }

function Get-FieldXml([hashtable]$F) {
    $id   = Get-StableGuid "Field.$($F.N)"
    $dn   = ConvertTo-XmlText (T $F.En $F.He)
    $req  = if ($F.ContainsKey('Req') -and $F.Req) { 'TRUE' } else { 'FALSE' }
    $idx  = if ($F.ContainsKey('Idx') -and $F.Idx) { ' Indexed="TRUE"' } else { '' }
    $head = "ID=`"{$id}`" Name=`"$($F.N)`" StaticName=`"$($F.N)`" DisplayName=`"$dn`" Group=`"$Script:FieldGrp`" Required=`"$req`"$idx"
    $def  = if ($F.ContainsKey('Def')) { "<Default>$(ConvertTo-XmlText $F.Def)</Default>" } else { '' }
    $choicesXml = {
        param($set)
        '<CHOICES>' + (($Choices[$set] | ForEach-Object { "<CHOICE>$(ConvertTo-XmlText $_[0])</CHOICE>" }) -join '') + '</CHOICES>'
    }
    switch ($F.T) {
        'Text'        { $max = if ($F.ContainsKey('Max')) { $F.Max } else { 255 }
                        "<Field Type=`"Text`" $head MaxLength=`"$max`">$def</Field>" }
        'Note'        { "<Field Type=`"Note`" $head NumLines=`"6`" RichText=`"FALSE`" RichTextMode=`"Compatible`" AppendOnly=`"FALSE`">$def</Field>" }
        'Choice'      { "<Field Type=`"Choice`" $head Format=`"Dropdown`" FillInChoice=`"FALSE`">$(& $choicesXml $F.Set)$def</Field>" }
        'MultiChoice' { "<Field Type=`"MultiChoice`" $head FillInChoice=`"FALSE`">$(& $choicesXml $F.Set)$def</Field>" }
        'Number'      { $mm = ''
                        if ($F.ContainsKey('Min'))  { $mm += " Min=`"$($F.Min)`"" }
                        if ($F.ContainsKey('MaxN')) { $mm += " Max=`"$($F.MaxN)`"" }
                        "<Field Type=`"Number`" $head Decimals=`"0`"$mm>$def</Field>" }
        'DateTime'    { "<Field Type=`"DateTime`" $head Format=`"DateTime`" FriendlyDisplayFormat=`"Disabled`">$def</Field>" }
        'DateOnly'    { "<Field Type=`"DateTime`" $head Format=`"DateOnly`" FriendlyDisplayFormat=`"Disabled`">$def</Field>" }
        'Boolean'     { "<Field Type=`"Boolean`" $head>$def</Field>" }
        'User'        { "<Field Type=`"User`" $head List=`"UserInfo`" ShowField=`"ImnName`" UserSelectionMode=`"PeopleOnly`" UserSelectionScope=`"0`" />" }
        'UserMulti'   { "<Field Type=`"UserMulti`" $head List=`"UserInfo`" ShowField=`"ImnName`" UserSelectionMode=`"PeopleOnly`" UserSelectionScope=`"0`" Mult=`"TRUE`" />" }
        'URL'         { "<Field Type=`"URL`" $head Format=`"Hyperlink`" />" }
        default       { throw "Unknown field type $($F.T) for $($F.N)" }
    }
}
#endregion

#region ---------------------------------------------------------------- content types
# Id: 0x0100 + GUID (Item)  |  0x010100 + GUID (Document)
function Get-ContentTypeId([string]$Key, [string]$Parent) {
    $g = (Get-StableGuid "CT.$Key").ToString('N').ToUpperInvariant()
    if ($Parent -eq 'Document') { "0x010100$g" } else { "0x0100$g" }
}
$ContentTypes = [ordered]@{
    ControlledDocument = @{ En='DMS Controlled Document'; He='מסמך מבוקר'; Parent='Item'
        Fields=@('DocumentId','DocumentArea','DocumentType','ControlMode','LifecycleStatus','CurrentRevision','DraftRevision',
                 'DocumentOwner','OwnerDepartment','CustomerCode','ProjectCode','Classification','RetentionClass','DocumentLanguage',
                 'CurrentUncPath','WorkingUncPath','CurrentSHA256','PLMReference','MAEReference','PriorityReference',
                 'ReviewCycleMonths','NextReviewDate','EffectiveDate','LastApprovedUtc','ActiveWorkflowId') }
    WorkflowCycle = @{ En='DMS Workflow Cycle'; He='מחזור אישור'; Parent='Item'
        Fields=@('WorkflowId','DocumentId','Revision','CycleNumber','WorkflowStatus','RoutingMode','SubmittedBy','SubmittedUtc',
                 'MandatoryApprovers','ConditionalApprovers','AdditionalReviewers','FinalApprover','ChangeImpact','ChangeSummary',
                 'SubmittedSHA256','SubmittedUncPath','DecisionDueDate','CompletedUtc','FinalComment') }
    ApprovalDecision = @{ En='DMS Approval Decision'; He='החלטת מאשר'; Parent='Item'
        Fields=@('WorkflowId','DocumentId','Revision','Approver','ApproverRole','ApprovalStage','Decision','DecisionComment',
                 'DecisionUtc','DelegatedFrom','DecisionDueDate','ApprovalRef') }
    ApproverRule = @{ En='DMS Approver Rule'; He='כלל מאשרים'; Parent='Item'
        Fields=@('DocumentArea','DocumentType','MandatoryRoles','MandatoryApprovers','ConditionalRoles','ConditionalApprovers',
                 'FinalRole','FinalApprover','RoutingMode','SlaDays','IsActive') }
    ImpactRule = @{ En='DMS Impact Rule'; He='כלל השפעה'; Parent='Item'
        Fields=@('ChangeImpact','IncludeRoles','IncludeApprovers','IsActive') }
    Delegation = @{ En='DMS Delegation'; He='האצלת סמכות'; Parent='Item'
        Fields=@('Delegator','DelegateTo','ValidFrom','ValidTo','DelegationReason','DelegationStatus','DelegationApprovedBy') }
    FileAction = @{ En='DMS File Action'; He='פעולת קובץ'; Parent='Item'
        Fields=@('DocumentId','WorkflowId','Revision','ActionType','ActionStatus','SourceUncPath','TargetUncPath','ResultSHA256',
                 'ResultSizeBytes','FailureDetail','RequestedBy','RequestedUtc','ProcessedUtc','Attempts') }
    AuditEvent = @{ En='DMS Audit Event'; He='אירוע ביקורת'; Parent='Item'
        Fields=@('CorrelationId','AuditEventType','FromStatus','ToStatus','ActorEmail','EventUtc','EventSource','EventDetails') }
    UiLabel = @{ En='DMS UI Label'; He='תווית ממשק'; Parent='Item'
        Fields=@('LabelArea','LabelEN','LabelHE') }
    ExchangeRequest = @{ En='DMS Exchange Request'; He='בקשת העברת קבצים'; Parent='Item'
        Fields=@('RequestId','CustomerCode','ProjectCode','TransferDirection','PackageDescription','RequestedBy','UploaderEmail','GuestEmail',
                 'DestinationRelativePath','ExchangeStatus','DriveItemId','ExchangeFileName','ExpectedSizeBytes','DestinationSizeBytes',
                 'SHA256','UploadFolderUrl','TransferStartedUtc','TransferCompletedUtc','FailureDetail','CloudCopyDeleted',
                 'RetentionClass','ExpiryDate','ReviewedBy','DecisionComment','Attempts') }
    RoutingEntry = @{ En='DMS Routing Entry'; He='ניתוב לקוח/פרויקט'; Parent='Item'
        Fields=@('CustomerCode','CustomerName','ProjectCode','ProjectName','DestinationRelativePath','AllowedGuestDomains','IsActive') }
    ExchangeFile = @{ En='DMS Exchange File'; He='קובץ בהעברה'; Parent='Document'
        Fields=@('RequestId') }
}
#endregion

#region ---------------------------------------------------------------- lists, views, permissions
# Perm entries: group key -> role key. Role keys resolved later (built-in roles are localized on Hebrew sites).
$Q_OrderById   = "<OrderBy><FieldRef Name='DocumentId' /></OrderBy>"
$Q_Me          = { param($f) "<Eq><FieldRef Name='$f' /><Value Type='Integer'><UserID Type='Integer' /></Value></Eq>" }
function Get-CamlIn([string]$Field, [string[]]$Values) {
    "<In><FieldRef Name='$Field' /><Values>" + (($Values | ForEach-Object { "<Value Type='Text'>$_</Value>" }) -join '') + "</Values></In>"
}

$Lists = @(
    # ======================= DOCUMENT CONTROL SITE =======================
    @{ Site='DC'; Key='DocumentRegister'; Url='Lists/DocumentRegister'; Tpl='GenericList'; Ct='ControlledDocument'
       En='Document Register'; He='מרשם מסמכים'; TitleEn='Document Title'; TitleHe='כותרת המסמך'
       Versioning=$true; MajorVersions=500; Unique=@('DocumentId')
       Views=@(
         @{En='All Documents'; He='כל המסמכים'; Default=$true
           Fields=@('DocumentId','LinkTitle','DocumentArea','DocumentType','CurrentRevision','LifecycleStatus','ControlMode','DocumentOwner','NextReviewDate','Modified')
           Query=$Q_OrderById}
         @{En='My Documents'; He='המסמכים שלי'
           Fields=@('DocumentId','LinkTitle','DocumentType','CurrentRevision','DraftRevision','LifecycleStatus','NextReviewDate')
           Query="<Where>$(& $Q_Me 'DocumentOwner')</Where>$Q_OrderById"}
         @{En='Pending Approval'; He='ממתינים לאישור'
           Fields=@('DocumentId','LinkTitle','DocumentType','DraftRevision','DocumentOwner','ActiveWorkflowId','Modified')
           Query="<Where><Eq><FieldRef Name='LifecycleStatus' /><Value Type='Text'>Submitted</Value></Eq></Where>$Q_OrderById"}
         @{En='Due for Review (30 days)'; He='לסקירה ב-30 הימים הקרובים'
           Fields=@('DocumentId','LinkTitle','DocumentType','CurrentRevision','DocumentOwner','NextReviewDate')
           Query="<Where><And><Leq><FieldRef Name='NextReviewDate' /><Value Type='DateTime'><Today OffsetDays='30' /></Value></Leq>$(Get-CamlIn 'LifecycleStatus' @('Approved_ReadOnly','Released_PLM'))</And></Where><OrderBy><FieldRef Name='NextReviewDate' /></OrderBy>"}
         @{En='Obsolete and Archived'; He='מבוטלים ובארכיון'
           Fields=@('DocumentId','LinkTitle','DocumentType','CurrentRevision','LifecycleStatus','RetentionClass','Modified')
           Query="<Where>$(Get-CamlIn 'LifecycleStatus' @('Obsolete_ReadOnly','Archived'))</Where>$Q_OrderById"}
       ) }
    @{ Site='DC'; Key='WorkflowHistory'; Url='Lists/WorkflowHistory'; Tpl='GenericList'; Ct='WorkflowCycle'
       En='Workflow History'; He='היסטוריית תהליכים'; TitleEn='Workflow Title'; TitleHe='כותרת התהליך'
       Versioning=$true; MajorVersions=500; Unique=@('WorkflowId')
       Perms=@{ DcOwners='FullControl'; DcService='ServiceContribute'; DcControllers='Read'; DcApprovers='Read'; DcMembers='Read'; DcAuditors='Read' }
       Views=@(
         @{En='Active Workflows'; He='תהליכים פעילים'; Default=$true
           Fields=@('WorkflowId','DocumentId','Revision','LinkTitle','WorkflowStatus','SubmittedBy','SubmittedUtc','DecisionDueDate')
           Query="<Where>$(Get-CamlIn 'WorkflowStatus' @('Pending','InReview'))</Where><OrderBy><FieldRef Name='SubmittedUtc' Ascending='FALSE' /></OrderBy>"}
         @{En='All Workflows'; He='כל התהליכים'
           Fields=@('WorkflowId','DocumentId','Revision','CycleNumber','WorkflowStatus','SubmittedBy','SubmittedUtc','CompletedUtc')
           Query="<OrderBy><FieldRef Name='SubmittedUtc' Ascending='FALSE' /></OrderBy>"}
       ) }
    @{ Site='DC'; Key='ApprovalDecisions'; Url='Lists/ApprovalDecisions'; Tpl='GenericList'; Ct='ApprovalDecision'
       En='Approval Decisions'; He='החלטות מאשרים'; TitleEn='Decision Title'; TitleHe='כותרת ההחלטה'
       Versioning=$true; MajorVersions=100
       Perms=@{ DcOwners='FullControl'; DcService='ServiceContribute'; DcControllers='Read'; DcApprovers='Read'; DcMembers='Read'; DcAuditors='Read' }
       Views=@(
         @{En='My Pending Decisions'; He='החלטות הממתינות לי'; Default=$true
           Fields=@('WorkflowId','DocumentId','Revision','ApproverRole','ApprovalStage','Decision','DecisionDueDate')
           Query="<Where><And>$(& $Q_Me 'Approver')<Eq><FieldRef Name='Decision' /><Value Type='Text'>Pending</Value></Eq></And></Where><OrderBy><FieldRef Name='DecisionDueDate' /></OrderBy>"}
         @{En='All Decisions'; He='כל ההחלטות'
           Fields=@('WorkflowId','DocumentId','Revision','Approver','ApproverRole','ApprovalStage','Decision','DecisionUtc','DelegatedFrom')
           Query="<OrderBy><FieldRef Name='WorkflowId' /><FieldRef Name='ApprovalStage' /></OrderBy>"}
       ) }
    @{ Site='DC'; Key='ApproverMatrix'; Url='Lists/ApproverMatrix'; Tpl='GenericList'; Ct='ApproverRule'
       En='Approver Matrix'; He='מטריצת מאשרים'; TitleEn='Rule Name'; TitleHe='שם הכלל'
       Versioning=$true; MajorVersions=100
       Views=@(
         @{En='All Rules'; He='כל הכללים'; Default=$true
           Fields=@('LinkTitle','DocumentArea','DocumentType','MandatoryRoles','ConditionalRoles','FinalRole','SlaDays','IsActive')
           Query="<OrderBy><FieldRef Name='DocumentArea' /><FieldRef Name='DocumentType' /></OrderBy>"}
       ) }
    @{ Site='DC'; Key='ImpactRouting'; Url='Lists/ImpactRouting'; Tpl='GenericList'; Ct='ImpactRule'
       En='Impact Routing'; He='ניתוב לפי השפעה'; TitleEn='Rule Name'; TitleHe='שם הכלל'
       Versioning=$true; MajorVersions=100
       Views=@(@{En='All Impact Rules'; He='כל כללי ההשפעה'; Default=$true
                 Fields=@('LinkTitle','ChangeImpact','IncludeRoles','IncludeApprovers','IsActive'); Query=''}) }
    @{ Site='DC'; Key='Delegations'; Url='Lists/Delegations'; Tpl='GenericList'; Ct='Delegation'
       En='Delegations'; He='האצלות סמכות'; TitleEn='Delegation Title'; TitleHe='כותרת ההאצלה'
       Versioning=$true; MajorVersions=100
       Views=@(
         @{En='Active Delegations'; He='האצלות פעילות'; Default=$true
           Fields=@('Delegator','DelegateTo','ValidFrom','ValidTo','DelegationStatus','DelegationApprovedBy')
           Query="<Where><Eq><FieldRef Name='DelegationStatus' /><Value Type='Text'>Active</Value></Eq></Where><OrderBy><FieldRef Name='ValidTo' /></OrderBy>"}
       ) }
    @{ Site='DC'; Key='FileActionQueue'; Url='Lists/FileActionQueue'; Tpl='GenericList'; Ct='FileAction'
       En='File Action Queue'; He='תור פעולות קבצים'; TitleEn='Action Title'; TitleHe='כותרת הפעולה'
       Versioning=$true; MajorVersions=50
       Perms=@{ DcOwners='FullControl'; DcService='ServiceContribute'; DcControllers='Read'; DcAuditors='Read' }
       Views=@(
         @{En='Open Actions'; He='פעולות פתוחות'; Default=$true
           Fields=@('ID','ActionType','ActionStatus','DocumentId','Revision','WorkflowId','RequestedUtc','Attempts')
           Query="<Where>$(Get-CamlIn 'ActionStatus' @('Queued','Processing'))</Where><OrderBy><FieldRef Name='RequestedUtc' /></OrderBy>"}
         @{En='Failed Actions'; He='פעולות שנכשלו'
           Fields=@('ID','ActionType','DocumentId','Revision','FailureDetail','Attempts','ProcessedUtc')
           Query="<Where><Eq><FieldRef Name='ActionStatus' /><Value Type='Text'>Failed</Value></Eq></Where><OrderBy><FieldRef Name='ProcessedUtc' Ascending='FALSE' /></OrderBy>"}
       ) }
    @{ Site='DC'; Key='ControlAudit'; Url='Lists/ControlAudit'; Tpl='GenericList'; Ct='AuditEvent'
       En='Control Audit'; He='יומן ביקורת - בקרת מסמכים'; TitleEn='Event'; TitleHe='אירוע'
       Versioning=$true; MajorVersions=50
       Perms=@{ DcOwners='FullControl'; DcService='AppendOnly'; DcControllers='Read'; DcAuditors='Read' }
       Views=@(@{En='All Events'; He='כל האירועים'; Default=$true
                 Fields=@('EventUtc','CorrelationId','AuditEventType','FromStatus','ToStatus','ActorEmail','EventSource')
                 Query="<OrderBy><FieldRef Name='EventUtc' Ascending='FALSE' /></OrderBy>"}) }
    @{ Site='DC'; Key='UiLabels'; Url='Lists/UiLabels'; Tpl='GenericList'; Ct='UiLabel'
       En='UI Labels'; He='תוויות ממשק'; TitleEn='Label Key'; TitleHe='מפתח תווית'
       Versioning=$true; MajorVersions=50; Unique=@('Title')
       Views=@(@{En='All Labels'; He='כל התוויות'; Default=$true
                 Fields=@('LinkTitle','LabelArea','LabelEN','LabelHE')
                 Query="<OrderBy><FieldRef Name='Title' /></OrderBy>"}) }

    # ======================= LARGE FILE EXCHANGE SITE =======================
    @{ Site='EX'; Key='TemporaryUploads'; Url='TemporaryUploads'; Tpl='DocumentLibrary'; Ct='ExchangeFile'
       En='Temporary Uploads'; He='העלאות זמניות'
       Versioning=$false
       Perms=@{ ExOwners='FullControl'; ExService='Contribute'; ExControllers='DocumentController' }
       Views=@(@{En='By Request'; He='לפי בקשה'; Default=$true
                 Fields=@('DocIcon','LinkFilename','RequestId','FileSizeDisplay','Modified','Editor')
                 Query="<OrderBy><FieldRef Name='Modified' Ascending='FALSE' /></OrderBy>"}) }
    @{ Site='EX'; Key='UploadRequests'; Url='Lists/UploadRequests'; Tpl='GenericList'; Ct='ExchangeRequest'
       En='Upload Requests'; He='בקשות העלאה'; TitleEn='Request Title'; TitleHe='כותרת הבקשה'
       Versioning=$true; MajorVersions=100; Unique=@('RequestId'); Defaults=@{ RetentionClass='Temporary' }
       Perms=@{ ExOwners='FullControl'; ExService='ServiceContribute'; ExControllers='DocumentController'; ExEmployees='Read'; ExAuditors='Read' }
       Views=@(
         @{En='Active Requests'; He='בקשות פעילות'; Default=$true
           Fields=@('RequestId','LinkTitle','CustomerCode','ProjectCode','TransferDirection','ExchangeStatus','ExchangeFileName','ExpectedSizeBytes','ExpiryDate','Modified')
           Query="<Where>$(Get-CamlIn 'ExchangeStatus' @('Draft','AwaitingUpload','Uploaded','ReadyForTransfer','Transferring','Transferred','TransferFailed'))</Where><OrderBy><FieldRef Name='Modified' Ascending='FALSE' /></OrderBy>"}
         @{En='My Requests'; He='הבקשות שלי'
           Fields=@('RequestId','LinkTitle','CustomerCode','ProjectCode','ExchangeStatus','ExchangeFileName','Modified')
           Query="<Where>$(& $Q_Me 'RequestedBy')</Where><OrderBy><FieldRef Name='Modified' Ascending='FALSE' /></OrderBy>"}
         @{En='Failed Transfers'; He='העברות שנכשלו'
           Fields=@('RequestId','CustomerCode','ExchangeFileName','ExpectedSizeBytes','DestinationSizeBytes','FailureDetail','Attempts','Modified')
           Query="<Where><Eq><FieldRef Name='ExchangeStatus' /><Value Type='Text'>TransferFailed</Value></Eq></Where><OrderBy><FieldRef Name='Modified' Ascending='FALSE' /></OrderBy>"}
         @{En='Awaiting Cloud Deletion'; He='ממתינים למחיקה מהענן'
           Fields=@('RequestId','ExchangeFileName','ExchangeStatus','TransferCompletedUtc','CloudCopyDeleted','RetentionClass')
           Query="<Where><And><Eq><FieldRef Name='CloudCopyDeleted' /><Value Type='Boolean'>0</Value></Eq>$(Get-CamlIn 'ExchangeStatus' @('Transferred','Accepted','Rejected'))</And></Where>"}
       ) }
    @{ Site='EX'; Key='ExchangeAudit'; Url='Lists/ExchangeAudit'; Tpl='GenericList'; Ct='AuditEvent'
       En='Exchange Audit'; He='יומן ביקורת - העברת קבצים'; TitleEn='Event'; TitleHe='אירוע'
       Versioning=$true; MajorVersions=50
       Perms=@{ ExOwners='FullControl'; ExService='AppendOnly'; ExControllers='Read'; ExAuditors='Read' }
       Views=@(@{En='All Events'; He='כל האירועים'; Default=$true
                 Fields=@('EventUtc','CorrelationId','AuditEventType','FromStatus','ToStatus','ActorEmail','EventSource')
                 Query="<OrderBy><FieldRef Name='EventUtc' Ascending='FALSE' /></OrderBy>"}) }
    @{ Site='EX'; Key='RoutingCatalog'; Url='Lists/RoutingCatalog'; Tpl='GenericList'; Ct='RoutingEntry'
       En='Routing Catalog'; He='קטלוג ניתוב'; TitleEn='Route Name'; TitleHe='שם הניתוב'
       Versioning=$true; MajorVersions=100
       Perms=@{ ExOwners='FullControl'; ExService='Read'; ExControllers='DocumentController'; ExEmployees='Read'; ExAuditors='Read' }
       Views=@(@{En='Active Routes'; He='ניתובים פעילים'; Default=$true
                 Fields=@('LinkTitle','CustomerCode','CustomerName','ProjectCode','ProjectName','DestinationRelativePath','IsActive')
                 Query="<Where><Eq><FieldRef Name='IsActive' /><Value Type='Boolean'>1</Value></Eq></Where><OrderBy><FieldRef Name='CustomerCode' /><FieldRef Name='ProjectCode' /></OrderBy>"}) }
)

# Custom permission levels (created on each site collection root web)
$RoleDefs = @(
    @{ Key='DocumentController'; En='DMS Document Controller'; He='DMS - בקר מסמכים'; Clone='Contributor'
       Include=@('ApproveItems','CancelCheckout','ManageAlerts'); Exclude=@('DeleteVersions')
       DescEn='Controlled modify: edit registers and matrices, approve items. Cannot delete versions.'
       DescHe='שינוי מבוקר: עריכת מרשמים ומטריצות, אישור פריטים. ללא מחיקת גרסאות.' }
    @{ Key='ServiceContribute'; En='DMS Service Contribute'; He='DMS - תרומה לשירות'; Clone='Contributor'
       Include=@(); Exclude=@('DeleteListItems','DeleteVersions')
       DescEn='Workflow service identity: add and edit, never delete.'; DescHe='זהות שירות: הוספה ועריכה, ללא מחיקה.' }
    @{ Key='AppendOnly'; En='DMS Append Only'; He='DMS - הוספה בלבד'; Clone='Reader'
       Include=@('AddListItems'); Exclude=@()
       DescEn='Audit writers: add and read, no edit or delete.'; DescHe='כותבי ביקורת: הוספה וקריאה, ללא עריכה או מחיקה.' }
    @{ Key='UploadOnly'; En='DMS Upload Only'; He='DMS - העלאה בלבד'; Clone='Contributor'
       Include=@(); Exclude=@('DeleteListItems','DeleteVersions','ManagePersonalViews','CreateAlerts')
       DescEn='Per-request upload folders (employees and B2B guests). No delete.'; DescHe='תיקיות העלאה לבקשה (עובדים ואורחים). ללא מחיקה.' }
)

# SharePoint groups. Site = DC | EX. SiteRole = role key at site (web) level.
$Groups = @(
    @{ Key='DcOwners';      Site='DC'; En='DMS Owners';               He='DMS - בעלים';          SiteRole='FullControl'
       DescEn='M365 / SharePoint administrators (IT).'; DescHe='מנהלי M365 / SharePoint (מערכות מידע).' }
    @{ Key='DcControllers'; Site='DC'; En='DMS Document Controllers'; He='DMS - בקרי מסמכים';    SiteRole='DocumentController'
       DescEn='Document Control team.'; DescHe='צוות בקרת מסמכים.' }
    @{ Key='DcApprovers';   Site='DC'; En='DMS Approvers';            He='DMS - מאשרים';         SiteRole='Read'
       DescEn='Everyone who may appear in the approver matrix.'; DescHe='כל מי שעשוי להופיע במטריצת המאשרים.' }
    @{ Key='DcMembers';     Site='DC'; En='DMS Members';              He='DMS - עובדים';         SiteRole='Read'
       DescEn='Licensed employees. Writes only through flows.'; DescHe='עובדים מורשים. כתיבה רק דרך תהליכים.' }
    @{ Key='DcAuditors';    Site='DC'; En='DMS Auditors';             He='DMS - מבקרים';         SiteRole='Read'
       DescEn='Quality / InfoSec / internal audit (read everything).'; DescHe='איכות / אבטחת מידע / ביקורת פנים (קריאה בלבד).' }
    @{ Key='DcService';     Site='DC'; En='DMS Service Accounts';     He='DMS - חשבונות שירות';  SiteRole='ServiceContribute'
       DescEn='Power Automate connection owner account only.'; DescHe='חשבון השירות של Power Automate בלבד.' }
    @{ Key='ExOwners';      Site='EX'; En='Exchange Owners';          He='העברת קבצים - בעלים';   SiteRole='FullControl'
       DescEn='M365 / SharePoint administrators (IT).'; DescHe='מנהלי M365 / SharePoint (מערכות מידע).' }
    @{ Key='ExControllers'; Site='EX'; En='Exchange Document Control'; He='העברת קבצים - בקרת מסמכים'; SiteRole='DocumentController'
       DescEn='Document Control staff: accept / reject / route.'; DescHe='צוות בקרת מסמכים: קבלה / דחייה / ניתוב.' }
    @{ Key='ExEmployees';   Site='EX'; En='Exchange Employees';       He='העברת קבצים - עובדים';  SiteRole='Read'
       DescEn='Internal employees. Never add guests.'; DescHe='עובדים פנימיים בלבד. אין להוסיף אורחים.' }
    @{ Key='ExAuditors';    Site='EX'; En='Exchange Auditors';        He='העברת קבצים - מבקרים';  SiteRole='Read'
       DescEn='Security / audit read access.'; DescHe='אבטחת מידע / ביקורת - קריאה.' }
    @{ Key='ExService';     Site='EX'; En='Exchange Service Accounts'; He='העברת קבצים - חשבונות שירות'; SiteRole='ServiceContribute'
       DescEn='Power Automate connection owner account only.'; DescHe='חשבון השירות של Power Automate בלבד.' }
)
#endregion

#region ---------------------------------------------------------------- seed data
$ApproverMatrixSeed = @(
    # Area, Type, Mandatory, Conditional, Final
    ,@('Management','Company Profile','Marketing Manager','Quality; Legal','CEO')
    ,@('Management','Strategy','Relevant VP','Finance','CEO')
    ,@('Management','Policy','Department Manager','IT; HR; Quality; Legal','Authorized Executive')
    ,@('Management','Procedure','Department Manager','Quality; IT Security','Quality Manager')
    ,@('Commercial','Quotation','Sales Manager','Engineering; Finance; Purchasing','Commercial Manager')
    ,@('Commercial','Contract / NDA','Business Owner','Finance; Quality; IT Security','Legal / Signatory')
    ,@('Development','SOW','Engineering Manager','Finance; Operations; Customer','CTO')
    ,@('Development','SRS','Engineering Manager','Quality; Test; IT Security','Project Manager / CTO')
    ,@('Development','PDR / CDR','Engineering Lead','Quality; Manufacturing; Test; Customer','CTO')
    ,@('Development','FAT / SAT / FDR','Engineering Manager','Quality; Operations; Customer','Project Manager / CTO')
    ,@('Manufacturing','Work Instruction','Manufacturing Manager','Quality; Safety','Quality Manager')
    ,@('Test Engineering','Test Procedure','Test Manager','Development; Quality','Engineering / Quality')
    ,@('Quality','PFMEA / Control Plan','Quality Manager','Engineering; Manufacturing','Quality Manager')
    ,@('Changes','ECO / ECN','Engineering Manager','Quality; Manufacturing; Purchasing; Planning','Document Control / CTO')
    ,@('IT','IT Procedure','IT Manager','Information Security; Quality','CIO')
    ,@('InfoSec','Security Policy','Information Security Manager','Legal; HR; Quality','CEO / CIO')
)
$ImpactSeed = @(
    ,@('Financial or pricing','Finance')
    ,@('Contractual/customer commitment','Legal; CFT')
    ,@('Product design','Engineering')
    ,@('Manufacturing process','Manufacturing; Quality')
    ,@('Test/acceptance','Test Engineering; Quality')
    ,@('Cybersecurity/data','IT Security')
    ,@('Employee/organization','HR')
    ,@('Supplier/BOM','Purchasing; Quality')
    ,@('PLM/MAE/Priority integration','Document Control; System Owner')
)

# App labels and notification templates. {Placeholders} are replaced by Power Fx / Power Automate.
$AppLabels = @(
    ,@('app.title.dcc','Document Control Center','מרכז בקרת מסמכים')
    ,@('app.title.lfe','Large File Exchange Control','בקרת העברת קבצים גדולים')
    ,@('app.nav.home','Home','ראשי')
    ,@('app.nav.register','Document Register','מרשם מסמכים')
    ,@('app.nav.approvals','My Approvals','האישורים שלי')
    ,@('app.nav.doccontrol','Document Control','בקרת מסמכים')
    ,@('app.nav.admin','Administration','ניהול')
    ,@('app.nav.settings','Settings','הגדרות')
    ,@('app.tile.mydocs','My documents','המסמכים שלי')
    ,@('app.tile.pending','Waiting for my approval','ממתינים לאישורי')
    ,@('app.tile.submitted','In approval','בתהליך אישור')
    ,@('app.tile.duereview','Due for review','לסקירה תקופתית')
    ,@('app.tile.failed','Failed file actions','פעולות קבצים שנכשלו')
    ,@('app.btn.new','New document','מסמך חדש')
    ,@('app.btn.newrev','Create new revision','יצירת גרסה חדשה')
    ,@('app.btn.submit','Submit for approval','הגשה לאישור')
    ,@('app.btn.cancelwf','Cancel workflow','ביטול תהליך')
    ,@('app.btn.changeapprovers','Change approvers (restart)','שינוי מאשרים (הפעלה מחדש)')
    ,@('app.btn.obsolete','Make obsolete','העברה לבוטל')
    ,@('app.btn.openfolder','Open folder','פתיחת תיקייה')
    ,@('app.btn.copypath','Copy UNC path','העתקת נתיב UNC')
    ,@('app.btn.save','Save','שמירה')
    ,@('app.btn.cancel','Cancel','ביטול')
    ,@('app.btn.back','Back','חזרה')
    ,@('app.btn.search','Search','חיפוש')
    ,@('app.btn.newrequest','New request','בקשה חדשה')
    ,@('app.btn.ready','Ready for transfer','מוכן להעברה')
    ,@('app.btn.accept','Accept','קבלה')
    ,@('app.btn.reject','Reject','דחייה')
    ,@('app.btn.upload','Open upload folder','פתיחת תיקיית העלאה')
    ,@('app.lbl.language','Language','שפה')
    ,@('app.lbl.required','Required','שדה חובה')
    ,@('app.lbl.requiredapprovers','Required approvers (cannot be removed)','מאשרי חובה (לא ניתן להסיר)')
    ,@('app.lbl.addreviewers','Add reviewers','הוספת סוקרים')
    ,@('app.lbl.impact','What does this change affect?','על מה משפיע השינוי?')
    ,@('app.lbl.summary','Change summary','תקציר השינוי')
    ,@('app.lbl.history','Approval history','היסטוריית אישורים')
    ,@('app.lbl.checksum','Checksum (SHA-256)','ערך בקרה (SHA-256)')
    ,@('app.lbl.search','Search by ID, title, customer or project','חיפוש לפי מזהה, כותרת, לקוח או פרויקט')
    ,@('app.lbl.nodata','No items to show','אין פריטים להצגה')
    ,@('app.lbl.expiry','Upload link expires on','קישור ההעלאה בתוקף עד')
    ,@('app.err.required','Complete all required fields','יש למלא את כל שדות החובה')
    ,@('app.err.approvers','A required approver is missing','חסר מאשר חובה')
    ,@('app.err.duplicate','A request for this package is already in progress','בקשה עבור חבילה זו כבר בטיפול')
    ,@('app.err.path','The destination route is not approved','נתיב היעד אינו מאושר')
    ,@('app.ok.submitted','Submitted. Approvers were notified in Teams.','הוגש. המאשרים קיבלו הודעה ב-Teams.')
    ,@('app.ok.saved','Saved','נשמר')
)
$MsgLabels = @(
    ,@('msg.approval.title','Approval required: {DocumentId} {Revision} - {Title}','נדרש אישור: {DocumentId} {Revision} - {Title}')
    ,@('msg.approval.body','{Submitter} submitted {DocumentId} revision {Revision} for your approval. Change summary: {ChangeSummary}. File (read-only): {UncPath}. SHA-256: {Sha}. Due: {DueDate}.','{Submitter} הגיש/ה את {DocumentId} גרסה {Revision} לאישורך. תקציר השינוי: {ChangeSummary}. קובץ (קריאה בלבד): {UncPath}. SHA-256: {Sha}. תאריך יעד: {DueDate}.')
    ,@('msg.approved.owner','{DocumentId} revision {Revision} was approved and is now the current read-only revision.','{DocumentId} גרסה {Revision} אושרה והיא כעת הגרסה הנוכחית לקריאה בלבד.')
    ,@('msg.rejected.owner','{DocumentId} revision {Revision} was rejected by {Approver}. Comment: {Comment}. The draft was returned to Working.','{DocumentId} גרסה {Revision} נדחתה על ידי {Approver}. הערה: {Comment}. הטיוטה הוחזרה לתיקיית העבודה.')
    ,@('msg.reminder','Reminder: {DocumentId} revision {Revision} has been waiting for your decision for {Days} days.','תזכורת: {DocumentId} גרסה {Revision} ממתינה להחלטתך {Days} ימים.')
    ,@('msg.escalation','Escalation: {Approver} has not decided on {DocumentId} {Revision} for {Days} days.','הסלמה: {Approver} טרם החליט/ה על {DocumentId} {Revision} כבר {Days} ימים.')
    ,@('msg.cancelled','The approval of {DocumentId} revision {Revision} was cancelled by {Actor}. Reason: {Comment}.','תהליך האישור של {DocumentId} גרסה {Revision} בוטל על ידי {Actor}. סיבה: {Comment}.')
    ,@('msg.draft.ready','Draft {Revision} of {DocumentId} is ready for editing: {UncPath}','טיוטה {Revision} של {DocumentId} מוכנה לעריכה: {UncPath}')
    ,@('msg.review.due','{DocumentId} - {Title} is due for periodic review on {NextReviewDate}.','{DocumentId} - {Title} מגיע לסקירה תקופתית בתאריך {NextReviewDate}.')
    ,@('msg.review.overdue','{DocumentId} - {Title} is overdue for periodic review (due {NextReviewDate}).','{DocumentId} - {Title} חרג ממועד הסקירה התקופתית ({NextReviewDate}).')
    ,@('msg.obsolete','{DocumentId} - {Title} is now obsolete (read-only). Reason: {Comment}.','{DocumentId} - {Title} בוטל (קריאה בלבד). סיבה: {Comment}.')
    ,@('msg.fileaction.failed','File action {ActionType} failed for {DocumentId} {Revision}: {Error}','פעולת הקובץ {ActionType} נכשלה עבור {DocumentId} {Revision}: {Error}')
    ,@('msg.delegation.active','{Delegate} is acting for {Delegator} from {ValidFrom} to {ValidTo}.','{Delegate} ממלא/ת את מקומו/ה של {Delegator} מתאריך {ValidFrom} עד {ValidTo}.')
    ,@('msg.ex.created','Exchange request {RequestId} was created. Upload through: {UploadUrl}. The link expires on {ExpiryDate}.','בקשת העברה {RequestId} נוצרה. העלאה דרך: {UploadUrl}. הקישור בתוקף עד {ExpiryDate}.')
    ,@('msg.ex.transferred','{RequestId}: {FileName} ({SizeGB} GB) was transferred and verified (SHA-256 {Sha}). It is waiting in quarantine for Document Control.','{RequestId}: {FileName} ({SizeGB} GB) הועבר ואומת (SHA-256 {Sha}). הקובץ ממתין בהסגר לבקרת מסמכים.')
    ,@('msg.ex.failed','{RequestId}: transfer failed. {Error}. IT was notified. The cloud copy was kept.','{RequestId}: ההעברה נכשלה. {Error}. מערכות מידע קיבלו הודעה. העותק בענן נשמר.')
    ,@('msg.ex.accepted','{RequestId}: {FileName} was accepted by {Actor} and routed to {Destination}.','{RequestId}: {FileName} התקבל על ידי {Actor} ונותב אל {Destination}.')
    ,@('msg.ex.rejected','{RequestId}: {FileName} was rejected by {Actor}. Reason: {Comment}.','{RequestId}: {FileName} נדחה על ידי {Actor}. סיבה: {Comment}.')
    ,@('msg.ex.expiring','{RequestId}: the upload link expires in {Days} days.','{RequestId}: קישור ההעלאה יפוג בעוד {Days} ימים.')
    ,@('msg.ex.expired','{RequestId} expired and its temporary content was removed.','{RequestId} פג תוקף והתוכן הזמני הוסר.')
    ,@('msg.ex.deletefailed','{RequestId}: the cloud copy could not be deleted after a verified transfer. Manual action required.','{RequestId}: לא ניתן היה למחוק את העותק בענן לאחר העברה מאומתת. נדרשת פעולה ידנית.')
)
#endregion

#region ---------------------------------------------------------------- provisioning functions
function Get-RoleNameMap {
    # Built-in role names are localized (e.g. "Read" / "קריאה"); resolve them by RoleTypeKind.
    $all = Get-PnPRoleDefinition
    $map = @{
        FullControl = ($all | Where-Object RoleTypeKind -eq 'Administrator' | Select-Object -First 1).Name
        Contribute  = ($all | Where-Object RoleTypeKind -eq 'Contributor'   | Select-Object -First 1).Name
        Read        = ($all | Where-Object RoleTypeKind -eq 'Reader'        | Select-Object -First 1).Name
        Contributor = ($all | Where-Object RoleTypeKind -eq 'Contributor'   | Select-Object -First 1).Name
        Reader      = ($all | Where-Object RoleTypeKind -eq 'Reader'        | Select-Object -First 1).Name
    }
    foreach ($r in $RoleDefs) { $map[$r.Key] = (T $r.En $r.He) }
    $map
}

function Install-DmsRoleDefinition {
    Write-Step 'Permission levels'
    $existing = @(Get-PnPRoleDefinition | ForEach-Object Name)
    $builtIn  = Get-RoleNameMap
    foreach ($r in $RoleDefs) {
        $name = T $r.En $r.He
        if ($existing -contains $name) { Write-Skip $name; continue }
        $p = @{ RoleName = $name; Clone = $builtIn[$r.Clone]; Description = (T $r.DescEn $r.DescHe) }
        if ($r.Include.Count) { $p.Include = $r.Include }
        if ($r.Exclude.Count) { $p.Exclude = $r.Exclude }
        Add-PnPRoleDefinition @p | Out-Null
        Write-Ok $name
    }
}

function Install-DmsGroup([string]$SiteKey, [hashtable]$Roles) {
    Write-Step "SharePoint groups ($SiteKey)"
    $existing = @(Get-PnPGroup | ForEach-Object Title)
    foreach ($g in $Groups | Where-Object Site -eq $SiteKey) {
        $title = T $g.En $g.He
        if ($existing -notcontains $title) {
            New-PnPGroup -Title $title -Description (T $g.DescEn $g.DescHe) | Out-Null
            Write-Ok "group $title"
        } else { Write-Skip "group $title" }
        Set-PnPGroupPermissions -Identity $title -AddRole $Roles[$g.SiteRole] | Out-Null
        if ($GroupMembers.ContainsKey($g.Key)) {
            foreach ($m in $GroupMembers[$g.Key]) {
                try { Add-PnPGroupMember -Group $title -LoginName (Resolve-LoginName $m); Write-Ok "  member $m" }
                catch { Write-Warn2 "  member $m : $($_.Exception.Message)" }
            }
        }
    }
}

function Install-DmsSiteColumn([string[]]$Needed) {
    Write-Step "Site columns ($($Needed.Count))"
    foreach ($n in $Needed) {
        if (Get-PnPField -Identity $n -ErrorAction SilentlyContinue) { Write-Skip $n; continue }
        Add-PnPFieldFromXml -FieldXml (Get-FieldXml $FieldMap[$n]) | Out-Null
        Write-Ok $n
    }
}

function Install-DmsContentType([string]$Key) {
    $def  = $ContentTypes[$Key]
    $id   = Get-ContentTypeId $Key $def.Parent
    $name = T $def.En $def.He
    $ct   = Get-PnPContentType -Identity $id -ErrorAction SilentlyContinue
    if (-not $ct) {
        # The parent (Item 0x01 / Document 0x0101) is encoded in the ID; PnP 3.x rejects -ParentContentType with -ContentTypeId.
        Add-PnPContentType -Name $name -ContentTypeId $id -Group $Script:CtGrp | Out-Null
        Write-Ok "content type $name"
    } else { Write-Skip "content type $name" }
    # Load the content type's fields through CSOM (PnP 3.x Get-PnPProperty does not enumerate them).
    $ctObj = Get-PnPContentType -Identity $id
    $ctx   = Get-PnPContext
    $ctx.Load($ctObj.Fields)
    $ctx.ExecuteQuery()
    $ctFields = @(foreach ($f in $ctObj.Fields) { $f.InternalName })
    foreach ($n in $def.Fields) {
        if ($ctFields -contains $n) { continue }
        $req = [bool]($FieldMap[$n].ContainsKey('Req') -and $FieldMap[$n].Req)
        try { Add-PnPFieldToContentType -Field $n -ContentType $id -Required:$req }
        catch { if ($_.Exception.Message -notmatch 'already|קיים') { throw } }
    }
    $id
}

function Install-DmsList([hashtable]$L, [hashtable]$Roles) {
    $title = T $L.En $L.He
    Write-Step "List: $title"
    $list = Get-PnPList -Identity $L.Url -ErrorAction SilentlyContinue
    if (-not $list) {
        New-PnPList -Title $title -Template $L.Tpl -Url $L.Url -EnableContentTypes -OnQuickLaunch | Out-Null
        Write-Ok 'created'
    } else { Write-Skip 'exists' }

    # --- settings
    $set = @{ Identity = $L.Url; EnableContentTypes = $true; ListExperience = 'NewExperience' }
    if ($L.Tpl -eq 'GenericList') { $set.EnableAttachments = $false }       # REQ-17: no binaries in lists
    Set-PnPList @set | Out-Null
    try {
        if ($L.Versioning) { Set-PnPList -Identity $L.Url -EnableVersioning $true -MajorVersions $L.MajorVersions | Out-Null }
        else               { Set-PnPList -Identity $L.Url -EnableVersioning $false | Out-Null }
    } catch { Write-Warn2 "versioning: $($_.Exception.Message) (set the library version limit manually)" }

    # --- content type
    $ctId = Install-DmsContentType $L.Ct
    $listCts = Get-PnPContentType -List $L.Url
    if (-not ($listCts | Where-Object { $_.Id.StringValue.StartsWith($ctId) })) {
        Add-PnPContentTypeToList -List $L.Url -ContentType $ctId -DefaultContentType
        Write-Ok "content type added"
    }
    # Remove the default "Item" / "Document" content type so users cannot bypass the schema (folders stay).
    foreach ($x in @($listCts | Where-Object { -not $_.Id.StringValue.StartsWith($ctId) -and -not $_.Id.StringValue.StartsWith('0x0120') })) {
        try { Remove-PnPContentTypeFromList -List $L.Url -ContentType $x; Write-Ok "removed content type $($x.Name)" }
        catch { Write-Warn2 "could not remove content type $($x.Name): $($_.Exception.Message)" }
    }

    # --- Title display name per list
    if ($L.ContainsKey('TitleEn')) {
        Set-PnPField -List $L.Url -Identity 'Title' -Values @{ Title = (T $L.TitleEn $L.TitleHe) } | Out-Null
    }
    # --- unique keys (list-level) and list-specific defaults
    if ($L.ContainsKey('Unique')) {
        foreach ($u in $L.Unique) { Set-PnPField -List $L.Url -Identity $u -Values @{ Indexed = $true; EnforceUniqueValues = $true } | Out-Null }
    }
    if ($L.ContainsKey('Defaults')) {
        foreach ($k in $L.Defaults.Keys) { Set-PnPField -List $L.Url -Identity $k -Values @{ DefaultValue = $L.Defaults[$k] } | Out-Null }
    }

    # --- views
    $views = @(Get-PnPView -List $L.Url | ForEach-Object Title)
    foreach ($v in $L.Views) {
        $vt = T $v.En $v.He
        $isDefault = [bool]($v.ContainsKey('Default') -and $v.Default)
        if ($views -contains $vt) {
            Set-PnPView -List $L.Url -Identity $vt -Fields $v.Fields | Out-Null
            if ($isDefault) { Set-PnPView -List $L.Url -Identity $vt -Values @{ DefaultView = $true } | Out-Null }
            Write-Skip "view $vt (fields refreshed)"
        } else {
            $p = @{ List = $L.Url; Title = $vt; Fields = $v.Fields; RowLimit = 100; Paged = $true; SetAsDefault = $isDefault }
            if ($v.Query) { $p.Query = $v.Query }
            Add-PnPView @p | Out-Null
            Write-Ok "view $vt"
        }
    }

    # --- unique permissions
    if ($L.ContainsKey('Perms')) {
        $l2 = Get-PnPList -Identity $L.Url -Includes HasUniqueRoleAssignments
        if (-not $l2.HasUniqueRoleAssignments) {
            Set-PnPList -Identity $L.Url -BreakRoleInheritance -ClearSubScopes | Out-Null
            Write-Ok 'inheritance broken'
        }
        foreach ($gk in $L.Perms.Keys) {
            $g = $Groups | Where-Object Key -eq $gk
            Set-PnPListPermission -Identity $L.Url -Group (T $g.En $g.He) -AddRole $Roles[$L.Perms[$gk]] | Out-Null
            Write-Ok "  $($g.En) -> $($L.Perms[$gk])"
        }
    }
}

function Add-Seed([string]$ListUrl, [object[]]$Rows) {
    $list = Get-PnPList -Identity $ListUrl -Includes ItemCount
    if ($list.ItemCount -gt 0) { Write-Skip "$ListUrl already has $($list.ItemCount) items"; return }
    $batch = New-PnPBatch
    foreach ($r in $Rows) { Add-PnPListItem -List $ListUrl -Values $r -Batch $batch }
    Invoke-PnPBatch -Batch $batch
    Write-Ok "$ListUrl seeded ($($Rows.Count) rows)"
}

function Get-NeededField([string]$SiteKey) {
    $cts = $Lists | Where-Object Site -eq $SiteKey | ForEach-Object { $_.Ct } | Select-Object -Unique
    $cts | ForEach-Object { $ContentTypes[$_].Fields } | Select-Object -Unique
}
#endregion

#region ---------------------------------------------------------------- 1. sites + tenant-level site settings
try {
    Write-Step "Connecting to tenant admin ($AdminUrl)"
    Connect-Site $AdminUrl

    if (-not $SkipSiteCreation) {
        foreach ($s in @(
            @{ Url = $DcUrl; Title = (T 'Document Control System (DMS)' 'מערכת בקרת מסמכים (DMS)') },
            @{ Url = $ExUrl; Title = (T 'DMS - Large File Exchange' 'DMS - העברת קבצים גדולים') })) {
            if (Get-PnPTenantSite -Identity $s.Url -ErrorAction SilentlyContinue) { Write-Skip "site $($s.Url)"; continue }
            New-PnPSite -Type TeamSiteWithoutMicrosoft365Group -Title $s.Title -Url $s.Url -Owner $OwnerUpn -Lcid $Script:Lcid | Out-Null
            Write-Ok "site $($s.Url) (LCID $Script:Lcid)"
        }
    }

    Write-Step 'Sharing policy'
    # Document Control: internal only.
    Set-PnPTenantSite -Identity $DcUrl -SharingCapability Disabled
    Write-Ok "$DcUrl sharing = Disabled"
    # Exchange: authenticated guests only (no anonymous links), Specific-people links by default.
    $ex = @{ Identity = $ExUrl; SharingCapability = 'ExternalUserSharingOnly'; DefaultSharingLinkType = 'Direct'; DefaultLinkPermission = 'View' }
    if ($AllowedGuestDomains.Count) {
        $ex.SharingDomainRestrictionMode = 'AllowList'
        $ex.SharingAllowedDomainList     = ($AllowedGuestDomains -join ' ')
    }
    Set-PnPTenantSite @ex
    Write-Ok "$ExUrl sharing = ExternalUserSharingOnly, links = Specific people"

    foreach ($app in @(@{ Id = $TransferWorkerAppId; Site = $ExUrl; Name = 'RH-Exchange-Transfer-Worker' },
                       @{ Id = $WorkflowServiceAppId; Site = $DcUrl; Name = 'RH-DMS-Workflow-Service' })) {
        if (-not $app.Id -or $app.Id -eq [guid]::Empty) { continue }
        try {
            Grant-PnPEntraIDAppSitePermission -AppId $app.Id -DisplayName $app.Name -Site $app.Site -Permissions Write | Out-Null
            Write-Ok "Sites.Selected Write: $($app.Name) -> $($app.Site)"
        } catch { Write-Warn2 "Sites.Selected grant for $($app.Name): $($_.Exception.Message)" }
    }

    #endregion

    #region ------------------------------------------------------------ 2. per-site provisioning
    foreach ($site in @(@{ Key = 'DC'; Url = $DcUrl }, @{ Key = 'EX'; Url = $ExUrl })) {
        Write-Step "Provisioning $($site.Url)"
        Connect-Site $site.Url

        # Members may not reshare; only owners share.
        Set-PnPWeb -MembersCanShare:$false | Out-Null

        # Title (also on re-runs) and logo
        $siteTitle = if ($site.Key -eq 'DC') { T 'Document Control System (DMS)' 'מערכת בקרת מסמכים (DMS)' } else { T 'DMS - Large File Exchange' 'DMS - העברת קבצים גדולים' }
        Set-PnPWeb -Title $siteTitle | Out-Null
        if ($LogoPath -and (Test-Path $LogoPath)) {
            try { Set-PnPSite -LogoFilePath (Resolve-Path $LogoPath).Path | Out-Null; Write-Ok "logo $LogoPath" }
            catch { Write-Warn2 "logo: $($_.Exception.Message)" }
        } else { Write-Skip "no logo file at $LogoPath" }

        # With -SiteLanguage, show the SharePoint UI in the site language for everyone
        # (turns off alternate UI languages, which otherwise follow each user's personal language).
        if ($SiteLanguage) {
            try {
                $w = Get-PnPWeb -Includes IsMultilingual
                if ($w.IsMultilingual) { $w.IsMultilingual = $false; $w.Update(); Invoke-PnPQuery; Write-Ok "UI language fixed to $SiteLanguage" }
            } catch { Write-Warn2 "UI language: $($_.Exception.Message)" }
        }
        try { Set-PnPSite -DisableSharingForNonOwners | Out-Null }
        catch { Write-Warn2 "DisableSharingForNonOwners: $($_.Exception.Message)" }

        Install-DmsRoleDefinition
        $roles = Get-RoleNameMap
        Install-DmsGroup $site.Key $roles
        Install-DmsSiteColumn (Get-NeededField $site.Key)
        foreach ($L in $Lists | Where-Object Site -eq $site.Key) { Install-DmsList $L $roles }

        if (-not $SkipSeedData -and $site.Key -eq 'DC') {
            Write-Step 'Seed data'
            Add-Seed 'Lists/ApproverMatrix' ($ApproverMatrixSeed | ForEach-Object {
                @{ Title = "$($_[0]) - $($_[1])"; DocumentArea = $_[0]; DocumentType = $_[1]; MandatoryRoles = $_[2]
                   ConditionalRoles = $_[3]; FinalRole = $_[4]; RoutingMode = 'Hybrid'; SlaDays = 5; IsActive = $true } })
            Add-Seed 'Lists/ImpactRouting' ($ImpactSeed | ForEach-Object {
                @{ Title = $_[0]; ChangeImpact = $_[0]; IncludeRoles = $_[1]; IsActive = $true } })

            $labels = [System.Collections.Generic.List[hashtable]]::new()
            foreach ($a in $AppLabels) { $labels.Add(@{ Title = $a[0]; LabelArea = 'App';     LabelEN = $a[1]; LabelHE = $a[2] }) }
            foreach ($m in $MsgLabels) { $labels.Add(@{ Title = $m[0]; LabelArea = 'Message'; LabelEN = $m[1]; LabelHE = $m[2] }) }
            foreach ($f in $Fields)    { $labels.Add(@{ Title = "field.$($f.N)"; LabelArea = 'Field'; LabelEN = $f.En; LabelHE = $f.He }) }
            foreach ($l in $Lists)     { $labels.Add(@{ Title = "list.$($l.Key)"; LabelArea = 'List'; LabelEN = $l.En; LabelHE = $l.He }) }
            foreach ($set in $Choices.Keys) {
                foreach ($c in $Choices[$set]) {
                    $labels.Add(@{ Title = "choice.$set.$($c[0])"; LabelArea = 'Choice'; LabelEN = $c[0]; LabelHE = $c[1] })
                }
            }
            Add-Seed 'Lists/UiLabels' $labels.ToArray()
        }
    }
    #endregion

    Write-Step 'Done'
    Write-Host "  Document Control : $DcUrl"
    Write-Host "  Exchange         : $ExUrl"
    Write-Host '  Next: add Entra groups to SharePoint groups, assign people in Approver Matrix / Impact Routing,'
    Write-Host '        populate Routing Catalog, then import the Power Platform solution (see docs/).'
}
finally {
    Stop-Transcript | Out-Null
}
