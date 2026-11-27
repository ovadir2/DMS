# VAL-004 PQ Protocol - Performance Qualification

| | |
|---|---|
| Software revision | 01 - the whole validation set carries one version (`validation.json`) |
| System | RH DMS, production installation |
| Purpose | To show the DMS does, in real use, what Document Control needs it to do |
| Pre-requisite | VAL-002 and VAL-003 executed and signed; training recorded |
| Period | 10 working days, from ______ to ______ |
| Executed by | Document Control, with the named document owners and approvers |

PQ is not a rehearsal: the documents are the company's real documents, filed by the people whose work it
is, approved by their real approvers. IT does not operate the system during PQ; it collects the evidence.

`.\scripts\Invoke-DmsPQ.ps1 -From <date> -To <date>` reads the register and the Control Audit for the
period and writes the measured part of this report: what was released, by whom, how long each stage took,
what was returned with remarks, what was shared, and every error the DMS logged.

## What is exercised

| # | Case | Who | Acceptance criterion | Result |
|---|---|---|---|---|
| PQ-01 | At least 10 real documents taken from draft to released, across at least 3 departments | Their owners | All reach `Current_ReadOnly` with the right revision; none is lost or duplicated | |
| PQ-02 | At least 3 of them with more than one mandatory approver | Their approvers | Stage 1 completes only when every mandatory approver has answered | |
| PQ-03 | At least 2 returned with remarks and re-submitted | Owners and approvers | The remarks reach the owner; the re-submitted revision is approved and released | |
| PQ-04 | At least 1 delegation | An approver going on leave | The delegate answers; the approval returns afterwards; both are in Delegations and the audit | |
| PQ-05 | At least 2 new revisions of documents already in force | Owners | The previous revision moves to `Obsolete_ReadOnly`; the new one is in force; both are findable | |
| PQ-06 | At least 2 shares with a customer | Document Control | The customer receives the invitation and can open the file view-only; the share log and audit have it | |
| PQ-07 | Everyday use by people who are not approvers | Any user | They see what their AD groups allow and nothing else; no request for rights on the file server was needed | |
| PQ-08 | The AI answers from released documents only | Document Control | A question answered from a released revision; a draft or an obsolete revision is never quoted | |
| PQ-09 | Machine callers in real use (HRPortal, WidgetBuilder, the AI index) | Their owners | Each works within its scopes over the period; no call needed a super user | |

## What is measured

| # | Measure | Acceptance criterion | Measured |
|---|---|---|---|
| PQ-10 | Availability over the period | No unplanned outage longer than 30 minutes; the page answers every working day | |
| PQ-11 | Page response | Opening a folder, Approvals and My workflows each answer in under 5 seconds with the period's real data | |
| PQ-12 | Release correctness | 100% of released documents are read only in `Current_ReadOnly` with a Markdown beside them (or a card saying there is no text) | |
| PQ-13 | Audit completeness | Every release in the period has its full chain in Control Audit: created, submitted, each decision, released | |
| PQ-14 | Errors | No critical error in the DMS log that affected a document; every error is explained in the report | |
| PQ-15 | Data at the end | The register matches the file server: every record points at a file that exists, and every released file has a record (`Repair-DmsRegister.ps1 -WhatIf` reports nothing to fix) | |

## User feedback

Collected from at least five users at the end of the period: what they could not do, what they had to ask
IT for, and anything they did outside the DMS because the DMS made it hard. Each item is dispositioned.

| # | User | Observation | Disposition |
|---|---|---|---|
| | | | |

## Deviations

| # | Case | What happened | Class | Disposition | Closed (date, by) |
|---|---|---|---|---|---|
| | | | | | |

## Conclusion

The system **performs / does not perform** in daily use as intended (delete one). Accepted for production
use for controlled documents: **yes / no**.

| Role | Name | Signature | Date |
|---|---|---|---|
| Executed by (Document Control) | | | |
| Reviewed by (System owner) | | | |
| Approved by (Quality) | | | |
