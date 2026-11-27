# VAL-005 Requirements Traceability Matrix

| | |
|---|---|
| Software revision | 01 - the whole validation set carries one version (`validation.json`) |

Generated from SRS-001 and VAL-003 by `webapi\dms_api\traceability.py` - never written by hand, so it
cannot drift from them. A test in the suite fails if it is out of date, if a requirement has no step, or
if a step has no requirement.

Verification: T = automated test, W = the end-to-end walk, D = demonstration witnessed on the page,
I = inspection. Risk: H / M / L.

## 1. Every requirement to the step that proves it

| Requirement | What it states | Risk | Verify | Step | Evidence |
|---|---|---|---|---|---|
| SRS-010 | A user on the company network reaches the DMS with their Windows account and no login screen | M | W, D | OQ-01 | OQ-01: REQ-P03, witnessed |
| SRS-011 | The DMS identifies every caller before answering anything; an unidentified caller is refused | H | T, W | OQ-01 | OQ-01: REQ-P03, witnessed |
| SRS-012 | What a user may see and change is decided by their own AD groups through the file server's permissions, per folder and per file, on every request | H | T, D | OQ-03 | OQ-03: REQ-P12, witnessed |
| SRS-013 | A user needs no rights on the file server to read a document the DMS shows them; the DMS acts with its own account | H | D | OQ-16 | OQ-16: REQ-P09, REQ-P11, witnessed |
| SRS-014 | No software is installed on a user's PC: the browser is the whole client | M | I | IQ-15 | IQ-15 |
| SRS-015 | A super user (DMS_ADMINS) may act as another person and sees exactly that person's rights; the real account is kept and shown | H | W | OQ-02 | OQ-02: REQ-P31 |
| SRS-016 | A folder, a file or a document a user's groups do not allow is not listed, not searchable, not returned by the API and not openable by its path | H | T, D | OQ-03 | OQ-03: REQ-P12, witnessed |
| SRS-100 | The company's folder structure is defined in one place (the blueprint) and the DMS shows it in English and Hebrew | M | T, W | OQ-04 | OQ-04: REQ-P29, REQ-P02, automated |
| SRS-101 | A blueprint folder cannot be renamed or deleted from the page; what people make inside it is theirs | H | T, W | OQ-04 | OQ-04: REQ-P29, REQ-P02, automated |
| SRS-102 | A new customer, employee or candidate folder is cut from its skeleton: the skeleton's subfolders and the AD permissions on them, never its documents | H | T | OQ-05 | OQ-05: REQ-P93, automated |
| SRS-103 | Nothing is filed in a skeleton and no folder is made in one from the page | M | T, W | OQ-05 | OQ-05: REQ-P93, automated |
| SRS-104 | The workflow folders (Working, Submitted, Current_ReadOnly, Obsolete_ReadOnly) are made by the DMS beside a document, never by the blueprint and never by hand | H | T | OQ-24 | OQ-24: automated |
| SRS-105 | Nothing can be added, renamed or deleted from the page inside a DMS-kept folder: a workflow folder, a skeleton, a customer's Shared folder or an HR archive | H | T | OQ-24 | OQ-24: automated |
| SRS-106 | Each department has one KPIs folder, known to the DMS as such | L | W | OQ-27 | OQ-27: REQ-P14, REQ-P15 |
| SRS-107 | A document can be found without knowing where it is, and a search returns only what the person may see | M | W | OQ-26 | OQ-26: REQ-P87 |
| SRS-200 | A file is registered with a document id, a title, a type and an area taken from the register's own choices | M | W | OQ-06 | OQ-06: REQ-P88, REQ-P16, automated |
| SRS-201 | The initial revision is read from the file name when it carries one (v21, V01, Rev-3), and is 01 otherwise; the DMS shows what it read before registering | M | T, D | OQ-06 | OQ-06: REQ-P88, REQ-P16, automated |
| SRS-202 | A document id is unique and never reused | H | T | OQ-06 | OQ-06: REQ-P88, REQ-P16, automated |
| SRS-203 | A file is registered only where the user's AD rights allow writing | H | W | OQ-23 | OQ-23: REQ-P12, witnessed |
| SRS-204 | A document that is not controlled can be saved without a workflow and is then marked as such | M | W | OQ-15 | OQ-15: REQ-P49 |
| SRS-300 | On submission the file moves to Submitted and becomes read only on the file server | H | W | OQ-07 | OQ-07: REQ-P36, REQ-P52 |
| SRS-301 | The approvers are those chosen at submission, or - when none are chosen - the active Approver Matrix rule for that document type | H | T, W | OQ-07 | OQ-07: REQ-P36, REQ-P52 |
| SRS-302 | Stage 1 completes only when every mandatory approver has answered; stage 2 is the final approver | H | T, W | OQ-08 | OQ-08: REQ-P44 |
| SRS-303 | An approver who may not see the document cannot be chosen | H | W | OQ-07 | OQ-07: REQ-P36, REQ-P52 |
| SRS-304 | Nobody approves their own document, and nobody answers for an approver the document is not waiting on | H | W, D | OQ-10 | OQ-10: REQ-P54, witnessed |
| SRS-305 | A rejection requires a written reason, collects the remarks of the cycle and returns the document to its owner | H | T, D | OQ-09 | OQ-09: REQ-P47, witnessed |
| SRS-306 | The owner may withdraw a submission; the file returns to Working, writable, under the same name | M | W | OQ-09 | OQ-09: REQ-P47, witnessed |
| SRS-307 | A waiting approval can be delegated for a configured number of working days and returns afterwards; recorded in Delegations and the audit | M | W | OQ-12 | OQ-12: REQ-P50 |
| SRS-308 | An approver edits the document in the SharePoint copy with their own Microsoft account, needing no rights on the file server | H | D | OQ-16 | OQ-16: REQ-P09, REQ-P11, witnessed |
| SRS-309 | A document changed while it was being approved cannot be approved as it stands: it returns to its owner and the change is recorded | H | T | OQ-11 | OQ-11: automated |
| SRS-310 | Every decision records the approver, the time, the stage, the comment and the SHA-256 of the file the decision was made on | H | T, D | OQ-08, OQ-20 | OQ-08: REQ-P44; OQ-20: REQ-P59, witnessed |
| SRS-311 | Each step writes a notification row; mail and Teams are delivered from it | M | D | OQ-21 | OQ-21: witnessed |
| SRS-312 | The owner sees every document of theirs and where it stands; an approver sees what waits for them | M | W | OQ-25 | OQ-25: REQ-P56 |
| SRS-400 | An approved document is released into Current_ReadOnly beside its folder and is read only on the file server | H | T, W | OQ-13 | OQ-13: REQ-P23, automated |
| SRS-401 | A released file that lost its read-only flag gets it back on the next pass | H | W | OQ-13 | OQ-13: REQ-P23, automated |
| SRS-402 | A new revision starts from the revision in force, which stays current until the new one is released | H | W | OQ-14 | OQ-14: REQ-P48 |
| SRS-403 | On release the revision it replaces moves to Obsolete_ReadOnly beside it and stays readable | H | T, W | OQ-14 | OQ-14: REQ-P48 |
| SRS-404 | Exactly one revision of a document is in force at a time | H | T | OQ-14 | OQ-14: REQ-P48 |
| SRS-405 | A document is never deleted by the DMS: it is superseded or archived. The one exception is a rejected candidate's folder, after the retention period HR set, and each deletion is recorded | H | T | OQ-24 | OQ-24: automated |
| SRS-406 | An employee file is moved to the archive when the person leaves, read only, and comes back whole on a rehire | M | T | OQ-05 | OQ-05: REQ-P93, automated |
| SRS-500 | Only a released revision is shared outside the company, view only | H | W | OQ-18 | OQ-18: REQ-P72, REQ-P76 |
| SRS-501 | A share goes to a folder of the customers list; an address that belongs to no customer goes to the Other folder | H | T, W | OQ-19 | OQ-19: automated, witnessed |
| SRS-502 | Every share is written to the share log and the audit; the log is the DMS's own and cannot be edited from the page | H | W | OQ-18 | OQ-18: REQ-P72, REQ-P76 |
| SRS-503 | Shared files are removed from the exchange site after the configured number of days | M | T | OQ-18 | OQ-18: REQ-P72, REQ-P76 |
| SRS-600 | Every action - created, submitted, approved, rejected, delegated, released, permission changed, shared, deleted - is one audit row with actor, time, from/to state and details | H | T, D | OQ-20 | OQ-20: REQ-P59, witnessed |
| SRS-601 | The audit is append-only from the application: nothing in it is edited or removed by the DMS | H | I | OQ-20 | OQ-20: REQ-P59, witnessed |
| SRS-602 | A document can account for itself: its whole history is answerable from the DMS | H | W | OQ-20 | OQ-20: REQ-P59, witnessed |
| SRS-603 | The register and the file server agree: every record points at a file that exists, and the DMS corrects a record whose file it moved | H | T | OQ-13 | OQ-13: REQ-P23, automated |
| SRS-700 | A Markdown rendering is written beside every released document, at the moment it is released | M | T, W | OQ-17 | OQ-17: REQ-P38, REQ-P08, REQ-P95, REQ-P91, automated |
| SRS-701 | Word, Excel, PowerPoint, PDF, plain text and a scanned PDF (by OCR) are converted; a file with no readable text gets a card that says so | M | T | OQ-17 | OQ-17: REQ-P38, REQ-P08, REQ-P95, REQ-P91, automated |
| SRS-702 | Two documents of the same base name in one folder keep a Markdown each | M | T, W | OQ-17 | OQ-17: REQ-P38, REQ-P08, REQ-P95, REQ-P91, automated |
| SRS-703 | Each Markdown names the document, its revision and the file it was written for | M | W | OQ-17 | OQ-17: REQ-P38, REQ-P08, REQ-P95, REQ-P91, automated |
| SRS-704 | The AI is served from Current_ReadOnly only: never a draft, never an obsolete revision | H | T | OQ-17, PQ-08 | OQ-17: REQ-P38, REQ-P08, REQ-P95, REQ-P91, automated; PQ-08 |
| SRS-705 | What the AI may read for a person is what that person's AD groups allow | H | T | OQ-22 | OQ-22: REQ-P28, REQ-P39, automated |
| SRS-800 | A machine caller is identified by a key; a call without one is refused | H | T | OQ-22 | OQ-22: REQ-P28, REQ-P39, automated |
| SRS-801 | A key answers only within its scopes | H | T | OQ-22 | OQ-22: REQ-P28, REQ-P39, automated |
| SRS-802 | A key acts as an AD account, and every answer is filtered by that account's own rights - never as an administrator | H | T | OQ-22 | OQ-22: REQ-P28, REQ-P39, automated |
| SRS-803 | The API describes itself (OpenAPI), and the published reference matches the running build | L | T, W | OQ-22 | OQ-22: REQ-P28, REQ-P39, automated |
| SRS-804 | Every machine call is logged with the caller's name | M | I | OQ-22 | OQ-22: REQ-P28, REQ-P39, automated |
| SRS-900 | The DMS says which build and which software revision it is running, and whether that is the validated one | M | T | IQ-06 | IQ-06 |
| SRS-901 | A restart loses no work: a document waiting for approval is intact afterwards | H | D | OQ-28 | OQ-28: witnessed |
| SRS-902 | Opening a folder, Approvals and My workflows answer in under 5 seconds with production data | M | W | PQ-11 | PQ-11 |
| SRS-903 | The DMS writes a log that says what it did and what failed | M | I | IQ-17 | IQ-17 |
| SRS-904 | Configuration is held in one place, and no secret is written to a log, a report or an answer | H | I | IQ-10 | IQ-10 |
| SRS-905 | The upkeep pass moves files to where the register says they belong, and reports what it moved | M | W | OQ-27 | OQ-27: REQ-P14, REQ-P15 |

