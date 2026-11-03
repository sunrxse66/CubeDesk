param(
    [Parameter(Mandatory=$true)][int]$ParentPid,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$Candidate,
    [Parameter(Mandatory=$true)][string]$Sha256,
    [Parameter(Mandatory=$true)][string]$ExpectedVersion,
    [Parameter(Mandatory=$true)][string]$HealthToken,
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$DataDir
)
$ErrorActionPreference = 'Stop'
$Target = [IO.Path]::GetFullPath($Target)
$Candidate = [IO.Path]::GetFullPath($Candidate)
$DataDir = [IO.Path]::GetFullPath($DataDir)
$Backup = $Target + '.previous'
$ResultPath = Join-Path $DataDir 'updates/update-result.json'
$StartedApp = $null
$MovedOld = $false

function Save-Result([string]$Status, [string]$Message) {
    $result = @{status=$Status; version=$ExpectedVersion; message=$Message; time=(Get-Date).ToUniversalTime().ToString('o')}
    $tempPath = $ResultPath + '.tmp'
    $result | ConvertTo-Json | Set-Content -LiteralPath $tempPath -Encoding UTF8
    Move-Item -LiteralPath $tempPath -Destination $ResultPath -Force
}

function Launch-App([bool]$CheckHealth) {
    $launchArgs = @('--no-browser', '--port', "$Port", '--data-dir', ('"' + $DataDir + '"'))
    if ($CheckHealth) { $launchArgs += @('--update-health', $HealthToken) }
    return Start-Process -FilePath $Target -ArgumentList $launchArgs -WorkingDirectory ([IO.Path]::GetDirectoryName($Target)) -WindowStyle Hidden -PassThru
}

function Stop-NewApp {
    if ($null -eq $StartedApp) { return }
    # PyInstaller onefile has a parent bootloader and one child. Stop only this launch.
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($StartedApp.Id)" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        if ($child.ExecutablePath -and [IO.Path]::GetFullPath($child.ExecutablePath) -eq $Target) {
            Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($StartedApp.Id)" -ErrorAction SilentlyContinue
    if ($parent -and $parent.ExecutablePath -and [IO.Path]::GetFullPath($parent.ExecutablePath) -eq $Target) {
        Stop-Process -Id $StartedApp.Id -Force -ErrorAction SilentlyContinue
    }
}

try {
    $stageRoot = [IO.Path]::GetFullPath((Join-Path $DataDir 'updates')) + [IO.Path]::DirectorySeparatorChar
    if (-not $Candidate.StartsWith($stageRoot, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetExtension($Target) -ne '.exe' -or $Target -eq $Candidate) {
        throw 'Invalid executable or staging path.'
    }
    if ((Get-FileHash -LiteralPath $Candidate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha256) {
        throw 'Downloaded executable checksum mismatch.'
    }
    # Wait for the HTTP reply and old child to exit, then for the onefile bootloader lock.
    $old = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
    if ($old -and -not $old.WaitForExit(60000)) { throw 'The previous application did not exit.' }
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while (-not $MovedOld) {
        try {
            if (Test-Path -LiteralPath $Backup) { Remove-Item -LiteralPath $Backup -Force }
            Move-Item -LiteralPath $Target -Destination $Backup
            $MovedOld = $true
        } catch {
            if ([DateTime]::UtcNow -ge $deadline) { throw }
            Start-Sleep -Milliseconds 300
        }
    }
    Copy-Item -LiteralPath $Candidate -Destination $Target
    if ((Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha256) {
        throw 'Installed executable checksum mismatch.'
    }
    $StartedApp = Launch-App $true
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
            if ($health.app -eq 'CubeDesk' -and $health.version -eq $ExpectedVersion -and $health.update_nonce -eq $HealthToken) {
                Save-Result 'installed' 'CubeDesk updated successfully.'
                exit 0
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw 'The new version failed its startup health check.'
} catch {
    $failureMessage = $_.Exception.Message
    if ($MovedOld) {
        Stop-NewApp
        try {
            # Every path is a named sibling file; no directory or recursive removal is used.
            $deadline = [DateTime]::UtcNow.AddSeconds(20)
            while ($true) {
                try {
                    if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Force }
                    Move-Item -LiteralPath $Backup -Destination $Target
                    break
                } catch {
                    if ([DateTime]::UtcNow -ge $deadline) { throw }
                    Start-Sleep -Milliseconds 300
                }
            }
            Save-Result 'rolled_back' $failureMessage
            $StartedApp = Launch-App $false
        } catch {
            Save-Result 'error' ($failureMessage + ' Rollback failed: ' + $_.Exception.Message + ' Previous executable: ' + $Backup)
        }
    } else {
        Save-Result 'error' $failureMessage
        # The original file is untouched; restart if the parent has already exited.
        if (-not (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)) { $StartedApp = Launch-App $false }
    }
    exit 1
}
