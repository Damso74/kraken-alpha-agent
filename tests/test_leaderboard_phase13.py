"""Phase 13 leaderboard + multi-asset volume shock artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from reports._build_leaderboard import build_phase13_rows

REPO = Path(__file__).resolve().parent.parent


def test_build_phase13_rows_zero_oos_when_artifacts_present() -> None:
    runs = REPO / "reports" / "research_runs_phase13"
    source = runs / "volume_shock_multi_asset_365d.json"
    if not source.is_file():
        source = runs / "volume_shock_protocol_a_365d.json"
    if not source.is_file():
        return
    rows = build_phase13_rows()
    oos = [r for r in rows if r.final_verdict == "candidate for further OOS testing"]
    assert oos == []
    assert rows
    protocols = {r.protocol for r in rows}
    assert "protocol_a" in protocols


def test_phase13_json_has_provenance_and_holdout_on_btc() -> None:
    path = REPO / "reports" / "research_runs_phase13" / "volume_shock_protocol_a_365d.json"
    if not path.is_file():
        return
    doc = json.loads(path.read_text(encoding="utf-8"))
    btc = doc.get("assets", {}).get("BTC", {})
    assert btc.get("status") == "ok"
    variant = btc.get("variants", {}).get("vol_z20_high", {})
    assert variant.get("data_provenance")
    assert "holdout" in variant


def test_phase13_manifest_partial_sol() -> None:
    manifest = REPO / "reports" / "data_manifests_phase13" / "ohlcv_multi_asset_manifest.json"
    if not manifest.is_file():
        return
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    assert doc["decision"] == "partial_assets_available"
    assert doc["assets"]["SOL"]["status"] == "blocked_data"
