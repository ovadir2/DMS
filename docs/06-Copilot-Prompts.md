# 06 - Copilot Prompts for Power Automate

Ready-to-paste prompts that build every flow from [04 - Power Automate](04-Power-Automate.md) with Copilot in Power Automate. Each flow has one **build prompt**, a few **follow-up prompts** and a **check list** for the parts Copilot usually gets wrong.

## 1. How to use this page

1. Open the solution **RH Document Control** > **Objects** > **+ New** > **Automation** > **Cloud flow**. Pick the trigger type named in the flow section (Instant, Automated or Scheduled), give the flow its name, and open **Copilot** (top right). The new designer must be on.
2. Paste the **build prompt**. Wait until Copilot finishes.
3. Paste the **follow-up prompts** one at a time. Wait after each one.
4. Go through the **check list** by hand, then **Save**.
5. Test the flow before you build the next one. Build in the order of this page.

Rules that avoid most problems:

- One flow per conversation. Start a new Copilot chat for every flow.
- Short prompts work better than long ones. If Copilot stops half way, send `continue` or the next follow-up.
- Copilot cannot pick the SharePoint site and list for you in every case. If an action shows **Site Address** or **List Name** empty, choose them from the dropdown.
- Choice columns on these sites store **Hebrew values** (the sites were built with `-ChoiceLanguage he`). Always use the Hebrew value from section 2 in filters, conditions and updates. For choice fields in *Create item* / *Update item* choose **Enter custom value** and paste the Hebrew value.
- Person columns take an email address (Claims). Choice filters in OData use the Hebrew value: `LifecycleStatus eq 'בעבודה'`.

Sites used in the prompts (pilot):

| Name in prompts | URL |
| --- | --- |
| DC site | `https://rhisrael.sharepoint.com/sites/DocumentControl-TEST` |
| EX site | `https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST` |

For production, replace `-TEST` with the production site, or switch the actions to the environment variables `dms_SiteUrl_DC` / `dms_SiteUrl_EX`.

> The pilot flow **DC-P1 Pilot Approval** (imported from `scripts/New-DmsPilotFlowPackage.ps1`) does a simplified version of DC-03 + DC-04 + DC-05. Turn it **off** before you turn on DC-03, DC-04 and DC-05.

## 2. Choice values (English key → value stored on the site)

| Column | Value to use in flows |
| --- | --- |
| LifecycleStatus | Working = `בעבודה`, Submitted = `הוגש לאישור`, Approved_ReadOnly = `מאושר - קריאה בלבד`, Released_PLM = `שוחרר ל-PLM`, Obsolete_ReadOnly = `מבוטל - קריאה בלבד`, Archived = `בארכיון` |
| ControlMode | Collaboration = `שיתופי ללא תהליך`, Workflow Optional = `תהליך אישור רשות`, Workflow Required = `תהליך אישור חובה`, Read-Only Record = `רשומה לקריאה בלבד` |
| WorkflowStatus | Pending = `ממתין`, InReview = `בבדיקה`, Approved = `אושר`, Rejected = `נדחה`, Cancelled = `בוטל`, Restarted = `הופעל מחדש` |
| RoutingMode | Hybrid = `מקבילי ואז מאשר סופי`, Sequential = `סדרתי`, Parallel = `מקבילי` |
| Decision | Pending = `ממתין`, Approved = `אושר`, Rejected = `נדחה`, Delegated = `הואצל`, Cancelled = `בוטל`, Expired = `פג תוקף` |
| ApproverRole | Mandatory = `חובה`, Conditional = `מותנה`, Reviewer = `סוקר`, Final = `מאשר סופי` |
| DelegationStatus | Active = `פעיל`, Expired = `פג תוקף`, Revoked = `בוטל` |
| ActionType | VerifyWorkingFile = `אימות קובץ עבודה`, CreateDraftCopy = `יצירת טיוטת גרסה`, MoveToSubmitted = `העברה להגשה`, ReturnToWorking = `החזרה לעבודה`, PromoteToCurrent = `קידום לגרסה נוכחית`, MakeObsolete = `העברה לבוטל`, ReleaseToPLMQueue = `שחרור לתור PLM`, ArchiveRevision = `העברה לארכיון` |
| ActionStatus | Queued = `בתור`, Processing = `בעיבוד`, Completed = `הושלם`, Failed = `נכשל`, Cancelled = `בוטל` |
| ExchangeStatus | Draft = `טיוטה`, AwaitingUpload = `ממתין להעלאה`, Uploaded = `הועלה`, ReadyForTransfer = `מוכן להעברה`, Transferring = `בהעברה`, Transferred = `הועבר`, Accepted = `התקבל`, Rejected = `נדחה`, TransferFailed = `העברה נכשלה`, Cancelled = `בוטל`, Expired = `פג תוקף` |
| AuditEventType | Created = `נוצר`, StatusChanged = `שינוי סטטוס`, Submitted = `הוגש`, Approved = `אושר`, Rejected = `נדחה`, Delegated = `הואצל`, FileActionQueued = `פעולת קובץ בתור`, FileActionCompleted = `פעולת קובץ הושלמה`, FileActionFailed = `פעולת קובץ נכשלה`, TransferCompleted = `העברה הושלמה`, TransferFailed = `העברה נכשלה`, CloudCopyDeleted = `העותק בענן נמחק`, PermissionChanged = `שינוי הרשאות`, Cancelled = `בוטל`, Expired = `פג תוקף` |
| EventSource | `Power Apps`, `Power Automate`, `Transfer Worker`, `שירות תהליכים`, `ידני` |
| DocumentArea | Management = `ניהול`, Commercial = `מסחרי`, Development = `פיתוח`, Manufacturing = `ייצור`, Test Engineering = `הנדסת בדיקות`, Quality = `איכות`, Changes = `שינויים`, IT = `מערכות מידע`, InfoSec = `אבטחת מידע` |
| DocumentType | Policy = `מדיניות`, Procedure = `נוהל`, Contract / NDA = `חוזה / NDA`, Work Instruction = `הוראת עבודה`, Test Procedure = `נוהל בדיקה`, PFMEA / Control Plan = `PFMEA / תוכנית בקרה`, ECO / ECN = `ECO / ECN - הודעת שינוי`, IT Procedure = `נוהל מערכות מידע`, Security Policy = `מדיניות אבטחת מידע` (full list in 01) |
| RetentionClass | Legal Hold = `הקפאה משפטית` |

