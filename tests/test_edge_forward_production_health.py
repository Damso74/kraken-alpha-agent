from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.check_edge_forward_production import build_health, write_health
from scripts.collect_world_order_flow_forward import (
    _capture_kraken_snapshot,
    _capture_snapshot,
)


def _seed_runtime(root: Path, now: datetime) -> Path:
    session = root / "data/collector_cache/kraken_execution_toxicity_hexe001/technical/sessions/s1"
    (session / "raw/2026-08-26").mkdir(parents=True)
    (session / "raw/2026-08-26/part-00000.jsonl.gz").write_bytes(b"gzip")
    progress = session / "progress.json"
    progress.write_text(
        json.dumps(
            {
                "schema_version": "h-exe-001-progress-v1",
                "session_id": "s1",
                "event_count": 42,
                "last_exchange_timestamp_ms": 1_700_000_000_000,
                "credentials_used": False,
                "orders_sent": 0,
            }
        ),
        encoding="utf-8",
    )
    timestamp = now.timestamp()
    for path in (session / "raw/2026-08-26/part-00000.jsonl.gz", progress):
        path.touch()
        path.chmod(0o600)
        os.utime(path, (timestamp, timestamp))
    wof = root / "data/collector_cache/world_order_flow_forward"

    def public_fetcher(url: str, _params: dict | None):
        if "exchangeInfo" in url:
            return {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "baseAsset": "BTC",
                        "quoteAsset": "USDT",
                        "status": "TRADING",
                        "isSpotTradingAllowed": True,
                    }
                ]
            }
        return {
            "error": [],
            "result": {
                "XBT/USD": {
                    "altname": "XBTUSD",
                    "wsname": "XBT/USD",
                    "aclass_base": "currency",
                    "base": "XBT",
                    "aclass_quote": "currency",
                    "quote": "USD",
                    "lot": "unit",
                    "status": "online",
                }
            },
        }

    _capture_snapshot(wof, now=now, fetcher=public_fetcher)
    _capture_kraken_snapshot(
        wof,
        now=now,
        fetcher=public_fetcher,
        minimum_assets=1,
        maximum_assets=1,
    )
    for target in (
        *wof.joinpath("snapshot_days").glob("*.json"),
        *wof.joinpath("kraken_universe_days").glob("*.json"),
    ):
        os.utime(target, (timestamp, timestamp))
    return progress


def test_health_is_green_for_fresh_safe_runtime(tmp_path: Path) -> None:
    now = datetime(2026, 8, 26, 20, tzinfo=UTC)
    _seed_runtime(tmp_path, now)
    health = build_health(
        repo_root=tmp_path,
        now=now,
        disk_free_bytes=500 * 1024**3,
    )
    assert health["healthy"] is True
    assert health["reason_codes"] == []
    assert health["h_exe_progress"]["event_count"] == 42
    assert health["h_wof_journal"]["healthy"] is True
    assert health["h_wof_journal"]["mode"] == "bootstrap-pending"
    digest = write_health(health, tmp_path / "health")
    assert digest.is_file()
    assert json.loads((tmp_path / "health/latest.json").read_text())["healthy"] is True


def test_health_fails_closed_on_stale_or_unsafe_progress(tmp_path: Path) -> None:
    now = datetime(2026, 8, 26, 20, tzinfo=UTC)
    progress = _seed_runtime(tmp_path, now - timedelta(minutes=3))
    payload = json.loads(progress.read_text(encoding="utf-8"))
    payload["orders_sent"] = 1
    progress.write_text(json.dumps(payload), encoding="utf-8")
    stale = (now - timedelta(minutes=3)).timestamp()
    os.utime(progress, (stale, stale))
    health = build_health(
        repo_root=tmp_path,
        now=now,
        disk_free_bytes=100 * 1024**3,
    )
    assert health["healthy"] is False
    assert "H_EXE_PROGRESS_STALE_GT_2_MIN" in health["reason_codes"]
    assert "H_EXE_PROGRESS_SAFETY_INVARIANT_FAILED" in health["reason_codes"]
    assert "DISK_FREE_BELOW_250_GIB" in health["reason_codes"]
