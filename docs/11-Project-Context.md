# Project context - the brief, as it was actually given

This is the record of what was asked for and decided while the DMS was built and piloted, written so that it
can be handed to someone - or to Claude - and the work carried on without the conversation it came from.

It is a condensed record, not a transcript: the standing rules, the decisions in the order they were made,
what each one was a reaction to, and what is still open.

---

## How to use this file to resume

> **Prompt.** You are continuing work on the RH DMS. Read `README.md`, `docs/10-Installation-and-Settings.md`
> and this file first. The standing rules in section 1 are not negotiable and were each learned the hard way.
> The repository is `ovadir2/dms`, work on `main`, run `webapi` tests before pushing, and never push to the
> pilot server yourself - the user pulls. The pilot is the IIS site `DMS-Pilot` on RHFS02 (`C:\DMS-Pilot\app`,
> repository `E:\Shares`, page `https://dms-pilot.rh.tech`). Section 5 lists what is open.

## 1. The standing rules

These came from the user, usually sharply, and everything else bends around them.

1. **Nothing is installed or configured on an approver's PC.** If a step needs something installed, it is the
   wrong step. (This is why Office trust prompts, drive mappings and handlers were all dead ends.)
2. **Approvers have no rights at all on the file server.** The DMS holds the only account with rights; the
   bridge to a person is SharePoint, and it is invisible to them.
3. **Visibility follows the AD groups, always.** "only AD group are allow to view .... so HR files even if in
   current_only are block for view". A workflow does not grant sight of a document: a person who may not see
   the folder cannot be an approver of what is in it.
4. **An approved document cannot be changed.** `Current_ReadOnly` is read only on the file system itself, not
   only in the page - "this is against policy".
5. **Nothing in `Current_ReadOnly` is deleted**, by anyone, super user included.
6. **View means reading.** Not a link that says view, not a copy someone can annotate and save.
7. **The DMS must look and act the same from the user's perspective**, whatever changes underneath.
8. **The user tests on the pilot and reports.** Push to `main`, they pull and restart. Never claim something
   works because the tests pass.

## 2. What was built, in the order it was asked for

### Sharing with customers
Guest invitation end to end on `LargeFileExchange-TEST`: the app could not invite an unknown address, so the
DMS creates the B2B guest with Graph `POST /invitations` first and then grants the folder by `objectId`. The
folder link goes in the invitation message, because a customer who clicked the tenant name could not reach
anything. A share log is written for unknown customers, and the `RequestId` column is filled after upload.

Learned on the way: Graph and SharePoint `Sites.Selected` are **two** grants; an app cannot create a
SharePoint list (`403`) or resolve an unknown external address.

### The approval loop
Approvals on the DMS page. The document opens in SharePoint with the person's own Microsoft account, comes
back to the file server when they finish, and the decision is recorded. An approver who edited the document
could still approve it from a stale page - the copy is now read at the moment of decision, and approving a
document that changed is refused.

### Released documents, read only for real
`Current_ReadOnly` is hardened on the file system: the AD groups that could see the folder keep Read and
Execute, the DMS keeps Modify, the files carry the read-only flag. A first attempt at this would have opened
HR folders to everyone (`/inheritance:r` plus Authenticated Users) - the user caught it. `Protect-DmsReadOnly.ps1`
does the folders that already exist; folders the DMS creates are hardened as they are made.