## 3. Before the first flow

1. Environment variables in the solution (see 04 §1.2). For the pilot you need at least `dms_SiteUrl_DC`, `dms_SiteUrl_EX`, `dms_Language` = `he`, `dms_DefaultSlaDays` = `5`, `dms_RepositoryRoot`, `dms_DocControlGroupId`, `dms_AdminGroupId`, `dms_DocControlLeadEmail`, `dms_ExpiryDays` = `14`, `dms_MaxFileSizeGB` = `100`, `dms_ArchiveAfterMonths` = `24`, `dms_RoleUploadOnly` = `DMS - העלאה בלבד`.
2. Connections: SharePoint, Approvals, Microsoft Teams, Office 365 Users, Office 365 Groups. For the pilot you may use your own account; for production use the service account.
3. The Entra group object IDs for `dms_DocControlGroupId` / `dms_AdminGroupId` are shown in Entra > Groups > the group > **Object ID**.

## 4. Utility child flows

Child flows: **Instant** flow with trigger **Manually trigger a flow**. After saving, open the flow details > **Run only users** > **Edit** and set every connection to **Use this connection**, otherwise *Run a Child Flow* fails.

### DMS-U1 Write Audit

Build prompt:

```text
Build a flow with the trigger "Manually trigger a flow" and 8 text inputs named exactly CorrelationId, EventType, FromStatus, ToStatus, Actor, Source, Details, Site.
Add a condition: if the Site input equals "EX", use SharePoint "Create item" on site https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST list "Exchange Audit", otherwise use SharePoint "Create item" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST list "Control Audit".
In both Create item actions set: Title = EventType input, a space, CorrelationId input. Correlation ID = CorrelationId. Event Type = EventType (custom value). From Status = FromStatus. To Status = ToStatus. Actor = Actor. Event Time (UTC) = expression utcNow(). Event Source = Source (custom value). Event Details = Details.
End with "Respond to a PowerApp or flow" with a text output named result = "ok".
```

Check list:

- [ ] Inputs have the 8 names (not "Input 1").
- [ ] *Event Type* and *Event Source* use **Enter custom value** with the input chip.
- [ ] *Event Time (UTC)* is the `utcNow()` expression chip.

Test: EventType `נוצר`, Source `ידני`, Site `DC` → a row appears in Control Audit.

### DMS-U2 Render Message

Build prompt:

```text
Build a flow with the trigger "Manually trigger a flow" and 3 text inputs named Key, Lang, Tokens.
Step 1: SharePoint "Get items" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST list "UI Labels" with filter query Title eq '<Key input>' and top count 1.
Step 2: Initialize a string variable msg with the expression: if(equals(triggerBody()?['text_1'],'he'), first(outputs('Get_items')?['body/value'])?['LabelHE'], first(outputs('Get_items')?['body/value'])?['LabelEN'])
Step 3: Apply to each over the expression json(if(empty(triggerBody()?['text_2']),'[]',triggerBody()?['text_2'])) with concurrency 1. Inside: Compose with replace(variables('msg'), concat('{', items('Apply_to_each')?['k'], '}'), string(items('Apply_to_each')?['v'])), then Set variable msg to the Compose output.
Step 4: "Respond to a PowerApp or flow" with a text output named Text = variable msg.
```

Check list:

- [ ] In the msg expression, `text_1` must be the Lang input and `text_2` the Tokens input. Open **Peek code** on the trigger to confirm the internal names; fix the expressions if they differ.
- [ ] Apply to each: **Settings** > Concurrency control **On**, degree **1**.

Test: Key `msg.approval.title`, Lang `he`, Tokens `[{"k":"DocumentId","v":"QA-PRO-00001"}]`.

### DMS-U4 Resolve Delegate

Build prompt:

```text
Build a flow with the trigger "Manually trigger a flow" and one text input named Email.
Step 1: SharePoint "Get items" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST list "Delegations" with filter query:
DelegationStatus eq 'פעיל' and Delegator/EMail eq '<Email input>' and ValidFrom le '<expression utcNow('yyyy-MM-dd')>' and ValidTo ge '<expression utcNow('yyyy-MM-dd')>'
and top count 1.
Step 2: Condition: the number of items is greater than 0 and the DelegationApprovedBy of the first item is not empty.
If yes: respond to PowerApp or flow with text outputs Effective = DelegateTo email of the first item and DelegatedFrom = Email input.
If no: respond with Effective = Email input and DelegatedFrom = empty.
```

Check list:

- [ ] Both branches end with *Respond to a PowerApp or flow* with the **same** two outputs.
- [ ] Expressions: `first(outputs('Get_items')?['body/value'])?['DelegateTo']?['Email']` and `first(outputs('Get_items')?['body/value'])?['DelegationApprovedBy']`.

### DMS-U3 Notify

Build prompt:

```text
Build a flow with the trigger "Manually trigger a flow" and 4 text inputs named Recipients, Key, Tokens, PostToChannel.
Step 1: Apply to each over split(Recipients input, ';'). Inside, a condition that the current item is not empty. If yes:
a) Office 365 Users "Get user profile (V2)" for the current item.
b) Compose Lang with expression: if(startsWith(toLower(coalesce(outputs('Get_user_profile_(V2)')?['body/preferredLanguage'], 'he')), 'he'), 'he', 'en')
c) Run the child flow "DMS-U2 Render Message" with Key, Lang (the Compose output) and Tokens.
d) Microsoft Teams "Post message in a chat or channel": post as Flow bot, post in Chat with Flow bot, recipient = the current item, message = <div dir="rtl">Text output of the child flow</div>.
Step 2: Condition PostToChannel is not equal to "none": run DMS-U2 twice (Lang en and Lang he) and post both texts to a Teams channel as Flow bot.
Step 3: Respond to a PowerApp or flow with text output result = "ok".
```

