"""High-level orchestrator used by the agent scripts.

``run_one_cycle`` walks the full pipeline for every symbol in the universe and
returns the list of decisions. The function is import-safe (no side effects
at module import time) so it can be unit-tested.
"""

from __future__ import annotations

import time
from typing import Iterable

from . import (
    execution as execution_mod,
    features as features_mod,
    llm_explainer,
    market_data,
    pnl as pnl_mod,
    portfolio,
    ranking as ranking_mod,
    risk as risk_mod,
    storage,
)
from .config import get_settings
from .logger import get_logger
from .schemas import Decision
from .strategies import breakout_score, combine, mean_reversion_score, momentum_score
from .universe import build_dynamic_universe, get_universe
from .utils import new_id, utc_now_iso, utc_now_ms

logger = get_logger(__name__)


def _vote_for(features) -> list:
    return [
        momentum_score(features),
        breakout_score(features),
        mean_reversion_score(features),
    ]


def _build_decision(
    *,
    cycle_id: str,
    ticker: dict,
    candles: list[dict],
    symbol: str,
    liquidity_score: float | None = None,
) -> Decision:
    settings = get_settings()
    feats = features_mod.compute_features(symbol=symbol, ticker=ticker, candles=candles)
    votes = _vote_for(feats)
    ensemble = combine(features=feats, votes=votes, liquidity_score=liquidity_score)
    snapshot = portfolio.get_snapshot()
    risk = risk_mod.evaluate_risk(
        ensemble=ensemble,
        features=feats,
        portfolio=snapshot,
        settings=settings,
    )
    execution_result = execution_mod.execute(
        features=feats,
        ensemble=ensemble,
        risk=risk,
    )
    decision = Decision(
        cycle_id=cycle_id,
        symbol=symbol,
        action=ensemble.action,
        final_score=ensemble.final_score,
        confidence=ensemble.confidence,
        suggested_size_usd=ensemble.suggested_size_usd,
        approved_size_usd=risk.adjusted_size_usd if risk.approved else 0.0,
        regime=ensemble.regime,
        features=feats,
        votes=ensemble.votes,
        risk=risk,
        execution=execution_result,
        mode=settings.env.trading_mode.lower(),  # type: ignore[arg-type]
        rationale=ensemble.rationale,
    )
    if settings.env.featherless_api_key:
        try:
            decision.llm = llm_explainer.explain(decision)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM explainer failed for %s: %s", symbol, exc)
    return decision


def _persist(decision: Decision) -> None:
    storage.write_decision(decision)
    storage.write_order(decision_id=decision.id, result=decision.execution)
    execution_mod.apply_to_portfolio(decision)
    if decision.risk.approved and decision.action in ("BUY", "SELL"):
        risk_mod.mark_traded(decision.symbol)


def resolve_universe(settings=None) -> tuple[list[str], dict[str, float], str]:
    """Return ``(symbols, liquidity_by_symbol, mode_label)``.

    In ``static`` mode this just reads the allowlist. In ``dynamic`` mode we
    run one ranking pass and keep the top-N candidates. The liquidity map is
    forwarded to the ensemble so downstream confidence reflects book health.
    """
    settings = settings or get_settings()
    uni_cfg = settings.config.universe
    mode = (uni_cfg.mode or "static").lower()
    allowlist = [u.ticker for u in get_universe()]
    if mode != "dynamic":
        return allowlist, {}, "static"

    # Lazy import to avoid a circular dependency on script startup.
    from . import ranking as _ranking_mod  # noqa: F401  (alias for clarity)

    rank_data: list = []
    for sym in allowlist:
        try:
            ticker = market_data.get_ticker(sym, uni_cfg.quote)
            ohlc = market_data.get_ohlc(sym, uni_cfg.quote, interval_minutes=60, count=24)
            book = None
            trades = None
            try:
                book = market_data.get_orderbook(sym, uni_cfg.quote, count=10)
            except Exception as exc:  # noqa: BLE001
                logger.debug("orderbook fetch failed for %s: %s", sym, exc)
            try:
                trades = market_data.get_trades(sym, uni_cfg.quote, count=50)
            except Exception as exc:  # noqa: BLE001
                logger.debug("trades fetch failed for %s: %s", sym, exc)
            from .universe import pair_format
            ranked = ranking_mod.compute_symbol_rank(
                sym,
                pair=pair_format(sym, uni_cfg.quote),
                ticker=ticker,
                candles=ohlc,
                orderbook=book,
                trades=trades,
            )
            rank_data.append(ranked)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ranking pass failed for %s: %s", sym, exc)
    selected = build_dynamic_universe(rank_data, uni_cfg)
    liq_map = {r.symbol: r.liquidity_score for r in rank_data}
    if not selected:
        return allowlist, liq_map, "static_fallback"
    return selected, liq_map, "dynamic"


