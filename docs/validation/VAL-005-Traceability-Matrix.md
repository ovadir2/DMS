# VAL-005 Requirements Traceability Matrix

Every requirement the end-to-end walk proves, the OQ step that covers it, and where the evidence is. The
walk (`scripts\\Test-DmsSmoke.ps1`) prints the requirement id on each line it proves, so a line of the walk
report is the evidence for the row.

## 1. Walk requirements to OQ steps

| Requirement | What it states | OQ step | Evidence |
|---|---|---|---|
| REQ-P02 | a folder can be made where AD allows it | OQ-04 | Walk report line `REQ-P02`, OQ report |
| REQ-P03 | the DMS knows who is calling, by AD | OQ-01 | Walk report line `REQ-P03`, OQ report |
| REQ-P08 | each Markdown names the file it was written for | OQ-17 | Walk report line `REQ-P08`, OQ report |
| REQ-P09 | a text file is read on the page itself | OQ-16 | Walk report line `REQ-P09`, OQ report |
| REQ-P11 | a link can be shared without naming the file server | OQ-16 | Walk report line `REQ-P11`, OQ report |
| REQ-P12 | the page knows what this person may do here | OQ-03, OQ-23 | Walk report line `REQ-P12`, OQ report |
| REQ-P14 | the upkeep pass runs and reports | OQ-27 | Walk report line `REQ-P14`, OQ report |
| REQ-P15 | the department's KPIs folder is known as one | OQ-27 | Walk report line `REQ-P15`, OQ report |
| REQ-P16 | the register's own document types are used, not words made up here | OQ-06 | Walk report line `REQ-P16`, OQ report |
| REQ-P23 | a released file that lost its read-only flag gets it back | OQ-13 | Walk report line `REQ-P23`, OQ report |
| REQ-P28 | the API describes itself | OQ-22 | Walk report line `REQ-P28`, OQ report |
| REQ-P29 | the company's structure is the blueprint, in both languages | OQ-04 | Walk report line `REQ-P29`, OQ report |
| REQ-P31 | Acting as is a super user seeing as somebody, and the real account is kept | OQ-02 | Walk report line `REQ-P31`, OQ report |
| REQ-P36 | the file moved to Submitted | OQ-07 | Walk report line `REQ-P36`, OQ report |
| REQ-P38 | its Markdown is beside it, with the revision it is | OQ-17 | Walk report line `REQ-P38`, OQ report |
| REQ-P39 | the RAG's list | OQ-22 | Walk report line `REQ-P39`, OQ report |
| REQ-P44 | the approver answers, and the decision is recorded | OQ-08 | Walk report line `REQ-P44`, OQ report |
| REQ-P47 | a submission can be taken back by its owner | OQ-09 | Walk report line `REQ-P47`, OQ report |
| REQ-P48 | the next revision starts from the one in force, which stays current | OQ-14 | Walk report line `REQ-P48`, OQ report |
| REQ-P49 | a file can be released without a workflow, straight to Current_ReadOnly | OQ-15 | Walk report line `REQ-P49`, OQ report |
| REQ-P50 | an approval is passed to somebody else for this cycle | OQ-12 | Walk report line `REQ-P50`, OQ report |
| REQ-P52 | an approver who may not see the document cannot be chosen | OQ-07 | Walk report line `REQ-P52`, OQ report |
| REQ-P54 | somebody who is not the approver cannot answer for them | OQ-10 | Walk report line `REQ-P54`, OQ report |
| REQ-P56 | the owner sees it in My workflows | OQ-25 | Walk report line `REQ-P56`, OQ report |
| REQ-P59 | the document can account for itself | OQ-20 | Walk report line `REQ-P59`, OQ report |
| REQ-P72 | a released revision is shared with somebody outside the company | OQ-18 | Walk report line `REQ-P72`, OQ report |
| REQ-P76 | the share log is the DMS's own: it is not edited from the page | OQ-18 | Walk report line `REQ-P76`, OQ report |
| REQ-P87 | it can be found without knowing where it is | OQ-26 | Walk report line `REQ-P87`, OQ report |
| REQ-P88 | a file is dropped into the folder, with AD asked for Modify | OQ-06 | Walk report line `REQ-P88`, OQ report |
| REQ-P91 | the DMS can say why, file by file | OQ-17 | Walk report line `REQ-P91`, OQ report |
| REQ-P93 | nothing is filed in the customer skeleton | OQ-05 | Walk report line `REQ-P93`, OQ report |
| REQ-P95 | a workbook released under the document's own name keeps a Markdown of its own | OQ-17 | Walk report line `REQ-P95`, OQ report |

## 2. OQ steps with no walk requirement

These are witnessed on the page, or covered by the automated suite, because what they judge is what a
person sees or what the code refuses.

| OQ step | Covered by |
|---|---|
| OQ-09 (return with remarks) | Automated suite + witnessed on the page |
| OQ-11 (changed during approval) | Automated suite |
| OQ-19 (share rules) | Automated suite + witnessed |
| OQ-21 (notifications) | Witnessed: the mail and the Teams message arrive |
| OQ-24 (DMS-kept folders refuse changes) | Automated suite |
| OQ-28 (recovery after a restart) | Witnessed |

## 3. Specifications to qualifications

| Specification | Qualification |
|---|---|
| `docs/01-Architecture-and-Data-Model.md` | IQ-08, IQ-11, OQ-04, OQ-20 |
| `docs/02-Security-and-Permissions.md` | IQ-05, IQ-14, OQ-01 to OQ-03, OQ-10, OQ-16, OQ-23, OQ-24 |
| `docs/03-Installation-and-Settings.md` | IQ-01 to IQ-13 |
| `docs/04-Using-the-DMS.md` | OQ-04 to OQ-06, OQ-13 to OQ-18, OQ-25 to OQ-27 |
| `docs/05-Approval-Flow.md` | OQ-07 to OQ-12, OQ-20, OQ-21 |
| `docs/09-Machine-API.md` | OQ-22, PQ-09 |

## 4. Coverage

Every requirement in section 1 is covered by at least one OQ step. A requirement whose step is `-` is a gap
and must be closed before the OQ report is signed.