Check list:

- [ ] The Teams channel post: pick your Document Control team and channel (or IT alerts when PostToChannel = `it`).
- [ ] The RTL `<div>` is only needed for Hebrew; it does no harm for English.
- [ ] Wrap *Get user profile (V2)* in a scope or set its **Configure run after** so a guest or unknown address does not fail the whole loop.

## 5. Document-control flows

### DC-00 Get User Context (Instant, trigger **When Power Apps calls a flow (V2)**)

Build prompt:

```text
Build a flow triggered by "When Power Apps calls a flow (V2)" with no inputs.
Step 1: Compose Email = toLower(triggerOutputs()?['headers']?['x-ms-user-email'])
Step 2: Office 365 Groups "List group members" for the group ID from environment variable dms_DocControlGroupId, top 999. Filter array where toLower(item()?['mail']) equals the Email compose. Compose isDocumentController = greater(length(body('Filter_array')), 0).
Step 3: Do the same with the group ID from dms_AdminGroupId to get isAdmin.
Step 4: Office 365 Users "Get user profile (V2)" for the Email.
Step 5: "Respond to a PowerApp or flow" with outputs isDocumentController (yes/no), isAdmin (yes/no), preferredLanguage (text).
```

Check list:

- [ ] Both *Filter array* actions have unique names; the second Compose uses the second Filter array.
- [ ] Keep the two Entra groups flat (no nested groups).

### DC-05 File Action Result (Automated, trigger **When an item is created or modified**)

Build it before DC-01 to DC-04, because they depend on it.

Build prompt:

```text
Build a flow triggered by SharePoint "When an item is created or modified" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST list "File Action Queue".
Add a Switch on the ActionType value with cases: אימות קובץ עבודה, יצירת טיוטת גרסה, העברה להגשה, החזרה לעבודה, קידום לגרסה נוכחית, שחרור לתור PLM, העברה לבוטל, העברה לארכיון.
In every case add a condition: ActionStatus value equals "הושלם".
```

Follow-up prompts (one at a time):

```text
Before the Switch, add SharePoint "Get items" on list "Document Register" with filter query DocumentId eq '<DocumentId from trigger>' and top count 1, and "Get items" on list "Workflow History" with filter query WorkflowId eq '<WorkflowId from trigger>' and top count 1.
```

```text
In case "העברה להגשה" when completed: update the Workflow History item with SubmittedUncPath = TargetUncPath, SubmittedSHA256 = ResultSHA256 and WorkflowStatus = "בבדיקה". Update the Document Register item with LifecycleStatus = "הוגש לאישור". When not completed: update Workflow History WorkflowStatus = "בוטל" and clear ActiveWorkflowId on the Document Register item.
```

```text
In case "החזרה לעבודה" when completed: update the Document Register item with LifecycleStatus = "בעבודה", WorkingUncPath = TargetUncPath and ActiveWorkflowId empty.
In case "יצירת טיוטת גרסה" when completed: update the Document Register item with WorkingUncPath = TargetUncPath and LifecycleStatus = "בעבודה"; when not completed clear DraftRevision.
In case "אימות קובץ עבודה" when completed: update the Document Register item with WorkingUncPath = SourceUncPath.
```

```text
In case "קידום לגרסה נוכחית" when completed: add a condition that ResultSHA256 equals the SubmittedSHA256 of the Workflow History item. If equal, update the Document Register item with CurrentRevision = Revision, DraftRevision empty, CurrentUncPath = TargetUncPath, CurrentSHA256 = ResultSHA256, LifecycleStatus = "מאושר - קריאה בלבד", LastApprovedUtc = utcNow(), EffectiveDate = utcNow('yyyy-MM-dd'), NextReviewDate = addToTime(utcNow(), ReviewCycleMonths, 'Month', 'yyyy-MM-dd') and ActiveWorkflowId empty. If not equal, post a Teams message to the IT alerts channel "Hash mismatch" with the DocumentId.
```

```text
In case "שחרור לתור PLM" when completed set LifecycleStatus "שוחרר ל-PLM". In case "העברה לבוטל" when completed set "מבוטל - קריאה בלבד". In case "העברה לארכיון" when completed set "בארכיון".
At the end of the flow (after the Switch) run the child flow "DMS-U1 Write Audit" with CorrelationId = DocumentId, EventType = if ActionStatus is "הושלם" then "פעולת קובץ הושלמה" else "פעולת קובץ נכשלה", Source = "Power Automate", Site = "DC".
```

Check list:

- [ ] Trigger **Settings** > **Trigger conditions**: `@or(equals(triggerOutputs()?['body/ActionStatus/Value'],'הושלם'), equals(triggerOutputs()?['body/ActionStatus/Value'],'נכשל'))`
- [ ] Every *Update item* uses the ID from the matching *Get items* (`first(outputs('Get_items')?['body/value'])?['ID']`). Copilot often puts it in an *Apply to each*; that is fine for Top 1.
- [ ] Choice fields in *Update item* use **Enter custom value** with the Hebrew text.
- [ ] Empty values: type the expression `null` (for dates and text) instead of leaving the field empty, otherwise the old value stays.
- [ ] Notifications (`msg.approved.owner`, `msg.draft.ready` and others): add *Run a Child Flow* DMS-U3 in each branch with Recipients = owner email, Key as in 04 §3 DC-05.

### DC-01 Register Document (Instant, **When Power Apps calls a flow (V2)**)

Build prompt:

