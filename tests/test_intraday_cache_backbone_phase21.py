"""Phase 21 intraday data backbone — cache audit and builder (hermetic)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts.audit_ohlcv_caches import (
    audit_manifest,
    can_run_full_tournament,
)
from src.data.collectors.binance_public import (
    MIN_ROWS_DATA_OK,
    default_ohlc_cache_path,
    fetch_binance_klines,
    parse_binance_klines_intraday,
    save_ohlc_cache,
)

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "reports" / "data_manifests_phase21" / "ohlcv_backbone_manifest.json"


def _make_candles(
    *,
    count: int,
    step_seconds: int,
    start_ts: int | None = None,
) -> list[dict]:
    if start_ts is None:
        start_ts = int(
            datetime(2020, 1, 1, tzinfo=UTC).timestamp()
        )
    out: list[dict] = []
    for i in range(count):
        ts = start_ts + i * step_seconds
        close = 50_000.0 + i * 0.01
        out.append(
            {
                "timestamp": ts,
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "vwap": close,
                "volume": 10.0 + i,
            }
        )
    return out


def _seed_backbone(tmp_path: Path, asset: str) -> None:
    for tf, step in (("1d", 86400), ("4h", 14400), ("1h", 3600)):
        rows = _make_candles(count=MIN_ROWS_DATA_OK[tf] + 10, step_seconds=step)
        path = tmp_path / default_ohlc_cache_path(asset, tf).name
        save_ohlc_cache(path, ticker=asset, timeframe=tf, rows=rows)


def test_manifest_file_exists() -> None:
    assert MANIFEST.is_file(), f"missing manifest: {MANIFEST}"


def test_manifest_schema() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "entries" in payload
    assert isinstance(payload["entries"], list)
    for row in payload["entries"]:
        for key in (
            "asset",
            "timeframe",
            "cache_path",
            "row_count",
            "data_ok",
            "sha256",
            "source",
            "generated_at_utc",
            "blocked_reason",
        ):
            assert key in row


def test_can_run_full_tournament_requires_btc_eth_all_tf() -> None:
    manifest = [
        {"asset": "BTC", "timeframe": tf, "data_ok": True}
        for tf in ("1d", "4h", "1h")
    ] + [
        {"asset": "ETH", "timeframe": tf, "data_ok": True}
        for tf in ("1d", "4h", "1h")
    ]
    assert can_run_full_tournament(manifest) is True
    broken = [dict(r, data_ok=False) for r in manifest if r["timeframe"] == "1h"]
    assert can_run_full_tournament(broken) is False


def test_audit_manifest_on_fixtures(tmp_path: Path) -> None:
    for asset in ("BTC", "ETH"):
        _seed_backbone(tmp_path, asset)
    manifest = audit_manifest(assets=("BTC", "ETH", "SOL"), cache_root=tmp_path)
    btc_eth = [e for e in manifest if e["asset"] in ("BTC", "ETH")]
    assert all(e["data_ok"] for e in btc_eth if e["timeframe"] in ("1d", "4h", "1h"))
    sol_rows = [e for e in manifest if e["asset"] == "SOL"]
    assert all(not e["data_ok"] for e in sol_rows)


def test_parse_binance_klines_intraday_preserves_open_time() -> None:
    open_ms = 1_700_000_000_000
    payload = [
        [open_ms, "1", "2", "0.5", "1.5", "100", 0, "150"],
    ]
    rows = parse_binance_klines_intraday(payload)
    assert rows[0]["timestamp"] == open_ms // 1000


def test_fetch_binance_klines_1h_injected_fetcher() -> None:
    step = 3600

    def fake_fetcher(_url: str, params: dict) -> list:
        start_ms = int(params["startTime"])
        out = []
        for i in range(1200):
            ms = start_ms + i * step * 1000
            c = 65000.0 + i
            out.append([ms, str(c), str(c + 1), str(c - 1), str(c), "1.0", 0, "6500"])
        return out

    rows = fetch_binance_klines(
        "BTC",
        "1h",
        coverage_days=60,
        fetcher=fake_fetcher,
    )
    assert len(rows) >= 1000


def test_default_ohlc_cache_path_names() -> None:
    assert default_ohlc_cache_path("btc", "1h").name == "ohlc_1h_BTC.json"
    assert default_ohlc_cache_path("eth", "4h").name == "ohlc_4h_ETH.json"
    assert default_ohlc_cache_path("sol", "1d").name == "ohlc_daily_SOL.json"
