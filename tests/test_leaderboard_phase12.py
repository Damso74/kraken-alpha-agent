"""Phase 12 leaderboard + red team JSON gating."""

from __future__ import annotations

import json
from pathlib import Path

from reports._build_leaderboard import (
    RED_TEAM_VERDICTS_JSON,
    apply_red_team_final_cap,
    build_phase12_rows,
    load_red_team_verdict_rules,
    lookup_red_team_status,
)

REPO = Path(__file__).resolve().parent.parent


def test_red_team_verdicts_json_loads() -> None:
    rules = load_red_team_verdict_rules()
    assert rules
    doc = json.loads(RED_TEAM_VERDICTS_JSON.read_text(encoding="utf-8"))
    assert doc["schema_version"] == "phase12-v1"


def test_lookup_wikipedia_revoked() -> None:
    assert lookup_red_team_status("wikipedia_crypto_basket_z2.0") == "revoked"


def test_red_team_fail_blocks_oos() -> None:
    verdict, reason = apply_red_team_final_cap(
        "candidate for further OOS testing",
        "fail",
    )
    assert verdict == "weak evidence"
    assert reason is not None


def test_build_phase12_rows_zero_oos_when_artifacts_present() -> None:
    runs = REPO / "reports" / "research_runs_phase12"
    if not (runs / "volume_shock_all_365d.json").is_file():
        return
    rows = build_phase12_rows()
    oos = [r for r in rows if r.final_verdict == "candidate for further OOS testing"]
    assert oos == []
