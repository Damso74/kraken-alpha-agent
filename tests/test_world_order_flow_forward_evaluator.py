from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from scripts.collect_world_order_flow_forward import (
    _capture_kraken_snapshot,
    _capture_snapshot,
    _current_source_hashes,
)
from scripts.evaluate_world_order_flow_forward import (
    CI_RECEIPT_SCHEMA,
    _ci_receipt_valid,
    evaluate_and_write,
)


def _bootstrap_journal(root: Path) -> None:
    def fetcher(url: str, _params: dict | None):
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

    observed = datetime(2026, 8, 26, 12, tzinfo=UTC)
    _capture_snapshot(root, now=observed, fetcher=fetcher)
    _capture_kraken_snapshot(
        root,
        now=observed,
        fetcher=fetcher,
        minimum_assets=1,
        maximum_assets=1,
    )


def test_evaluator_requires_a_separate_exact_cache_replay(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    _bootstrap_journal(root)
    baseline, baseline_digest = evaluate_and_write(
        root=root, mode="baseline", today=date(2026, 8, 26)
    )
    verified, verified_digest = evaluate_and_write(
        root=root, mode="verify-cache", today=date(2026, 8, 26)
    )
    assert baseline_digest.is_file()
    assert verified_digest.is_file()
    assert baseline["reproduction"]["verified"] is False
    assert verified["reproduction"]["verified"] is True
    assert baseline["scientific_sha256"] == verified["scientific_sha256"]
    assert verified["evaluation"]["status"] == "collecting"
    assert verified["evaluation"]["decision"] == "NO-GO"
    assert verified["safety"]["authorizes_paper_or_live"] is False


def test_ci_receipt_is_bound_to_exact_sources_and_safety_scope(tmp_path: Path) -> None:
    source_hashes = _current_source_hashes()
    receipt = tmp_path / "ci.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": CI_RECEIPT_SCHEMA,
                "source_hashes": source_hashes,
                "ruff_scope": "src tests scripts",
                "ruff_passed": True,
                "pytest_collected": 1160,
                "pytest_passed": True,
                "safety_env": {
                    "ALLOW_LIVE_ORDERS": "false",
                    "KRAKEN_CLI_TRANSPORT": "mock",
                    "LIVE_TRADING": "false",
                    "TRADING_MODE": "dry_run",
                },
            }
        ),
        encoding="utf-8",
    )
    valid, reasons = _ci_receipt_valid(receipt, source_hashes=source_hashes)
    assert valid is True
    assert reasons == []
    tampered = {**source_hashes, "analysis_sha256": "0" * 64}
    valid, reasons = _ci_receipt_valid(receipt, source_hashes=tampered)
    assert valid is False
    assert "CI_RECEIPT_SOURCE_HASH_MISMATCH" in reasons
