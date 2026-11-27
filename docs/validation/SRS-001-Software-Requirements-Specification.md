# SRS-001 Software Requirements Specification - RH DMS

| | |
|---|---|
| System | RH DMS (Document Management System) |
| Software revision | 01 - the whole validation set carries one version (`validation.json`) |
| Status | Baseline for validation |
| Owner | IT (system owner) with Document Control (process owner) |

This is the specification the system is validated against. Every requirement has an id, the reason it
exists, a risk class, and how it is verified. Nothing is tested that is not here, and nothing is here that
is not tested: VAL-005 proves both directions, and a test that fails is a requirement not met.

**Verification methods.** T = test (automated, in `webapi\tests`), W = walk (`Test-DmsSmoke.ps1`, against
the running installation), D = demonstration witnessed on the page, I = inspection (configuration or
document).

**Risk.** H = a controlled document could be wrongly released, wrongly visible or lost. M = a specified
function fails and work stops. L = inconvenience.

## 1. Identity and access

| Id | Requirement | Risk | Verify | OQ |
|---|---|---|---|---|
| SRS-010 | A user on the company network reaches the DMS with their Windows account and no login screen | M | W, D | OQ-01 |
| SRS-011 | The DMS identifies every caller before answering anything; an unidentified caller is refused | H | T, W | OQ-01 |
| SRS-012 | What a user may see and change is decided by their own AD groups through the file server's permissions, per folder and per file, on every request | H | T, D | OQ-03 |
| SRS-013 | A user needs no rights on the file server to read a document the DMS shows them; the DMS acts with its own account | H | D | OQ-16 |
| SRS-014 | No software is installed on a user's PC: the browser is the whole client | M | I | IQ-15 |
| SRS-015 | A super user (DMS_ADMINS) may act as another person and sees exactly that person's rights; the real account is kept and shown | H | W | OQ-02 |
| SRS-016 | A folder, a file or a document a user's groups do not allow is not listed, not searchable, not returned by the API and not openable by its path | H | T, D | OQ-03 |

## 2. The repository and its structure

| Id | Requirement | Risk | Verify | OQ |
|---|---|---|---|---|
| SRS-100 | The company's folder structure is defined in one place (the blueprint) and the DMS shows it in English and Hebrew | M | T, W | OQ-04 |
| SRS-101 | A blueprint folder cannot be renamed or deleted from the page; what people make inside it is theirs | H | T, W | OQ-04 |
| SRS-102 | A new customer, employee or candidate folder is cut from its skeleton: the skeleton's subfolders and the AD permissions on them, never its documents | H | T | OQ-05 |
| SRS-103 | Nothing is filed in a skeleton and no folder is made in one from the page | M | T, W | OQ-05 |
| SRS-104 | The workflow folders (Working, Submitted, Current_ReadOnly, Obsolete_ReadOnly) are made by the DMS beside a document, never by the blueprint and never by hand | H | T | OQ-24 |
| SRS-105 | Nothing can be added, renamed or deleted from the page inside a DMS-kept folder: a workflow folder, a skeleton, a customer's Shared folder or an HR archive | H | T | OQ-24 |
| SRS-106 | Each department has one KPIs folder, known to the DMS as such | L | W | OQ-27 |
| SRS-107 | A document can be found without knowing where it is, and a search returns only what the person may see | M | W | OQ-26 |

## 3. Registering a document

| Id | Requirement | Risk | Verify | OQ |
|---|---|---|---|---|
| SRS-200 | A file is registered with a document id, a title, a type and an area taken from the register's own choices | M | W | OQ-06 |
| SRS-201 | The initial revision is read from the file name when it carries one (v21, V01, Rev-3), and is 01 otherwise; the DMS shows what it read before registering | M | T, D | OQ-06 |
| SRS-202 | A document id is unique and never reused | H | T | OQ-06 |
| SRS-203 | A file is registered only where the user's AD rights allow writing | H | W | OQ-23 |
| SRS-204 | A document that is not controlled can be saved without a workflow and is then marked as such | M | W | OQ-15 |

## 4. The approval workflow

| Id | Requirement | Risk | Verify | OQ |
|---|---|---|---|---|
| SRS-300 | On submission the file moves to Submitted and becomes read only on the file server | H | W | OQ-07 |
| SRS-301 | The approvers are those chosen at submission, or - when none are chosen - the active Approver Matrix rule for that document type | H | T, W | OQ-07 |
| SRS-302 | Stage 1 completes only when every mandatory approver has answered; stage 2 is the final approver | H | T, W | OQ-08 |
| SRS-303 | An approver who may not see the document cannot be chosen | H | W | OQ-07 |
| SRS-304 | Nobody approves their own document, and nobody answers for an approver the document is not waiting on | H | W, D | OQ-10 |
| SRS-305 | A rejection requires a written reason, collects the remarks of the cycle and returns the document to its owner | H | T, D | OQ-09 |
| SRS-306 | The owner may withdraw a submission; the file returns to Working, writable, under the same name | M | W | OQ-09 |
| SRS-307 | A waiting approval can be delegated for a configured number of working days and returns afterwards; recorded in Delegations and the audit | M | W | OQ-12 |
| SRS-308 | An approver edits the document in the SharePoint copy with their own Microsoft account, needing no rights on the file server | H | D | OQ-16 |
| SRS-309 | A document changed while it was being approved cannot be approved as it stands: it returns to its owner and the change is recorded | H | T | OQ-11 |
| SRS-310 | Every decision records the approver, the time, the stage, the comment and the SHA-256 of the file the decision was made on | H | T, D | OQ-08, OQ-20 |
| SRS-311 | Each step writes a notification row; mail and Teams are delivered from it | M | D | OQ-21 |
| SRS-312 | The owner sees every document of theirs and where it stands; an approver sees what waits for them | M | W | OQ-25 |