```text
Build a flow triggered by "When Power Apps calls a flow (V2)" with text inputs Title, Area, Type, ControlMode, OwnerEmail, Department, CustomerCode, ProjectCode, Classification, Retention, Language, WorkingUncPath and a number input ReviewMonths.
Add a scope named Try. Inside it:
1. Condition: Title, Area, Type and OwnerEmail are not empty, and WorkingUncPath (lower case) starts with the lower case of environment variable dms_RepositoryRoot, contains "\working\" and does not contain "..". If not, respond to Power Apps with status "error" and message "validation" and terminate.
2. Compose FinalMode = if(contains(createArray('מדיניות','נוהל','חוזה / NDA','ECO / ECN - הודעת שינוי','הוראת עבודה','נוהל בדיקה','PFMEA / תוכנית בקרה','נוהל מערכות מידע','מדיניות אבטחת מידע'), Type), 'תהליך אישור חובה', ControlMode)
3. SharePoint "Create item" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST list "Document Register" with Title, DocumentId = concat('TMP-', guid()), Document Area = Area, Document Type = Type, Control Mode = FinalMode, Lifecycle Status = "בעבודה", Draft Revision = "Rev01", Document Owner = OwnerEmail, and the other inputs in the matching columns.
```

Follow-up prompts:

```text
After Create item add a Compose named AreaCodes with the JSON {"ניהול":"MGT","מסחרי":"COM","פיתוח":"DEV","ייצור":"MFG","הנדסת בדיקות":"TST","איכות":"QA","שינויים":"CHG","מערכות מידע":"IT","אבטחת מידע":"SEC"} and a Compose named TypeCodes with the type codes from document 01 section 4.3.
Then SharePoint "Update item" on the created item with DocumentId = concat(outputs('AreaCodes')?[Area], '-', outputs('TypeCodes')?[Type], '-', formatNumber(outputs('Create_item')?['body/ID'], '00000')).
```

```text
Then SharePoint "Create item" in list "File Action Queue" with Title = the new DocumentId, DocumentId, Revision "Rev01", Action Type "אימות קובץ עבודה", Action Status "בתור", Source Unc Path = WorkingUncPath, Requested By = the caller email from triggerOutputs()?['headers']?['x-ms-user-email'], Requested Utc = utcNow().
Then run the child flow "DMS-U1 Write Audit" with CorrelationId = the new DocumentId, EventType "נוצר", ToStatus "בעבודה", Actor = caller email, Source "Power Automate", Site "DC".
Then respond to Power Apps with status "ok" and documentid.
```

```text
Add a scope named Catch after Try that runs only if Try has failed or timed out. Inside: run DMS-U1 Write Audit with EventType "שינוי סטטוס" and Details = string(result('Try')), then respond to Power Apps with status "error" and message "flow".
```

Check list:

- [ ] Catch scope: **Configure run after** = *has failed* and *has timed out* (not *is successful*).
- [ ] TypeCodes: copy the exact codes from 01 §4.3, keyed by the **Hebrew** type value.
- [ ] Only one *Respond to a PowerApp or flow* runs per path.

### DC-02 Create New Revision (Instant, **When Power Apps calls a flow (V2)**)

Build prompt:

```text
Build a flow triggered by "When Power Apps calls a flow (V2)" with a text input DocumentId.
1. SharePoint "Get items" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST list "Document Register" filter DocumentId eq '<DocumentId>' top 1.
2. Condition: LifecycleStatus value of the first item is "מאושר - קריאה בלבד" or "שוחרר ל-PLM", and ActiveWorkflowId is empty. If not, respond with status "error" and stop.
3. Compose Next = concat('Rev', formatNumber(add(int(substring(CurrentRevision, 3)), 1), '00')).
4. Compose Target = replace(replace(CurrentUncPath, '\Current_ReadOnly\', '\Working\'), concat('_', CurrentRevision, '.'), concat('_', outputs('Next'), '_DRAFT.')).
5. Create item in "File Action Queue": Action Type "יצירת טיוטת גרסה", Action Status "בתור", DocumentId, Revision = Next, Source Unc Path = CurrentUncPath, Target Unc Path = Target, Requested By = caller email, Requested Utc = utcNow().
6. Update the register item: Draft Revision = Next.
7. Run DMS-U1 Write Audit with EventType "פעולת קובץ בתור". Respond with status "ok".
```

Check list:

- [ ] The caller check (owner or Document Controller): add *Run a Child Flow* is not possible for DC-00 (Power Apps trigger); instead copy DC-00 steps 1-2 or compare `DocumentOwner/Email` with the caller email.
- [ ] `CurrentRevision` must be read from `first(outputs('Get_items')?['body/value'])?['CurrentRevision']`.

### DC-03 Submit For Approval (Instant, **When Power Apps calls a flow (V2)**)

Build prompt:

```text
Build a flow triggered by "When Power Apps calls a flow (V2)" with text inputs DocumentId, Revision, ChangeSummary, Impacts, RequiredEmails, ConditionalEmails, ReviewerEmails, FinalEmail, DueDate, Justification.
1. Compose Caller = toLower(triggerOutputs()?['headers']?['x-ms-user-email']).
2. SharePoint "Get items" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST list "Document Register" filter DocumentId eq '<DocumentId>' top 1.
3. Condition: the owner email of that item equals Caller, LifecycleStatus is "בעבודה", ControlMode is not "שיתופי ללא תהליך" and ActiveWorkflowId is empty. If not, respond status "error" and stop.
4. Get items "Workflow History" filter DocumentId eq '<DocumentId>' and Revision eq '<Revision>' and (WorkflowStatus eq 'ממתין' or WorkflowStatus eq 'בבדיקה'). If any found, respond status "ok" with that WorkflowId and stop.
```

Follow-up prompts:

```text
Next: Get items "Approver Matrix" filter DocumentType eq '<DocumentType value of the register item>' and IsActive eq 1 top 1. Get items "Impact Routing" filter IsActive eq 1.
Initialize an array variable Required with the lower case emails of MandatoryApprovers of the matrix item (use a Select with toLower(item()?['Email'])).
Apply to each impact rule whose ChangeImpact value is contained in split(Impacts, ';'): apply to each of its IncludeApprovers and append toLower(Email) to Required.
Compose Final = toLower(first matrix item FinalApprover Email). If Final is empty respond status "error" message "app.err.approvers" and stop.
```

