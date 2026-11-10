param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$rootPattern = [regex]::Escape($workspaceRoot + '\')
$entryPattern = $rootPattern + '(?:maya\.py|serve\\server\.py)(?=[\s"]|$)'

try {
    $snapshot = @(Get-CimInstance Win32_Process)
    $seeds = @($snapshot | Where-Object {
        $command = [string]$_.CommandLine
        $engine = $_.Name -in @('maya.exe', 'maya-vision.exe') -and (
            ([string]$_.ExecutablePath).StartsWith($workspaceRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $command -match ('^\s*"?' + $rootPattern))
        $pythonEntry = $_.Name -match '^pythonw?\.exe$' -and (
            $command -match $entryPattern -or
            ($command -match $rootPattern -and $command -match '(?:^|\s)-m\s+serve\.server(?:\s|$)'))
        $engine -or $pythonEntry
    })
    if ($seeds.Count -eq 0) {
        Write-Host 'No Maya process from this project is running.'
        exit 0
    }
    $owned = @{}
    foreach ($item in $seeds) { $owned[[int]$item.ProcessId] = $item }
    do {
        $added = $false
        foreach ($item in $snapshot) {
            if (-not $owned.ContainsKey([int]$item.ProcessId) -and $owned.ContainsKey([int]$item.ParentProcessId)) {
                $owned[[int]$item.ProcessId] = $item
                $added = $true
            }
        }
    } while ($added)
    $owned.Values | Sort-Object ProcessId | Select-Object ProcessId, Name, CommandLine | Format-Table -AutoSize -Wrap
    if ($DryRun) { Write-Host 'Dry run: no process was stopped.'; exit 0 }

    # Closing the launcher/server closes its child pipes, allowing the engine to
    # finish through its normal EOF/QUIT handling before the fallback below.
    foreach ($item in $seeds | Where-Object { $_.Name -match '^pythonw?\.exe$' }) {
        Stop-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
    }
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(15)
    do {
        $remaining = @(Get-CimInstance Win32_Process | Where-Object {
            $owned.ContainsKey([int]$_.ProcessId) -and $_.CreationDate -and
            $_.CreationDate -eq $owned[[int]$_.ProcessId].CreationDate
        })
        if ($remaining.Count -eq 0) { Write-Host 'Maya stopped.'; exit 0 }
        Start-Sleep -Milliseconds 500
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    foreach ($item in $remaining) {
        $live = Get-CimInstance Win32_Process -Filter "ProcessId=$($item.ProcessId)"
        if ($live -and $live.CreationDate -eq $item.CreationDate) {
            try { Stop-Process -Id $item.ProcessId -Force -ErrorAction Stop }
            catch {
                $stillThere = Get-CimInstance Win32_Process -Filter "ProcessId=$($item.ProcessId)"
                if ($stillThere -and $stillThere.CreationDate -eq $item.CreationDate) { throw }
            }
        }
    }
    Write-Host 'Maya stopped (remaining child processes terminated).'
} catch {
    Write-Host ('Failed to stop Maya: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
