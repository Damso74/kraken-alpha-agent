from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.collect_world_order_flow_forward import (
    KRAKEN_ASSET_PAIRS_URL,
    KRAKEN_OHLC_URL,
    _capture_kraken_snapshot,
    _capture_snapshot,
    collect_forward_day,
    collect_mature_week_outcome,
    healthcheck_forward,
    main,
    parse_kraken_asset_pairs,
)
from src.data.collectors._common import CollectorError


def _exchange_info(asset_count: int = 2) -> dict:
    return {
        "symbols": [
            {
                "symbol": f"A{index}USDT",
                "baseAsset": f"A{index}",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
            }
            for index in range(asset_count)
        ]
    }


def _kraken_asset_pairs(asset_count: int = 2) -> dict:
    return {
        "error": [],
        "result": {
            f"A{index}/USD": {
                "altname": f"A{index}USD",
                "wsname": f"A{index}/USD",
                "aclass_base": "currency",
                "base": f"A{index}",
                "aclass_quote": "currency",
                "quote": "USD",
                "lot": "unit",
                "status": "online",
            }
            for index in range(asset_count)
        },
    }


def _fetcher(calls: list[tuple[str, dict | None]]):
    def fetch(url: str, params: dict | None):
        calls.append((url, params))
        if "exchangeInfo" in url:
            return _exchange_info()
        if "AssetPairs" in url:
            return _kraken_asset_pairs()
        assert params is not None
        timestamp = int(params["startTime"])
        return [
            [
                timestamp,
                "100",
                "101",
                "99",
                "100",
                "10",
                timestamp + 86_400_000 - 1,
                "1000",
                10,
                "6",
                "600",
            ]
        ]

    return fetch


def _capture_prior_universes(root: Path, when: datetime, fetcher) -> None:
    _capture_snapshot(root, now=when, fetcher=fetcher)
    _capture_kraken_snapshot(
        root,
        now=when,
        fetcher=fetcher,
        minimum_assets=2,
        maximum_assets=3,
    )


def _collect_forward_range(root: Path, *, first_day: datetime, days: int, fetcher) -> None:
    for offset in range(days):
        target = first_day + timedelta(days=offset)
        collect_forward_day(
            root=root,
            now=target + timedelta(days=1, hours=1),
            fetcher=fetcher,
            minimum_assets=2,
            maximum_assets=3,
        )


def _outcome_fetcher(calls: list[tuple[str, dict | None]]):
    base = _fetcher(calls)

    def fetch(url: str, params: dict | None):
        if url != KRAKEN_OHLC_URL:
            return base(url, params)
        calls.append((url, params))
        assert params is not None
        entry = int(params["since"]) + 3_600
        exit_timestamp = entry + 7 * 86_400
        pair = str(params["pair"])
        return {
            "error": [],
            "result": {
                pair: [
                    [entry, "100", "101", "99", "100", "100", "10", 1],
                    [
                        exit_timestamp,
                        "102",
                        "103",
                        "101",
                        "102",
                        "102",
                        "10",
                        1,
                    ],
                ],
                "last": exit_timestamp,
            },
        }

    return fetch


