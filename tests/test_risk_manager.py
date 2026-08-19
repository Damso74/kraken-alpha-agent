"""Tests for paper risk manager."""

from __future__ import annotations

from src.bot.orders import Order
from src.bot.risk_manager import RiskConfig, RiskManager


def test_deny_max_position_fraction() -> None:
    rm = RiskManager(RiskConfig(max_position_fraction=0.10))
    rm.on_bar(equity=1000.0, timestamp="2024-01-01")
    order = Order("BTC", "buy", 1.0, 200.0, 0, 1, "t")
    d = rm.validate_order(
        order,
        equity=1000.0,
        cash_usd=1000.0,
        position_fraction=0.0,
        exposure_fraction=0.0,
    )
    assert d.verdict == "deny"
    assert d.rule == "max_position_fraction"


def test_allow_small_order() -> None:
    rm = RiskManager()
    rm.on_bar(equity=1000.0, timestamp="2024-01-01")
    order = Order("BTC", "buy", 0.01, 100.0, 0, 1, "t")
    d = rm.validate_order(
        order,
        equity=1000.0,
        cash_usd=1000.0,
        position_fraction=0.0,
        exposure_fraction=0.0,
    )
    assert d.verdict == "allow"


# --- exit-only : un ordre qui REDUIT l'exposition ne doit jamais etre bloque ---
#
# Chaque test ci-dessous sature une garde de risque, puis verifie que la VENTE
# passe (la position reste soldable) alors que l'ACHAT reste refuse par cette
# meme garde dans la meme situation.


def _order(side: str, qty: float, price: float) -> Order:
    return Order("BTC", side, qty, price, 0, 1, "t")


def test_sell_allowed_over_max_position_fraction() -> None:
    """Position a 30% pour un plafond de 20% : la sortie doit rester possible."""
    rm = RiskManager(
        RiskConfig(max_position_fraction=0.20, max_total_exposure=1.0, max_trades_per_day=100)
    )
    rm.on_bar(equity=1250.0, timestamp="2024-01-01")
    kwargs = {
        "equity": 1250.0,
        "cash_usd": 875.0,
        "position_fraction": 0.30,
        "exposure_fraction": 0.30,
    }

    sell = rm.validate_order(_order("sell", 1.0, 250.0), **kwargs)
    assert sell.verdict == "allow", sell

    buy = rm.validate_order(_order("buy", 1.0, 250.0), **kwargs)
    assert buy.verdict == "deny"
    assert buy.rule == "max_position_fraction"


def test_sell_allowed_over_max_total_exposure() -> None:
    """Exposition a 60% pour un plafond de 50% : une reduction partielle passe."""
    rm = RiskManager(
        RiskConfig(
            max_total_exposure=0.50,
            max_position_fraction=1.0,
            min_cash_reserve=0.0,
            max_trades_per_day=100,
        )
    )
    rm.on_bar(equity=1000.0, timestamp="2024-01-01")
    kwargs = {
        "equity": 1000.0,
        "cash_usd": 400.0,
        "position_fraction": 0.60,
        "exposure_fraction": 0.60,
    }

    sell = rm.validate_order(_order("sell", 1.0, 50.0), **kwargs)
    assert sell.verdict == "allow", sell

    buy = rm.validate_order(_order("buy", 1.0, 50.0), **kwargs)
    assert buy.verdict == "deny"
    assert buy.rule == "max_total_exposure"


def test_sell_allowed_when_daily_trade_quota_exhausted() -> None:
    """Quota de trades du jour epuise : on peut encore solder, pas rentrer."""
    rm = RiskManager(
        RiskConfig(max_trades_per_day=2, max_position_fraction=1.0, max_total_exposure=1.0)
    )
    rm.on_bar(equity=1000.0, timestamp="2024-01-01")
    rm.record_trade()
    rm.record_trade()
    kwargs = {
        "equity": 1000.0,
        "cash_usd": 500.0,
        "position_fraction": 0.05,
        "exposure_fraction": 0.05,
    }

    sell = rm.validate_order(_order("sell", 1.0, 50.0), **kwargs)
    assert sell.verdict == "allow", sell

    buy = rm.validate_order(_order("buy", 1.0, 50.0), **kwargs)
    assert buy.verdict == "deny"
    assert buy.rule == "max_trades_per_day"


def test_sell_allowed_after_max_drawdown_stop() -> None:
    """Stop de drawdown declenche : il coupe le risque, il ne piege pas la position."""
    rm = RiskManager(
        RiskConfig(
            max_drawdown_pct=0.15,
            max_daily_loss_pct=1.0,
            max_position_fraction=1.0,
            max_total_exposure=1.0,
            max_trades_per_day=100,
        )
    )
    rm.on_bar(equity=1000.0, timestamp="2024-01-01")
    rm.on_bar(equity=800.0, timestamp="2024-01-01")
    kwargs = {
        "equity": 800.0,
        "cash_usd": 400.0,
        "position_fraction": 0.05,
        "exposure_fraction": 0.05,
    }

    sell = rm.validate_order(_order("sell", 1.0, 50.0), **kwargs)
    assert sell.verdict == "allow", sell

    buy = rm.validate_order(_order("buy", 1.0, 50.0), **kwargs)
    assert buy.verdict == "deny"
    assert buy.rule == "max_drawdown_pct"


def test_sell_allowed_after_max_daily_loss_stop() -> None:
    """Stop de perte journaliere declenche : la sortie reste possible."""
    rm = RiskManager(
        RiskConfig(
            max_daily_loss_pct=0.03,
            max_drawdown_pct=1.0,
            max_position_fraction=1.0,
            max_total_exposure=1.0,
            max_trades_per_day=100,
        )
    )
    rm.on_bar(equity=1000.0, timestamp="2024-01-01")
    kwargs = {
        "equity": 900.0,
        "cash_usd": 400.0,
        "position_fraction": 0.05,
        "exposure_fraction": 0.05,
    }

    sell = rm.validate_order(_order("sell", 1.0, 50.0), **kwargs)
    assert sell.verdict == "allow", sell

    buy = rm.validate_order(_order("buy", 1.0, 50.0), **kwargs)
    assert buy.verdict == "deny"
    assert buy.rule == "max_daily_loss_pct"


def test_zero_equity_still_denies_both_sides() -> None:
    """Garde de donnees degeneres (pas un plafond de risque) : inchangee."""
    rm = RiskManager()
    kwargs = {
        "equity": 0.0,
        "cash_usd": 0.0,
        "position_fraction": 0.0,
        "exposure_fraction": 0.0,
    }
    for side in ("buy", "sell"):
        d = rm.validate_order(_order(side, 1.0, 50.0), **kwargs)
        assert d.verdict == "deny"
        assert d.rule == "equity"
