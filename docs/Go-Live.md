# Go-live: from the pilot to production

The pilot runs as `DMS-Pilot` on RHFS02, against the `-TEST` sites, with test documents in the register.
Going live is not a rename: it is a clean environment, a repository registered from what is really on the
file server, and a package that no longer carries the pilot with it.

This is the checklist. Nothing here is done automatically - each step says what to run and how to see that it
worked. Do them in order: the names move first, then the data, then the package, then the pilot goes.

The decision, taken: **the pilot becomes production.** Not a second installation beside it, not a second
set of SharePoint sites - the one that runs is the one that stays, and what makes it a pilot is taken out
of it. Section A is that path, and it is the one to follow. Sections 0-6 below are the full rebuild, kept
for the day a clean environment is wanted instead.

What that costs, said once so it is not a surprise:

- The sites keep their URLs, `…/sites/DocumentControl-TEST` and `…/sites/LargeFileExchange-TEST`. A
  SharePoint site's address cannot be changed afterwards; its **title** can, and that is what people see.
  Renaming the address means a new site, which is the full rebuild.
- The register keeps every row the pilot wrote. The test documents have to be taken out by hand - there is
  no "clear the pilot" button, and there should not be.
- The Control Audit keeps the pilot's lines. That is not a defect: it is the history of those documents.

---

## A. Promoting the pilot in place - the chosen path

One morning, in this order. Each step says how to see that it worked.

**A1. Back up first.** A full copy of `E:\Shares`, and an export of the Document Register, the Control
Audit and the Approval Decisions. Everything here is reversible only from these.

**A2. Take the pilot out of the installation.** In `webapi\.env` (remember: the **first** occurrence of a
key wins, so look for a leftover line above):

| Out | Why |
| --- | --- |
| `DMS_AUTH_MODE=dev`, `DMS_DEV_USER` | dev mode is a DMS with no authentication at all |
| `DMS_DEV_USERS` | "Acting as": a super user being somebody else |
| `DMS_SHAREPOINT=memory` | the playground register |

| In | |
| --- | --- |
| `DMS_AUTH_MODE=windows` | |
| `DMS_FILE_SERVICE_SECONDS=60` | the upkeep pass runs by itself |
| `DMS_REVIEW_LIBRARY=Approvals`, `DMS_VIEW_LIBRARY=Views` | the bridge: View makes a PDF, approvers edit a copy |

Then `.\scripts\Restart-Dms.ps1` and `.\scripts\Test-DmsProductionReady.ps1` - it reads the `.env`, asks
the DMS, and looks at the file server, and prints PASS or FAIL per line with what to run.

**A3. Clear the pilot's data from the file server.** Delete every `DMS_ACCESS_CANARY_*`, the test drafts,
and the pilot's `04_Workflow_System\Recycle\*`. `CheckedOut.json` must be empty - a document still out in
SharePoint has not come back yet, so bring it back on the page first (Done editing). The readiness check
covers all three.