```text
Next: Filter array Required where not(contains(concat(';', toLower(RequiredEmails), ';'), concat(';', item(), ';'))). If the result is not empty, or toLower(FinalEmail) is not equal to Final, respond status "error" and stop.
If Caller is in Required or equals Final, replace it with the environment variable dms_DocControlLeadEmail.
```

```text
Next: Get items "Workflow History" filter DocumentId eq '<DocumentId>' to count previous cycles. Create item in "Workflow History": Title = DocumentId + " " + Revision, DocumentId, Revision, Workflow Status "ממתין", Routing Mode = the matrix RoutingMode value or "מקבילי ואז מאשר סופי", Mandatory Approvers = Required emails, Conditional Approvers = ConditionalEmails, Additional Reviewers = ReviewerEmails, Final Approver = Final, Change Summary, Decision Due Date = DueDate or addDays(utcNow(), mul(SlaDays, 2), 'yyyy-MM-dd'), Cycle Number = previous count + 1, Submitted By = Caller, Submitted Utc = utcNow().
Update that item: WorkflowId = concat('WF-', utcNow('yyyy'), '-', formatNumber(ID, '000000')). Update the register item: ActiveWorkflowId = the new WorkflowId.
```

```text
Next: Create item in "File Action Queue": Action Type "העברה להגשה", Action Status "בתור", DocumentId, WorkflowId, Revision, Source Unc Path = WorkingUncPath of the register item, Target Unc Path = replace(WorkingUncPath, '\Working\', '\Submitted\'), Requested By = Caller, Requested Utc = utcNow().
Run DMS-U1 Write Audit with EventType "הוגש". If Justification is not empty, run DMS-U1 again with Details = Justification.
Respond to Power Apps with status "ok" and workflowid.
```

Check list:

- [ ] Multi-person fields (Mandatory Approvers, Conditional Approvers, Additional Reviewers): switch the field to **array input** (the small **T** icon) and use a *Select* that maps each email to `{"Claims": "i:0#.f|membership|<email>"}`.
- [ ] Wrap the body in Try / Catch scopes like DC-01.
- [ ] Owner email: `first(outputs('Get_items')?['body/value'])?['DocumentOwner']?['Email']`.

### DC-04 Run Approval Cycle (Automated, **When an item is created or modified**)

Build prompt:

```text
Build a flow triggered by SharePoint "When an item is created or modified" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST list "Workflow History".
1. Get items "Approval Decisions" filter WorkflowId eq '<WorkflowId>'. If any exist, terminate with status Succeeded.
2. Initialize array variable Stage1. Apply to each over union of the emails of MandatoryApprovers, ConditionalApprovers and AdditionalReviewers (concurrency 1): run child flow "DMS-U4 Resolve Delegate" with the email, append Effective to Stage1, and create an item in "Approval Decisions" with WorkflowId, DocumentId, Revision, Approver = Effective, Delegated From = DelegatedFrom, Approval Stage 1, Decision "ממתין", Decision Due Date = DecisionDueDate.
3. "Start and wait for an approval" named Stage1Approval, type "Approve/Reject - Everyone must approve", title "אישור מסמך: " + Title, assigned to join(variables('Stage1'), ';'), details with DocumentId, Revision, ChangeSummary, SubmittedUncPath and SubmittedSHA256, item link = the Document Register item link.
```

Follow-up prompts:

```text
After Stage1Approval: Apply to each over outputs('Stage1Approval')?['body/responses']. Get items "Approval Decisions" filter WorkflowId eq '<WorkflowId>' and Approver/EMail eq '<responder email>' top 1 and update it with Decision = if approverResponse is "Approve" then "אושר" else "נדחה", Decision Comment = comments, Decision Utc = responseDate.
Then set all remaining "ממתין" decisions of this WorkflowId to "בוטל".
Then get the Workflow History item again; if its WorkflowStatus is no longer "בבדיקה", terminate.
```

```text
If Stage1Approval outcome is "Approve": run DMS-U4 for the FinalApprover email, create an Approval Decisions item with Approval Stage 2 and Approver Role "מאשר סופי", then "Start and wait for an approval" named FinalApproval, type "Approve/Reject - First to respond", same title and details, assigned to the Effective email. Record its response the same way.
```

```text
Outcome: if both approvals are "Approve": update Workflow History WorkflowStatus "אושר" and CompletedUtc = utcNow(), create a "File Action Queue" item Action Type "קידום לגרסה נוכחית", Action Status "בתור", Source Unc Path = SubmittedUncPath, Target Unc Path = replace(replace(SubmittedUncPath, '\Submitted\', '\Current_ReadOnly\'), '_DRAFT', ''), and run DMS-U1 with EventType "אושר".
Otherwise: update Workflow History WorkflowStatus "נדחה", CompletedUtc and FinalComment = the rejecting comment, create a "File Action Queue" item "החזרה לעבודה" with Source Unc Path = SubmittedUncPath and Target Unc Path = replace(SubmittedUncPath, '\Submitted\', '\Working\'), run DMS-U3 to notify the document owner with Key "msg.rejected.owner", and run DMS-U1 with EventType "נדחה".
```

Check list:

- [ ] Trigger condition: `@equals(triggerOutputs()?['body/WorkflowStatus/Value'], 'בבדיקה')`
- [ ] Both approval actions: **Settings** > **Timeout** = `P25D`.
- [ ] Add a parallel branch after Stage1Approval with **Configure run after** = *has timed out*: set decisions to `פג תוקף`, Workflow History to `בוטל` with FinalComment "Expired after 25 days", queue `החזרה לעבודה`.
- [ ] RoutingMode `מקבילי` (Parallel): add FinalApprover to Stage1 and skip the second approval. `סדרתי` (Sequential): see 04 §3 DC-04 step 4.

