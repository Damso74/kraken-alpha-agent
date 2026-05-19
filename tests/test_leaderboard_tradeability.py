"""Leaderboard V2 economic overlay — deterministic, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reports._build_leaderboard import (
    PHASE6,
    apply_red_team_final_cap,
    build_phase11_rows,
    build_rows,
    row_from_json_with_economics,
)
from src.research.tradeability import (
    TURNOVER_REJECT_THRESHOLD,
    TradeabilityVerdict,
    apply_economic_verdict_overlay,
    build_leaderboard_economic_overlay,
    compute_turnover_proxy,
    select_return_cell_for_economics,
)

REPO = Path(__file__).resolve().parent.parent


def _cell(
    *,
    metric: str = "return",
    window: str = "post_7",
    mean: float = 0.012,
    p: float = 0.03,
) -> dict:
    return {
        "metric": metric,
        "window": window,
        "mean": mean,
        "baseline": 0.0,
        "n_events": 20,
        "two_sided_p": p,
    }


def test_select_return_cell_prefers_bh_rejected_post_7() -> None:
    cells = [
        _cell(window="post_1", mean=0.02, p=0.01),
        _cell(window="post_7", mean=0.015, p=0.04),
        _cell(metric="realized_vol", window="post_7", mean=0.03, p=0.01),
    ]
    mask = [False, True, True]
    picked = select_return_cell_for_economics(cells, bh_rejected_mask=mask)
    assert picked is not None
    assert picked["window"] == "post_7"
    assert picked["metric"] == "return"


def test_select_return_cell_falls_back_to_post_7_without_bh() -> None:
    cells = [
        _cell(window="post_3", mean=0.01),
        _cell(window="post_7", mean=0.008),
    ]
    picked = select_return_cell_for_economics(cells)
    assert picked is not None
    assert picked["window"] == "post_7"


def test_turnover_proxy_flags_high_activation() -> None:
    ratio, too_high = compute_turnover_proxy(40, 100)
    assert ratio == pytest.approx(0.4)
    assert too_high is True

    low_ratio, low_flag = compute_turnover_proxy(10, 100)
    assert low_ratio == pytest.approx(0.1)
    assert low_flag is False


def test_overlay_cost_dominated_even_when_bh_supported() -> None:
    report = {
        "events_count": 20,
        "candles_count": 400,
        "bh_rejected": 1,
        "bh_rejected_mask": [False, True, False],
        "cells": [
            _cell(window="post_3", mean=0.007, p=0.02),
            _cell(window="post_7", mean=0.007, p=0.01),
            _cell(window="post_1", mean=0.002, p=0.5),
        ],
    }
    overlay = build_leaderboard_economic_overlay(report, bh_supported=True)
    assert overlay.cost_dominated is True
    assert overlay.economic_reject is True
    assert overlay.tradeability_verdict == TradeabilityVerdict.COST_DOMINATED.value
    assert overlay.reference_cell == "return/post_7"


def test_overlay_rejects_high_turnover() -> None:
    report = {
        "events_count": 150,
        "candles_count": 400,
        "bh_rejected": 0,
        "cells": [_cell(mean=0.025)],
    }
    overlay = build_leaderboard_economic_overlay(report)
    assert overlay.turnover_proxy == pytest.approx(150 / 400)
    assert overlay.turnover_proxy > TURNOVER_REJECT_THRESHOLD
    assert overlay.economic_reject is True
    assert "turnover" in (overlay.economic_reject_reason or "").lower()


def test_overlay_rejects_few_events() -> None:
    report = {
        "events_count": 3,
        "candles_count": 365,
        "bh_rejected": 0,
        "cells": [_cell(mean=0.03)],
    }
    overlay = build_leaderboard_economic_overlay(report)
    assert overlay.economic_reject is True
    assert "events" in (overlay.economic_reject_reason or "").lower()


def test_overlay_rejects_high_concentration_when_contributions_present() -> None:
    report = {
        "events_count": 6,
        "candles_count": 365,
        "bh_rejected": 1,
        "bh_rejected_mask": [True],
        "cells": [_cell(mean=0.025)],
        "event_returns": [80.0, 5.0, 5.0, 5.0, 3.0, 2.0],
        "event_months": ["2024-01"] * 6,
    }
    overlay = build_leaderboard_economic_overlay(report, bh_supported=True)
    assert overlay.concentration_verdict == "high_concentration_risk"
    assert overlay.economic_reject is True
    assert "concentration" in (overlay.economic_reject_reason or "").lower() or "dominated" in (
        overlay.economic_reject_reason or ""
    ).lower()


def test_apply_economic_verdict_downgrades_oos_candidate() -> None:
    overlay = build_leaderboard_economic_overlay(
        {
            "events_count": 20,
            "candles_count": 400,
            "bh_rejected": 1,
            "bh_rejected_mask": [True],
            "cells": [_cell(mean=0.007)],
        },
        bh_supported=True,
    )
    verdict, reason = apply_economic_verdict_overlay(
        "candidate for OOS retest",
        None,
        overlay,
    )
    assert verdict == "weak evidence"
    assert reason is not None
    assert overlay.economic_reject_reason in reason or reason.startswith(overlay.economic_reject_reason or "")


def test_row_from_json_with_economics_on_demo_fng_artifact() -> None:
    path = REPO / "reports" / "research_runs_v2" / "demo_fng_365d.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    meta = PHASE6["known_json"]["demo_fng_365d.json"]
    row = row_from_json_with_economics(
        "demo_fng_365d.json",
        meta,
        report,
        runs_rel="reports/research_runs_v2",
        run_log=PHASE6["run_log"],
        verdict_rules="phase6",
    )
    assert row.tradeability_verdict is not None
    assert row.economic_reject is True
    assert row.verdict == "weak evidence"
    assert row.cost_dominated is True


def test_phase11_red_team_fail_revokes_oos_candidate() -> None:
    verdict, reason = apply_red_team_final_cap(
        "candidate for further OOS testing",
        "fail",
        rejection_reason="BH vol/volume",
    )
    assert verdict == "weak evidence"
    assert reason is not None
    assert "red team" in reason.lower()


def test_phase11_red_team_revoked_wikipedia_tag() -> None:
    verdict, reason = apply_red_team_final_cap(
        "candidate for further OOS testing",
        "revoked",
    )
    assert verdict == "weak evidence"
    assert reason is not None
    assert "revoked_by_red_team" in reason


def test_phase11_red_team_warning_does_not_block_by_itself() -> None:
    verdict, _ = apply_red_team_final_cap(
        "candidate for further OOS testing",
        "warning",
    )
    assert verdict == "candidate for further OOS testing"


def test_build_phase11_rows_zero_oos_after_red_team() -> None:
    rows = build_phase11_rows()
    assert rows
    oos = [r for r in rows if r.final_verdict == "candidate for further OOS testing"]
    assert oos == []
    wiki = [r for r in rows if r.signal.startswith("wikipedia_")]
    assert wiki
    for row in wiki:
        assert row.red_team_status == "revoked"
        assert row.final_verdict == "weak evidence"
        assert row.rejection_reason is not None
        assert "revoked_by_red_team" in row.rejection_reason


def test_build_rows_v2_includes_economic_fields() -> None:
    rows = build_rows(PHASE6)
    evaluated = [r for r in rows if r.artifact]
    assert evaluated
    for row in evaluated:
        assert row.turnover_proxy is not None
        assert row.tradeability_verdict is not None or row.gross_avg_return_pct is None