## 2. Every OQ step to the requirements behind it

| Step | Function | Requirements |
|---|---|---|
| OQ-01 | Sign-in | SRS-010, SRS-011 |
| OQ-02 | Acting as | SRS-015 |
| OQ-03 | Visibility follows AD | SRS-012, SRS-016 |
| OQ-04 | Blueprint structure | SRS-100, SRS-101 |
| OQ-05 | Customer / employee / candidate folders | SRS-102, SRS-103, SRS-406 |
| OQ-06 | Upload and register | SRS-200, SRS-201, SRS-202 |
| OQ-07 | Submit for approval | SRS-300, SRS-301, SRS-303 |
| OQ-08 | Approve, stage 1 and stage 2 | SRS-302, SRS-310 |
| OQ-09 | Return with remarks, and withdraw | SRS-305, SRS-306 |
| OQ-10 | Nobody answers for somebody else | SRS-304 |
| OQ-11 | Changed during approval | SRS-309 |
| OQ-12 | Delegation | SRS-307 |
| OQ-13 | Release | SRS-400, SRS-401, SRS-603 |
| OQ-14 | Revision | SRS-402, SRS-403, SRS-404 |
| OQ-15 | Copy as approved (no workflow) | SRS-204 |
| OQ-16 | Reading without rights on the file server | SRS-013, SRS-308 |
| OQ-17 | Markdown for the AI | SRS-700, SRS-701, SRS-702, SRS-703, SRS-704 |
| OQ-18 | Share with a customer | SRS-500, SRS-502, SRS-503 |
| OQ-19 | Share rules | SRS-501 |
| OQ-20 | Audit trail | SRS-310, SRS-600, SRS-601, SRS-602 |
| OQ-21 | Notifications | SRS-311 |
| OQ-22 | Machine API | SRS-705, SRS-800, SRS-801, SRS-802, SRS-803, SRS-804 |
| OQ-23 | Negative - permissions | SRS-203 |
| OQ-24 | Negative - DMS-kept folders | SRS-104, SRS-105, SRS-405 |
| OQ-25 | My workflows | SRS-312 |
| OQ-26 | Finding a document | SRS-107 |
| OQ-27 | The upkeep pass | SRS-106, SRS-905 |
| OQ-28 | Recovery | SRS-901 |