def test_forward_collection_is_causal_append_only_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    calls: list[tuple[str, dict | None]] = []
    fetcher = _fetcher(calls)
    sunday = datetime(2024, 1, 7, 12, tzinfo=UTC)
    tuesday = datetime(2024, 1, 9, 1, tzinfo=UTC)
    _capture_prior_universes(root, sunday, fetcher)

    result = collect_forward_day(
        root=root,
        now=tuesday,
        fetcher=fetcher,
        minimum_assets=2,
        maximum_assets=3,
    )
    assert result["mode"] == "network"
    assert result["day"] == "2024-01-08"
    assert result["row_count"] == 2
    day_path = root / "days" / "2024-01-08.json"
    day = json.loads(day_path.read_text(encoding="utf-8"))
    assert set(day) >= {
        "rows",
        "binance_snapshot_sha256",
        "kraken_universe_sha256",
    }
    assert not ({"return", "exit_price", "outcome", "pnl"} & set(day))
    assert len((root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()) == 1

    calls.clear()
    # Simulate a crash after the atomic day write but before manifest append.
    (root / "manifest.jsonl").unlink()
    repeated = collect_forward_day(
        root=root,
        now=tuesday,
        fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("network forbidden")),
        minimum_assets=2,
        maximum_assets=3,
    )
    assert repeated["mode"] == "idempotent-cache-hit"
    assert repeated["day_sha256"] == result["day_sha256"]
    assert calls == []
    assert len((root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_cache_only_and_health_digest_verify_exact_journal(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    fetcher = _fetcher([])
    sunday = datetime(2024, 1, 7, 12, tzinfo=UTC)
    tuesday = datetime(2024, 1, 9, 1, tzinfo=UTC)
    _capture_prior_universes(root, sunday, fetcher)
    collect_forward_day(
        root=root,
        now=tuesday,
        fetcher=fetcher,
        minimum_assets=2,
        maximum_assets=3,
    )
    cached = collect_forward_day(
        root=root,
        now=tuesday,
        cache_only=True,
        minimum_assets=2,
        maximum_assets=3,
    )
    first = healthcheck_forward(root=root, today=tuesday.date())
    second = healthcheck_forward(root=root, today=tuesday.date())
    assert cached["mode"] == "cache-only"
    assert first["healthy"] is True
    assert first["journal_sha256"] == second["journal_sha256"]
    assert first["latest_day"] == "2024-01-08"


def test_healthcheck_detects_day_tampering(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    fetcher = _fetcher([])
    sunday = datetime(2024, 1, 7, 12, tzinfo=UTC)
    tuesday = datetime(2024, 1, 9, 1, tzinfo=UTC)
    _capture_prior_universes(root, sunday, fetcher)
    collect_forward_day(
        root=root,
        now=tuesday,
        fetcher=fetcher,
        minimum_assets=2,
        maximum_assets=3,
    )
    day_path = root / "days" / "2024-01-08.json"
    day_path.write_text(day_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    health = healthcheck_forward(root=root, today=tuesday.date())
    assert health["healthy"] is False
    assert any("digest" in error for error in health["errors"])


def test_bootstrap_refuses_to_use_snapshot_captured_after_week_start(
    tmp_path: Path,
) -> None:
    root = tmp_path / "journal"
    tuesday = datetime(2024, 1, 9, 1, tzinfo=UTC)
    with pytest.raises(CollectorError, match="bootstrap incomplete"):
        collect_forward_day(
            root=root,
            now=tuesday,
            fetcher=_fetcher([]),
            minimum_assets=2,
            maximum_assets=3,
        )
    assert not (root / "days" / "2024-01-08.json").exists()
    assert not (root / "manifest.jsonl").exists()


def test_missing_member_aborts_day_without_partial_artifact(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    sunday = datetime(2024, 1, 7, 12, tzinfo=UTC)
    tuesday = datetime(2024, 1, 9, 1, tzinfo=UTC)
    _capture_prior_universes(root, sunday, _fetcher([]))

    def missing_second(url: str, params: dict | None):
        if "exchangeInfo" in url:
            return _exchange_info()
        if "AssetPairs" in url:
            return _kraken_asset_pairs()
        assert params is not None
        if params["symbol"] == "A1USDT":
            return []
        return _fetcher([])(url, params)

    with pytest.raises(CollectorError, match="closed daily kline missing"):
        collect_forward_day(
            root=root,
            now=tuesday,
            fetcher=missing_second,
            minimum_assets=2,
            maximum_assets=3,
        )
    assert not (root / "days" / "2024-01-08.json").exists()
    assert not (root / "manifest.jsonl").exists()


def test_kraken_assetpairs_normalization_is_public_spot_crypto_only() -> None:
    payload = _kraken_asset_pairs()
    payload["result"].update(
        {
            "XBT/USDT": {
                "altname": "XBTUSDT",
                "wsname": "XBT/USDT",
                "aclass_base": "currency",
                "base": "XBT",
                "aclass_quote": "currency",
                "quote": "USDT",
                "lot": "unit",
                "status": "online",
            },
            "XBT/USD": {
                "altname": "XBTUSD",
                "wsname": "XBT/USD",
                "aclass_base": "currency",
                "base": "XBT",
                "aclass_quote": "currency",
                "quote": "USD",
                "lot": "unit",
                "status": "online",
            },
            "AAPLx/USD": {
                "altname": "AAPLxUSD",
                "wsname": "AAPL.x/USD",
                "aclass_base": "currency",
                "base": "AAPLx",
                "aclass_quote": "currency",
                "quote": "USD",
                "lot": "unit",
                "status": "online",
            },
            "EUR/USD": {
                "altname": "EURUSD",
                "wsname": "EUR/USD",
                "aclass_base": "currency",
                "base": "EUR",
                "aclass_quote": "currency",
                "quote": "USD",
                "lot": "unit",
                "status": "online",
            },
        }
    )
    snapshot = parse_kraken_asset_pairs(
        payload,
        observed_at=datetime(2024, 1, 7, tzinfo=UTC),
        minimum_assets=2,
        maximum_assets=3,
    )
    assert snapshot["source"] == KRAKEN_ASSET_PAIRS_URL
    assert snapshot["base_assets"] == ["A0", "A1", "BTC"]
    btc = next(row for row in snapshot["pairs"] if row["base_asset"] == "BTC")
    assert btc["quote_asset"] == "USD"
    assert all(row["mode"] == "spot_long_only" for row in snapshot["pairs"])


def test_cli_forbids_backdated_network_capture(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "collect_world_order_flow_forward.py",
            "snapshot",
            "--as-of-date",
            "2024-01-09",
        ],
    )
    assert main() == 2
    assert "historical network capture is forbidden" in capsys.readouterr().err


def test_scheduled_collect_treats_only_causal_bootstrap_as_healthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "journal"
    monkeypatch.setattr(
        "scripts.collect_world_order_flow_forward.default_http_fetcher",
        _fetcher([]),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "collect_world_order_flow_forward.py",
            "collect-scheduled",
            "--root",
            str(root),
            "--minimum-assets",
            "2",
            "--maximum-assets",
            "3",
        ],
    )
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["healthy"] is True
    assert output["mode"] == "bootstrap-pending"
    assert output["snapshots_captured"] is True
    assert len(list((root / "snapshot_days").glob("*.json"))) == 1
    assert len(list((root / "kraken_universe_days").glob("*.json"))) == 1
    assert not (root / "days").exists()


def test_snapshot_kraken_subcommand_writes_public_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "journal"
    monkeypatch.setattr(
        "scripts.collect_world_order_flow_forward.default_http_fetcher",
        _fetcher([]),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "collect_world_order_flow_forward.py",
            "snapshot-kraken",
            "--root",
            str(root),
            "--minimum-assets",
            "2",
            "--maximum-assets",
            "3",
        ],
    )
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["source"] == KRAKEN_ASSET_PAIRS_URL
    assert output["assets"] == 2
    files = list((root / "kraken_universe_days").glob("*.json"))
    assert len(files) == 1
    snapshot = json.loads(files[0].read_text(encoding="utf-8"))
    assert snapshot["source_params"] == {"assetVersion": 1}


def test_mature_week_outcome_captures_exact_kraken_opens_append_only(
    tmp_path: Path,
) -> None:
    root = tmp_path / "journal"
    calls: list[tuple[str, dict | None]] = []
    fetcher = _outcome_fetcher(calls)
    delays: list[float] = []
    sunday = datetime(2024, 1, 7, 12, tzinfo=UTC)
    _capture_prior_universes(root, sunday, fetcher)
    _collect_forward_range(
        root,
        first_day=datetime(2024, 1, 8, tzinfo=UTC),
        days=15,
        fetcher=fetcher,
    )

    finalized = collect_mature_week_outcome(
        root=root,
        now=datetime(2024, 1, 23, 3, tzinfo=UTC),
        fetcher=fetcher,
        request_interval_seconds=1.05,
        sleeper=delays.append,
    )
    assert finalized["mode"] == "week-finalized"
    assert finalized["source_week_start"] == "2024-01-08"
    assert finalized["status"] == "complete"
    assert finalized["row_count"] == 2
    assert delays == [1.05]
    artifact = json.loads((root / "week_outcomes" / "2024-01-08.json").read_text(encoding="utf-8"))
    assert artifact["safety"] == {
        "credentials_used": False,
        "orders_sent": 0,
        "public_only": True,
    }
    assert {row["entry_price"] for row in artifact["rows"]} == {100.0}
    assert {row["exit_price"] for row in artifact["rows"]} == {102.0}
    assert len(artifact["daily_source_hashes"]) == 7
    (root / "week_outcome_manifest.jsonl").unlink()
    recovered = collect_mature_week_outcome(
        root=root,
        now=datetime(2024, 1, 23, 4, tzinfo=UTC),
        fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("network forbidden")),
        request_interval_seconds=0,
    )
    assert recovered["mode"] == "week-idempotent-cache-hit"
    repeated = collect_mature_week_outcome(
        root=root,
        now=datetime(2024, 1, 23, 5, tzinfo=UTC),
        fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("network forbidden")),
        request_interval_seconds=0,
    )
    assert repeated == {"mode": "no-mature-week"}
    health = healthcheck_forward(root=root, today=datetime(2024, 1, 23).date())
    assert health["healthy"] is True
    assert health["week_outcome_records"] == 1


def test_mature_week_outcome_missing_exact_price_writes_nothing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "journal"
    base_fetcher = _fetcher([])
    _capture_prior_universes(root, datetime(2024, 1, 7, 12, tzinfo=UTC), base_fetcher)
    _collect_forward_range(
        root,
        first_day=datetime(2024, 1, 8, tzinfo=UTC),
        days=15,
        fetcher=base_fetcher,
    )

    def missing_open(url: str, params: dict | None):
        if url != KRAKEN_OHLC_URL:
            return base_fetcher(url, params)
        return {"error": [], "result": {"PAIR": [], "last": 0}}

    with pytest.raises(CollectorError, match="exact open missing"):
        collect_mature_week_outcome(
            root=root,
            now=datetime(2024, 1, 23, 3, tzinfo=UTC),
            fetcher=missing_open,
            request_interval_seconds=0,
        )
    assert not (root / "week_outcomes" / "2024-01-08.json").exists()
    assert not (root / "week_outcome_manifest.jsonl").exists()


def test_bootstrap_health_expires_after_first_causal_day_is_due(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    _capture_prior_universes(
        root,
        datetime(2026, 8, 26, 12, tzinfo=UTC),
        _fetcher([]),
    )
    pending = healthcheck_forward(root=root, today=datetime(2026, 9, 1).date())
    overdue = healthcheck_forward(root=root, today=datetime(2026, 9, 2).date())
    assert pending["healthy"] is True
    assert pending["mode"] == "bootstrap-pending"
    assert overdue["healthy"] is False
    assert "no_forward_days" in overdue["errors"]