### DC-06 Reminders and Escalation (Scheduled)

Build prompt:

```text
Build a scheduled flow that runs Monday to Friday at 07:00 Israel Standard Time.
1. SharePoint "Get items" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST list "Approval Decisions" filter Decision eq 'ממתין', top 5000, pagination on.
2. Apply to each item: Compose Days = div(sub(ticks(utcNow()), ticks(item()?['Created'])), 864000000000). Compose Sla = int(environment variable dms_DefaultSlaDays).
3. If Days >= Sla and mod(sub(Days, Sla), 2) equals 0: run child flow DMS-U3 Notify with Recipients = Approver email, Key "msg.reminder", Tokens with DocumentId and WorkflowId, PostToChannel "none".
4. If Days >= mul(Sla, 2): run DMS-U3 with Recipients = the document owner email, Key "msg.escalation", PostToChannel "doccontrol".
```

### DC-07 Cancel or Restart Workflow (Instant, **When Power Apps calls a flow (V2)**)

Build prompt:

```text
Build a flow triggered by "When Power Apps calls a flow (V2)" with text inputs WorkflowId, Mode, Reason.
1. Get items "Workflow History" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST filter WorkflowId eq '<WorkflowId>' top 1, and the matching "Document Register" item by DocumentId.
2. Update the Workflow History item: WorkflowStatus = "בוטל" when Mode is "Cancel", otherwise "הופעל מחדש"; FinalComment = Reason.
3. Get items "Approval Decisions" filter WorkflowId eq '<WorkflowId>' and Decision eq 'ממתין'; update each to "בוטל" and collect the approver emails.
4. Run DMS-U3 Notify with those emails and Key "msg.cancelled".
5. If Mode is "Cancel": create "File Action Queue" item "החזרה לעבודה" (Source = SubmittedUncPath, Target = replace(SubmittedUncPath, '\Submitted\', '\Working\')) and clear ActiveWorkflowId on the register item.
6. Run DMS-U1 with EventType "בוטל" and Details = Reason. Respond status "ok".
```

Check list:

- [ ] Caller must be the owner or a Document Controller (compare caller email as in DC-02).
- [ ] Restart: after step 3, repeat the DC-03 validation and create a new Workflow History item directly with status `בבדיקה`, the same SubmittedUncPath / SubmittedSHA256 and `CycleNumber + 1` (DC-04 starts by itself).

### DC-08 Periodic Review (Scheduled)

```text
Build a scheduled flow that runs every day at 06:30 Israel Standard Time.
1. SharePoint "Get items" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST list "Document Register" filter (LifecycleStatus eq 'מאושר - קריאה בלבד' or LifecycleStatus eq 'שוחרר ל-PLM') and NextReviewDate le '<addDays(utcNow(), 30, 'yyyy-MM-dd')>'.
2. For each item: if formatDateTime(NextReviewDate,'yyyy-MM-dd') equals addDays(utcNow(),30,'yyyy-MM-dd') or addDays(utcNow(),7,'yyyy-MM-dd'), run DMS-U3 to the owner with Key "msg.review.due".
3. If NextReviewDate is before today and dayOfWeek(utcNow()) equals 1, run DMS-U3 to the owner with Key "msg.review.overdue" and PostToChannel "doccontrol".
```

### DC-09 Make Obsolete (Instant, **When Power Apps calls a flow (V2)**)

```text
Build a flow triggered by "When Power Apps calls a flow (V2)" with text inputs DocumentId and Reason.
1. Check the caller (x-ms-user-email header) is a member of the Entra group from environment variable dms_DocControlGroupId (Office 365 Groups "List group members" + Filter array). If not, respond status "error" and stop.
2. Get items "Document Register" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST filter DocumentId eq '<DocumentId>' top 1. Require LifecycleStatus "מאושר - קריאה בלבד" or "שוחרר ל-PLM" and empty ActiveWorkflowId.
3. Create "File Action Queue" item: Action Type "העברה לבוטל", Action Status "בתור", Source Unc Path = CurrentUncPath, Target Unc Path = replace(CurrentUncPath, '\Current_ReadOnly\', '\Obsolete_ReadOnly\').
4. Run DMS-U1 with EventType "פעולת קובץ בתור" and Details = Reason. Respond status "ok".
```

### DC-10 Release to PLM (child flow, **Manually trigger a flow**)

```text
Build a flow with the trigger "Manually trigger a flow" and text inputs DocumentId, Revision, SourceUncPath.
Create an item in "File Action Queue" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST with Action Type "שחרור לתור PLM", Action Status "בתור", DocumentId, Revision, Source Unc Path = SourceUncPath, Target Unc Path = concat(environment variable dms_RepositoryRoot, '\03_Operations_Staging\PLM_Release_Queue\', DocumentId, '_', Revision).
Run DMS-U1 with EventType "פעולת קובץ בתור". Respond with result "ok".
```

Then in DC-05, case `קידום לגרסה נוכחית`, add after the register update: *Run a Child Flow* DC-10 when `DocumentArea` is `פיתוח`, `שינויים`, `ייצור` or `הנדסת בדיקות` and `ControlMode` is `תהליך אישור חובה`, or when `PLMReference` is not empty.

### DC-11 Delegation Lifecycle (Scheduled)

```text
Build a scheduled flow that runs every day at 00:15 Israel Standard Time on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST.
1. Get items "Delegations" filter DelegationStatus eq 'פעיל' and ValidTo lt '<utcNow('yyyy-MM-dd')>'; update each DelegationStatus to "פג תוקף".
2. Get items "Delegations" filter DelegationStatus eq 'פעיל' and ValidFrom eq '<utcNow('yyyy-MM-dd')>'; for each item where DelegationApprovedBy is not empty run DMS-U3 to the Delegator and DelegateTo emails with Key "msg.delegation.active".
3. Get items "Delegations" filter DelegationStatus eq 'פעיל'; if any has an empty DelegationApprovedBy, post one Teams channel message to Document Control listing them.
```