**A4. Clear the pilot's rows from the register.** The ones that are tests, not documents. For each: open it
in the Document Register and delete the item, or - better - take the file out of `Current_ReadOnly` on the
page (the owner's own command moves it to `Obsolete_ReadOnly` with its Markdown). Keep every row whose file
is a real document. `.\scripts\Repair-DmsRegister.ps1` lists the rows whose file is not on the server any
more, which is most of the pilot's.

**A5. Make the repository the real one.** The pilot ran against part of `E:\Shares`; production is all of
it. Point `DMS_REPOSITORY_ROOT` at the root that is wanted, then:

```powershell
.\scripts\Sync-DmsFileServer.ps1 -Write      # what is on the disk and not in the DMS
.\scripts\New-DmsMarkdown.ps1 -Write         # the Markdown the AI reads, for everything released
.\scripts\Compare-DmsTree.ps1                # the DMS and the disk agree
```

A file sitting in a `Current_ReadOnly` that nobody registered is **not** an approved document: list them
first and decide one by one - register it, or move it out.

**A6. The names people see.** The URLs stay; the titles and the address do not have to:

- Rename the IIS site and pool `DMS-Pilot` → `DMS` (or leave them: nobody outside the server sees them).
- Add the production binding `dms.rh.tech` to the same site with its certificate, and keep
  `dms-pilot.rh.tech` answering as a redirect to it until the bookmarks have followed. Set
  `DMS_PAGE_URL=https://dms.rh.tech/dms/dms-page` so notifications point at the new one.
- In SharePoint, change the **titles** of the two sites and of the lists from "… TEST" to the real ones.
  The URLs keep `-TEST` and nothing breaks: the DMS reads them from `.env`, and people see the titles.
- `C:\DMS-Pilot` may stay as the folder. Renaming it means IIS, the application pool, the service and
  `web.config` all follow - cost with no benefit.

**A7. New keys for the applications.** A key is an identity, and the pilot's were handed out to try things:
`.\scripts\New-DmsApiKey.ps1` one per caller (the RAG `documents`, the KPI Builder `kpi`), each with its
own AD account; remove the old lines from `DMS_API_KEYS`, restart, tell each caller its new key.

**A8. The last look, before anyone is told.** `.\scripts\Test-DmsProductionReady.ps1` with nothing left
failing, then by hand: submit a document and approve it end to end, watch it land read-only in
`Current_ReadOnly` with its Markdown beside it, View opens a PDF, share one with a customer, and
`.\scripts\Open-DmsSwagger.ps1` answers on the production address.

**A9. Say it is production.** The address, what changed for people (nothing in how they work), and that the
pilot is over. `docs/08-Pilot-Process.md` gets a first line saying the pilot ran from <date> to <date>.

What is **not** needed on this path: new SharePoint sites, a new certificate, a new `Sites.Selected` grant,
a second IIS site, first loading. What is still worth doing, after the move rather than before: the package
builder (so `git pull` stops installing the playground along with the product) and the operations document.

---

## 0. Before the day - the full rebuild (the other path)

> Sections 0-6 describe building production as a separate environment. They are not the chosen path; they
> are here for the day a clean environment is wanted, or if A4 shows the register is past cleaning.

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
  | API document | `dms-pilot.rh.tech/api/openapi.json` | `dms.rh.tech/api/openapi.json` |
  | Swagger UI / ReDoc | `dms-pilot.rh.tech/dms/api-docs` | `dms.rh.tech/dms/api-docs` |

- [ ] A full backup of `E:\Shares` and an export of the SharePoint lists (register, Control Audit, approval
      decisions). Everything below is reversible only from these.
- [ ] **Decided: the pilot is not kept.** Production is built beside it on the same server, the switch is
      made in one morning, and the pilot is retired the same day (section 6). It is not left running
      read-only: two addresses means people find the wrong one, and two DMSs writing to `E:\Shares` means
      two file services moving the same files.

      Built beside it, not renamed into it, for one reason: the production register is built by first
      loading from the file server, and a register full of pilot rows cannot be cleaned into one. The pilot
      keeps answering until production has passed its checks - that is the rollback - and is removed when
      it has.

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
- [ ] `.\scripts\Open-DmsSwagger.ps1 -Url https://dms.rh.tech -NoOpen` - it prints the build, how many
      endpoints answered and the ways in. It is the quickest proof that the API is up on the production
      address, with the production build, before anybody is sent to it.
- [ ] Anonymous authentication stays **off** on `/dms/api-docs` and `/api/openapi.json`: the document says
      what every endpoint takes, and it is for people who have signed in. The one place anonymous is on is
      `/api/kpi`, for the sandboxed pages (`scripts\Set-DmsKpiKeyAccess.ps1`), and that stays as it is.

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
- [ ] New keys for the applications - the pilot's are not carried over (`scripts\New-DmsApiKey.ps1`, one per
      caller, each with its own AD account: the RAG reads with `documents`, the KPI Builder publishes with
      `kpi`). Retire the pilot keys the day the pilot stops answering, and tell each caller the production
      address and its new key.

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
- [ ] **The API document regenerated against production**: `.\scripts\New-DmsApiDocs.ps1` writes
      `docs\14-API-Reference.md` and `docs\dms-openapi.json` from the API itself. Both carry the pilot's
      address in their examples today; after the rename, regenerate them and read the result for
      `dms-pilot`, `-TEST` and `C:\DMS-Pilot`. A test fails if either file is behind the code, so this
      cannot be forgotten quietly.
