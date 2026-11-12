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
        if ($k.Trim() -eq $Name) {
            # a comment after the value (" # ..."), the way the DMS reads its own .env
            return ($v -replace '\s+#.*$', '').Trim().Trim("'", '"')
        }
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
            # Ask IIS rather than guess: the site whose folder holds these scripts is the one they belong
            # to, whatever it is called - DMS, DMS-Pilot or anything else. A name is assumed only where
            # IIS cannot be read at all (a PC that just maps the drive).
            $app = (Split-Path -Parent $PSScriptRoot).ToLower().TrimEnd('\')
            try {
                Import-Module WebAdministration -ErrorAction Stop
                $all = @(Get-Website)
                $mine = @($all | Where-Object {
                    $p = "$($_.physicalPath)".ToLower().TrimEnd('\')
                    $p -and ($app -eq $p -or $app.StartsWith($p + '\') -or $p.StartsWith($app + '\'))
                })
                if ($mine.Count -and $mine[0].Name) { return "$($mine[0].Name)" }
                $named = @($all | Where-Object { $_.Name -eq 'DMS' -or $_.Name -eq 'DMS-Pilot' })
                if ($named.Count) { return "$($named[0].Name)" }
            } catch { }
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