def run_one_cycle(
    symbols: Iterable[str] | None = None,
    *,
    cycle_id: str | None = None,
) -> list[Decision]:
    settings = get_settings()
    cycle_id = cycle_id or new_id("cyc")
    storage.start_cycle(cycle_id, settings.env.trading_mode.lower())
    started_ms = utc_now_ms()
    if symbols is not None:
        universe = list(symbols)
        liquidity_map: dict[str, float] = {}
        mode_label = "explicit"
    else:
        universe, liquidity_map, mode_label = resolve_universe(settings)
    logger.info(
        "cycle=%s mode=%s profile=%s universe(%d)=%s",
        cycle_id,
        mode_label,
        settings.active_profile,
        len(universe),
        universe,
    )
    decisions: list[Decision] = []
    errors = 0
    for symbol in universe:
        try:
            ticker = market_data.get_ticker(symbol, settings.config.universe.quote)
            candles = market_data.get_ohlc(
                symbol,
                settings.config.universe.quote,
                interval_minutes=60,
                count=24,
            )
            decision = _build_decision(
                cycle_id=cycle_id,
                ticker=ticker,
                candles=candles,
                symbol=symbol,
                liquidity_score=liquidity_map.get(symbol),
            )
            _persist(decision)
            decisions.append(decision)
            logger.info(
                "cycle=%s %s action=%s score=%+.3f conf=%.2f approved=%s",
                cycle_id, symbol, decision.action, decision.final_score,
                decision.confidence, decision.risk.approved,
            )
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.exception("cycle=%s %s failed: %s", cycle_id, symbol, exc)
            storage.record_error("run_one_cycle", str(exc), {"symbol": symbol})

    snap = pnl_mod.snapshot_and_persist()
    duration_ms = utc_now_ms() - started_ms
    approved = sum(1 for d in decisions if d.risk.approved)
    storage.finish_cycle(
        cycle_id,
        duration_ms=duration_ms,
        symbols_seen=len(universe),
        decisions=len(decisions),
        approved=approved,
        errors=errors,
        summary={
            "net_pnl_usd": snap.net_usd,
            "equity_usd": snap.equity_usd,
            "approved_actions": [d.symbol for d in decisions if d.risk.approved],
            "started_at": utc_now_iso(),
        },
    )
    return decisions


def run_loop(stop_event=None) -> None:
    """Continuous cycle runner used by ``scripts/run_agent_loop.py``."""
    settings = get_settings()
    interval = max(2, settings.config.trading.cycle_interval_seconds)
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        try:
            run_one_cycle()
        except Exception as exc:  # noqa: BLE001
            logger.exception("cycle crashed: %s", exc)
            storage.record_error("run_loop", str(exc))
        # Sleep in 1-second slices so Ctrl+C remains responsive.
        for _ in range(interval):
            if stop_event is not None and stop_event.is_set():
                return
            time.sleep(1)


__all__ = ["run_one_cycle", "run_loop", "resolve_universe"]