- [ ] **Decide who may read Swagger in production.** It is behind Windows authentication, so everyone who
      can open the DMS can open it, and it describes every endpoint including what an application key may
      do. If that is more than you want, put the production `/dms/api-docs` behind an AD group in IIS -
      the document at `/api/openapi.json` is what the Builder and the RAG actually need, and it can stay
      open to signed-in callers while the page is not.
- [ ] **Swagger UI needs the internet** on the PC that opens it (its JavaScript comes from jsdelivr).
      `/dms/api-redoc` reads the same document without it: say which one the people who will use it should
      open, so "Swagger is broken" does not become a ticket on a server with no way out.
- [ ] **One document that does not exist yet**: how the DMS is operated day to day - restart, the logs, the
      certificate's expiry, what the upkeep pass does, what to do when SharePoint refuses. Today that
      knowledge is in this session's history, which is not where it belongs.

## 5. The day itself

- [ ] Announce the address change. The old one should answer with a redirect for a while, not an error.
- [ ] Watch the first approvals end to end: submit, approve, the file moves to `Current_ReadOnly`, it is
      read-only on the server, its Markdown appears beside it, View opens a PDF.
- [ ] Watch the first share with a customer end to end, including the guest invitation reaching them.
- [ ] `DMS_FILE_SERVICE_SECONDS` set (60), and the upkeep pass seen running in the log.
- [ ] Nothing below is done until every check in this section has passed - the pilot is the way back, and
      the way back ends in section 6.
- [ ] The applications answered from production, not from the pilot: the RAG's
      `GET /api/v1/approved-documents` and the Builder's `POST /api/v1/kpi/publish`, each with its new key,
      against `dms.rh.tech`. Try them from `/dms/api-docs` with the key in the Authorize box - that is what
      the page is for.

## 6. Retiring the pilot, the same day

Only once production has passed section 5. Until then the pilot is the rollback: leave it alone.

- [ ] Stop the pilot so nobody is in it while the last checks run:
      `Stop-Website DMS-Pilot; Stop-WebAppPool DMS-Pilot`
- [ ] `dms-pilot.rh.tech` answers with a redirect to `dms.rh.tech`, not an error: an IIS site of that name
      with a single HTTP redirect rule, and the certificate kept until the DNS entry goes. Everyone has the
      old address in a mail, a bookmark and a Teams card.
- [ ] The pilot's keys stop working: remove their lines from the pilot's `.env`, and tell each caller (the
      RAG, the KPI Builder) the production address and its new key. A key is an identity - it is retired,
      not moved.
- [ ] Nothing of the pilot writes to `E:\Shares` any more: the pilot's file service is off with its pool,
      and `04_Workflow_System\CheckedOut.json` has nothing left out for editing. Check it before removing
      anything - a copy still out in SharePoint has not come back yet.
- [ ] Keep, do not delete: the `-TEST` sites and their lists, read-only, for three months. They are the
      audit of the pilot. Take the export of the register, the Control Audit and the approval decisions
      first, and keep it with the backup of the day.
- [ ] After a week with no surprises: remove the IIS site `DMS-Pilot` and its pool, the folder
      `C:\DMS-Pilot`, and the pilot's certificate. Leave the folder's last backup.
- [ ] `docs/08-Pilot-Process.md` gets a first line saying the pilot ran from <date> to <date> and that it is
      history, not how the system works.

## What the pilot taught, so it is not relearned

- An approver needs no rights on the file server, and must not be given any: the DMS acts with its own account.
- Nothing is installed on an approver's PC. Where a step needs something installed, it is the wrong step.
- Visibility follows the AD groups, always. A workflow does not grant sight of a document: a person who may
  not see the folder cannot be an approver of what is in it.
- View is a PDF copy the DMS makes. A link that says "view" does not make a document read-only - a standing
  permission on the library beats it, and Excel ignores it outright.
- `Current_ReadOnly` is read-only on the file system itself, and nothing in it is deleted.
- An application is not a super user: a key names an AD account, and the DMS answers that account exactly
  what it may see. That is why there are three machine endpoints and not thirty.