### Reading without a copy to write on
View went through several forms, each one failing in an instructive way: a view-scope sharing link (beaten by
a standing permission on the library), a separate `Views` library with no permissions (Excel ignores "open to
view"), a PDF copy in that library (SharePoint's PDF viewer offers to edit it). It ended where it should have
started: SharePoint converts the document to a PDF, the DMS fetches it and **deletes the copy at once**, and
serves the PDF itself. A PDF, a picture or a text file is served straight from the file server.

### Markdown for the company AI
"לטובת ה RAG עדיף md" - so beside every released document sits `<name>.md`, written by a converter inside the
DMS rather than a general-purpose tool (markitdown read a procedure's header block as a six-column grid and
called none of its hand-numbered sections headings). It is written at the moment of release, by all three
routes into `Current_ReadOnly`, and the Markdown of a replaced revision is **removed** so nothing answers from
a revision no longer in force. It lives on the file server so AD decides who may read it.

### The page as a file explorer
"I want to modify the UI to act as file explorer with all custom right-click defined. all logic functionality
needs to be kept." A folder tree beside a detailed list; folders and files in one list; yellow for a folder
someone made and grey for the skeleton and the DMS's own; right-click for the commands of the row, in three
named groups, always the same lines with what does not apply greyed; double-click to open; drag files or a
whole folder in from Windows; the search in the top bar; window buttons in the corner.

The menu is built from the row's own buttons and clicks them, so no rule is written twice and a command added
anywhere appears there by itself.

### The things that were wrong and why
- Office refused `file://` links from the file server (zone), and refused a bare UNC path even harder
  (Restricted Sites). The answer was to stop sending Office at the file server at all.
- A record keeps the path a file had when it was written, and the file moves on its own - rows "lost" their
  documents until they learned to follow them, including the rename an approval performs.
- `os.path.isfile` says a path over ~260 characters is not there; a few Hebrew folder names reach that alone.
- The page was served without `no-store`, so changes "did not arrive" for hours.
- `_protect` passed the folder to PowerShell after `-Command`, where it was parsed as code: every folder the
  DMS tried to harden failed quietly for weeks.

## 3. The decisions that shaped it

| Decision | Why |
| --- | --- |
| SharePoint is the bridge, not the store | Rules 1 and 2: the person needs no rights and installs nothing |
| View is a PDF the DMS serves, with no copy left behind | Every other form of "read only" was beaten by a permission or by Office |
| The right-click menu is built from the row's buttons | One place decides what may be done; the menu cannot drift from it |
| The generic menu shows what is not allowed, greyed | The user asked for it: a menu that changes shape is a menu people hunt in |
| Markdown on the file server, not in SharePoint | AD decides who may read it, and the AI portal crawls the server |
| The Markdown of an obsolete revision is deleted | Otherwise an answer could come from a revision nobody may follow |
| One editing copy, ever | Two drafts of one document is the thing a register cannot express |
| Nobody approves their own document | Writing it and approving it are two people |

## 4. The shape of the thing

- `webapi/dms_api/main.py` - the API and every rule that is not about files on disk
- `webapi/dms_api/file_service.py` - the upkeep pass: moving files to match status, read-only, Markdown
- `webapi/dms_api/sharepoint.py` - the bridge: the register, the copies, the guests, the PDF conversion
- `webapi/dms_api/markdown.py` - the converter written for procedures
- `webapi/dms_api/static/dms-page.html` - the whole page: layout, menus, dialogs, drag and drop
- `webapi/tests/test_api.py` - one file, every test; each one says in its docstring what would otherwise break
- `scripts/` - what IT runs: provisioning, permissions, Markdown, comparison, restart

## 5. What is open

1. **`DMS_FILE_SERVICE_SECONDS=60`** on the pilot - still unset, so the upkeep pass never runs by itself.
2. **Formats the AI cannot read**: `.doc`, `.ppt`, scanned PDFs, and `.xls` until `xlrd` is installed.
   Decide: convert them on release, or accept that they are invisible to the AI.
3. **Drag and drop as a move** (deleting the user's local file after copying) - offered, not built; it needs a
   permission prompt per drag and only works in Chromium browsers.
4. **A stray `QP-1.0E REV 30 Quality Manual.pdf`** sits unregistered in a `Current_ReadOnly`, sharing a name
   with the Word document beside it. Decide which one is the document.
5. **Go-live** - `docs/Go-Live.md`: the names, the pilot's data, first loading, and separating the package
   from what exists only to try it (the playground, the "Acting as" list, `DMS_AUTH_MODE=dev`).
6. **`docs/01`-`docs/08`** still describe the blueprint and the pilot as designed, not as built.