## 5. Release, revisions and retention

| Id | Requirement | Risk | Verify | OQ |
|---|---|---|---|---|
| SRS-400 | An approved document is released into Current_ReadOnly beside its folder and is read only on the file server | H | T, W | OQ-13 |
| SRS-401 | A released file that lost its read-only flag gets it back on the next pass | H | W | OQ-13 |
| SRS-402 | A new revision starts from the revision in force, which stays current until the new one is released | H | W | OQ-14 |
| SRS-403 | On release the revision it replaces moves to Obsolete_ReadOnly beside it and stays readable | H | T, W | OQ-14 |
| SRS-404 | Exactly one revision of a document is in force at a time | H | T | OQ-14 |
| SRS-405 | A document is never deleted by the DMS: it is superseded or archived. The one exception is a rejected candidate's folder, after the retention period HR set, and each deletion is recorded | H | T | OQ-24 |
| SRS-406 | An employee file is moved to the archive when the person leaves, read only, and comes back whole on a rehire | M | T | OQ-05 |

## 6. Sharing outside the company

| Id | Requirement | Risk | Verify | OQ |
|---|---|---|---|---|
| SRS-500 | Only a released revision is shared outside the company, view only | H | W | OQ-18 |
| SRS-501 | A share goes to a folder of the customers list; an address that belongs to no customer goes to the Other folder | H | T, W | OQ-19 |
| SRS-502 | Every share is written to the share log and the audit; the log is the DMS's own and cannot be edited from the page | H | W | OQ-18 |
| SRS-503 | Shared files are removed from the exchange site after the configured number of days | M | T | OQ-18 |

## 7. The record

| Id | Requirement | Risk | Verify | OQ |
|---|---|---|---|---|
| SRS-600 | Every action - created, submitted, approved, rejected, delegated, released, permission changed, shared, deleted - is one audit row with actor, time, from/to state and details | H | T, D | OQ-20 |
| SRS-601 | The audit is append-only from the application: nothing in it is edited or removed by the DMS | H | I | OQ-20 |
| SRS-602 | A document can account for itself: its whole history is answerable from the DMS | H | W | OQ-20 |
| SRS-603 | The register and the file server agree: every record points at a file that exists, and the DMS corrects a record whose file it moved | H | T | OQ-13 |

## 8. What the AI reads

| Id | Requirement | Risk | Verify | OQ |
|---|---|---|---|---|
| SRS-700 | A Markdown rendering is written beside every released document, at the moment it is released | M | T, W | OQ-17 |
| SRS-701 | Word, Excel, PowerPoint, PDF, plain text and a scanned PDF (by OCR) are converted; a file with no readable text gets a card that says so | M | T | OQ-17 |
| SRS-702 | Two documents of the same base name in one folder keep a Markdown each | M | T, W | OQ-17 |
| SRS-703 | Each Markdown names the document, its revision and the file it was written for | M | W | OQ-17 |
| SRS-704 | The AI is served from Current_ReadOnly only: never a draft, never an obsolete revision | H | T | OQ-17, PQ-08 |
| SRS-705 | What the AI may read for a person is what that person's AD groups allow | H | T | OQ-22 |

## 9. The machine API

| Id | Requirement | Risk | Verify | OQ |
|---|---|---|---|---|
| SRS-800 | A machine caller is identified by a key; a call without one is refused | H | T | OQ-22 |
| SRS-801 | A key answers only within its scopes | H | T | OQ-22 |
| SRS-802 | A key acts as an AD account, and every answer is filtered by that account's own rights - never as an administrator | H | T | OQ-22 |
| SRS-803 | The API describes itself (OpenAPI), and the published reference matches the running build | L | T, W | OQ-22 |
| SRS-804 | Every machine call is logged with the caller's name | M | I | OQ-22 |

## 10. Operation

| Id | Requirement | Risk | Verify | OQ |
|---|---|---|---|---|
| SRS-900 | The DMS says which build and which software revision it is running, and whether that is the validated one | M | T | IQ-06 |
| SRS-901 | A restart loses no work: a document waiting for approval is intact afterwards | H | D | OQ-28 |
| SRS-902 | Opening a folder, Approvals and My workflows answer in under 5 seconds with production data | M | W | PQ-11 |
| SRS-903 | The DMS writes a log that says what it did and what failed | M | I | IQ-17 |
| SRS-904 | Configuration is held in one place, and no secret is written to a log, a report or an answer | H | I | IQ-10 |
| SRS-905 | The upkeep pass moves files to where the register says they belong, and reports what it moved | M | W | OQ-27 |

## 11. Not requirements of this system

- Electronic signatures under 21 CFR Part 11. Approvals are authenticated AD identities recorded in the
  audit; if Part 11 becomes a requirement, this SRS is revised first.
- Backup and restore of the file server and SharePoint: the platform's, verified at IQ-16.
- The content of a document: the DMS controls documents, it does not judge them.
