<#
    Where the scripts get their defaults, so no script carries the name of one installation.

    Dot-source it after param() and fill in what the caller left empty:

        param([string]$Url = '', [string]$Site = '', [string]$App = '')
        . "$PSScriptRoot\_DmsDefaults.ps1"
        if (-not $Url)  { $Url  = Get-DmsDefault Url }
        if (-not $Site) { $Site = Get-DmsDefault Site }
        if (-not $App)  { $App  = Get-DmsDefault App }

    In order: the environment variable (DMS_URL, DMS_IIS_SITE), then webapi\.env beside the script
    (DMS_PAGE_URL for the address), then the plain production name. An installation that is still called
    something else only has to say so once, in its own .env or in the call.
#>

function Get-DmsEnvFile {
    $root = Split-Path -Parent $PSScriptRoot
    $here = Join-Path $root 'webapi\.env'
    if (Test-Path $here) { return $here }
    return ''
}

function Get-DmsEnvValue([string]$Name) {
    $file = Get-DmsEnvFile
    if (-not $file) { return '' }
    foreach ($line in Get-Content $file) {                 # the first occurrence wins, as the DMS reads it
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $k, $v = $line -split '=', 2
        if ($k.Trim() -eq $Name) { return $v.Trim() }
    }
    return ''
}

function Get-DmsDefault([ValidateSet('Url', 'Site', 'App')][string]$What) {
    switch ($What) {
        'Url' {
            if ($env:DMS_URL) { return $env:DMS_URL.TrimEnd('/') }
            $page = Get-DmsEnvValue 'DMS_PAGE_URL'         # https://dms.rh.tech/dms/dms-page?lang=HE
            if ($page -match '^(https?://[^/]+)') { return $Matches[1] }
            return 'https://dms.rh.tech'
        }
        'Site' {
            if ($env:DMS_IIS_SITE) { return $env:DMS_IIS_SITE }
            # Ask IIS rather than guess: the site whose folder is this installation is the one these
            # scripts belong to, whatever it is called - DMS, DMS-Pilot or anything else. Only when IIS
            # cannot be read (a PC that just maps the drive) is a name assumed.
            $app = Split-Path -Parent $PSScriptRoot
            if (Get-Module -ListAvailable -Name WebAdministration) {
                try {
                    Import-Module WebAdministration -ErrorAction Stop
                    $sites = @(Get-ChildItem IIS:\Sites -ErrorAction Stop)
                    $mine = $sites | Where-Object {
                        $p = $_.physicalPath
                        $p -and ((Join-Path $p '') -like (Join-Path $app '*') -or $app -like ((Join-Path $p '') + '*'))
                    }
                    if ($mine) { return $mine[0].Name }
                    $named = $sites | Where-Object { $_.Name -in @('DMS', 'DMS-Pilot') }
                    if ($named) { return $named[0].Name }
                } catch { }
            }
            return 'DMS'
        }
        'App' {
            $root = Split-Path -Parent $PSScriptRoot
            $here = Join-Path $root 'webapi'
            if (Test-Path $here) { return $here }          # the installation these scripts belong to
            return 'C:\DMS\app\webapi'
        }
    }
}
