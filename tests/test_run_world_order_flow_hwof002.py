from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.run_world_order_flow_hwof002 import run
from src.data.collectors._common import CollectorError
from src.data.collectors.binance_world_order_flow import parse_exchange_info

MONDAY = 1_704_067_200


def _bundle(path: Path, *, stage: str = "validation") -> None:
    snapshot = parse_exchange_info(
        {
            "symbols": [
                {
                    "symbol": f"A{i:02d}USDT",
                    "baseAsset": f"A{i:02d}",
                    "quoteAsset": "USDT",
                    "status": "TRADING",
                    "isSpotTradingAllowed": True,
                }
                for i in range(30)
            ]
        },
        observed_at=datetime(2023, 12, 31, tzinfo=UTC),
    )
    payload = {
        "schema_version": "hwof002-bundle-v1",
        "stage": stage,
        "data_end_exclusive": "2026-01-01",
        "universe_snapshots": [snapshot.to_dict()],
        "kraken_assets_by_week": [
            {
                "week_start": MONDAY,
                "observed_at": MONDAY - 1,
                "base_assets": [f"A{i:02d}" for i in range(30)],
            }
        ],
        "weekly_flows": [
            {
                "week_start": MONDAY,
                "base_asset": f"A{i:02d}",
                "quote_volume": 1_000.0,
                "taker_buy_quote_volume": 600.0,
            }
            for i in range(30)
        ],
        "weekly_prices": [
            {
                "week_start": MONDAY,
                "base_asset": f"A{i:02d}",
                "entry_timestamp": MONDAY + 7 * 86_400 + 3_600,
                "exit_timestamp": MONDAY + 14 * 86_400 + 3_600,
                "entry_price": 100.0,
                "exit_price": 101.0,
            }
            for i in range(30)
        ],
        "provenance": [
            {"source": "hermetic-fixture", "sha256": hashlib.sha256(b"fixture").hexdigest()}
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _args(cache: Path, output: Path, *, stage: str = "validation", cache_only: bool = True):
    return argparse.Namespace(
        stage=stage, cache_only=cache_only, cache_dir=cache, output_dir=output
    )


def test_runner_is_cache_only_and_reports_no_go(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    cache = tmp_path / "cache"
    output = tmp_path / "reports"
    _bundle(cache / "validation_bundle.json")
    report = run(_args(cache, output))
    repeated = run(_args(cache, output))
    assert report["status"] == "no_go"
    assert repeated["segments"] == report["segments"]
    assert repeated["bundle_sha256"] == report["bundle_sha256"]
    assert report["test_final_sealed"] is True
    assert (output / "validation.json").is_file()
    with pytest.raises(ValueError, match="explicit --cache-only"):
        run(_args(cache, output, cache_only=False))


def test_final_lock_refuses_failed_validation_before_loading_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    cache = tmp_path / "cache"
    output = tmp_path / "reports"
    _bundle(cache / "validation_bundle.json")
    run(_args(cache, output))
    with pytest.raises(RuntimeError, match="validation did not pass"):
        run(_args(cache, output, stage="final"))


def test_missing_exact_bundle_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    with pytest.raises(CollectorError, match="missing exact bundle"):
        run(_args(tmp_path / "cache", tmp_path / "reports"))


def test_validation_bundle_rejects_2026_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    cache = tmp_path / "cache"
    path = cache / "validation_bundle.json"
    _bundle(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["weekly_prices"][0]["exit_timestamp"] = 1_767_225_600
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CollectorError, match="2026 price outcome"):
        run(_args(cache, tmp_path / "reports"))
