[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$Replace
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) {
    $PythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
$python = (Resolve-Path -LiteralPath $PythonPath).Path
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$exeTaskName = 'KrakenEdge-H-EXE-Technical'
$wofTaskName = 'KrakenEdge-H-WOF-Forward'
$healthTaskName = 'KrakenEdge-Forward-Health'

function Assert-TaskCanBeRegistered {
    param([Parameter(Mandatory)][string]$TaskName)

    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing -and -not $Replace) {
        throw "Scheduled task already exists: $TaskName. Use -Replace only after reviewing it."
    }
    if ($existing -and $Replace) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
}

Assert-TaskCanBeRegistered -TaskName $exeTaskName
Assert-TaskCanBeRegistered -TaskName $wofTaskName
Assert-TaskCanBeRegistered -TaskName $healthTaskName

$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited

$exeAction = New-ScheduledTaskAction `
    -Execute $python `
    -Argument 'scripts\run_execution_toxicity_ops_once.py --duration-seconds 3580 --storage-cap-gib 100' `
    -WorkingDirectory $repoRoot
$exeTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$exeSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun `
    -Hidden `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 65)

$wofAction = New-ScheduledTaskAction `
    -Execute $python `
    -Argument 'scripts\collect_world_order_flow_forward.py collect-scheduled' `
    -WorkingDirectory $repoRoot
$wofTrigger = New-ScheduledTaskTrigger -Daily -At '02:15'
$wofSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun `
    -Hidden `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$healthScript = Join-Path $repoRoot 'scripts\check_edge_forward_production.ps1'
$healthAction = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$healthScript`" -SkipTaskInspection" `
    -WorkingDirectory $repoRoot
$healthTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$healthSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun `
    -Hidden `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $exeTaskName `
    -Action $exeAction `
    -Trigger $exeTrigger `
    -Settings $exeSettings `
    -Principal $principal `
    -Description 'H-EXE-001 public Kraken shadow collection; no credentials or orders.' | Out-Null

Register-ScheduledTask `
    -TaskName $wofTaskName `
    -Action $wofAction `
    -Trigger $wofTrigger `
    -Settings $wofSettings `
    -Principal $principal `
    -Description 'H-WOF-002 causal public-data journal; no credentials or orders.' | Out-Null

Register-ScheduledTask `
    -TaskName $healthTaskName `
    -Action $healthAction `
    -Trigger $healthTrigger `
    -Settings $healthSettings `
    -Principal $principal `
    -Description 'Local fail-closed health digest for H-EXE/H-WOF shadow production.' | Out-Null

Get-ScheduledTask -TaskName $exeTaskName, $wofTaskName, $healthTaskName |
    Select-Object TaskName, State, Author
