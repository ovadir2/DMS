# Go-live: from the pilot to production

The pilot runs as `DMS-Pilot` on RHFS02, against the `-TEST` sites, with test documents in the register.
Going live is not a rename: it is a clean environment, a repository registered from what is really on the
file server, and a package that no longer carries the pilot with it.

This is the checklist. Nothing here is done automatically - each step says what to run and how to see that it
worked. Do them in order: the names move first, then the data, then the package.

---

## 0. Before the day

- [ ] Decide the production names and write them here once, so every step below reads from one place.

  | | Pilot | Production |
  | --- | --- | --- |
  | IIS site and pool | `DMS-Pilot` | `DMS` |
  | Folder | `C:\DMS-Pilot` | `C:\DMS` |
  | Address | `dms-pilot.rh.tech` | `dms.rh.tech` |
  | Repository root | `E:\Shares` (pilot subset) | `E:\Shares` |
  | Control site | `DocumentControl-TEST` | `DocumentControl` |
  | Exchange site | `LargeFileExchange-TEST` | `LargeFileExchange` |
  | Review library | `Approvals` | `Approvals` |
  | Reading library | `Views` | `Views` |

- [ ] A full backup of `E:\Shares` and an export of the SharePoint lists (register, Control Audit, approval
      decisions). Everything below is reversible only from these.
- [ ] Decide what happens to the pilot: kept read-only for a month beside production, or removed. Keeping it
      means two IIS sites and two certificates, and users will find both - say which address is the real one.

## 1. The production environment

- [ ] Provision the production sites with `scripts/Provision-DMS.ps1` (no `-TEST` suffix), including the
      Approver Matrix and the UI labels.
- [ ] Create the `Views` library on the production control site by hand - an app-only account cannot create a
      list (`403 UnauthorizedAccessException`), which is why it had to be made by hand in the pilot too.
      Remove every standing permission from it: it must hold nothing but the copies the DMS puts there.
- [ ] Grant the DMS account `Sites.Selected` on both production sites, for SharePoint **and** for Graph -
      they are two separate grants and the second is the one that is forgotten (`scripts/Grant-DmsSitePermission.ps1`).
- [ ] A certificate of its own for production (`scripts/new_dms_cert.py`), uploaded to the Entra app. Do not
      carry the pilot's certificate over: when it expires, both environments stop at once.
- [ ] `C:\DMS\app` from `main`, its own `.venv`, its own `webapi\.env`. Remember that the **first** occurrence
      of a key in `.env` wins - a leftover line above is the usual reason a setting "does not take".
- [ ] IIS site `DMS` with the production certificate and Windows Authentication, and
      `.\scripts\Restart-Dms.ps1` to bring it up. `iisreset` is not the way: it leaves the site stopped.

## 2. The pilot's data stays behind

- [ ] Nothing from the pilot register is carried over. The production register is built by **first loading**,
      which registers what is really on the file server - that is the point of it.
- [ ] On the file server, remove what the pilot created: `DMS_ACCESS_CANARY_*`, the test drafts, and
      `04_Workflow_System\Recycle\*` from the pilot days. `04_Workflow_System\CheckedOut.json` and
      `OpenLinks.json` must start empty.
- [ ] Empty the `Approvals` and `Views` libraries on the production site before anyone uses them.
- [ ] A file that is in `Current_ReadOnly` and is not registered is not approved - it is a file in a folder.
      List them before first loading and decide for each: register it, or move it out.
- [ ] Run `.\scripts\New-DmsMarkdown.ps1 -Write` after first loading, so every released document has its
      Markdown for the AI from day one.

## 3. First loading

- [ ] First loading is for super users only, and it is the one irreversible step of the day: it writes a
      record for every document it finds. Run it on a copy first if you can.
- [ ] Check the type and area it assigns against the blueprint on a folder or two before letting it run over
      the whole tree.
- [ ] After it: `scripts\Compare-DmsTree.ps1` for each top folder, so the DMS and the disk agree.

## 4. The package itself: production only

The repository still carries the pilot inside it. Before production this has to be separated, so that what is
installed is the product and the pilot is history rather than part of the build.

- [ ] **Out of the shipped package**: everything that exists to try the system rather than to run it -
      `Start-DmsPlayground.ps1` and the playground register (`dms_api/memory.py`), `DMS_SHAREPOINT=memory`,
      the "Acting as" list (`DMS_DEV_USERS`), `DMS_AUTH_MODE=dev` and `DMS_DEV_USER`,
      `scripts/New-DmsPilotFlowPackage.ps1`, and `docs/08-Pilot-Process.md`. They stay in the repository (the
      tests use them), but they must not be installed, and the production `.env` must not mention them.
      A production `.env` that carries `DMS_AUTH_MODE=dev` is a system with no authentication at all.
- [ ] **A builder that produces the installed set**, so "what is on the server" stops being a copy of the
      working tree: the package, `webapi\`, `scripts\` without the pilot scripts, `assets\`, `docs\` as
      shipped, and nothing else. Until that exists, `git pull` on the server installs the pilot too.
- [ ] **README to production**: the quick start describes installing the DMS, not trying it. The pilot
      sections move to a short "History" line pointing at `docs/08-Pilot-Process.md`.
- [ ] **Every document checked for pilot wording**: `-TEST` site names, `dms-pilot.rh.tech`, `C:\DMS-Pilot`,
      "pilot" as a description of how the system works rather than of a stage that ended. `docs/07` and
      `docs/08` were written for the pilot and need saying so in their first line.
- [ ] **One document that does not exist yet**: how the DMS is operated day to day - restart, the logs, the
      certificate's expiry, what the upkeep pass does, what to do when SharePoint refuses. Today that
      knowledge is in this session's history, which is not where it belongs.

## 5. The day itself

- [ ] Announce the address change. The old one should answer with a redirect for a while, not an error.
- [ ] Watch the first approvals end to end: submit, approve, the file moves to `Current_ReadOnly`, it is
      read-only on the server, its Markdown appears beside it, View opens a PDF.
- [ ] Watch the first share with a customer end to end, including the guest invitation reaching them.
- [ ] `DMS_FILE_SERVICE_SECONDS` set (60), and the upkeep pass seen running in the log.

## What the pilot taught, so it is not relearned

- An approver needs no rights on the file server, and must not be given any: the DMS acts with its own account.
- Nothing is installed on an approver's PC. Where a step needs something installed, it is the wrong step.
- Visibility follows the AD groups, always. A workflow does not grant sight of a document: a person who may
  not see the folder cannot be an approver of what is in it.
- View is a PDF copy the DMS makes. A link that says "view" does not make a document read-only - a standing
  permission on the library beats it, and Excel ignores it outright.
- `Current_ReadOnly` is read-only on the file system itself, and nothing in it is deleted.
