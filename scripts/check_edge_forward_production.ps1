[CmdletBinding()]
param(
    [string]$OutputRoot,
    [switch]$SkipTaskInspection
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Split-Path -Parent $PSScriptRoot)
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot 'data\collector_cache\edge_forward_health'
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$tracePath = Join-Path $OutputRoot 'run-trace.log'
function Write-HealthTrace {
    param([Parameter(Mandatory)][string]$Stage)
    Add-Content -LiteralPath $tracePath -Value "$([datetime]::UtcNow.ToString('o')) pid=$PID stage=$Stage"
}
Write-HealthTrace -Stage 'start'

$exeTaskName = 'KrakenEdge-H-EXE-Technical'
$wofTaskName = 'KrakenEdge-H-WOF-Forward'
$expectedPython = (Resolve-Path -LiteralPath (Join-Path $repoRoot '.venv\Scripts\python.exe')).Path
$expectedExeArguments = 'scripts\run_execution_toxicity_ops_once.py --duration-seconds 3580 --storage-cap-gib 200'
$expectedWofArguments = 'scripts\collect_world_order_flow_forward.py collect-scheduled'
$reasons = [System.Collections.Generic.List[string]]::new()

function Get-TaskSnapshot {
    param(
        [Parameter(Mandatory)][string]$TaskName,
        [Parameter(Mandatory)][string]$ExpectedArguments
    )

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        $reasons.Add("TASK_MISSING:$TaskName")
        return $null
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    $action = @($task.Actions)[0]
    if ($action.Execute -ne $expectedPython) {
        $reasons.Add("TASK_EXECUTABLE_MISMATCH:$TaskName")
    }
    if ($action.Arguments -ne $ExpectedArguments) {
        $reasons.Add("TASK_ARGUMENTS_MISMATCH:$TaskName")
    }
    if ($action.WorkingDirectory -ne $repoRoot) {
        $reasons.Add("TASK_WORKDIR_MISMATCH:$TaskName")
    }
    if ($task.State -notin @('Ready', 'Running')) {
        $reasons.Add("TASK_STATE_INVALID:${TaskName}:$($task.State)")
    }
    if ($task.State -eq 'Ready' -and $info.LastRunTime -gt [datetime]::MinValue -and $info.LastTaskResult -ne 0) {
        $reasons.Add("TASK_LAST_RESULT_NONZERO:${TaskName}:$('{0:X8}' -f $info.LastTaskResult)")
    }
    return [ordered]@{
        name = $TaskName
        state = [string]$task.State
        last_run_time = if ($info.LastRunTime -gt [datetime]::MinValue) { $info.LastRunTime.ToUniversalTime().ToString('o') } else { $null }
        last_task_result = ('{0:X8}' -f $info.LastTaskResult)
        next_run_time = if ($info.NextRunTime -gt [datetime]::MinValue) { $info.NextRunTime.ToUniversalTime().ToString('o') } else { $null }
        execute = $action.Execute
        arguments = $action.Arguments
        working_directory = $action.WorkingDirectory
    }
}

if ($SkipTaskInspection) {
    $exeTask = [ordered]@{ inspection = 'skipped_in_scheduled_context' }
    $wofTask = [ordered]@{ inspection = 'skipped_in_scheduled_context' }
} else {
    $exeTask = Get-TaskSnapshot -TaskName $exeTaskName -ExpectedArguments $expectedExeArguments
    $wofTask = Get-TaskSnapshot -TaskName $wofTaskName -ExpectedArguments $expectedWofArguments
}
Write-HealthTrace -Stage 'task-inspection-complete'

$now = [datetime]::UtcNow
$hExeRoot = Join-Path $repoRoot 'data\collector_cache\kraken_execution_toxicity_hexe001'
$technicalGateRoot = Join-Path $hExeRoot 'technical\ops\technical_gates'
$hasTechnicalGate = Get-ChildItem -LiteralPath $technicalGateRoot -Filter 'technical-gate-*.json' -File -ErrorAction SilentlyContinue |
    Select-Object -First 1
$hExePhase = if ($hasTechnicalGate) { 'validation' } else { 'technical' }
$rawRoot = Join-Path $hExeRoot "$hExePhase\sessions"
$latestRaw = Get-ChildItem -LiteralPath $rawRoot -Filter '*.jsonl.gz' -Recurse -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
$rawAgeMinutes = $null
if (-not $latestRaw) {
    $reasons.Add('H_EXE_RAW_MISSING')
} else {
    $rawAgeMinutes = ($now - $latestRaw.LastWriteTimeUtc).TotalMinutes
}
Write-HealthTrace -Stage 'raw-check-complete'

