# 04 - Power Automate

All flows live in the solution `RH Document Control`. The owner is the dedicated application-owner account, with at least two co-owners (Phase 7). **Every flow is metadata-only.** None of them uses *Get file content*, the File System connector, *Create file* on-premises, binary variables or list attachments (blueprint 9.4).

## 1. Solution plumbing

### 1.1 Connection references

| Reference | Connector | Connected as |
| --- | --- | --- |
| `dms_cr_SharePoint` | SharePoint | Flow service account (member of *DMS Service Accounts* / *Exchange Service Accounts*) |
| `dms_cr_Teams` | Microsoft Teams | Flow service account |
| `dms_cr_O365Users` | Office 365 Users | Flow service account |
| `dms_cr_Approvals` | Approvals | Flow service account |
| `dms_cr_O365Groups` | Office 365 Groups | Flow service account (DC-00 group membership check) |

All five connectors are standard and must be in the **Business** DLP group.

For every flow with a Power Apps trigger, go to **Run only users** and set every connection to *Use this connection (service account)*. Users then need only Read on the lists, and all writes are validated and audited by the flow.

### 1.2 Environment variables

| Name | Example | Used by |
| --- | --- | --- |
| `dms_SiteUrl_DC` | `https://contoso.sharepoint.com/sites/DocumentControl` | all DC flows |
| `dms_SiteUrl_EX` | `https://contoso.sharepoint.com/sites/LargeFileExchange` | all EX flows |
| `dms_Language` | `en` or `he` | default when a user has no `preferredLanguage` |
| `dms_TeamId` | Document Control team ID | channel posts |
| `dms_Channel_DocControl` | channel ID | approvals status, failures, overdue |
| `dms_Channel_ITAlerts` | channel ID | transfer failures, deletion failures, flow errors |
| `dms_DocControlGroupId` | Entra object ID of `GG_DMS_DocumentControl` | DC-00 |
| `dms_AdminGroupId` | Entra object ID of `GG_DMS_ITAdmins` | DC-00 |
| `dms_DocControlLeadEmail` | `doc.control.lead@contoso.com` | replaces a submitter who is also a locked approver |
| `dms_RepositoryRoot` | `\\FILE-SERVER\Corporate_Data` | path validation |
| `dms_ExpiryDays` | `14` | EX-01 |
| `dms_MaxFileSizeGB` | `100` | EX-03 |
| `dms_DefaultSlaDays` | `5` | DC-04, DC-06 |
| `dms_ArchiveAfterMonths` | `24` | DC-12 |
| `dms_RoleUploadOnly` | `DMS Upload Only` (or `DMS - העלאה בלבד` on a Hebrew site) | EX-01 |

### 1.3 Standard patterns used by every flow

**Try / Catch / Finally.** Put the body in a `Scope - Try`. `Scope - Catch` runs after *has failed* or *has timed out*. It calls `DMS-U1 Write Audit` (EventType `StatusChanged`, details = `result('Scope_-_Try')`), posts to `dms_Channel_ITAlerts` and, for Power Apps triggers, runs *Respond to a PowerApp* with `{"status":"error","message":"<localized>"}`.

**Caller identity (Power Apps V2 trigger).** `triggerOutputs()?['headers']?['x-ms-user-email']`. Never trust an email passed as a parameter for authorization.

**Localized text.** Always use `DMS-U2 Render Message`. Never type user-facing text into a flow.

**IDs from the item ID.** Create the item first, then update its business ID from `outputs('Create_item')?['body/ID']`. This is race-free.

**Choice columns in OData filters.** `LifecycleStatus eq 'Submitted'`. Person columns: `DocumentOwner/EMail eq 'x@contoso.com'`.

## 2. Utility child flows

Child flows use the trigger *Manually trigger a flow* and are called with *Run a Child Flow*. They end with *Respond to a PowerApp or flow*.

### DMS-U1 Write Audit

| | |
| --- | --- |
| Inputs | `Site` (DC or EX), `CorrelationId`, `EventType`, `FromStatus`, `ToStatus`, `Actor`, `Source`, `Details` |
| Logic | *Create item* in `Control Audit` (DC) or `Exchange Audit` (EX). Title = `concat(EventType,' ',CorrelationId)`, `EventUtc = utcNow()` |
| Output | `ok` |

The service account has only **Append Only** on audit lists, so the flow cannot edit or delete events even by mistake.

### DMS-U2 Render Message

| | |
| --- | --- |
| Inputs | `Key` (for example `msg.approval.body`), `Lang` (`en`/`he`), `Tokens` (JSON array text `[{"k":"DocumentId","v":"QA-PFM-00042"}]`) |
| Output | `Text` |

1. *Get items* `UI Labels`, Filter query `Title eq '@{triggerBody()['text']}'`, Top 1.
2. *Initialize variable* `msg` (String) =
   `if(equals(triggerBody()['text_1'],'he'), first(outputs('Get_items')?['body/value'])?['LabelHE'], first(outputs('Get_items')?['body/value'])?['LabelEN'])`