### DC-12 Archive Sweep (Scheduled)

```text
Build a scheduled flow that runs monthly on day 1 at 02:00 Israel Standard Time.
Get items "Document Register" on site https://rhisrael.sharepoint.com/sites/DocumentControl-TEST filter LifecycleStatus eq 'מבוטל - קריאה בלבד' and Modified lt '<addToTime(utcNow(), mul(-1, int(environment variable dms_ArchiveAfterMonths)), 'Month')>' and RetentionClass ne 'הקפאה משפטית'.
For each item create "File Action Queue" item: Action Type "העברה לארכיון", Action Status "בתור", DocumentId, Source Unc Path = CurrentUncPath, Target Unc Path = replace(CurrentUncPath, '\Obsolete_ReadOnly\', '\Archive\'). Run DMS-U1 with EventType "פעולת קובץ בתור".
```

## 6. Large-file exchange flows

Site for every action: `https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST`. Audit calls use DMS-U1 with Site = `EX`.

### EX-02 FileUploadedMetadata (Automated, **When a file is created (properties only)**)

```text
Build a flow triggered by SharePoint "When a file is created (properties only)" on site https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST library "Temporary Uploads".
1. Compose RequestId = split(triggerOutputs()?['body/{Path}'], '/')[1].
2. SharePoint "Get file metadata" with the file identifier from the trigger.
3. Get items "Upload Requests" filter RequestId eq '<RequestId>' top 1. Require ExchangeStatus "ממתין להעלאה" or "הועלה".
4. If ExchangeFileName is not empty and different from the new file name: update the request FailureDetail "One file per request - upload a single ZIP", post to the Document Control Teams channel, and stop.
5. Update the request: ExchangeFileName = {FilenameWithExtension}, ExpectedSizeBytes = Size from Get file metadata, DriveItemId = ID of the file, ExchangeStatus "הועלה".
6. Update file properties on the file: RequestId. Run DMS-U1 with EventType "שינוי סטטוס", ToStatus "הועלה", Site "EX".
```

### EX-04 TransferStatusNotification (Automated, **When an item is created or modified**, list **Upload Requests**)

```text
Build a flow triggered by SharePoint "When an item is created or modified" on site https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST list "Upload Requests".
1. Get items "Exchange Audit" filter CorrelationId eq '<RequestId>' order by Created desc top 1. If its ToStatus equals the current ExchangeStatus value, terminate.
2. Switch on ExchangeStatus value:
- "הועבר": run DMS-U3 to RequestedBy with Key "msg.ex.transferred", Tokens including SizeGB = div(float(ExpectedSizeBytes), 1073741824), PostToChannel "doccontrol".
- "העברה נכשלה": DMS-U3 to RequestedBy with Key "msg.ex.failed", PostToChannel "it".
- "התקבל": DMS-U3 to RequestedBy with Key "msg.ex.accepted".
- "נדחה": DMS-U3 to RequestedBy with Key "msg.ex.rejected".
3. Run DMS-U1 with EventType "שינוי סטטוס", ToStatus = ExchangeStatus, Site "EX".
```

Check list:

- [ ] Trigger condition: `@contains(createArray('הועבר','העברה נכשלה','התקבל','נדחה'), triggerOutputs()?['body/ExchangeStatus/Value'])`
- [ ] Extra rule: when status is `הועבר` or `התקבל`, `CloudCopyDeleted` is false and FailureDetail contains `delete` → DMS-U3 Key `msg.ex.deletefailed`, PostToChannel `it`.

### EX-01 CreateExchangeRequest (Instant, **When Power Apps calls a flow (V2)**)

Build prompt:

```text
Build a flow triggered by "When Power Apps calls a flow (V2)" with text inputs CustomerCode, ProjectCode, Direction, PackageDescription, RoutingId, RequesterEmail, GuestEmail.
1. SharePoint "Get item" on site https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST list "Routing Catalog" with ID = RoutingId. Require IsActive true and CustomerCode and ProjectCode equal to the inputs. If GuestEmail is not empty, require contains(toLower(AllowedGuestDomains), toLower(last(split(GuestEmail, '@')))).
2. Reject (respond status "error") when DestinationRelativePath contains "..", ":" or "//", or starts with "\" or "/".
3. Get items "Upload Requests" with the same RequestedBy, ProjectCode and PackageDescription and ExchangeStatus not "התקבל", "נדחה", "בוטל" or "פג תוקף". If any, respond status "error" message "app.err.duplicate".
4. Create item "Upload Requests" with ExchangeStatus "טיוטה", Transfer Direction = Direction (custom value "נכנס" or "יוצא"), Destination Relative Path from the Routing Catalog item, and the other inputs in the matching columns. Update it with RequestId = concat('EXC-', utcNow('yyyyMMdd'), '-', formatNumber(ID,'0000')).
5. SharePoint "Create new folder" in library "Temporary Uploads" named RequestId.
```

Follow-up prompts:

```text
Next add "Send an HTTP request to SharePoint" actions on the same site:
a) POST _api/web/GetFolderByServerRelativeUrl('TemporaryUploads/<RequestId>')/ListItemAllFields/breakroleinheritance(copyRoleAssignments=false,clearSubscopes=true)
b) POST _api/web/ensureuser with body {"logonName":"i:0#.f|membership|<RequesterEmail>"} and header Accept application/json;odata=nometadata; keep the Id from the response. Do the same for GuestEmail when it is not empty.
c) GET _api/web/roledefinitions/getbyname('<environment variable dms_RoleUploadOnly>') and keep the Id.
d) POST _api/web/GetFolderByServerRelativeUrl('TemporaryUploads/<RequestId>')/ListItemAllFields/roleassignments/addroleassignment(principalid=<user Id>,roledefid=<role Id>) for the requester and the guest.
e) GET _api/web/sitegroups/getbyname('העברת קבצים - בקרת מסמכים') and GET _api/web/roledefinitions/getbyname('DMS - בקר מסמכים'), then addroleassignment for that group.
```