$latestProgress = Get-ChildItem -LiteralPath $rawRoot -Filter 'progress.json' -Recurse -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
$progressPayload = $null
$progressAgeMinutes = $null
if (-not $latestProgress) {
    $reasons.Add('H_EXE_PROGRESS_MISSING')
} else {
    $progressAgeMinutes = ($now - $latestProgress.LastWriteTimeUtc).TotalMinutes
    if ($progressAgeMinutes -gt 2) {
        $reasons.Add('H_EXE_PROGRESS_STALE_GT_2_MIN')
    }
    try {
        $progressPayload = Get-Content -LiteralPath $latestProgress.FullName -Raw | ConvertFrom-Json
        if ($progressPayload.schema_version -ne 'h-exe-001-progress-v1') {
            $reasons.Add('H_EXE_PROGRESS_SCHEMA_INVALID')
        }
        if ([long]$progressPayload.event_count -le 0) {
            $reasons.Add('H_EXE_PROGRESS_EVENT_COUNT_EMPTY')
        }
        if ($progressPayload.credentials_used -ne $false -or [int]$progressPayload.orders_sent -ne 0) {
            $reasons.Add('H_EXE_PROGRESS_SAFETY_INVARIANT_FAILED')
        }
    } catch {
        $reasons.Add('H_EXE_PROGRESS_JSON_INVALID')
    }
}
Write-HealthTrace -Stage 'progress-check-complete'

$snapshotRoots = @(
    (Join-Path $repoRoot 'data\collector_cache\world_order_flow_forward\snapshot_days'),
    (Join-Path $repoRoot 'data\collector_cache\world_order_flow_forward\kraken_universe_days')
)
$snapshotState = [System.Collections.Generic.List[object]]::new()
foreach ($snapshotRoot in $snapshotRoots) {
    $latest = Get-ChildItem -LiteralPath $snapshotRoot -Filter '*.json' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $latest) {
        $reasons.Add("WOF_SNAPSHOT_MISSING:$snapshotRoot")
        continue
    }
    $ageHours = ($now - $latest.LastWriteTimeUtc).TotalHours
    if ($ageHours -gt 48) {
        $reasons.Add("WOF_SNAPSHOT_STALE_GT_48_HOURS:$snapshotRoot")
    }
    $snapshotState.Add([ordered]@{
        path = $latest.FullName
        bytes = $latest.Length
        age_hours = [math]::Round($ageHours, 3)
        last_write_utc = $latest.LastWriteTimeUtc.ToString('o')
    })
}
Write-HealthTrace -Stage 'snapshot-check-complete'

$driveName = ([System.IO.Path]::GetPathRoot($repoRoot)).TrimEnd('\').TrimEnd(':')
$drive = Get-PSDrive -Name $driveName
$freeGiB = $drive.Free / 1GB
if ($freeGiB -lt 250) {
    $reasons.Add('DISK_FREE_BELOW_250_GIB')
}
Write-HealthTrace -Stage 'disk-check-complete'

$payload = [ordered]@{
    schema_version = 'edge-forward-production-health-v1'
    generated_at = $now.ToString('o')
    healthy = ($reasons.Count -eq 0)
    reason_codes = @($reasons)
    credentials_used = $false
    orders_sent = 0
    tasks = [ordered]@{
        h_exe = [ordered]@{
            scheduler = $exeTask
            collection_phase = $hExePhase
        }
        h_wof = $wofTask
    }
    h_exe_raw = if ($latestRaw) {
        [ordered]@{
            path = $latestRaw.FullName
            bytes = $latestRaw.Length
            age_minutes = [math]::Round($rawAgeMinutes, 3)
            state = if ($latestRaw.Length -gt 0) { 'receiving' } else { 'rotation_grace' }
            last_write_utc = $latestRaw.LastWriteTimeUtc.ToString('o')
        }
    } else { $null }
    h_exe_progress = if ($latestProgress) {
        [ordered]@{
            path = $latestProgress.FullName
            age_minutes = [math]::Round($progressAgeMinutes, 3)
            event_count = if ($progressPayload) { [long]$progressPayload.event_count } else { $null }
            last_exchange_timestamp_ms = if ($progressPayload) { [long]$progressPayload.last_exchange_timestamp_ms } else { $null }
            last_write_utc = $latestProgress.LastWriteTimeUtc.ToString('o')
        }
    } else { $null }
    h_wof_snapshots = @($snapshotState)
    disk_free_gib = [math]::Round($freeGiB, 3)
}
Write-HealthTrace -Stage 'payload-built'

$digestRoot = Join-Path $OutputRoot 'digests'
New-Item -ItemType Directory -Path $digestRoot -Force | Out-Null
$stamp = $now.ToString('yyyyMMddTHHmmss.fffffffZ')
$json = $payload | ConvertTo-Json -Depth 8
$digestPath = Join-Path $digestRoot "digest-$stamp.json"
$digestTemp = "$digestPath.tmp"
[System.IO.File]::WriteAllText($digestTemp, $json, [System.Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $digestTemp -Destination $digestPath
$latestPath = Join-Path $OutputRoot 'latest.json'
$latestTemp = "$latestPath.tmp"
[System.IO.File]::WriteAllText($latestTemp, $json, [System.Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $latestTemp -Destination $latestPath -Force
Write-HealthTrace -Stage 'digest-written'

Write-Output $json
Write-Output "digest=$digestPath"
if ($payload.healthy) {
    Write-HealthTrace -Stage 'exit-0'
    exit 0
}
Write-HealthTrace -Stage 'exit-2'
exit 2