3. *Apply to each* `json(triggerBody()['text_2'])` (concurrency 1):
   - *Compose* `replace(variables('msg'), concat('{', items('Apply_to_each')?['k'], '}'), string(items('Apply_to_each')?['v']))`
   - *Set variable* `msg` = `outputs('Compose')`
4. Respond `Text = variables('msg')`.

### DMS-U3 Notify

| | |
| --- | --- |
| Inputs | `Recipients` (`;`-separated emails), `Key`, `Tokens`, `PostToChannel` (`none`/`doccontrol`/`it`) |

1. *Apply to each* `split(Recipients, ';')` where the item is not empty:
   - *Get user profile (V2)* → `Lang = if(startsWith(toLower(coalesce(outputs('Get_user_profile_(V2)')?['body/preferredLanguage'], parameters('dms_Language'))), 'he'), 'he', 'en')`
   - Run child `DMS-U2` (Key, Lang, Tokens)
   - Teams *Post message in a chat or channel*. Post as **Flow bot**, Post in **Chat with Flow bot**, Recipient = item, Message = rendered text. For Hebrew, wrap it in `<div dir="rtl">…</div>`.
2. If `PostToChannel <> none`, render in **both** languages (EN, a line break, then HE in `<div dir="rtl">`) and post to the channel.

### DMS-U4 Resolve Delegate

| | |
| --- | --- |
| Input | `Email` |
| Output | `Effective` (email), `DelegatedFrom` (email or empty) |

*Get items* `Delegations`, filter
`DelegationStatus eq 'Active' and Delegator/EMail eq '@{Email}' and ValidFrom le '@{utcNow('yyyy-MM-dd')}' and ValidTo ge '@{utcNow('yyyy-MM-dd')}'`, Top 1.
If found and `DelegationApprovedBy` is not empty, return the delegate. Otherwise return the input.

## 3. Document-control flows

| ID | Name | Trigger | Purpose |
| --- | --- | --- | --- |
| DC-00 | Get User Context | Power Apps V2 | Role flags and language for the app |
| DC-01 | Register Document | Power Apps V2 | **Creation** - new controlled document |
| DC-02 | Create New Revision | Power Apps V2 | **Revision** - draft copy of the current revision |
| DC-03 | Submit For Approval | Power Apps V2 | **Review** - validate approvers, open the cycle |
| DC-04 | Run Approval Cycle | Workflow History item → `InReview` | **Approval** - Teams approvals, stage 1 and final |
| DC-05 | File Action Result | File Action Queue item → `Completed` or `Failed` | **Versioning** - apply outcome to the register |
| DC-06 | Reminders and Escalation | Recurrence, weekdays 07:00 | **Notifications** - SLA |
| DC-07 | Cancel or Restart Workflow | Power Apps V2 | Approver change = cancel + restart |
| DC-08 | Periodic Review | Recurrence, daily 06:30 | Review-cycle notifications |
| DC-09 | Make Obsolete | Power Apps V2 | Withdraw a document |
| DC-10 | Release to PLM | child of DC-05 | Queue the PLM hand-off with a manifest |
| DC-11 | Delegation Lifecycle | Recurrence, daily 00:15 | Activate, expire and notify delegations |
| DC-12 | Archive Sweep | Recurrence, monthly | **Archival** of old obsolete revisions |

### DC-00 Get User Context

1. `email = toLower(triggerOutputs()?['headers']?['x-ms-user-email'])`
2. Office 365 Groups *List group members* (`dms_DocControlGroupId`, Top 999) → *Filter array* `toLower(item()?['mail']) eq email` → `isDocumentController = greater(length(body('Filter_array')), 0)`.
3. The same for `dms_AdminGroupId` → `isAdmin`.
4. *Get user profile (V2)* → `preferredLanguage`.
5. Respond `isDocumentController`, `isAdmin`, `preferredLanguage`.

Keep these two groups flat (no nested groups), because *List group members* is not transitive.

### DC-01 Register Document (creation)

Inputs: Title, Area, Type, ControlMode, OwnerEmail, Department, CustomerCode, ProjectCode, Classification, Retention, Language, ReviewMonths, WorkingUncPath.

