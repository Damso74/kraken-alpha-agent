"""Phase 16 intraday cache readiness audit tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from src.bot.data_loader import summarize_candles

REPO = Path(__file__).resolve().parents[1]
CACHE_ROOT = REPO / "data" / "collector_cache"
MANIFEST = REPO / "reports" / "data_manifests_phase16" / "ohlcv_intraday_readiness.json"

ASSETS = ("BTC", "ETH", "SOL")
TIMEFRAMES = ("1d", "4h", "1h")


def _build_manifest_entry(asset: str, tf: str) -> dict:
    summary = summarize_candles(asset, tf, CACHE_ROOT)
    data_ok = summary.status == "available"
    return {
        "asset": asset,
        "timeframe": tf,
        "cache_path": summary.path,
        "data_ok": data_ok,
        "blocked_reason": summary.blocked_reason,
        "candle_count": summary.candle_count,
        "coverage_start": summary.first_timestamp,
        "coverage_end": summary.last_timestamp,
        "sha256": summary.sha256,
        "source": "local_cache",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "commit_sha": None,
        "can_run_strategy_zoo": data_ok,
    }


def test_manifest_file_exists() -> None:
    assert MANIFEST.is_file(), f"missing manifest: {MANIFEST}"


def test_manifest_schema() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == len(ASSETS) * len(TIMEFRAMES)
    for row in payload:
        for key in (
            "asset",
            "timeframe",
            "cache_path",
            "data_ok",
            "candle_count",
            "can_run_strategy_zoo",
        ):
            assert key in row


def test_blocked_data_when_cache_missing(tmp_path: Path) -> None:
    summary = summarize_candles("NOASSET", "1h", tmp_path)
    assert summary.status == "blocked_data"
    assert summary.blocked_reason == "cache file missing"