## 3. The walk's own requirement ids

The end-to-end walk prints one of these on every line it proves, so a line of its report is the evidence
for the step that cites it.

| Walk id | What the line proves |
|---|---|
| REQ-P02 | a folder can be made where AD allows it |
| REQ-P03 | the DMS knows who is calling, by AD |
| REQ-P08 | each Markdown names the file it was written for |
| REQ-P09 | a text file is read on the page itself |
| REQ-P11 | a link can be shared without naming the file server |
| REQ-P12 | the page knows what this person may do here |
| REQ-P14 | the upkeep pass runs and reports |
| REQ-P15 | the department's KPIs folder is known as one |
| REQ-P16 | the register's own document types are used, not words made up here |
| REQ-P23 | a released file that lost its read-only flag gets it back |
| REQ-P28 | the API describes itself |
| REQ-P29 | the company's structure is the blueprint, in both languages |
| REQ-P31 | Acting as is a super user seeing as somebody, and the real account is kept |
| REQ-P36 | the file moved to Submitted |
| REQ-P38 | its Markdown is beside it, with the revision it is |
| REQ-P39 | the RAG's list |
| REQ-P44 | the approver answers, and the decision is recorded |
| REQ-P47 | a submission can be taken back by its owner |
| REQ-P48 | the next revision starts from the one in force, which stays current |
| REQ-P49 | a file can be released without a workflow, straight to Current_ReadOnly |
| REQ-P50 | an approval is passed to somebody else for this cycle |
| REQ-P52 | an approver who may not see the document cannot be chosen |
| REQ-P54 | somebody who is not the approver cannot answer for them |
| REQ-P56 | the owner sees it in My workflows |
| REQ-P59 | the document can account for itself |
| REQ-P72 | a released revision is shared with somebody outside the company |
| REQ-P76 | the share log is the DMS's own: it is not edited from the page |
| REQ-P87 | it can be found without knowing where it is |
| REQ-P88 | a file is dropped into the folder, with AD asked for Modify |
| REQ-P91 | the DMS can say why, file by file |
| REQ-P93 | nothing is filed in the customer skeleton |
| REQ-P95 | a workbook released under the document's own name keeps a Markdown of its own |

## 4. Coverage

| | |
|---|---|
| Requirements in SRS-001 | 65 |
| Requirements with at least one step | 65 |
| OQ steps | 28 |
| OQ steps with at least one requirement | 28 |
| Walk requirement ids | 32 |
