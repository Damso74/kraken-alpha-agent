# Phase 30 - VPS/local observation once (cache refresh + daemon + reports).
# Usage: powershell -File scripts/ops_run_observation_once_phase30.ps1
# Env: KRAKEN_ALPHA_ROOT overrides repo root detection.

$ErrorActionPreference = "Stop"

if ($env:KRAKEN_ALPHA_ROOT) {
    $RepoRoot = (Resolve-Path $env:KRAKEN_ALPHA_ROOT).Path
} else {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

Set-Location $RepoRoot

$ObsBase = Join-Path $RepoRoot "reports\paper_observation_phase28"
$OpsLogs = Join-Path $ObsBase "ops_logs"
$StopFlag = Join-Path $ObsBase "STOP_OBSERVATION"
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
$LogFile = Join-Path $OpsLogs "${Timestamp}.log"

New-Item -ItemType Directory -Force -Path $OpsLogs | Out-Null

function Write-OpsLog {
    param([string]$Message)
    $Line = "[{0}] {1}" -f (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"), $Message
    Add-Content -Path $LogFile -Value $Line -Encoding utf8
    Write-Host $Line
}

function Write-OpsWarn {
    param([string]$Message)
    Write-OpsLog ("WARNING: " + $Message)
}

$VenvActivate = Join-Path $RepoRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    . $VenvActivate
}

$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

Write-OpsLog ("Phase 30 observation once - repo=" + $RepoRoot)

if (Test-Path $StopFlag) {
    Write-OpsLog ("STOP_OBSERVATION present at " + $StopFlag + " - skipping daemon (exit 0)")
    exit 0
}

Write-OpsLog "Optional cache refresh (failures are non-fatal)"

function Invoke-CacheRefresh {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$PythonArgs
    )
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $Output = & $Python @PythonArgs 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if ($Output) {
        Add-Content -Path $LogFile -Value ($Output | Out-String) -Encoding utf8
    }
    return $code
}

$refreshExit = Invoke-CacheRefresh -PythonArgs @(
    "scripts/build_intraday_cache.py", "--assets", "ETH", "--timeframes", "4h"
)
if ($refreshExit -ne 0) {
    Write-OpsWarn "build_intraday_cache.py ETH 4h failed - continuing with existing cache"
}

$refreshExit = Invoke-CacheRefresh -PythonArgs @(
    "scripts/build_derivatives_cache_phase26.py", "--assets", "ETH"
)
if ($refreshExit -ne 0) {
    Write-OpsWarn "build_derivatives_cache_phase26.py ETH failed - continuing with existing cache"
}

$refreshExit = Invoke-CacheRefresh -PythonArgs @(
    "scripts/build_basis_cache_phase27.py", "--assets", "ETH"
)
if ($refreshExit -ne 0) {
    Write-OpsWarn "build_basis_cache_phase27.py ETH failed - continuing with existing cache"
}

Write-OpsLog "Running overlay observation daemon once cache-only all targets"
& $Python scripts/run_overlay_observation_daemon_phase28.py `
    --run-all-targets `
    --mode once `
    --cache-only 2>&1 | Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-OpsLog "Generating overlay observation reports"
& $Python scripts/generate_overlay_observation_report_phase28.py --all-targets 2>&1 |
    Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-OpsLog "Aggregating observation metrics Phase 29"
& $Python scripts/aggregate_observation_metrics_phase29.py 2>&1 |
    Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ReportFail = $false
Write-OpsLog "Generating observation dashboard Phase 30.2"
& $Python scripts/generate_observation_dashboard_phase30.py 2>&1 |
    Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) { $ReportFail = $true; Write-OpsWarn "generate_observation_dashboard_phase30.py failed" }

Write-OpsLog "Generating observation alerts Phase 30.3"
& $Python scripts/generate_observation_alerts_phase30.py 2>&1 |
    Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) {
    Write-OpsWarn "generate_observation_alerts_phase30.py returned non-zero (STOP flag?)"
}

Write-OpsLog "Checking state.json legacy metadata"
$LegacyScript = Join-Path $env:TEMP ("phase30_legacy_check_{0}.py" -f $Timestamp)
@'
import sys
from pathlib import Path

repo_root = Path(r"__REPO_ROOT__")
obs_base = Path(r"__OBS_BASE__")
sys.path.insert(0, str(repo_root))

from src.bot.observation_ops_guards import check_all_target_state_warnings
from src.bot.overlay_observation_engine import PHASE28_TARGETS, default_state_dir

dirs = [default_state_dir(obs_base, s, v) for s, v, _ in PHASE28_TARGETS]
for msg in check_all_target_state_warnings(dirs):
    print(msg)
'@.Replace('__REPO_ROOT__', $RepoRoot).Replace('__OBS_BASE__', $ObsBase) | Set-Content -Path $LegacyScript -Encoding utf8

try {
    $LegacyWarnings = & $Python $LegacyScript 2>&1
    if ($LegacyWarnings) {
        foreach ($Line in $LegacyWarnings) {
            if ($Line) { Write-OpsWarn ("state legacy: " + $Line) }
        }
    } else {
        Write-OpsLog "state.json legacy check: OK"
    }
} finally {
    if (Test-Path $LegacyScript) {
        Remove-Item $LegacyScript -Force
    }
}

if ($ReportFail) {
    Write-OpsWarn "dashboard generation failed - see alerts.json after manual regen"
}

Write-OpsLog "Running observation healthcheck Phase 30.4 fail-soft"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $Python scripts/check_observation_health_phase30.py --cron-active 2>&1 |
        Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        Write-OpsWarn "healthcheck reported fail - see HEALTHCHECK.md / healthcheck.json"
    }
} finally {
    $ErrorActionPreference = $prevEap
}

Write-OpsLog "Generating observation ops digest Phase 30.4 fail-soft"
$ErrorActionPreference = "Continue"
try {
    & $Python scripts/generate_observation_ops_digest_phase30.py 2>&1 |
        Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        Write-OpsWarn "ops digest generation failed"
    }
} finally {
    $ErrorActionPreference = $prevEap
}

Write-OpsLog ("Phase 30 observation once complete - log=" + $LogFile)
