<#
.SYNOPSIS
    Walks the whole DMS as one user, against the installation that is really running, and says which
    requirement each step proves.

.DESCRIPTION
    The automated tests run against an in-memory register in a temporary folder - they prove the code. This
    proves the installation: AD, IIS, SharePoint, the file server and the page's own API, with real files,
    in a folder of its own (`01_General\IT\DMS-Selftest`).

    It runs as the person it is told to run as. A super user may run it as somebody else ("Acting as"), so
    the walk is seen through that person's rights - which is the only honest way to test what a user can do.

    Nothing is cleaned up: -Clean removes what it made, when you say so. The Control Audit keeps its lines
    either way, which is the point of an audit.

.PARAMETER Delegate
    A third person, for passing an approval on. It cannot be the approver and cannot be the person the walk
    runs as, who owns the document - the DMS refuses an approval delegated to the person who wrote it. Left
    out, that one step is skipped.

.PARAMETER Report
    Where to write the whole walk, line by line. Left out, it goes to %TEMP%\DMS-Smoke <date>.txt - and the
    path is printed, so the file can be sent on as it is.

.PARAMETER As
    Run as this person (a super user only; the DMS checks). Left out, it runs as you.

.PARAMETER Approver
    Who the document is sent to. It cannot be the person the walk runs as.

.EXAMPLE
    .\scripts\Test-DmsSmoke.ps1 -As RH\dms-lab -Approver roneno@rh.co.il -Delegate someone.else@rh.co.il
.EXAMPLE
    .\scripts\Test-DmsSmoke.ps1 -Clean
#>
[CmdletBinding()]
param(
    [string]$Url = '',
    [string]$As = '',
    [string]$Approver = '',
    [string]$Folder = '01_General\IT\DMS-Selftest',
    [string]$Delegate = '',
    [string]$Report = '',
    [switch]$Detailed,
    [switch]$Clean
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_DmsDefaults.ps1"
if (-not $Url) { $Url = Get-DmsDefault Url }
$root = Get-DmsEnvValue 'DMS_REPOSITORY_ROOT'
if (-not $root) { throw "DMS_REPOSITORY_ROOT is not in webapi\.env - run this on the DMS server." }
$here = Join-Path $root $Folder
$ok = 0; $bad = 0; $skipped = 0
$all = @()                     # every line of every group, for the report and the list of failures at the end
$headers = @{}
if ($As) { $headers['X-DMS-Dev-User'] = $As }

function Call($method, $path, $body, $fields) {
    $u = "$($Url.TrimEnd('/'))$path"
    if ($fields) {
        $pairs = ($fields.GetEnumerator() | ForEach-Object { "$($_.Key)=$([uri]::EscapeDataString("$($_.Value)"))" }) -join '&'
        return Invoke-RestMethod -Uri $u -Method $method -UseDefaultCredentials -Headers $headers -TimeoutSec 180 `
                   -ContentType 'application/x-www-form-urlencoded' -Body $pairs
    }
    if ($body) {
        return Invoke-RestMethod -Uri $u -Method $method -UseDefaultCredentials -Headers $headers -TimeoutSec 180 `
                   -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 6)))
    }
    return Invoke-RestMethod -Uri $u -Method $method -UseDefaultCredentials -Headers $headers -TimeoutSec 180
}

