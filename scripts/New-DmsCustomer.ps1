<#
.SYNOPSIS
    A new customer, cut from the customer skeleton - its folders and the AD permissions on them.
.DESCRIPTION
    One folder under 02_Customers is kept as the shape of a customer: Customer_Skeleton. A new customer is
    that folder's tree copied, with the NTFS permissions each folder carries (the AD groups, and the broken
    inheritance where a department's folder is closed) - which the blueprint cannot carry, because they live
    on the folders and not in a list of names.

    Nothing inside the skeleton's folders is copied: it keeps no documents, and the DMS refuses to file one
    there.

    The DMS does the same thing when somebody makes a customer folder on the page; this is for making several
    at once, or for a server where the DMS is not running yet.

    Run on the file server, as someone who may read the skeleton's permissions and write under 02_Customers.
.EXAMPLE
    .\scripts\New-DmsCustomer.ps1 -Name Elbit -WhatIf
.EXAMPLE
    .\scripts\New-DmsCustomer.ps1 -Name 'Elbit','Rafael'
.EXAMPLE
    # the one-time rename of the old sample customer into the skeleton
    .\scripts\New-DmsCustomer.ps1 -MakeSkeletonFrom Customer_A
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string[]]$Name = @(),
    [string]$Root = '',
    [string]$CustomersFolder = '02_Customers',
    [string]$Skeleton = 'Customer_Skeleton',
    [string]$MakeSkeletonFrom = '',                  # rename an existing customer into the skeleton, once
    [switch]$Access                                  # also run Set-DmsAccess.ps1 for each new customer
)

$ErrorActionPreference = 'Stop'

if (-not $Root) {
    $envFile = Join-Path $PSScriptRoot '..\webapi\.env'
    if (Test-Path -LiteralPath $envFile) {
        $line = Select-String -LiteralPath $envFile -Pattern '^\s*DMS_REPOSITORY_ROOT\s*=' | Select-Object -First 1
        if ($line) { $Root = ($line.Line -replace '^\s*DMS_REPOSITORY_ROOT\s*=', '' -replace '\s+#.*$', '').Trim() }
    }
}
if (-not $Root) { throw "The repository root was not found in webapi\.env: give it with -Root" }
$customers = Join-Path $Root $CustomersFolder
if (-not (Test-Path -LiteralPath $customers)) { throw "There is no $customers" }

if ($MakeSkeletonFrom) {
    $from = Join-Path $customers $MakeSkeletonFrom
    if (-not (Test-Path -LiteralPath $from)) { throw "There is no $from" }
    $to = Join-Path $customers $Skeleton
    if (Test-Path -LiteralPath $to) { throw "$to already exists" }
    if ($PSCmdlet.ShouldProcess($from, "rename to $Skeleton")) {
        Rename-Item -LiteralPath $from -NewName $Skeleton
        Write-Host "  [ok]   $MakeSkeletonFrom is now $Skeleton" -ForegroundColor Green
        Write-Host "  note   its documents are still in it; the DMS keeps the folders and files nothing new there." -ForegroundColor DarkGray
        Write-Host "  note   a document registered under the old name: run .\scripts\Sync-DmsFileServer.ps1 -Write" -ForegroundColor DarkGray
    }
}

$shape = Join-Path $customers $Skeleton
if ($Name.Count -and -not (Test-Path -LiteralPath $shape)) {
    throw "The skeleton was not found: $shape (make one with -MakeSkeletonFrom <an existing customer>)"
}

foreach ($one in $Name) {
    $target = Join-Path $customers $one
    if (Test-Path -LiteralPath $target) { Write-Host "  [skip] $one is already there" -ForegroundColor DarkGray; continue }
    if (-not $PSCmdlet.ShouldProcess($target, "cut from $Skeleton")) { continue }
    # /E every folder, /XF * none of the files in them, /COPYALL the permissions and the owner with each folder
    $out = robocopy $shape $target /E /XF * /COPYALL /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) {
        Write-Host "  [warn] $one : robocopy $LASTEXITCODE - the folders may be there without their permissions" -ForegroundColor Yellow
        Write-Host ($out | Select-Object -Last 5) -ForegroundColor DarkGray
    } else {
        $n = (Get-ChildItem -LiteralPath $target -Recurse -Directory -ErrorAction SilentlyContinue).Count
        Write-Host "  [ok]   $one : $n folders, with their permissions" -ForegroundColor Green
    }
    if ($Access) {
        $script = Join-Path $PSScriptRoot 'Set-DmsAccess.ps1'
        if (Test-Path -LiteralPath $script) { & $script -Root $Root -Customer $one -Apply }
        else { Write-Host "  [warn] Set-DmsAccess.ps1 was not found beside this script" -ForegroundColor Yellow }
    }
}
