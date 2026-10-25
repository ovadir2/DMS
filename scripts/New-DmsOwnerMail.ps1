<#
.SYNOPSIS
    A short letter for each department's owners: the folder they are responsible for in 01_General, and the
    parallel folders of every customer that go with it.
.DESCRIPTION
    scripts\dms-access.csv already says it - each department has its AD group and the customer folders that
    carry the same access. People do not read a CSV, so this turns each row into one short letter.

    It writes the drafts to a folder and never sends anything: read them, then send from Outlook.
.EXAMPLE
    .\scripts\New-DmsOwnerMail.ps1
.EXAMPLE
    .\scripts\New-DmsOwnerMail.ps1 -Department Commercial -Language EN
#>
[CmdletBinding()]
param(
    [string]$Csv        = (Join-Path $PSScriptRoot 'dms-access.csv'),
    [string]$OutDir     = (Join-Path $PSScriptRoot 'out\owner-mail'),
    [string]$Department = '',
    [ValidateSet('HE', 'EN')][string]$Language = 'HE',
    [string]$DmsUrl     = 'https://dms-pilot.rh.tech'
)

$rows = Import-Csv -LiteralPath $Csv | Where-Object { $_.Department -and $_.Department -ne '01_General' }
if ($Department) { $rows = $rows | Where-Object Department -eq $Department }
if (-not $rows) { throw "No department rows in $Csv" }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

foreach ($r in $rows) {
    $dep   = $r.Department
    $subs  = @($r.CustomerFolders -split ';' | Where-Object { $_ })
    $owner = $r.Groups
    $list  = if ($subs) { ($subs | ForEach-Object { "02_Customers\<לקוח>\$_" }) -join "`r`n  " } else { '' }

    if ($Language -eq 'HE') {
        $subject = "אחריות על תיקיית $dep ב-DMS"
        $body = @"
שלום,

במערכת ניהול המסמכים (DMS) אתם בעלי האחריות על התיקייה:

  01_General\$dep

האחריות הזאת חלה גם על התיקיות המקבילות אצל כל לקוח:

  $(if ($list) { $list } else { "אין תיקיות מקבילות אצל לקוחות עבור $dep" })

כלומר אותם כללים בדיוק: מי שרשאי לראות ולערוך ב-01_General רשאי גם שם, מסמך מאושר הוא לקריאה בלבד,
וכל שינוי עובר בתהליך אישור ב-DMS ולא ישירות בשרת הקבצים.

הגישה ניתנת דרך הקבוצה $owner. בקשה להוספה או להסרה של אדם - פנו ל-IT ולא דרך הרשאות בתיקייה.

ה-DMS: $DmsUrl

תודה,
בקרת מסמכים
"@
    } else {
        $subject = "Ownership of the $dep folder in the DMS"
        $body = @"
Hello,

In the document management system (DMS) you are the owners of:

  01_General\$dep

The same responsibility covers the parallel folder of every customer:

  $(if ($list) { ($subs | ForEach-Object { "02_Customers\<customer>\$_" }) -join "`r`n  " } else { "no parallel customer folders for $dep" })

The rules there are the same: whoever may read and edit in 01_General may do so there, an approved document
is read only, and a change goes through the approval workflow in the DMS rather than on the file server.

Access is given through $owner. To add or remove a person, ask IT - not by changing permissions on the folder.

The DMS: $DmsUrl

Thank you,
Document Control
"@
    }

    $file = Join-Path $OutDir ("{0}.{1}.txt" -f $dep, $Language)
    "Subject: $subject`r`nTo: $owner`r`n`r`n$body" | Set-Content -LiteralPath $file -Encoding UTF8
    Write-Host "written  $file"
}

Write-Host "`nDrafts in $OutDir - read them, then send from Outlook. Nothing was sent."
