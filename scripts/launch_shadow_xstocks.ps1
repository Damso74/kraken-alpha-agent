# launch_shadow_xstocks.ps1 — Hackathon shadow xStocks dry_run launcher.
#
# This script runs the Kraken Alpha Agent loop in **strict dry_run** mode
# against real Kraken xStocks tickers for ~36-40 hours. NO live order is
# ever placed: TRADING_MODE / LIVE_TRADING / ALLOW_LIVE_ORDERS are forced
# to dry_run / false / false at the env layer, the active profile is
# locked to ``shadow_xstocks_36h`` (engine: spot), and the
# ``src/execution._assert_not_dry_run`` tripwire raises if a refactor
# ever lets a dry_run request fall through to a mutating CLI call.
#
# Restart policy:
# - On a non-zero exit from python, the script sleeps with exponential
#   backoff (5s -> 30s -> 5min capped) and re-launches the loop.
# - Ctrl+C in this window stops the launcher and the underlying python
#   child cleanly.
# - All stdout/stderr is mirrored to data/shadow_session.log via Tee.
#
# Usage (PowerShell, from repo root):
#   .\scripts\launch_shadow_xstocks.ps1
#
# To monitor in another window (READ-ONLY, will not stop the session):
#   .\.venv\Scripts\Activate.ps1
#   python scripts/monitor_shadow_session.py
#
# To stop the session: hit Ctrl+C in THIS window. Then export with:
#   python scripts/export_shadow_session_for_submission.py

[CmdletBinding()]
param(
    [string]$Profile = "shadow_xstocks_36h",
    [int]$LoopIntervalSeconds = 60,
    [string]$LogFile = "data/shadow_session.log",
    [int]$MaxBackoffSeconds = 300
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Resolve repo root (the directory above the scripts/ folder)
# ---------------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $RepoRoot

# ---------------------------------------------------------------------------
# Activate the venv if present
# ---------------------------------------------------------------------------
$VenvActivate = Join-Path $RepoRoot ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $VenvActivate)) {
    Write-Host "ERROR: .venv missing at $VenvActivate" -ForegroundColor Red
    Write-Host "Create it first: python -m venv .venv && .\.venv\Scripts\Activate.ps1 && pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}
. $VenvActivate

# ---------------------------------------------------------------------------
# Force dry_run env vars regardless of what the user has in their session
# ---------------------------------------------------------------------------
$env:TRADING_MODE         = "dry_run"
$env:LIVE_TRADING         = "false"
$env:ALLOW_LIVE_ORDERS    = "false"
$env:KRAKEN_ALPHA_PROFILE = $Profile
$env:LOOP_INTERVAL_SECONDS = "$LoopIntervalSeconds"
if (-not $env:KRAKEN_CLI_TRANSPORT) {
    $env:KRAKEN_CLI_TRANSPORT = "auto"
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
$LogPath  = Join-Path $RepoRoot $LogFile
$LogDir   = Split-Path -Parent $LogPath
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}
$StartedAt    = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
$StartedAtUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$SessionMetadata = @{
    started_at_local   = $StartedAt
    started_at_utc     = $StartedAtUtc
    profile            = $Profile
    loop_interval_s    = $LoopIntervalSeconds
    log_file           = $LogPath
    pid                = $PID
    repo_root          = "$RepoRoot"
} | ConvertTo-Json -Depth 4
$SessionMetadataFile = Join-Path $RepoRoot "data\shadow_session.json"
$SessionMetadata | Set-Content -Path $SessionMetadataFile -Encoding UTF8

$Banner = @"
============================================================
SHADOW XSTOCKS DRY-RUN — DO NOT SHUT DOWN
============================================================
started_at        : $StartedAt
profile           : $Profile
loop_interval_s   : $LoopIntervalSeconds
TRADING_MODE      : dry_run   (forced)
LIVE_TRADING      : false     (forced)
ALLOW_LIVE_ORDERS : false     (forced)
KRAKEN_CLI_TRANSPORT : $($env:KRAKEN_CLI_TRANSPORT)
log_file          : $LogPath
working_dir       : $RepoRoot

NO LIVE ORDER WILL BE PLACED. Read-only Kraken CLI calls only
(ticker / ohlc / orderbook / trades / balance). Dry-run fills
are persisted to data/agent.sqlite (+ data/decisions.jsonl,
data/trades.jsonl) for the post-run submission export.

To MONITOR (in a separate PowerShell window — read-only,
will NOT stop this session):
  .\.venv\Scripts\Activate.ps1
  python scripts/monitor_shadow_session.py

To STOP CLEANLY: press Ctrl+C in THIS window. Once stopped,
export the session for submission with:
  python scripts/export_shadow_session_for_submission.py

To READ THE LIVE LOG without stopping the session:
  Get-Content $LogPath -Wait

============================================================
"@

Write-Host $Banner -ForegroundColor Cyan
Add-Content -Path $LogPath -Value $Banner

# ---------------------------------------------------------------------------
# Restart-on-crash loop with exponential backoff
# ---------------------------------------------------------------------------
$Backoff       = 5
$RestartCount  = 0
$KeepRunning   = $true

# Trap Ctrl+C: handled by python's signal handler, but we also stop the
# outer loop here so the launcher exits cleanly without re-spawning.
[Console]::TreatControlCAsInput = $false
$null = Register-EngineEvent PowerShell.Exiting -Action {
    Write-Host "`nshadow launcher exiting." -ForegroundColor Yellow
}

try {
    while ($KeepRunning) {
        $CycleHeader = "[$(Get-Date -Format o)] starting agent loop (attempt $($RestartCount + 1))"
        Write-Host $CycleHeader -ForegroundColor Green
        Add-Content -Path $LogPath -Value $CycleHeader

        # Stream python output to the log file AND the console.
        # Tee-Object preserves stdout to the console while appending to a file.
        $ExitCode = 0
        try {
            python "scripts\run_agent_loop.py" 2>&1 | Tee-Object -FilePath $LogPath -Append
            $ExitCode = $LASTEXITCODE
        } catch {
            $ExitCode = 99
            $ErrorLine = "[$(Get-Date -Format o)] launcher caught exception: $_"
            Write-Host $ErrorLine -ForegroundColor Red
            Add-Content -Path $LogPath -Value $ErrorLine
        }

        if ($ExitCode -eq 0) {
            $StopMsg = "[$(Get-Date -Format o)] agent loop exited cleanly (exit_code=0). Launcher stopping."
            Write-Host $StopMsg -ForegroundColor Yellow
            Add-Content -Path $LogPath -Value $StopMsg
            $KeepRunning = $false
            break
        }

        $RestartCount++
        $RestartMsg = "[$(Get-Date -Format o)] agent loop crashed (exit_code=$ExitCode). Restart #$RestartCount in ${Backoff}s."
        Write-Host $RestartMsg -ForegroundColor Red
        Add-Content -Path $LogPath -Value $RestartMsg

        Start-Sleep -Seconds $Backoff

        # Exponential backoff capped at MaxBackoffSeconds
        $Backoff = [Math]::Min($Backoff * 2, $MaxBackoffSeconds)
    }
} finally {
    $StoppedAt = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    $FinalLine = "[$StoppedAt] launcher exit. restart_count=$RestartCount"
    Write-Host $FinalLine -ForegroundColor Yellow
    Add-Content -Path $LogPath -Value $FinalLine
}
