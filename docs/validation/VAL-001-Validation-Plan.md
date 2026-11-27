# VAL-001 Validation Plan - RH DMS

| | |
|---|---|
| Document | VAL-001, Validation Plan |
| System | RH DMS (Document Management System), `https://dms.rh.tech` |
| Owner | Ronen Ovadia, IT |
| Process owner | Document Control |
| Version | 1.0 |
| Status | For approval |

## 1. Purpose

To show, with recorded evidence, that the DMS is installed as intended, works as specified, and does in
daily use what Document Control needs it to do - before it is relied on for controlled documents.

## 2. Scope

**In scope.** The DMS web application and its API on the production server (IIS site `DMS`), the document
repository on the file server, the SharePoint lists it keeps (Document Register, Control Audit, Approver
Matrix, Notifications, Approval Decisions, Delegations), Windows/AD sign-in and the permission model, the
approval workflow, release and revision handling, the share-with-customer path, the machine API, and the
Markdown the AI reads.

**Out of scope.** Active Directory itself, the file server hardware and its backup, SharePoint Online as a
platform, Microsoft 365 sign-in, the Power Automate flow that delivers notifications (its output is checked,
its internals are not), HRPortal, WidgetBuilder and the AI server - each validated by its own owner.

## 3. System classification and approach

| Item | Determination |
|---|---|
| Software category (GAMP 5) | Category 5 - configured and bespoke application developed in-house |
| Quality standard | ISO 9001:2015 clause 7.5 (documented information) and the company's AS9100D document-control procedure |
| Electronic records | The DMS is the record for controlled documents. Every action is written to Control Audit with actor, time, before/after state, and the SHA-256 of the file the decision was made on |
| Electronic signatures | Not claimed. Approvals are authenticated AD identities recorded in the audit, not 21 CFR Part 11 signatures. If Part 11 becomes a requirement this plan is re-issued |
| Risk | Medium. Wrong release or wrong visibility of a controlled document is the risk that matters; data loss is covered by the file server's own backup |

Validation is performed in three qualifications, each with a protocol executed and signed before the next
begins:

- **IQ** - the system is installed and configured as specified (VAL-002).
- **OQ** - each specified function behaves as specified, including the negative cases (VAL-003).
- **PQ** - the system performs in real use, with real documents and real people, over an agreed period (VAL-004).

Supporting evidence: the automated test suite (`webapi/tests`, 250 tests) and the end-to-end walk
(`scripts/Test-DmsSmoke.ps1`), both run against the production installation and attached to the OQ report.

## 4. Responsibilities

| Role | Who | Responsibility |
|---|---|---|
| System owner | IT (Ronen Ovadia) | Installation, protocol execution, reports, change control |
| Process owner | Document Control | Approves the protocols, witnesses PQ, accepts the system |
| Quality | QA manager | Approves this plan, the protocols and the reports; rules on deviations |
| Users | Named approvers and document owners | Execute the PQ cases in their own work |

An execution step is recorded by the person who performed it, with the date, and is not self-approved: the
reports are signed by the system owner and approved by Quality.

## 5. Acceptance criteria

The system is accepted for production when, all three reports signed:

1. Every IQ step passes, or its deviation is closed.
2. Every OQ step passes. No deviation classified **critical** (wrong release, wrong visibility, lost
   document, lost audit row) may remain open.
3. PQ runs for 10 working days with at least 10 real documents taken through the full workflow by their own
   owners and approvers, with no critical deviation and no data loss.
4. The traceability matrix (VAL-005) shows every requirement covered by at least one executed step.
5. Training is recorded for Document Control and the named approvers.

## 6. Deviations

A step that does not meet its expected result is recorded as a deviation on the report, classified:

| Class | Meaning | Disposition |
|---|---|---|
| Critical | A controlled document could be wrongly released, wrongly visible, lost, or an audit row missing | Must be fixed and the step re-executed before acceptance |
| Major | A specified function does not work; a workaround exists | Fixed, or accepted in writing by Quality with a dated corrective action |
| Minor | Cosmetic, wording, convenience | Listed; corrected in a later release |

Every deviation carries: what was expected, what happened, the cause, the fix, and the re-execution result.

## 7. Change control after validation

After acceptance, a change to the DMS requires: a recorded reason, the automated suite green, the OQ steps
that touch the changed area re-executed, and an entry in the validation log (VAL-007). A change that alters
the approval rules, the permission model or the release path requires Quality's approval before deployment.

## 8. Documents of this validation

| Id | Document |
|---|---|
| VAL-001 | This plan |
| VAL-002 | IQ protocol and report |
| VAL-003 | OQ protocol and report |
| VAL-004 | PQ protocol and report |
| VAL-005 | Requirements traceability matrix |
| VAL-006 | Validation summary report |
| VAL-007 | Validation log (changes after acceptance) |

Specifications referenced: `docs/01-Architecture-and-Data-Model.md`, `docs/02-Security-and-Permissions.md`,
`docs/03-Installation-and-Settings.md`, `docs/04-Using-the-DMS.md`, `docs/05-Approval-Flow.md`,
`docs/09-Machine-API.md`.

## 9. Approval

| Role | Name | Signature | Date |
|---|---|---|---|
| Prepared by (System owner) | | | |
| Reviewed by (Document Control) | | | |
| Approved by (Quality) | | | |