1. **Validate**
   - Title, Area, Type and Owner are not empty.
   - `WorkingUncPath` starts with `dms_RepositoryRoot`, contains `\Working\`, and does not contain `..`:
     `and(startsWith(toLower(p), toLower(parameters('dms_RepositoryRoot'))), contains(toLower(p), '\working\'), not(contains(p, '..')))`
   - Force the control mode for mandatory types:
     `if(contains(createArray('Policy','Procedure','Contract / NDA','ECO / ECN','Work Instruction','Test Procedure','PFMEA / Control Plan','IT Procedure','Security Policy'), Type), 'Workflow Required', ControlMode)`
2. **Create item** `Document Register` with LifecycleStatus `Working`, CurrentRevision empty, DraftRevision `Rev01`, and a temporary `DocumentId` = `concat('TMP-', guid())`.
3. **Compose codes** with two *Compose* actions holding JSON maps (see 01 §4.3), for example
   `json('{"Management":"MGT","Commercial":"COM","Development":"DEV","Manufacturing":"MFG","Test Engineering":"TST","Quality":"QA","Changes":"CHG","IT":"IT","InfoSec":"SEC"}')[Area]`
4. **Update item**: `DocumentId = concat(areaCode, '-', typeCode, '-', formatNumber(outputs('Create_item')?['body/ID'], '00000'))`.
5. **Create item** `File Action Queue`: ActionType `VerifyWorkingFile`, SourceUncPath = WorkingUncPath, DocumentId, Revision `Rev01`, RequestedBy = caller, RequestedUtc = `utcNow()`.
6. U1 audit `Created`.
7. Respond `{status:'ok', documentid}`.

#### Copilot prompt

```text
When Power Apps calls the flow with inputs Title, Area, Type, ControlMode, OwnerEmail, Department,
CustomerCode, ProjectCode, Classification, Retention, Language, ReviewMonths and WorkingUncPath:
validate that required inputs are not empty and that WorkingUncPath starts with the environment
variable dms_RepositoryRoot, contains "\Working\" and does not contain "..". Create an item in the
SharePoint list "Document Register" on site dms_SiteUrl_DC with LifecycleStatus "Working" and
DraftRevision "Rev01". Then update the item so DocumentId is the area code, a dash, the type code, a
dash and the item ID padded to 5 digits. Create an item in "File Action Queue" with ActionType
"VerifyWorkingFile" and ActionStatus "Queued". Create an audit item in "Control Audit". Respond to Power
Apps with status and documentid. Wrap everything in a Try scope and a Catch scope that responds with an
error.
```

### DC-02 Create New Revision (revision / versioning)

Inputs: DocumentId.

1. Get the register item. Require `LifecycleStatus in (Approved_ReadOnly, Released_PLM)`, an empty `ActiveWorkflowId`, and a caller who is the owner or a Document Controller (DC-00 logic).
2. `next = concat('Rev', formatNumber(add(int(substring(CurrentRevision, 3)), 1), '00'))`
3. *Create item* `File Action Queue`: `CreateDraftCopy`, SourceUncPath = CurrentUncPath, TargetUncPath =
   `replace(replace(CurrentUncPath, '\Current_ReadOnly\', '\Working\'), concat('_', CurrentRevision, '.'), concat('_', next, '_DRAFT.'))`, Revision = next.
4. Update the register: `DraftRevision = next`. The status stays at the current value until DC-05 confirms the copy.
5. U1 audit `FileActionQueued`. Respond ok.

#### Copilot prompt

```text
When Power Apps calls with DocumentId: get the Document Register item with that DocumentId. If its
LifecycleStatus is not Approved_ReadOnly or Released_PLM, or ActiveWorkflowId is not empty, respond with
an error. Calculate the next revision label by adding 1 to the number after "Rev" in CurrentRevision,
padded to two digits. Create a File Action Queue item with ActionType "CreateDraftCopy", SourceUncPath =
CurrentUncPath and TargetUncPath = the same path with "\Current_ReadOnly\" replaced by "\Working\" and
"_<current>." replaced by "_<next>_DRAFT.". Update DraftRevision on the register item, write an audit
event, and respond ok.
```

### DC-03 Submit For Approval (review)

Inputs: DocumentId, Revision, ChangeSummary, Impacts (`;`), RequiredEmails (`;`), ConditionalEmails (`;`), ReviewerEmails (`;`), FinalEmail, DueDate, Justification.

1. **Load**: the register item, the Approver Matrix item where `DocumentType eq '<type>' and IsActive eq 1`, and Impact Routing items where `IsActive eq 1`.
2. **Authorize**: the caller is the owner, `LifecycleStatus eq 'Working'`, `ControlMode ne 'Collaboration'`, and `ActiveWorkflowId` is empty.
3. **Idempotency**: *Get items* `Workflow History` with filter `DocumentId eq '<id>' and Revision eq '<rev>' and (WorkflowStatus eq 'Pending' or WorkflowStatus eq 'InReview')`. If found, respond ok with the existing WorkflowId.
4. **Recompute the required set on the server**
   - `mandatory = Select(matrix.MandatoryApprovers, toLower(item()?['Email']))`
   - `impactApprovers`: *Filter array* over the impact rules where `contains(split(Impacts,';'), first(item()?['ChangeImpact'])?['Value'])`. Then use a nested *Apply to each* (rule, then `IncludeApprovers`) and *Append to array variable* `arrImpact` with `toLower(item()?['Email'])`.
   - `required = union(mandatory, impactApprovers)`
   - `final = toLower(matrix.FinalApprover.Email)`. If empty, respond error `app.err.approvers` ("Approver matrix incomplete").
5. **Check nothing was removed**. *Filter array* `required` where
   `not(contains(concat(';', toLower(RequiredEmails), ';'), concat(';', item(), ';')))`.
   If the length is greater than 0, respond error (AC-12 / blueprint 7.1 "cannot remove required approvers").
   Also require `toLower(FinalEmail) = final`.
6. **Separation of duties**. Remove the caller from every set. If the caller was in `required` or was `final`, add `dms_DocControlLeadEmail` in that slot.
7. **Create** `Workflow History`: Title `concat(DocumentId,' ',Revision)`, WorkflowStatus `Pending`, RoutingMode from the matrix (default `Hybrid`), person fields from the email lists (Claims = `concat('i:0#.f|membership|', email)`), ChangeImpact, ChangeSummary, DueDate (default `addDays(utcNow(), mul(SlaDays, 2), 'yyyy-MM-dd')`), `CycleNumber = add(length(previousCycles), 1)`, SubmittedBy = caller.
8. **Update** it with `WorkflowId = concat('WF-', utcNow('yyyy'), '-', formatNumber(ID, '000000'))`, and the register item with `ActiveWorkflowId = WorkflowId`.
9. **Queue** `MoveToSubmitted` (SourceUncPath = WorkingUncPath, TargetUncPath = WorkingUncPath with `\Working\` replaced by `\Submitted\`).
10. U1 audit `Submitted`. If `Justification` is not empty, add a second audit event whose details list the removed conditional approvers and the reason.
11. Respond `{status:'ok', workflowid}`.

#### Copilot prompt

```text
When Power Apps calls with DocumentId, Revision, ChangeSummary, Impacts, RequiredEmails,
ConditionalEmails, ReviewerEmails, FinalEmail, DueDate and Justification: get the Document Register
item, the active Approver Matrix item for its DocumentType, and all active Impact Routing items. Verify
the caller (x-ms-user-email header) is the document owner, the status is Working and there is no active
workflow. Build the list of required approver emails from the matrix MandatoryApprovers plus the
IncludeApprovers of every impact rule whose ChangeImpact is in Impacts. If any required email is missing
from RequiredEmails, or FinalEmail differs from the matrix FinalApprover, respond with an error. Remove
the caller from all approver lists. Create a Workflow History item with status Pending, set WorkflowId
to "WF-" + year + "-" + the item ID padded to 6 digits, save it on the register as ActiveWorkflowId,
create a File Action Queue item "MoveToSubmitted", write audit events and respond with the WorkflowId.
```

### DC-04 Run Approval Cycle (approval)

**Trigger**: SharePoint *When an item is created or modified* on `Workflow History`.
Trigger condition: `@equals(triggerOutputs()?['body/WorkflowStatus/Value'], 'InReview')`.
DC-05 sets `InReview` only after the Workflow Service confirms the file is read-only in `Submitted`, so approvers never review a file that is still changing.

1. **Guard (idempotent)**: *Get items* `Approval Decisions` filter `WorkflowId eq '<id>'`. If any exist, *Terminate* (Succeeded).
2. **Stage-1 list** = `union(Mandatory, Conditional, AdditionalReviewers)` emails. When RoutingMode = `Parallel`, append FinalApprover too.
3. **Delegation**: *Apply to each* stage-1 email (concurrency 1). Run U4, append `Effective` to `arrStage1`, and *Create item* `Approval Decisions` (Approver = Effective, DocumentType = the register item's DocumentType, DelegatedFrom, ApproverRole, `ApprovalStage 1`, Decision `Pending`, `DecisionDueDate`).
4. **Approval card**. *Start and wait for an approval*:
   - Type: **Approve/Reject - Everyone must approve** (one rejection completes the approval as *Reject*). For `Sequential`, loop over `arrStage1` with one single-approver approval each, and stop at the first reject.
   - Title: rendered `msg.approval.title` in `dms_Language`.
   - Assigned to: `join(variables('arrStage1'), ';')`
   - Details (Markdown, bilingual, one card for all approvers):

     ```text
     **@{DocumentId} @{Revision} - @{Title}**
     Change summary: @{ChangeSummary}
     File (read-only): `@{SubmittedUncPath}`
     SHA-256: `@{SubmittedSHA256}`
     Due: @{DueDate}
     ---
     <div dir="rtl">(Hebrew rendering of msg.approval.body)</div>
     ```

   - Item link: the register item URL. Item link description: `DocumentId`.
   - Enable notifications: **Yes** (Teams Approvals app and activity feed. There are no attachments).
   - Action **Settings → Timeout**: `P25D` (below the 30-day flow run limit).
5. **Record decisions**. *Apply to each* `outputs('Start_and_wait_for_an_approval')?['body/responses']`: update the matching Approval Decisions item (`Approver/EMail eq responder.email`) with `Decision = if(equals(item()?['approverResponse'],'Approve'),'Approved','Rejected')`, `DecisionComment = item()?['comments']`, `DecisionUtc = item()?['responseDate']`. Then set any remaining `Pending` items for this WorkflowId to `Cancelled`.
6. **Still valid?** Get the Workflow History item again. If `WorkflowStatus` is no longer `InReview` (DC-07 cancelled it), *Terminate*. The outcome is ignored and recorded as `Cancelled`.
7. **Stage 2 (Hybrid only, and only if stage 1 = Approve)**: resolve the delegate for FinalApprover, create the decision item (`ApprovalStage 2`, role `Final`), then *Start and wait for an approval* with **Approve/Reject - First to respond** and the same details. Record the decision as in step 5.
8. **Outcome**
   - **Rejected** → Workflow History `Rejected`, `CompletedUtc`, `FinalComment` = the rejecting comment. Queue `ReturnToWorking`. U3 notify the owner with `msg.rejected.owner`. U1 audit `Rejected`.
   - **Approved** → Workflow History `Approved`, `CompletedUtc`. Queue `PromoteToCurrent` (SourceUncPath = SubmittedUncPath, TargetUncPath = the `\Current_ReadOnly\` path without `_DRAFT`). U1 audit `Approved`. The owner is notified by DC-05 after the file is really promoted.
9. **Timeout branch** (configure *run after: has timed out* on the approval action): Decisions → `Expired`, Workflow History → `Cancelled` with FinalComment "Expired after 25 days", queue `ReturnToWorking`, post to `dms_Channel_DocControl`.

#### Copilot prompt

```text
When an item in the SharePoint list "Workflow History" is created or modified and WorkflowStatus equals
"InReview": stop if any "Approval Decisions" items already exist for its WorkflowId. Combine the emails
of MandatoryApprovers, ConditionalApprovers and AdditionalReviewers. For each email, look up an active
approved delegation in "Delegations" and use the delegate instead, and create a Pending Approval
Decisions item. Start and wait for an approval of type "Approve/Reject - Everyone must approve" assigned
to all these people, with the document ID, revision, change summary, UNC path and SHA-256 in the details
and a 25-day timeout. For each response, update the matching Approval Decisions item with the decision,
comments and date. If approved, start a second "First to respond" approval for the FinalApprover and
record it the same way. If anything was rejected, set the workflow to Rejected and create a File Action
Queue item "ReturnToWorking"; if all approved, set it to Approved and create "PromoteToCurrent". Write
an audit event and notify the document owner in Teams.
```

### DC-05 File Action Result (versioning)

**Trigger**: *When an item is created or modified* on `File Action Queue`.
Trigger condition: `@or(equals(triggerOutputs()?['body/ActionStatus/Value'],'Completed'), equals(triggerOutputs()?['body/ActionStatus/Value'],'Failed'))`.

*Switch* on `ActionType`:

| ActionType | On `Completed` | On `Failed` |
| --- | --- | --- |
| `VerifyWorkingFile` | Register: WorkingUncPath = SourceUncPath. Notify the owner (`app.ok.saved`) | Notify the owner and Document Control (`msg.fileaction.failed`) |
| `CreateDraftCopy` | Register: WorkingUncPath = TargetUncPath, LifecycleStatus `Working`. Notify with `msg.draft.ready` | Register: DraftRevision cleared. Notify |
| `MoveToSubmitted` | Workflow History: SubmittedUncPath = TargetUncPath, SubmittedSHA256 = ResultSHA256, **WorkflowStatus `InReview`** (starts DC-04). Register: LifecycleStatus `Submitted` | Workflow History `Cancelled`, register ActiveWorkflowId cleared. Notify |
| `ReturnToWorking` | Register: LifecycleStatus `Working`, WorkingUncPath = TargetUncPath, ActiveWorkflowId cleared | Notify Document Control (manual fix) |
| `PromoteToCurrent` | **Integrity check**: `equals(ResultSHA256, WorkflowHistory.SubmittedSHA256)`. If they differ, treat it as Failed and alert IT. Register: CurrentRevision = Revision, DraftRevision cleared, CurrentUncPath = TargetUncPath, CurrentSHA256 = ResultSHA256, LifecycleStatus `Approved_ReadOnly`, LastApprovedUtc = `utcNow()`, EffectiveDate = today, `NextReviewDate = addToTime(utcNow(), ReviewCycleMonths, 'Month', 'yyyy-MM-dd')`, ActiveWorkflowId cleared. Notify the owner with `msg.approved.owner` and the channel. Run **DC-10** when the document is PLM-bound | Notify Document Control and IT |
| `ReleaseToPLMQueue` | Register: LifecycleStatus `Released_PLM` | Notify Document Control |
| `MakeObsolete` | Register: LifecycleStatus `Obsolete_ReadOnly`. Notify with `msg.obsolete` | Notify Document Control |
| `ArchiveRevision` | Register: LifecycleStatus `Archived` | Notify Document Control |

Every branch ends with U1 audit `FileActionCompleted` or `FileActionFailed`.

### DC-06 Reminders and Escalation (notifications)

Recurrence: Monday to Friday, 07:00 (Israel Standard Time).

1. *Get items* `Approval Decisions` filter `Decision eq 'Pending'` (Top 5000, pagination on).
2. For each item: `days = div(sub(ticks(utcNow()), ticks(item()?['Created'])), 864000000000)`, and `sla` = SlaDays of the matrix rule, or `dms_DefaultSlaDays`.
3. If `days >= sla` and `mod(sub(days, sla), 2) = 0` → U3 notify the approver with `msg.reminder`.
4. If `days >= mul(sla, 2)` → U3 notify the owner and `PostToChannel = doccontrol` with `msg.escalation`.

### DC-07 Cancel or Restart Workflow

Inputs: WorkflowId, Mode (`Cancel` or `Restart`), Reason, plus the DC-03 approver inputs for Restart.

1. Authorize: the owner or a Document Controller.
2. Workflow History → `Cancelled` (Cancel) or `Restarted` (Restart), with FinalComment = Reason. Every `Pending` decision → `Cancelled`.
3. U3 notify the stage-1 approvers with `msg.cancelled`, so they know the open Teams card is void. DC-04 ignores its outcome (step 6).
4. **Cancel**: queue `ReturnToWorking`, clear ActiveWorkflowId.
   **Restart**: the file stays in `Submitted`. Run the DC-03 validation (steps 4-6), create a new Workflow History cycle (`CycleNumber + 1`) directly in `InReview` with the same SubmittedUncPath and SubmittedSHA256, and update ActiveWorkflowId. DC-04 starts automatically.
5. U1 audit `Cancelled`.

### DC-08 Periodic Review

Daily 06:30. *Get items* `Document Register` filter
`(LifecycleStatus eq 'Approved_ReadOnly' or LifecycleStatus eq 'Released_PLM') and NextReviewDate le '@{addDays(utcNow(), 30, 'yyyy-MM-dd')}'`.

- `NextReviewDate` = today + 30 or today + 7 → U3 owner `msg.review.due`
- `NextReviewDate` < today and today is Monday → U3 owner + channel `msg.review.overdue`

### DC-09 Make Obsolete

Inputs: DocumentId, Reason. The caller must be a Document Controller (DC-00 check in-flow). The status must be `Approved_ReadOnly` or `Released_PLM` with no active workflow. Queue `MakeObsolete` (TargetUncPath = the `\Obsolete_ReadOnly\` path). U1 audit with the reason. Respond ok.

### DC-10 Release to PLM (child of DC-05)

It runs when `DocumentArea in (Development, Changes, Manufacturing, Test Engineering)` and `ControlMode = Workflow Required`, or when `PLMReference` is not empty. It queues `ReleaseToPLMQueue` with TargetUncPath = `concat(dms_RepositoryRoot, '\03_Operations_Staging\PLM_Release_Queue\', DocumentId, '_', Revision)`. The Workflow Service writes the file plus `manifest.json` `{DocumentId, Revision, SHA256, ApprovedUtc, WorkflowId, Approvers[]}` (AC-14). MAE and Priority use the same pattern with their own queue folders.

### DC-11 Delegation Lifecycle

Daily 00:15.

- `ValidTo lt today` and Active → `Expired`.
- `ValidFrom eq today` and Active and approved → U3 notify the delegator and the delegate with `msg.delegation.active`.
- An Active item without `DelegationApprovedBy` is ignored by U4. Post a daily reminder to the channel.

### DC-12 Archive Sweep (archival)

Monthly, on day 1 at 02:00. Register items with `LifecycleStatus eq 'Obsolete_ReadOnly'` and `Modified lt addToTime(utcNow(), -dms_ArchiveAfterMonths, 'Month')` → queue `ArchiveRevision`. Legal Hold items (`RetentionClass eq 'Legal Hold'`) are skipped. Seven-year retention is enforced by Veeam compliance restore points (blueprint 11), not by SharePoint.

## 4. Large-file exchange flows (blueprint 9.4)

| ID | Blueprint name | Trigger |
| --- | --- | --- |
| EX-01 | CreateExchangeRequest | Power Apps V2 |
| EX-02 | FileUploadedMetadata | *When a file is created (properties only)* - Temporary Uploads |
| EX-03 | SubmitTransferRequest | Power Apps V2 |
| EX-04 | TransferStatusNotification | *When an item is created or modified* - Upload Requests |
| EX-05 | ExpiryControl | Recurrence daily 01:00 |
| EX-06 | AcceptTransferredFile | Power Apps V2 |
| EX-07 | CancelExchangeRequest | Power Apps V2 |

### EX-01 CreateExchangeRequest

Inputs: CustomerCode, ProjectCode, Direction, PackageDescription, RoutingId, RequesterEmail, GuestEmail.

1. Get Routing Catalog item `RoutingId`. It must be active, and CustomerCode and ProjectCode must match.
2. **Path safety (AC-09)**. Reject when
   `or(contains(p,'..'), startsWith(p,'\'), startsWith(p,'/'), contains(p,':'), contains(p,'//'))`, where `p = DestinationRelativePath`.
3. If GuestEmail is given, its domain must be in `AllowedGuestDomains`: `contains(toLower(AllowedGuestDomains), toLower(last(split(GuestEmail,'@'))))`.
4. **Duplicate**: an open request (Draft to Transferring) with the same requester, project and description → error `app.err.duplicate`.
5. *Create item* Upload Requests (Draft), then set `RequestId = concat('EXC-', utcNow('yyyyMMdd'), '-', formatNumber(ID,'0000'))`.
6. *Create new folder* in `TemporaryUploads` with the name RequestId.
7. **Unique permissions** (*Send an HTTP request to SharePoint*, site `dms_SiteUrl_EX`):
   - `POST _api/web/GetFolderByServerRelativeUrl('TemporaryUploads/<RequestId>')/ListItemAllFields/breakroleinheritance(copyRoleAssignments=false,clearSubscopes=true)`
   - `POST _api/web/ensureuser` body `{"logonName":"i:0#.f|membership|<RequesterEmail>"}` → `d.Id`. Do the same for GuestEmail. The guest must already be invited (Phase 9).
   - `GET _api/web/roledefinitions/getbyname('<dms_RoleUploadOnly>')` → `d.Id`
   - `POST .../ListItemAllFields/roleassignments/addroleassignment(principalid=<id>,roledefid=<rid>)` for each user
   - The Exchange Document Control group: `GET _api/web/sitegroups/getbyname('Exchange Document Control')` → addroleassignment with the *DMS Document Controller* role
8. Update the item: ExchangeStatus `AwaitingUpload`, `UploadFolderUrl = concat(parameters('dms_SiteUrl_EX'), '/TemporaryUploads/Forms/AllItems.aspx?id=', encodeUriComponent(concat(uriPath(parameters('dms_SiteUrl_EX')), '/TemporaryUploads/', RequestId)))`, `ExpiryDate = addDays(utcNow(), int(parameters('dms_ExpiryDays')), 'yyyy-MM-dd')`, RequestedBy, UploaderEmail, GuestEmail.
9. U1 audit (EX) `Created`. U3 notify the requester with `msg.ex.created`.
10. Respond `{status, requestid, uploadurl}`.

#### Copilot prompt

```text
When Power Apps calls with CustomerCode, ProjectCode, Direction, PackageDescription, RoutingId,
RequesterEmail and GuestEmail: get the "Routing Catalog" item by ID and verify it is active and matches
the codes; reject if its DestinationRelativePath contains "..", ":" or starts with a slash or backslash.
Create an "Upload Requests" item with status Draft and set RequestId to "EXC-" + today (yyyyMMdd) + "-" +
the item ID padded to 4 digits. Create a folder with that name in the "TemporaryUploads" library, break
its permission inheritance with a SharePoint HTTP request, grant the permission level "DMS Upload Only"
to the requester and the guest and "DMS Document Controller" to the group "Exchange Document Control".
Set the status to AwaitingUpload, save the folder URL and an expiry date 14 days ahead, write an audit
event in "Exchange Audit", and respond with requestid and uploadurl.
```

### EX-02 FileUploadedMetadata

1. Trigger on the library root, including subfolders. `{Path}` looks like `TemporaryUploads/EXC-20260924-0012/`, so
   `requestId = split(triggerOutputs()?['body/{Path}'], '/')[1]`.
2. *Get file metadata* (Id = `{Identifier}`) → `Size`.
3. Get the Upload Requests item by RequestId. Its status must be `AwaitingUpload`, or `Uploaded` when the file is being replaced.
4. **One file per request** (blueprint schema). If `ExchangeFileName` is already set to a different name → FailureDetail "One file per request - upload a single ZIP", post to the Document Control channel, stop.
5. Update: ExchangeFileName = `{FilenameWithExtension}`, ExpectedSizeBytes = Size, DriveItemId = the file's list item `ID` (the worker resolves `/sites/{site}/lists/{list}/items/{ID}/driveItem`), ExchangeStatus `Uploaded`.
6. Stamp `RequestId` on the file (*Update file properties*). U1 audit `StatusChanged`.

### EX-03 SubmitTransferRequest

The caller is the requester or Document Control. The status must be `Uploaded`, with `ExpectedSizeBytes > 0` and at most `mul(dms_MaxFileSizeGB, 1073741824)`, and the destination is re-validated. Set `ReadyForTransfer` and audit. The Transfer Worker picks it up within `TransferPollMinutes`.

### EX-04 TransferStatusNotification

Trigger condition: the status is `Transferred`, `TransferFailed`, `Accepted` or `Rejected`.
Guard: the last Exchange Audit event for RequestId already has `ToStatus` = the current status → stop (no duplicate messages).

| Status | Message | Recipients |
| --- | --- | --- |
| Transferred | `msg.ex.transferred` (SizeGB = `div(float(ExpectedSizeBytes), 1073741824)`) | Requester + Document Control channel |
| TransferFailed | `msg.ex.failed` | Requester + IT channel |
| Transferred / Accepted with `CloudCopyDeleted = false` and FailureDetail containing `delete` | `msg.ex.deletefailed` | IT channel |
| Accepted | `msg.ex.accepted` | Requester |
| Rejected | `msg.ex.rejected` | Requester |

### EX-05 ExpiryControl

1. Requests in `Draft`, `AwaitingUpload` or `Uploaded` with `ExpiryDate` = today + 2 → U3 `msg.ex.expiring`.
2. Requests in those states with `ExpiryDate lt today` → *Delete folder* `TemporaryUploads/<RequestId>` (this removes the guest's access with it), status `Expired`, audit, U3 `msg.ex.expired`.
3. `Transferred` or `Accepted` with `CloudCopyDeleted eq 0` and `TransferCompletedUtc` older than 1 day → IT channel `msg.ex.deletefailed`.

### EX-06 AcceptTransferredFile

Inputs: RequestId, Decision (`Accept` or `Reject`), Comment.
Only Document Control may call it. The status must be `Transferred`, with `SHA256` set. Set `Accepted` or `Rejected`, ReviewedBy and DecisionComment, then audit. The Transfer Worker moves the quarantined file to `Accepted\<RequestId>\` and then to `dms_RepositoryRoot\02_Customers\<DestinationRelativePath>`, or to `Rejected\`. If CrowdStrike has quarantined the file, the worker finds it missing or locked and sets `TransferFailed` "Security detection". Acceptance is therefore blocked (AC-10) and Security owns the release decision.

### EX-07 CancelExchangeRequest

The caller is the requester or Document Control. The status must be `Draft`, `AwaitingUpload` or `Uploaded`. *Delete folder*, then status `Cancelled`, then audit.

## 5. On-premises worker contracts

These are PowerShell 7 scheduled tasks running under gMSAs on the CrowdStrike-protected integration server (blueprint Phase 6), code-signed, every 1-5 minutes, with *IgnoreNew* concurrency.

### 5.1 Workflow Service (`RH-DMS-Workflow-Service`, Sites.Selected Write on the DC site)

1. Graph `GET /sites/{dc}/lists/FileActionQueue/items?$filter=fields/ActionStatus eq 'Queued'&$expand=fields`. `ActionStatus` is indexed, so the filter stays valid above 5,000 items.
2. For each row, `PATCH` ActionStatus `Processing` and `Attempts + 1`.
3. Validate both paths: they are under `dms_RepositoryRoot`, contain no `..`, and the target folder is one of `Working | Submitted | Current_ReadOnly | Obsolete_ReadOnly | Archive | 03_Operations_Staging`.
4. Execute the command (01 §3.1). Moves use `Move-Item` on the same volume (atomic). A copy writes to `<target>.partial`, verifies size and SHA-256, then renames.
5. Set NTFS: `Submitted`, `Current_ReadOnly` and `Obsolete_ReadOnly` files get the read-only attribute. The folder ACLs come from the DL_ groups (02 §3.2).
6. `PATCH` `Completed` with ResultSHA256, ResultSizeBytes, TargetUncPath and ProcessedUtc. On error, retry up to 3 attempts, then `Failed` with a safe FailureDetail (no stack traces or credentials).
7. Log to `04_Workflow_System\Processing\logs` and to the Windows event log. The Veeam backup includes it.

### 5.2 Transfer Worker (`RH-Exchange-Transfer-Worker`, blueprint 9.5)

Its configuration is unchanged from blueprint 9.5 (`solution.parameters.json`). The verified-deletion gate follows blueprint 8.3 exactly. On acceptance it also routes the file as described in EX-06.

## 6. Build order and testing

1. Utilities U1, U2, U4, then U3.
2. DC-00 and DC-05 first (DC-05 has no dependencies), then DC-01, DC-02, DC-03, DC-04, DC-07 and the scheduled flows.
3. EX-02 and EX-04 before EX-01, then EX-03, EX-06, EX-07, EX-05.
4. Turn on every flow and add the Power Apps flows to the apps.
5. Run the acceptance tests AC-01 to AC-15 (blueprint 13), plus these.

| Test | Expected |
| --- | --- |
| Submit with a crafted request that drops a mandatory approver | DC-03 error, no history item |
| One approver rejects while others are pending | The card completes as Reject immediately, the others are `Cancelled`, the file returns to Working |
| Change approvers mid-cycle | Old cycle `Restarted`, a new cycle with `CycleNumber = 2`, old cards void |
| Promote with a tampered file (hash differs) | DC-05 blocks promotion and alerts IT |
| Approver on leave with an approved delegation | The delegate receives the card, and `DelegatedFrom` is recorded |
| Language = he | Teams messages are in Hebrew and right-aligned, and the approval details are bilingual |
