from __future__ import annotations

from unittest.mock import patch

import pytest

from src.research.world_order_flow import (
    WEEK_SECONDS,
    analyze_portfolios,
    build_asset_weeks,
    build_portfolio_weeks,
)

MONDAY = 1_704_067_200


def _inputs(asset_count: int = 30, weeks: int = 2):
    flows: list[dict] = []
    prices: list[dict] = []
    universe: dict[int, list[str]] = {}
    for week_index in range(weeks):
        week = MONDAY + week_index * WEEK_SECONDS
        universe[week] = []
        for asset_index in range(asset_count):
            base = f"A{asset_index:02d}"
            universe[week].append(base)
            quote = 1_000.0
            buy = 500.0 + asset_index
            flows.append(
                {
                    "week_start": week,
                    "base_asset": base,
                    "quote_volume": quote,
                    "taker_buy_quote_volume": buy,
                }
            )
            prices.append(
                {
                    "week_start": week,
                    "base_asset": base,
                    "entry_timestamp": week + WEEK_SECONDS + 3_600,
                    "exit_timestamp": week + 2 * WEEK_SECONDS + 3_600,
                    "entry_price": 100.0,
                    "exit_price": 102.0 + asset_index / 100.0,
                }
            )
    return flows, prices, universe


def test_cross_section_selects_positive_top_quintile_equal_weight() -> None:
    flows, prices, universe = _inputs()
    asset_weeks, diagnostics = build_asset_weeks(flows, prices, universe)
    portfolios = build_portfolio_weeks(asset_weeks)
    assert diagnostics["incomplete_weeks_excluded"] == 0
    assert len(portfolios) == 2
    assert portfolios[0].universe_size == 30
    assert portfolios[0].selected_assets == tuple(f"A{i:02d}" for i in range(24, 30))
    assert portfolios[0].gross_return > 0


def test_missing_member_excludes_whole_week_without_replacement() -> None:
    flows, prices, universe = _inputs(weeks=1)
    prices.pop()
    asset_weeks, diagnostics = build_asset_weeks(flows, prices, universe)
    assert asset_weeks == []
    assert diagnostics["missing_asset_weeks"] == 1
    assert diagnostics["incomplete_weeks_excluded"] == 1


def test_cash_week_has_no_cost() -> None:
    flows, prices, universe = _inputs(weeks=1)
    for row in flows:
        row["taker_buy_quote_volume"] = 400.0
    asset_weeks, _ = build_asset_weeks(flows, prices, universe)
    portfolio = build_portfolio_weeks(asset_weeks)[0]
    assert portfolio.selected_assets == ()
    assert portfolio.net_return(150.0) == 0.0


def test_non_positive_top_quintile_slots_remain_cash() -> None:
    flows, prices, universe = _inputs(weeks=1)
    # Three of six target slots remain non-positive; selected slots must not be
    # reweighted to a 100% portfolio.
    for index, row in enumerate(flows):
        row["taker_buy_quote_volume"] = 503.0 if index >= 27 else 497.0
    asset_weeks, _ = build_asset_weeks(flows, prices, universe)
    portfolio = build_portfolio_weeks(asset_weeks)[0]
    assert portfolio.target_slots == 6
    assert len(portfolio.selected_assets) == 3
    assert portfolio.net_return(100.0) < portfolio.gross_return
    assert portfolio.net_return(100.0) == pytest.approx(portfolio.gross_return - 0.005)


def test_all_analysis_gates_are_cumulative() -> None:
    flows, prices, universe = _inputs(weeks=104)
    asset_weeks, _ = build_asset_weeks(flows, prices, universe)
    portfolios = build_portfolio_weeks(asset_weeks)
    with (
        patch(
            "src.research.world_order_flow._block_bootstrap_lower_bound",
            return_value=0.001,
        ),
        patch(
            "src.research.world_order_flow._sign_permutation_p_value",
            return_value=0.001,
        ),
    ):
        result = analyze_portfolios(portfolios)
    assert result["eligible_weeks"] == 104
    assert result["status"] == "candidate_for_forward_observation"
    assert all(result["gates"].values())
