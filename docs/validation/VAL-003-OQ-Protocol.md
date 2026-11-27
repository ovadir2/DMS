# VAL-003 OQ Protocol - Operational Qualification

| | |
|---|---|
| System | RH DMS, production installation |
| Purpose | To show each specified function behaves as specified, including what it must refuse |
| Pre-requisite | VAL-002 (IQ) executed and signed |
| Executed by | |
| Date | |
| Build under test | |

Two kinds of evidence are collected, and both are attached to the report:

- **Automated.** `webapi\tests` (250 tests) run against this build, and `scripts\Test-DmsSmoke.ps1`, the
  end-to-end walk against the running installation with real Word, Excel, PDF and text files. The walk
  prints a requirement id for every step it proves; those ids appear in the table below.
- **Witnessed.** The steps marked **witnessed** are performed on the page by the executor with Document
  Control watching, because what is being judged is what a person sees.

Run `.\scripts\Invoke-DmsOQ.ps1`: it runs both, maps each result to the steps below, and writes the report.
The walk uses the DMS test accounts only, so no real approver is sent a test document.

## Steps

| # | Function | Expected result | Evidence | P/F |
|---|---|---|---|---|
| OQ-01 | Sign-in | A user reaches the page with no login screen and is identified by their AD account | REQ-P03, witnessed | |
| OQ-02 | Acting as | A super user may see the DMS as another person, with that person's rights; the real account is kept and shown | REQ-P31 | |
| OQ-03 | Visibility follows AD | A folder a person's AD groups do not allow is not listed, not searchable and not openable - including by direct path. The page says what this person may do here | REQ-P12, witnessed | |
| OQ-04 | Blueprint structure | The company's folders are the structure, in both languages; a folder can be made where AD allows it, and a blueprint folder cannot be renamed or deleted from the page | REQ-P29, REQ-P02, automated | |
| OQ-05 | Customer / employee / candidate folders | Made from the matching skeleton: its folders and their AD permissions, never its documents; nothing is filed in a skeleton | REQ-P93, automated | |
| OQ-06 | Upload and register | A file dropped in a folder is registered with a document id, the register's own type and area, and a revision read from the file name when it carries one | REQ-P88, REQ-P16, automated | |
| OQ-07 | Submit for approval | The document moves to Submitted, read only, and reaches exactly the chosen approvers; an approver who may not see it cannot be chosen; with none chosen the Approver Matrix decides | REQ-P36, REQ-P52 | |
| OQ-08 | Approve, stage 1 and stage 2 | Each mandatory approver answers, then the final approver; the decision is recorded with the file's SHA-256 | REQ-P44 | |
| OQ-09 | Return with remarks, and withdraw | A rejection requires a reason and returns the document with the remarks of the cycle; the owner can also take a submission back | REQ-P47, witnessed | |
| OQ-10 | Nobody answers for somebody else | The DMS refuses an approval by the owner, and by anybody the document does not wait for | REQ-P54, witnessed | |
| OQ-11 | Changed during approval | A document edited in the SharePoint copy cannot be approved as it stands: it goes back to its owner and the change is in the audit | automated | |
| OQ-12 | Delegation | A waiting approval can be passed on for the configured working days and returns afterwards; recorded in Delegations and the audit | REQ-P50 | |
| OQ-13 | Release | The approved revision lands in `Current_ReadOnly`, read only on the file server; a released file that lost the flag gets it back | REQ-P23, automated | |
| OQ-14 | Revision | The next revision starts from the one in force, which stays current until the new one is released; the superseded file moves to `Obsolete_ReadOnly` | REQ-P48 | |
| OQ-15 | Copy as approved (no workflow) | A file can be released straight to `Current_ReadOnly`, registered as approved, with no workflow offered for it afterwards | REQ-P49 | |
| OQ-16 | Reading without rights on the file server | A text file is read on the page itself; a document opens View-only; a link can be shared without naming the file server | REQ-P09, REQ-P11, witnessed | |
| OQ-17 | Markdown for the AI | Word, Excel, PowerPoint, PDF, scanned PDF (OCR) and text each produce a Markdown beside the released file, naming the file and the revision; two documents of the same name keep one each; a file with no text says why | REQ-P38, REQ-P08, REQ-P95, REQ-P91, automated | |
| OQ-18 | Share with a customer | A released revision is shared outside the company view-only, and the share log is the DMS's own: it cannot be edited from the page | REQ-P72, REQ-P76 | |
| OQ-19 | Share rules | A share is refused to a folder that is not in the customers list; `Other_Share` accepts an address outside the company | automated, witnessed | |
| OQ-20 | Audit trail | The document can account for itself: every action with actor, time, from/to state and details, and the SHA-256 the decision was made on | REQ-P59, witnessed | |
| OQ-21 | Notifications | Each step writes a row to DMS Notifications; the flow delivers it by mail and Teams | witnessed | |
| OQ-22 | Machine API | A call without a key is refused; the API describes itself; a key answers only within its scopes and only what its AD account may see | REQ-P28, REQ-P39, automated | |
| OQ-23 | Negative - permissions | A user with Read only cannot save, rename, delete or release there, and the refusal says why | REQ-P12, witnessed | |
| OQ-24 | Negative - DMS-kept folders | Nothing can be added, renamed or deleted inside `Submitted`, `Current_ReadOnly`, `Obsolete_ReadOnly`, a skeleton, a customer's Shared folder or an HR archive | automated | |
| OQ-25 | My workflows | The owner sees their documents and where each one stands, and what is waiting for them | REQ-P56 | |
| OQ-26 | Finding a document | A document is found without knowing where it is, within what the person may see | REQ-P87 | |
| OQ-27 | The upkeep pass | The file service runs and reports what it moved; a KPIs folder is known as one | REQ-P14, REQ-P15 | |
| OQ-28 | Recovery | The DMS is restarted (`Restart-Dms.ps1`) while a document is waiting for approval; afterwards the approval is intact and can be completed | witnessed | |

## Deviations

| # | Step | What happened | Class | Disposition | Closed (date, by) |
|---|---|---|---|---|---|
| | | | | | |

## Conclusion

The system **performs / does not perform** its specified functions (delete one).

| Role | Name | Signature | Date |
|---|---|---|---|
| Executed by | | | |
| Witnessed by (Document Control) | | | |
| Approved by (Quality) | | | |
