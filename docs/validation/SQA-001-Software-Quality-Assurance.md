# SQA-001 Software Quality Assurance Plan and Test Report

| | |
|---|---|
| System | RH DMS |
| Stage | Development verification - **before** IQ |
| Software revision | 01 - the whole validation set carries one version (`validation.json`) |
| Owner | IT (system owner) |

Qualification starts with an installed system. SQA is what happens before that: the evidence that the code
being installed was written, reviewed and tested to a standard, and that it meets SRS-001. IQ then shows
that this build is installed correctly, OQ that it behaves as specified, PQ that it does the work.

Order of the validation: **SRS-001 → SQA-001 → VAL-002 (IQ) → VAL-003 (OQ) → VAL-004 (PQ) → VAL-006**.

## 1. How the software is built

| | |
|---|---|
| Source of truth | `github.com/ovadir2/DMS`, branch `main`. Nothing reaches the server that is not committed there |
| Language and frameworks | Python 3.11+, FastAPI, served by uvicorn behind IIS (HttpPlatformHandler) |
| Change unit | One commit with its reason in the message; the server deploys by `git pull` and `Restart-Dms.ps1` |
| Build identity | The running commit is answered by `/api/health`, with the software revision from `docs/validation/validation.json` |
| Configuration | `webapi\.env` on the server, never in the repository. No secret is committed, logged or returned by an endpoint |

## 2. Practices the code is held to

| # | Practice | Evidence |
|---|---|---|
| SQA-01 | Every change is reviewed before it is merged - by the system owner, or by a second pair of eyes for anything touching approvals, permissions or release | The commit history and its messages |
| SQA-02 | Every change ships with its tests; a defect is fixed with the test that would have caught it | `webapi\tests` grows with each change |
| SQA-03 | The whole suite runs before every deployment, and must be green | The SQA report below |
| SQA-04 | The generated documents cannot drift from the code: the API reference, the Swagger file, the blueprint folder list and the traceability matrix are regenerated and compared by tests that fail when they are behind | `test_swagger_is_four_calls_and_nothing_else`, `test_blueprint_folder_list_matches_the_tree_script_file`, `test_the_traceability_matrix_is_generated_and_complete` |
| SQA-05 | The scripts are linted by tests of their own - a function named after a PowerShell alias, a `$var:` inside a string, a line that silently continues a string | `test_no_script_names_a_function_after_a_powershell_alias` and the two beside it |
| SQA-06 | Nothing in the code decides what a user may see: that is asked of Windows, per path, per request | `security.py`, and the permission tests |
| SQA-07 | A failure never passes silently: an endpoint answers with the reason, and the DMS logs what it could not do | The error-path tests |

## 3. What the tests cover

| Level | What it is | Where |
|---|---|---|
| Unit | Readers, Markdown conversion, revision parsing, the skeleton, the blueprint, paths and permissions logic | `webapi\tests\test_api.py`, `test_sharepoint.py`, `test_ai.py` |
| Integration | Every endpoint against a register in memory and a temporary repository on disk: register, submit, approve, reject, delegate, release, revise, share, the machine API | `webapi\tests\test_api.py` |
| System | The end-to-end walk against the running installation, with real Word, Excel, PDF and text files | `scripts\Test-DmsSmoke.ps1` (executed at OQ) |
| Static | The drift and lint tests above; `pip check` for the dependency set | `webapi\tests`, IQ-02 |

The suite runs offline: SharePoint is a memory implementation, the repository is a temporary folder, and
no test needs AD, the network or the production server. That is what makes it runnable before every
deployment, and what makes IQ and OQ meaningful - they test the things the suite cannot.

## 4. Requirements coverage

Every requirement of SRS-001 verified by **T** (automated test) is covered here; VAL-005 lists each one
with its step. The requirements verified by W, D or I are covered at OQ, PQ or by inspection, because they
need the installation, a person, or the configuration.

## 5. Defects

| Class | Meaning | Exit rule |
|---|---|---|
| Critical | Wrong release, wrong visibility, a lost document, a missing audit row | None open. The build is not qualified |
| Major | A specified function fails; a workaround exists | None open without Quality's written acceptance |
| Minor | Cosmetic or convenience | Listed, with the revision that will carry the fix |

## 6. Exit criteria into IQ

1. The whole suite passes on the build to be installed.
2. The drift tests pass: the published reference, the Swagger file, the blueprint list and the traceability matrix match the code.
3. Every SRS requirement is traced to a step (VAL-005 shows no gap in either direction).
4. No critical or major defect is open.
5. The build is committed, pushed and identified: commit and software revision recorded below.

---

# SQA test report

Produced by `.\scripts\Invoke-DmsSQA.ps1`, which runs the suite and the checks and fills this in.

| | |
|---|---|
| Executed | |
| By | |
| Commit under test | |
| Software revision | |

| # | Check | Expected | Found | P/F |
|---|---|---|---|---|
| SQA-R1 | The working tree is the committed build | clean, and pushed | | |
| SQA-R2 | The automated suite | all pass, none skipped unexpectedly | | |
| SQA-R3 | Dependency set | `pip check` clean | | |
| SQA-R4 | Drift tests | reference, Swagger, blueprint list and matrix all current | | |
| SQA-R5 | Script lint tests | pass | | |
| SQA-R6 | Traceability | no requirement without a step, no step without a requirement | | |
| SQA-R7 | Secrets | no key, token or password in the repository | | |

## Defects found and their disposition

| # | Defect | Class | Fixed in | Re-tested |
|---|---|---|---|---|
| | | | | |

## Conclusion

The build **is / is not** fit to be installed for qualification (delete one).

| Role | Name | Signature | Date |
|---|---|---|---|
| Prepared by (System owner) | | | |
| Reviewed by (Document Control) | | | |
| Approved by (Quality) | | | |
