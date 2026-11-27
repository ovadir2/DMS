# VAL-008 Change Impact Assessment

One of these is completed for **every** change to the DMS after the system is validated, before the change
is deployed. It is the record that says why the new software revision is still a validated system. The
completed assessments are released with the validation set, and the one-line summary of each goes into
VAL-007 (the validation log).

| | |
|---|---|
| Software revision | 01 - the whole validation set carries one version (`validation.json`) |
| Change | |
| Raised by | |
| Date | |
| Software revision before / after | |
| Commit | |

## 1. What changes, and why

Plain words: what a user will see differently, and what problem it solves. Attach the request if there is one.

## 2. What it touches

| Area | Touched? | Why / why not |
|---|---|---|
| Sign-in and identity | | |
| Permissions and visibility (AD, NTFS) | | |
| The approval workflow and its rules | | |
| Release, revisions, obsolete handling | | |
| The audit trail | | |
| Sharing outside the company | | |
| The machine API and its scopes | | |
| The Markdown the AI reads | | |
| Installation and settings | | |

## 3. Risk

| | |
|---|---|
| What could go wrong if the change is faulty | |
| Who it affects | |
| Severity (critical / major / minor) | |
| Likelihood | |
| Mitigation | |

## 4. Validation impact

| Document | Revised? | What changed in it |
|---|---|---|
| VAL-001 Validation Plan | | |
| VAL-002 IQ Protocol | | |
| VAL-003 OQ Protocol | | |
| VAL-004 PQ Protocol | | |
| VAL-005 Traceability Matrix | | |

## 5. Testing

| | |
|---|---|
| Automated suite (`webapi\tests`) | ___ passed, ___ failed |
| New or changed automated tests | |
| OQ steps re-executed | |
| End-to-end walk (`Test-DmsSmoke.ps1`) | |
| Evidence attached | |

A change that touches an area in section 2 re-executes the OQ steps of that area. A change that touches the
approval rules, the permission model or the release path re-executes those **and** is approved by Quality
before deployment.

## 6. Decision

| | |
|---|---|
| The system remains validated at the new revision | yes / no |
| Conditions or follow-up actions | |

| Role | Name | Signature | Date |
|---|---|---|---|
| Prepared by (System owner) | | | |
| Reviewed by (Document Control) | | | |
| Approved by (Quality) - required when section 2 marks workflow, permissions or release | | | |