```text
Next update the Upload Requests item: ExchangeStatus "ממתין להעלאה", UploadFolderUrl = concat('https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST/TemporaryUploads/Forms/AllItems.aspx?id=', encodeUriComponent(concat('/sites/LargeFileExchange-TEST/TemporaryUploads/', RequestId))), ExpiryDate = addDays(utcNow(), int(environment variable dms_ExpiryDays), 'yyyy-MM-dd'), RequestedBy = RequesterEmail, UploaderEmail = RequesterEmail, GuestEmail.
Run DMS-U1 with EventType "נוצר", Site "EX". Run DMS-U3 to RequesterEmail with Key "msg.ex.created". Respond with status "ok", requestid and uploadurl.
```

Check list:

- [ ] Every HTTP action has header `Accept: application/json;odata=nometadata`, so the Id is `body('...')?['Id']`.
- [ ] On an English site the group and role names are `Exchange Document Control` and `DMS Document Controller`.
- [ ] The guest must already be invited to the tenant (Phase 9), otherwise *ensureuser* fails.

### EX-03 SubmitTransferRequest (Instant, **When Power Apps calls a flow (V2)**)

```text
Build a flow triggered by "When Power Apps calls a flow (V2)" with a text input RequestId.
1. Get items "Upload Requests" on site https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST filter RequestId eq '<RequestId>' top 1.
2. Require: the caller (x-ms-user-email header) is RequestedBy or a Document Controller, ExchangeStatus is "הועלה", ExpectedSizeBytes is greater than 0 and not greater than mul(int(environment variable dms_MaxFileSizeGB), 1073741824). Otherwise respond status "error".
3. Get the Routing Catalog item of the request and re-check DestinationRelativePath has no "..", ":" or leading slash.
4. Update the request ExchangeStatus "מוכן להעברה". Run DMS-U1 with ToStatus "מוכן להעברה", Site "EX". Respond status "ok".
```

### EX-06 AcceptTransferredFile (Instant, **When Power Apps calls a flow (V2)**)

```text
Build a flow triggered by "When Power Apps calls a flow (V2)" with text inputs RequestId, Decision, Comment.
1. Check the caller is in the Entra group from dms_DocControlGroupId (List group members + Filter array). Otherwise respond status "error".
2. Get items "Upload Requests" on site https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST filter RequestId eq '<RequestId>' top 1. Require ExchangeStatus "הועבר" and SHA256 not empty.
3. Update the request: ExchangeStatus = "התקבל" if Decision is "Accept" else "נדחה", ReviewedBy = caller email, DecisionComment = Comment.
4. Run DMS-U1 with ToStatus = the new status, Details = Comment, Site "EX". Respond status "ok".
```

### EX-07 CancelExchangeRequest (Instant, **When Power Apps calls a flow (V2)**)

```text
Build a flow triggered by "When Power Apps calls a flow (V2)" with a text input RequestId.
1. Get items "Upload Requests" on site https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST filter RequestId eq '<RequestId>' top 1.
2. Require the caller is RequestedBy or a Document Controller, and ExchangeStatus is "טיוטה", "ממתין להעלאה" or "הועלה".
3. Send an HTTP request to SharePoint: POST _api/web/GetFolderByServerRelativeUrl('TemporaryUploads/<RequestId>')/recycle
4. Update the request ExchangeStatus "בוטל". Run DMS-U1 with EventType "בוטל", Site "EX". Respond status "ok".
```

### EX-05 ExpiryControl (Scheduled)

```text
Build a scheduled flow that runs every day at 01:00 Israel Standard Time on site https://rhisrael.sharepoint.com/sites/LargeFileExchange-TEST.
1. Get items "Upload Requests" filter (ExchangeStatus eq 'טיוטה' or ExchangeStatus eq 'ממתין להעלאה' or ExchangeStatus eq 'הועלה') and ExpiryDate eq '<addDays(utcNow(),2,'yyyy-MM-dd')>'. For each run DMS-U3 to RequestedBy with Key "msg.ex.expiring".
2. Get items with the same statuses and ExpiryDate lt '<utcNow('yyyy-MM-dd')>'. For each: Send an HTTP request to SharePoint POST _api/web/GetFolderByServerRelativeUrl('TemporaryUploads/<RequestId>')/recycle, update ExchangeStatus "פג תוקף", run DMS-U1 with EventType "פג תוקף", Site "EX", and DMS-U3 with Key "msg.ex.expired".
3. Get items with ExchangeStatus "הועבר" or "התקבל", CloudCopyDeleted eq 0 and TransferCompletedUtc lt '<addDays(utcNow(),-1)>'. If any, post one message to the IT alerts Teams channel listing the RequestIds (Key "msg.ex.deletefailed").
```

## 7. After all flows are built

1. Turn every flow **On**. Turn **DC-P1 Pilot Approval** **Off**.
2. For every flow with a Power Apps trigger: **Run only users** > every connection **Use this connection**.
3. Add the Power Apps flows to the Canvas apps (see [03 - Power Apps](03-Power-Apps.md)).
4. Run the tests in 04 §6.

Common Copilot mistakes and fixes:

| Symptom | Fix |
| --- | --- |
| A choice update fails with "value not valid" | Use **Enter custom value** and the exact Hebrew value from section 2 |
| Filter query returns nothing | The value in the filter must be the Hebrew value, inside single quotes |
| *Run a Child Flow* fails with a connection error | Open the child flow > **Run only users** > **Use this connection** |
| Trigger fires in a loop | Add the trigger condition from the check list; the flow's own update changes the status so the condition becomes false |
| Person field update fails | Use the email or the claims form `i:0#.f&#124;membership&#124;<email>`; for multi-person fields use array input with Claims objects |
| Copilot wrapped a single item in *Apply to each* | It still works for Top 1; or replace it with `first(outputs('Get_items')?['body/value'])` |
