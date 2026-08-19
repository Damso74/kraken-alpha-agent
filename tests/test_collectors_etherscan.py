"""Hermetic tests for :mod:`src.data.collectors.etherscan`."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.data.collectors.etherscan import (
    BLOCKED_MISSING_GAS_HISTORY,
    SYNTHETIC_GAS_HISTORY_EXAMPLE,
    CollectorError,
    append_oracle_snapshot_to_history,
    default_gas_history_example_path,
    fetch_gas_oracle,
    load_gas_history,
    merge_gas_history,
    normalize_gas_history_row,
    parse_gas_oracle_payload,
    persist_gas_history,
    resolve_gas_history,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

GAS_FIXTURE = {
    "status": "1",
    "message": "OK",
    "result": {
        "SafeGasPrice": "10",
        "ProposeGasPrice": "12",
        "FastGasPrice": "15",
    },
}


def test_parse_gas_oracle_payload() -> None:
    rows = parse_gas_oracle_payload(GAS_FIXTURE, fetched_at=1_700_000_000)
    assert len(rows) == 1
    assert rows[0]["safe_gwei"] == 10.0
    assert rows[0]["fast_gwei"] == 15.0
    assert rows[0]["timestamp"] == 1_700_000_000


def test_parse_gas_oracle_payload_error_status() -> None:
    with pytest.raises(CollectorError):
        parse_gas_oracle_payload({"status": "0", "message": "NOTOK", "result": {}})


def test_fetch_gas_oracle_uses_injected_fetcher(tmp_path: Path) -> None:
    def fake_fetcher(_key: str | None) -> dict:
        return GAS_FIXTURE

    rows = fetch_gas_oracle(fetcher=fake_fetcher, api_key="test-key")
    assert len(rows) == 1
    assert rows[0]["has_api_key"] is True


def test_fetch_gas_oracle_cache_hit(tmp_path: Path) -> None:
    cache_path = tmp_path / "gas.json"
    snapshot = parse_gas_oracle_payload(GAS_FIXTURE, fetched_at=int(time.time()))[0]
    snapshot["has_api_key"] = True
    cache_path.write_text(
        json.dumps({"fetched_at": snapshot["timestamp"], "snapshot": snapshot}),
        encoding="utf-8",
    )

    def explode(_key: str | None) -> dict:
        raise AssertionError("fetcher must not run on fresh cache")

    rows = fetch_gas_oracle(cache_path=cache_path, fetcher=explode, api_key="k")
    assert rows[0]["safe_gwei"] == 10.0


def test_fetch_gas_oracle_no_key_degrades_on_error() -> None:
    def failing_fetcher(_key: str | None) -> dict:
        raise CollectorError("rate limited")

    rows = fetch_gas_oracle(fetcher=failing_fetcher, api_key="")
    assert rows == []


def test_normalize_gas_history_row_midnight_utc() -> None:
    # 2021-01-01 12:34:56 UTC → midnight same day
    row = normalize_gas_history_row({"timestamp": 1_609_499_696, "fast_gwei": 20.0})
    assert row is not None
    assert row["timestamp"] == 1_609_459_200
    assert row["fast_gwei"] == 20.0
    assert row["source"] == "etherscan_gas_history"


def test_normalize_rejects_invalid_rows() -> None:
    assert normalize_gas_history_row({"timestamp": "x", "fast_gwei": 1.0}) is None
    assert normalize_gas_history_row({"timestamp": 1, "fast_gwei": -1.0}) is None


def test_load_and_persist_gas_history_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    persist_gas_history(path, SYNTHETIC_GAS_HISTORY_EXAMPLE["entries"]["daily"])
    loaded = load_gas_history(path)
    assert len(loaded) == 2
    assert loaded[0]["fast_gwei"] == 42.0


def test_merge_gas_history_overwrites_same_day() -> None:
    existing = [{"timestamp": 1_609_459_200, "fast_gwei": 10.0, "source": "etherscan_gas_history"}]
    fresh = [{"timestamp": 1_609_499_000, "fast_gwei": 99.0, "source": "etherscan_gas_history"}]
    merged = merge_gas_history(existing, fresh)
    assert len(merged) == 1
    assert merged[0]["fast_gwei"] == 99.0


def test_append_oracle_snapshot_to_history(tmp_path: Path) -> None:
    snap = parse_gas_oracle_payload(GAS_FIXTURE, fetched_at=1_700_000_000)
    merged = append_oracle_snapshot_to_history([], snap)
    assert len(merged) == 1
    assert merged[0]["fast_gwei"] == 15.0


def test_resolve_gas_history_cache_only_empty_raises(tmp_path: Path) -> None:
    path = tmp_path / "missing_history.json"
    with pytest.raises(CollectorError, match=BLOCKED_MISSING_GAS_HISTORY):
        resolve_gas_history(path, use_cache_only=True)


def test_resolve_gas_history_cache_only_loads(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    persist_gas_history(path, [{"timestamp": 1_609_459_200, "fast_gwei": 1.0, "source": "etherscan_gas_history"}])

    def explode(_key: str | None) -> dict:
        raise AssertionError("network fetch must not run in cache-only mode")

    rows = resolve_gas_history(
        path,
        use_cache_only=True,
        snapshot_cache_path=tmp_path / "snap.json",
        fetcher=explode,
    )
    assert len(rows) == 1


def test_resolve_gas_history_merges_snapshot_without_network(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    snap_path = tmp_path / "snap.json"

    def fake_fetcher(_key: str | None) -> dict:
        return GAS_FIXTURE

    rows = resolve_gas_history(
        history_path,
        use_cache_only=False,
        snapshot_cache_path=snap_path,
        fetcher=fake_fetcher,
        api_key="k",
    )
    assert rows
    assert history_path.exists()
    reloaded = load_gas_history(history_path)
    assert reloaded[0]["fast_gwei"] == 15.0


def test_committed_example_matches_synthetic_constant() -> None:
    example_path = REPO_ROOT / default_gas_history_example_path()
    if not example_path.is_file():
        pytest.skip("example file not on disk")
    on_disk = json.loads(example_path.read_text(encoding="utf-8"))
    assert on_disk["_meta"]["label"] == "SYNTHETIC_EXAMPLE"
    assert on_disk["source"] == SYNTHETIC_GAS_HISTORY_EXAMPLE["source"]
    assert len(on_disk["entries"]["daily"]) == 2


def test_event_study_eth_gas_cache_only_blocked_message(tmp_path: Path) -> None:
    empty = tmp_path / "empty_gas_history.json"
    empty.write_text("{}", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "event_study_eth_gas.py"),
            "--use-cache-only",
            "--history-cache",
            str(empty),
            "--days",
            "30",
            "--n-placebos",
            "5",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert BLOCKED_MISSING_GAS_HISTORY in proc.stderr
