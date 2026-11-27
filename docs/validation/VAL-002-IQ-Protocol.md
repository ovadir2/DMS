# VAL-002 IQ Protocol - Installation Qualification

| | |
|---|---|
| Software revision | 01 - the whole validation set carries one version (`validation.json`) |
| System | RH DMS, production server RHFS02, IIS site `DMS`, `https://dms.rh.tech` |
| Purpose | To show the DMS is installed and configured as specified before any function is tested |
| Executed by | | 
| Date | |
| Build under test (`/api/health` → `version`) | |

Run `.\scripts\Invoke-DmsIQ.ps1` on the server: it performs steps IQ-01 to IQ-16, writes the result of each
one with what it actually found, and leaves a report file to attach here. A step the script cannot judge is
marked **manual** below and is performed by the executor.

## Pre-requisites

- The server is in its production state (no debugging switches, no pilot data).
- The executor has local administrator rights on the server and is a DMS super user.
- `webapi\.env` holds the production settings. **Values of keys, certificates and passwords are never
  written into this report** - only whether the setting is present.

## Steps

| # | Step | Expected result | Found | P/F |
|---|---|---|---|---|
| IQ-01 | Application files are the released build | The working tree is a clean checkout of `main`; `git status` reports no modified file; the commit is recorded here | | |
| IQ-02 | Python runtime and packages | The virtual environment exists under `webapi\.venv`; `pip check` reports no broken requirement | | |
| IQ-03 | IIS site exists and is started | Site `DMS` is **Started**, physical path `C:\DMS-Pilot\app\webapi`, its application pool is **Started** | | |
| IQ-04 | HTTPS binding and certificate | Binding on 443 for `dms.rh.tech` with SNI; the certificate covers that name, is in date, and its chain resolves | | |
| IQ-05 | Windows Authentication | Windows Authentication **enabled**, Anonymous **disabled**, `forwardWindowsAuthToken` **true** in `web.config` | | |
| IQ-06 | The service answers | `GET /api/health` returns `status: ok`, the build version, and `rootReachable: true` | | |
| IQ-07 | Repository root | `DMS_REPOSITORY_ROOT` points at the production repository; the path exists and the DMS account can write in it | | |
| IQ-08 | Folder tree matches the blueprint | Every line of `scripts\blueprint-folders.txt` that is not a `<placeholder>` exists on the file server | | |
| IQ-09 | Released folders are protected | `Current_ReadOnly` and `Obsolete_ReadOnly` folders carry the read-only protection (`Protect-DmsReadOnly.ps1` has been run) | | |
| IQ-10 | Settings present | Every setting the production configuration requires is present in `webapi\.env` (names only, no values): site, repository root, auth mode, approvals mode, review library, admins | | |
| IQ-11 | SharePoint lists | `GET /api/diagnostics/sharepoint` shows all six lists existing, with "you may add" true for the DMS account | | |
| IQ-12 | SharePoint certificate validity | `certDaysLeft` is greater than 30 | | |
| IQ-13 | Approver Matrix populated | At least one active rule exists, and every document type in use has one (`GET /api/options`, `GET /api/approver-rule`) | | |
| IQ-14 | AD groups and permissions (manual) | The groups named in `scripts\dms-ad-groups.csv` exist, and the NTFS permissions on the repository are granted to groups, not to people. Evidence: `Get-DmsAccess.ps1` output attached | | |
| IQ-15 | No user software (manual) | Nothing was installed on any approver's PC; the system is used through the browser only | | |
| IQ-16 | Backup (manual) | The repository and the SharePoint site are covered by the company backup; the restore point and owner are recorded | | |

## Deviations

| # | Step | What happened | Class | Disposition | Closed (date, by) |
|---|---|---|---|---|---|
| | | | | | |

## Conclusion

The installation **meets / does not meet** the specified configuration (delete one).

| Role | Name | Signature | Date |
|---|---|---|---|
| Executed by | | | |
| Reviewed by (Document Control) | | | |
| Approved by (Quality) | | | |
