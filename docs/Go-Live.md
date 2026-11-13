# Go-live: from the pilot to production

The pilot runs as `DMS-Pilot` on RHFS02, against the `-TEST` sites, with test documents in the register.

This is the checklist. Nothing here is done automatically - each step says what to run and how to see that
it worked.

The decision, taken: **the pilot becomes production by being renamed.** Not a second installation, not a
second set of sites - the one that runs is the one that stays. What has to change is the names people see
and the lines in `.env` that follow them.

---

## A. The rename - the chosen path

One sitting. Back up first: a copy of `E:\Shares` and an export of the Document Register, the Control
Audit and the Approval Decisions.

### A1. SharePoint: drop the `-TEST`

A SharePoint Online site's **address can be changed**, in the SharePoint admin centre: Active sites, pick
the site, Change site address. The site keeps its id, its lists, its items and its permissions - so the
`Sites.Selected` grant and the certificate stay as they are - and the old address redirects for a while.

- [ ] `…/sites/DocumentControl-TEST` → `…/sites/DocumentControl`
- [ ] `…/sites/LargeFileExchange-TEST` → `…/sites/LargeFileExchange`
- [ ] Change the two site **titles** as well, and the titles of the lists that carry "TEST" in their name.
      The list URLs are internal; nobody reads them.
- [ ] Give it an hour: the change is not instant, and the DMS answers 404 from SharePoint until it has gone
      through. Then check with the page's own SharePoint diagnostics (the ⋮ menu, super users).

### A2. The DMS: the lines that name them

`.\scripts\Rename-DmsToProduction.ps1` does A2 to A4 in one go - it checks that the renamed sites answer
before it writes anything, looks at IIS authentication, changes the `.env` (keeping a copy beside it),
renames the IIS site and pool with `-RenameSite`, then restarts and runs the readiness check. Without
`-Write` it only says what it would do. By hand, it is this:

In `webapi\.env` - and remember the **first** occurrence of a key wins, so look for a leftover line above:

| | From | To |
| --- | --- | --- |
| `DMS_SITE_URL` | `…/sites/DocumentControl-TEST` | `…/sites/DocumentControl` |
| `DMS_EX_SITE_URL` | `…/sites/LargeFileExchange-TEST` | `…/sites/LargeFileExchange` |
| `DMS_REVIEW_SITE_URL` | (if set) the `-TEST` one | the new one |
| `DMS_PAGE_URL` | `https://dms-pilot.rh.tech/...` | `https://dms.rh.tech/...` |

Then `.\scripts\Restart-Dms.ps1`, and read the `.env` back (`Select-String -Path webapi\.env -Pattern
'SITE_URL|PAGE_URL|DEV_'`): no line should still carry a pilot name.

### A3. The address: drop the `pilot`

- [ ] DNS: `dms.rh.tech` to the same server.
- [ ] A certificate that carries `dms.rh.tech` (the same one may carry both, as a SAN).
- [ ] In IIS, add the `dms.rh.tech` binding to the **same** site, and keep `dms-pilot.rh.tech` answering -
      as a redirect once people have moved. Everyone has the old address in a mail and a bookmark.
- [ ] `DMS_PAGE_URL` already points at the new one (A2), so notifications carry it from now on.

### A4. The installation's own names (optional, nobody outside the server sees them)

- [ ] IIS site and pool `DMS-Pilot` → `DMS`.
- [ ] Folder `C:\DMS-Pilot` → `C:\DMS`. If you do this, the site's physical path, the pool and
      `webapi\web.config` all have to follow, and the scheduled task if there is one.
- [ ] The scripts need no editing either way: they take the site from `DMS_IIS_SITE` (or `-Site`), the
      address from `DMS_PAGE_URL` (or `-Url`), and the application from the folder they sit in.

### A5. What still says "pilot" and should not

- [ ] The two words in the DMS page's title bar, if the pilot is named there.
- [ ] `docs/08-Pilot-Process.md`: a first line saying the pilot ran from <date> to <date> and that it is
      history, not how the system works.
- [ ] **Everything that was played with, in one command.** `.\scripts\Reset-DmsPilotData.ps1` says what it
      would clear and changes nothing; `-Write` does it, after typing RESET:

      | | |
      | --- | --- |
      | SharePoint, the control site | Document Register, Control Audit, Approval Decisions, Delegations, DMS Notifications - emptied, not deleted. The **Approver Matrix is left alone**: those are the rules, not the pilot's data. The DMS's own certificate does it, so there is nothing to install and no site administrator is needed |
      | SharePoint, both sites | the `Approvals` and `Views` libraries, and the Exchange site's libraries - the copies and what was shared with customers |
      | The file server | every file, every workflow folder, the folders somebody made (a KPI build's folder included), the canaries, the recycle folder, `CheckedOut.json` |

      What is left is the blueprint: every folder it defines, the KPIs folders among them, each customer
      with its own tree, and the system folders with their shape. `-Customers` removes the customer folders
      too (the skeleton always stays). Back up `E:\Shares` and export the lists first - this cannot be
      undone.
- [ ] `.\scripts\Restart-Dms.ps1` after the reset: the DMS keeps the register for a minute, so the page
      still shows the old documents until it does.
- [ ] Anything still out for editing in SharePoint comes back **before** the reset (Done editing on the
      page): a copy that comes back afterwards writes a file into a folder that was just cleared.
- [ ] New keys for the applications if the pilot's were handed out to try things
      (`.\scripts\New-DmsApiKey.ps1`), and the old lines removed from `DMS_API_KEYS`.

### A6. Then look at it

`.\scripts\Test-DmsSmoke.ps1` with nothing failing, and by hand: submit and approve a document
end to end, see it land read-only in `Current_ReadOnly` with its Markdown beside it, View opens a PDF,
share one with a customer, and `.\scripts\Open-DmsSwagger.ps1` answers on `dms.rh.tech`.

Worth doing after the rename, not before: the package builder (so `git pull` stops installing the
playground and dev mode along with the product) and the operations document.

---

## 0. Before the day - the full rebuild (the other path)

> Sections 0-6 describe building production as a separate environment, with its own sites, certificate and
> first loading. They are **not** the chosen path - section A is - and are kept for the day a clean
> environment is wanted instead, or if the register turns out to be past cleaning.

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
      `DMS_AUTH_MODE=dev` and `DMS_DEV_USER`,
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