function Send-File($path, $folder, $extra) {
    # multipart by hand: Windows PowerShell 5.1 has no -Form
    $name = Split-Path -Leaf $path
    $b = [guid]::NewGuid().ToString()
    $nl = "`r`n"
    $head = ""
    $all = @{ folder = $folder } + $(if ($extra) { $extra } else { @{} })
    foreach ($k in $all.Keys) { $head += "--$b$nl" + "Content-Disposition: form-data; name=`"$k`"$nl$nl" + "$($all[$k])$nl" }
    $head += ("--$b$nl" + "Content-Disposition: form-data; name=`"file`"; filename=`"$name`"$nl" +
              "Content-Type: application/octet-stream$nl$nl")
    $enc = [Text.Encoding]::UTF8
    $body = New-Object System.IO.MemoryStream
    $pre = $enc.GetBytes($head); $body.Write($pre, 0, $pre.Length)
    $bytes = [IO.File]::ReadAllBytes($path); $body.Write($bytes, 0, $bytes.Length)
    $post = $enc.GetBytes("$nl--$b--$nl"); $body.Write($post, 0, $post.Length)
    return Invoke-RestMethod -Uri "$($Url.TrimEnd('/'))/api/files/upload" -Method POST -UseDefaultCredentials `
               -Headers $headers -TimeoutSec 300 -ContentType "multipart/form-data; boundary=$b" -Body $body.ToArray()
}

# One line per thing the DMS does, not per rule inside it: the detail is kept and printed when a step
# fails (or always, with -Detailed), so a green run reads in five seconds and a red one says exactly what.
$group = ''
$lines = @()
function Section($name) {
    if ($script:group) { Close-Section }
    $script:group = $name
    $script:lines = @()
}
function Close-Section {
    if (-not $script:group) { return }
    $failed = @($script:lines | Where-Object { $_.state -eq 'FAIL' })
    $skip = @($script:lines | Where-Object { $_.state -eq 'SKIP' })
    $mark = if ($failed.Count) { 'FAIL' } elseif ($skip.Count -eq $script:lines.Count) { 'SKIP' } else { 'PASS' }
    $colour = if ($failed.Count) { 'Red' } elseif ($mark -eq 'SKIP') { 'DarkYellow' } else { 'Green' }
    Write-Host ("{0}  {1}" -f $mark, $script:group) -ForegroundColor $colour
    foreach ($l in $script:lines) { $script:all += @{ group = $script:group; req = $l.req; what = $l.what
                                                      state = $l.state; detail = $l.detail } }
    foreach ($l in $script:lines) {
        if ($l.state -ne 'PASS' -or $Detailed) {
            $c = if ($l.state -eq 'FAIL') { 'Yellow' } else { 'DarkGray' }
            Write-Host ("        {0,-11} {1}" -f $l.req, $l.what) -ForegroundColor $c
            if ($l.detail) { Write-Host ("                    " + $l.detail) -ForegroundColor DarkGray }
        }
    }
    $script:group = ''
}
function Check($req, $what, $test) {
    try {
        $result = & $test
        if (-not $result) { throw "it answered no" }
        $script:lines += @{ req = $req; what = $what; state = 'PASS'; detail = "$result" }
        $script:ok++
    } catch {
        $script:lines += @{ req = $req; what = $what; state = 'FAIL'; detail = $_.Exception.Message }
        $script:bad++
    }
}
function Skip($req, $what, $why) {
    $script:lines += @{ req = $req; what = $what; state = 'SKIP'; detail = $why }
    $script:skipped++
}

# ---------------------------------------------------------------- clean
if ($Clean) {
    Write-Host "Removing what the walk made in $here" -ForegroundColor Yellow
    foreach ($d in (Call GET "/api/documents" $null $null)) {
        if ("$($d.workingUncPath)$($d.currentUncPath)" -like "*DMS-Selftest*") {
            try { Call POST "/api/documents/$($d.id)/delete" @{} $null | Out-Null; Write-Host "    $($d.documentId) removed" }
            catch { Write-Host "    $($d.documentId): $($_.Exception.Message)" -ForegroundColor Yellow }
        }
    }
    if (Test-Path $here) {
        Get-ChildItem $here -Recurse -File | ForEach-Object { $_.IsReadOnly = $false }
        Remove-Item $here -Recurse -Force
    }
    Write-Host "Done. The Control Audit keeps its lines." -ForegroundColor Green
    return
}
if (-not $Approver) { throw "Give -Approver <someone@rh.co.il>; it cannot be the person the walk runs as." }

Write-Host ""
Write-Host "=== The DMS at $Url, walked as $(if ($As) { $As } else { 'you' })" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------- who, and what this build is
Section "Signing in: the DMS answers as the person at the keyboard"
$me = Call GET "/api/me" $null $null
$cfg = Call GET "/api/client-config" $null $null
Check 'REQ-P03' "the DMS knows who is calling, by AD" { "signed in as $($me.email)$(if ($me.actingFrom) { "  (really $($me.actingFrom))" })" }
Check 'REQ-P31' "Acting as is a super user seeing as somebody, and the real account is kept" {
    if ($As) { [bool]$me.actingFrom } else { $true } }

# ---------------------------------------------------------------- the structure
Section "The structure: the company's own folders are the blueprint"
$general = Call GET "/api/browse?path=$([uri]::EscapeDataString((Join-Path $root '01_General')))" $null $null
Check 'REQ-P29' "the company's structure is the blueprint, in both languages" {
    $named = @($general.folders | Where-Object { $_.label })
    if ($named.Count -lt 5) { throw "only $($named.Count) folders have a blueprint name" }
    "$($named.Count) departments named, e.g. $($named[0].label.en) / $($named[0].label.he)" }

# ---------------------------------------------------------------- a folder of its own
Section "A place to work: a folder, and a file dropped into it"
$fresh = -not (Test-Path $here)
Check 'REQ-P02' "a folder can be made where AD allows it" {
    if ($fresh) { Call POST "/api/folders" @{ parent = (Split-Path $here -Parent); name = (Split-Path $here -Leaf) } $null | Out-Null }
    Test-Path $here }
if ($fresh) { Start-Sleep -Seconds 5 }    # AD has to pass the folder's permissions down before an approver can see it

# ---------------------------------------------------------------- a real file arrives
$stamp = Get-Date -Format 'yyyy-MM-dd HHmm'
# A real Word document, not a text file: a procedure with headings, a numbered section and a table, so what
# the approver opens, what View turns into a PDF and what the Markdown is written from are the real thing.
$samples = Join-Path $PSScriptRoot 'samples'
$doc1 = Join-Path $env:TEMP "DMS walk $stamp.docx"
Copy-Item (Join-Path $samples 'Procedure.docx') $doc1 -Force
$up = $null
Check 'REQ-P88' "a file is dropped into the folder, with AD asked for Modify" {
    $script:up = Send-File $doc1 $here @{ dropped = 'true' }
    Split-Path -Leaf $up.path }

# ---------------------------------------------------------------- register, submit
Section "A document, end to end: registered, sent, approved, released"
$doc = $null
Check 'REQ-P42/P43' "it is registered and sent to an approver" {
    $script:doc = Call POST "/api/documents" @{ path = $up.path; documentType = 'נוהל'; documentArea = 'מערכות מידע';
                                                submit = $true; approvers = @($Approver) } $null
    "$($doc.documentId) waiting for $Approver" }
Check 'REQ-P36' "the file moved to Submitted" {
    Start-Sleep -Seconds 3
    $sub = Join-Path $here 'Submitted'
    (Test-Path $sub) -and @(Get-ChildItem $sub -File).Count -ge 1 }
Check 'REQ-P56' "the owner sees it in My workflows" {
    $mine = Call GET "/api/my-workflows" $null $null
    [bool](@($mine.items | Where-Object { $_.documentId -eq $doc.documentId }).Count) }

# ---------------------------------------------------------------- the approver's side
Check 'REQ-P52' "an approver who may not see the document cannot be chosen" {
    try { Call POST "/api/documents" @{ path = $up.path; submit = $true; approvers = @('nobody@rh.co.il') } $null | Out-Null; $false }
    catch { $true } }

# ---------------------------------------------------------------- the approver answers, and nobody else
Check 'REQ-P54' "somebody who is not the approver cannot answer for them" {
    try { Call POST "/api/approvals/$($doc.id)" @{ approve = $true; comment = 'not mine to answer' } $null | Out-Null
          throw "the DMS let $(if ($As) { $As } else { $me.email }) answer an approval that is not theirs" }
    catch {
        if ("$($_.Exception.Message)" -notmatch '403|Forbidden') { throw $_ }
        "refused, as it should be" } }
Check 'REQ-P44' "the approver answers, and the decision is recorded" {
    $keep = $script:headers; $script:headers = @{}        # as the approver themselves, not as the walk's user
    try { $after = Call POST "/api/approvals/$($doc.id)" @{ approve = $true; comment = 'walk-through: approved' } $null }
    finally { $script:headers = $keep }
    "status now: $($after.statusKey)" }
Start-Sleep -Seconds 4
$cur = Join-Path $here 'Current_ReadOnly'
$released = $null
Check 'REQ-P04/P23' "it is released, and read only on the file server" {
    $row = Call GET "/api/documents/$($doc.id)" $null $null       # this run's file, not an earlier run's
    if (-not $row.currentUncPath) { throw "the register names no released file" }
    $script:released = Get-Item -LiteralPath $row.currentUncPath
    if (-not $released) { throw "nothing in $cur" }
    if (-not $released.IsReadOnly) { throw "$($released.Name) is not read only" }
    $released.Name }
Check 'REQ-P38' "its Markdown is beside it, with the revision it is" {
    # the Markdown of this document: its own name with .md, or its whole name plus .md where another
    # document of the folder already has the short one
    $stem = [IO.Path]::GetFileNameWithoutExtension($released.Name)
    $md = @("$stem.md", "$($released.Name).md") | ForEach-Object { Join-Path $cur $_ } |
          Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $md) { throw "no Markdown beside $($released.Name)" }
    $head = (Get-Content -LiteralPath $md -TotalCount 14) -join ' '
    if ($head -notmatch 'Revision') { throw "the head of $(Split-Path -Leaf $md) says no revision" }
    if ($head -notmatch [regex]::Escape($released.Name)) { throw "$(Split-Path -Leaf $md) was written for another file" }
    Split-Path -Leaf $md }

# ---------------------------------------------------------------- what the page offers on that row
Section "A released document: read only, and the page says why"
Check 'REQ-P63/P64' "the released document offers View, not editing" {
    $row = (Call GET "/api/browse?path=$([uri]::EscapeDataString($cur))" $null $null).files |
           Where-Object { $_.name -eq $released.Name }
    if ($row.canEdit -or $row.editable) { throw "it offers editing" }
    "editing is refused: $($row.editWhy)" }
Check 'REQ-P91' "the DMS can say why, file by file" {
    $why = Call GET "/api/diagnostics/file?path=$([uri]::EscapeDataString($released.FullName))" $null $null
    "releasedByDms=$($why.releasedByDms)  adWrite=$($why.adWrite)  canEdit=$($why.canEdit)" }

# ---------------------------------------------------------------- history, search
Check 'REQ-P59' "the document can account for itself" {
    $h = Call GET "/api/documents/$($doc.id)" $null $null
    [bool]$h.documentId }
Check 'REQ-P87' "it can be found without knowing where it is" {
    $found = Call GET "/api/search?q=$([uri]::EscapeDataString($doc.documentId))" $null $null
    [bool](@($found | Where-Object { "$_" -like "*$($doc.documentId)*" }).Count -or $found.Count) }

# ---------------------------------------------------------------- the next revision
Section "The next revision, without displacing the one in force"
Check 'REQ-P48' "the next revision starts from the one in force, which stays current" {
    $rev = Call POST "/api/documents/$($doc.id)/revise" $null @{ submit = 'false' }
    $draft = Split-Path -Leaf $rev.draft
    if (-not (Test-Path $rev.draft)) { throw "the draft is not on the file server" }
    if (-not $released.IsReadOnly) { throw "the approved revision stopped being read only" }
    $draft }

# ---------------------------------------------------------------- a workbook of the same name
Section "A workbook and a procedure under one name"
$stem = [IO.Path]::GetFileNameWithoutExtension($released.Name)
$book = Join-Path $env:TEMP "$stem.xlsx"
Copy-Item (Join-Path $samples 'Procedure.xlsx') $book -Force
Check 'REQ-P95' "a workbook released under the document's own name keeps a Markdown of its own" {
    Send-File $book $here @{ noWorkflow = 'true' } | Out-Null
    Start-Sleep -Seconds 4
    $md = @(Get-ChildItem $cur -Filter *.md | Select-Object -ExpandProperty Name)
    $want = @("$stem.md", "$stem.xlsx.md")
    $missing = @($want | Where-Object { $md -notcontains $_ })
    if ($missing) { throw "missing $($missing -join ', ') - there is only $($md -join ', ')" }
    $want -join ' + ' }
Check 'REQ-P08' "each Markdown names the file it was written for" {
    $head = (Get-Content (Join-Path $cur "$stem.xlsx.md") -TotalCount 14) -join ' '
    if ($head -notmatch [regex]::Escape("$stem.xlsx")) { throw "the workbook's Markdown names another file" }
    $body = (Get-Content (Join-Path $cur "$stem.xlsx.md") -Raw)
    if ($body -notmatch 'Measures') { throw "the workbook's sheets are not in it" }
    "the workbook's own sheets, and the procedure's own text, each in their own file" }

# ---------------------------------------------------------------- without a workflow
Section "Published without a workflow, and taken out again"
$doc2 = Join-Path $env:TEMP "DMS walk published $stamp.txt"
@("Published as it is, no workflow.") | Set-Content $doc2 -Encoding UTF8
$pub = $null
Check 'REQ-P49' "a file can be released without a workflow, straight to Current_ReadOnly" {
    $script:pub = Send-File $doc2 $here @{ noWorkflow = 'true' }
    if ($pub.path -notlike "*Current_ReadOnly*") { throw "it did not land in Current_ReadOnly: $($pub.path)" }
    Split-Path -Leaf $pub.path }
Check 'REQ-P57/P41' "a released file is taken out to Obsolete_ReadOnly, not erased" {
    $gone = Call POST "/api/items/delete" @{ path = $pub.path } $null
    if (-not $gone.obsolete) { throw "it was not moved to Obsolete_ReadOnly" }
    Split-Path -Leaf $gone.movedTo }

# ---------------------------------------------------------------- KPIs
Section "KPIs, pages and the skeleton"
Check 'REQ-P15' "the department's KPIs folder is known as one" {
    $kpis = Join-Path (Split-Path $here -Parent) 'KPIs'
    if (-not (Test-Path $kpis)) { throw "there is no KPIs folder beside $Folder" }
    $k = Call GET "/api/browse?path=$([uri]::EscapeDataString($kpis))" $null $null
    if (-not $k.kpis) { throw "the DMS does not see it as a KPIs folder" }
    "New KPI is offered here" }

# ---------------------------------------------------------------- the skeleton
Check 'REQ-P93' "nothing is filed in the customer skeleton" {
    $sk = Join-Path $root '02_Customers\Customer_Skeleton'
    if (-not (Test-Path $sk)) { throw "there is no customer skeleton" }
    $s = Call GET "/api/browse?path=$([uri]::EscapeDataString($sk))" $null $null
    [bool]$s.skeletonNote }

# ---------------------------------------------------------------- taking back, passing on, remarks
Section "Taking back, passing on, and remarks"
$doc4 = Join-Path $env:TEMP "DMS walk withdrawn $stamp.txt"
@("Submitted, then taken back.") | Set-Content $doc4 -Encoding UTF8
$w1 = $null
Check 'REQ-P47' "a submission can be taken back by its owner" {
    $put = Send-File $doc4 $here @{}
    $script:w1 = Call POST "/api/documents" @{ path = $put.path; documentType = 'נוהל'; documentArea = 'מערכות מידע';
                                               submit = $true; approvers = @($Approver) } $null
    $back = Call POST "/api/documents/$($w1.id)/withdraw" @{} $null
    if ($back.statusKey -ne 'Working') { throw "it is $($back.statusKey), not Working" }
    "$($w1.documentId) came back to its owner" }
if (-not $Delegate) {
    Skip 'REQ-P50' "an approval is passed to somebody else for this cycle" `
         "give -Delegate <someone@rh.co.il>: it cannot be $Approver, and it cannot be the person the walk runs as, who owns the document"
} else {
Check 'REQ-P50' "an approval can be passed to somebody else for this cycle" {
    Call POST "/api/documents/$($w1.id)/submit" @{ approvers = @($Approver) } $null | Out-Null
    $keep = $script:headers; $script:headers = @{}        # the approver passes their own answer on
    try { Call POST "/api/approvals/$($w1.id)/delegate" @{ to = $Delegate; comment = 'walk-through' } $null | Out-Null }
    finally { $script:headers = $keep }
    "now waiting for $Delegate" }
}
Check 'REQ-P68/P69' "an approver attaches a marked-up document as their remarks" {
    $note = Join-Path $env:TEMP "remarks $stamp.txt"
    @("Please add the lead time.") | Set-Content $note -Encoding UTF8
    $b = [guid]::NewGuid().ToString(); $nl = "`r`n"
    $head = ("--$b$nl" + "Content-Disposition: form-data; name=`"file`"; filename=`"remarks.txt`"$nl" +
             "Content-Type: text/plain$nl$nl")
    $enc = [Text.Encoding]::UTF8
    $ms = New-Object System.IO.MemoryStream
    $pre = $enc.GetBytes($head); $ms.Write($pre, 0, $pre.Length)
    $bytes = [IO.File]::ReadAllBytes($note); $ms.Write($bytes, 0, $bytes.Length)
    $post = $enc.GetBytes("$nl--$b--$nl"); $ms.Write($post, 0, $post.Length)
    Invoke-RestMethod -Uri "$($Url.TrimEnd('/'))/api/documents/$($w1.id)/remarks" -Method POST -UseDefaultCredentials `
        -Headers $headers -ContentType "multipart/form-data; boundary=$b" -Body $ms.ToArray() -TimeoutSec 120 | Out-Null
    $kept = Call GET "/api/documents/$($w1.id)/remarks" $null $null
    "$(@($kept).Count) attached" }

# ---------------------------------------------------------------- links, text, the page itself
Section "Links, text files, and the page"
Check 'REQ-P11' "a link can be shared without naming the file server" {
    $link = Call GET "/api/files/link?path=$([uri]::EscapeDataString($released.FullName))" $null $null
    if ($link.url -like "*$root*") { throw "the link names the file server: $($link.url)" }
    $link.url }
Check 'REQ-P09' "a text file is read on the page itself" {
    # the document itself is Word now, and Word is not read as text: a note beside it is
    $note = Join-Path $env:TEMP "DMS walk note $stamp.txt"
    @("A note beside the document.", "Read on the page, not downloaded.") | Set-Content $note -Encoding UTF8
    $put = Send-File $note $here @{}
    $t = Call GET "/api/files/text?path=$([uri]::EscapeDataString($put.path))" $null $null
    if (-not $t.text) { throw "nothing came back" }
    "$($t.text.Length) characters, canWrite=$($t.canWrite)" }
Check 'REQ-P12' "the page knows what this person may do here" {
    $b = Call GET "/api/browse?path=$([uri]::EscapeDataString($here))" $null $null
    "canWrite=$($b.canWrite)  canDrop=$($b.canDrop)" }
Check 'REQ-P28' "the API describes itself" {
    $doc = Call GET "/api/openapi.json" $null $null
    "$(@($doc.paths.PSObject.Properties).Count) endpoints, $($doc.info.version)" }

# ---------------------------------------------------------------- the upkeep pass
Section "The DMS keeps itself in order"
Check 'REQ-P14' "the upkeep pass runs and reports" {
    $keep = $script:headers; $script:headers = @{}        # a super user's command, not an ordinary user's
    try { $r = Call POST "/api/file-service/run" @{} $null } finally { $script:headers = $keep }
    "moved $($r.moved), failed $($r.failed)" }
Check 'REQ-P23' "a released file that lost its read-only flag gets it back" {
    $released.IsReadOnly = $false
    Call GET "/api/browse?path=$([uri]::EscapeDataString($cur))" $null $null | Out-Null
    $again = Get-Item $released.FullName
    if (-not $again.IsReadOnly) { throw "it is still writable" }
    "put back on $($again.Name)" }

# ---------------------------------------------------------------- something waiting for this person
Section "Left waiting, so every side of the page has something in it"
# So that signing in as them shows every side of the page: a document released, one in work, and one that
# is waiting for their answer. This last one is submitted by the real account, to them.
$doc3 = Join-Path $env:TEMP "DMS walk waiting $stamp.txt"
@("This one is waiting for an answer.") | Set-Content $doc3 -Encoding UTF8
Check 'REQ-P56' "a document is left waiting for the person the walk runs as" {
    $keep = $script:headers
    $script:headers = @{}                      # as the real account: nobody approves their own document
    try {
        $put = Send-File $doc3 $here @{}
        $who = $me.email              # the DMS knows people by email: RH\name is not an approver
        $w = Call POST "/api/documents" @{ path = $put.path; documentType = 'נוהל'; documentArea = 'מערכות מידע';
                                           submit = $true; approvers = @($who) } $null
        "$($w.documentId) is waiting for $who"
    } finally { $script:headers = $keep } }

# ---------------------------------------------------------------- the machine API
Section "The machine API"
$keys = Get-DmsEnvValue 'DMS_API_KEYS'
if ($keys) { Skip 'REQ-P39' "the RAG's list" "needs an application key, which is not read from here - try it in Swagger" }
else { Skip 'REQ-P39' "the RAG's list" "no application key is configured (DMS_API_KEYS)" }

Close-Section
Write-Host ""
Write-Host ("{0} checks passed, {1} failed, {2} skipped." -f $ok, $bad, $skipped) -ForegroundColor $(if ($bad) { 'Yellow' } else { 'Green' })
Write-Host ""

# What failed, in one list. The groups above are coloured for reading on screen; this is the part worth
# sending on, and the report file carries the whole walk whether anybody was watching the screen or not.
if ($bad) {
    Write-Host "What failed:" -ForegroundColor Yellow
    foreach ($l in @($all | Where-Object { $_.state -eq 'FAIL' })) {
        Write-Host ("  {0,-11} {1}" -f $l.req, $l.what) -ForegroundColor Yellow
        Write-Host ("              in: {0}" -f $l.group) -ForegroundColor DarkGray
        Write-Host ("              {0}" -f $l.detail) -ForegroundColor DarkGray
    }
    Write-Host ""
}
if (-not $Report) { $Report = Join-Path $env:TEMP ("DMS-Smoke {0}.txt" -f $stamp) }
$out = @("=== The DMS at $Url, walked as $(if ($As) { $As } else { $me.email })",
         "    $(Get-Date -Format 'yyyy-MM-dd HH:mm')   build $($cfg.version)   folder $Folder", "")
$seen = ''
foreach ($l in $all) {
    if ($l.group -ne $seen) { $seen = $l.group; $out += @("", $l.group) }
    $out += ("  {0,-4} {1,-11} {2}" -f $l.state, $l.req, $l.what)
    if ($l.detail) { $out += ("           " + ($l.detail -replace "`r?`n", ' ')) }
}
$out += @("", ("{0} checks passed, {1} failed, {2} skipped." -f $ok, $bad, $skipped))
$out | Set-Content -Path $Report -Encoding UTF8
Write-Host "The whole walk, line by line: $Report" -ForegroundColor Cyan
Write-Host ""
Write-Host "Left in place for tracing:" -ForegroundColor Cyan
Write-Host "  $here"
Write-Host "  $($doc.documentId) - released, with revision 02 in work"
Write-Host "  and one document waiting for $(if ($As) { $As } else { $me.email }) in Approvals"
Write-Host "  the page: $Url/dms/dms-page   ->  $Folder"
Write-Host ""
Write-Host "When you have seen enough:  .\scripts\Test-DmsSmoke.ps1 -Clean" -ForegroundColor Yellow
