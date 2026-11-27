# Validating the DMS, and keeping it validated

The DMS is the system of record for controlled documents, so it is itself validated and then kept that
way. Everything here is the evidence of that.

## The documents

| Id | Document | What it is for |
|---|---|---|
| VAL-001 | Validation Plan | Scope, approach, responsibilities, acceptance criteria, change control |
| VAL-002 | IQ Protocol | The installation is as specified. Executed by `scripts\Invoke-DmsIQ.ps1` |
| VAL-003 | OQ Protocol | Each function behaves as specified. Executed by `scripts\Invoke-DmsOQ.ps1` |
| VAL-004 | PQ Protocol | The system performs in real use, over 10 working days |
| VAL-005 | Traceability Matrix | Every requirement to the step that proves it |
| VAL-006 | Validation Summary Report | The result, the deviations, the conclusion |
| VAL-007 | Validation Log | One row per change after acceptance |
| VAL-008 | Change Impact Assessment | One per change, before it is deployed |

The source of each one is its Markdown file here - that is what is reviewed and changed in git.

## The software revision

`validation.json` holds the revision of the software, and the DMS answers with it: `/api/health` carries
`softwareRevision`, `validationStatus`, `validatedCommit` and `runningValidatedBuild`. Production starts at
revision **01**. The revision of the validation documents is the revision of the software they validate -
they are never apart.

## A change, from now on

1. Make the change on a branch, with its tests.
2. Fill in a copy of **VAL-008** for it: what it touches, the risk, which validation documents are revised,
   which OQ steps are re-executed. A change to the approval rules, the permission model or the release path
   needs Quality's approval before it is deployed.
3. Run the automated suite, and the OQ steps the assessment names (`Invoke-DmsOQ.ps1` runs the lot).
4. Raise the revision in `validation.json` (01 -> 02), add the row to **VAL-007**, and revise the documents
   the assessment named.
5. Deploy, then run `scripts\Invoke-DmsIQ.ps1` against the new build.
6. Publish: `scripts\Publish-DmsValidation.ps1 -Apply`. Each document becomes the next revision of its own
   record in `01_General\Quality and Standards\DMS_Validation`; the DMS moves the revision it replaces to
   `Obsolete_ReadOnly`, exactly as it does for any controlled document.

## Where the documents live in the DMS

`01_General\Quality and Standards\DMS_Validation` - a blueprint folder, so it cannot be renamed or deleted
from the page. The revision in force is the one in its `Current_ReadOnly`, read only, with the rh logo, the
document number and the revision on every page.

## Building the set without publishing it

```
cd webapi
.\.venv\Scripts\python -m dms_api.validation_docs C:\Temp\validation --revision 01
```
