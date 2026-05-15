"""Calibration gates applied between the ensemble and the risk manager.

The actionability layer is a *pre-risk* filter that downgrades non-tradable
intents to HOLD before they ever reach the order builder. It is the single
place that owns these rules:

- BUY only if ``final_score >= trading.min_opportunity_score_buy``.
- BUY refused when ``no_trade_if_negative_opportunity`` and score < 0.
- SELL only if ``|final_score| >= trading.min_opportunity_score_sell``.
- SELL is exit-only by default — without an existing long position the
  trade is blocked unless ``shorting_enabled`` is true *both* in the config
  and in the env. The size is clamped to the open quantity.
- Low ``liquidity_score`` shrinks the suggested size by a deterministic
  factor (does not flip the action).

The function is pure: it takes an ``EnsembleResult`` and returns a new one
together with the :class:`Actionability` record explaining the decision.
"""

from __future__ import annotations

from typing import Optional

from .config import Settings, get_settings
from .schemas import Actionability, EnsembleResult, Features, Position


def _shorting_enabled(settings: Settings) -> bool:
    """Shorting requires BOTH env (`SHORTING_ENABLED=true`) AND YAML
    (`trading.shorting_enabled: true`) to be opted-in *independently*.

    The two flags are intentionally kept separate (not merged) so an
    operator can never turn shorting on by mistake by editing just one
    place — both a config commit *and* an explicit env decision are
    required.
    """
    env_on = bool(settings.env.shorting_enabled) if settings.env.shorting_enabled is not None else False
    yaml_on = bool(settings.config.trading.shorting_enabled)
    return env_on and yaml_on


def apply_actionability_gates(
    *,
    ensemble: EnsembleResult,
    features: Features,
    position: Optional[Position],
    liquidity_score: float,
    settings: Optional[Settings] = None,
) -> tuple[EnsembleResult, Actionability]:
    """Return ``(possibly_downgraded_ensemble, actionability)``.

    The returned ensemble is a fresh instance; the input is not mutated.
    """
    s = settings or get_settings()
    t = s.config.trading
    score = ensemble.final_score
    suggested_size = ensemble.suggested_size_usd
    action = ensemble.action

    buy_min = float(t.min_opportunity_score_buy)
    sell_min = float(t.min_opportunity_score_sell)
    dampener = float(t.liquidity_size_dampener)
    factor = float(t.liquidity_size_factor)
    liq = float(liquidity_score)

    size_dampened = False
    if liq < dampener and suggested_size > 0:
        suggested_size = suggested_size * factor
        size_dampened = True

    reason = ""
    new_action = action
    rationale_extra: list[str] = []
    if size_dampened:
        rationale_extra.append(
            f"liquidity_dampened(liq={liq:.2f}<{dampener:.2f},factor={factor:.2f})"
        )

    buy_eligible = False
    sell_eligible = False

    if action == "BUY":
        if score < buy_min:
            new_action = "HOLD"
            reason = f"below_buy_threshold(score={score:+.3f}<{buy_min:+.3f})"
        elif t.no_trade_if_negative_opportunity and score < 0:
            new_action = "HOLD"
            reason = f"negative_opportunity(score={score:+.3f})"
        else:
            buy_eligible = True
            reason = reason or "buy_eligible"
    elif action == "SELL":
        if abs(score) < sell_min:
            new_action = "HOLD"
            reason = f"below_sell_threshold(|score|={abs(score):.3f}<{sell_min:.3f})"
        else:
            has_long = position is not None and position.quantity > 0
            if not has_long:
                if _shorting_enabled(s):
                    # Shorting is explicitly on (env + YAML). We still log
                    # the fact so it is easy to audit retrospectively.
                    sell_eligible = True
                    reason = "short_open_authorised"
                else:
                    new_action = "HOLD"
                    reason = "sell_without_position_shorting_disabled"
            else:
                # Exit-only: clamp the SELL notional to the open quantity.
                max_notional = position.quantity * max(features.last_price, 0.01)
                if suggested_size <= 0 or suggested_size > max_notional:
                    suggested_size = max_notional
                sell_eligible = True
                reason = "sell_exit"
    else:
        reason = "hold"

    rationale = ensemble.rationale
    if rationale_extra:
        rationale = f"{rationale} | {' '.join(rationale_extra)}".strip(" |")
    if new_action != action:
        rationale = f"{rationale} | actionability={reason}".strip(" |")

    updated = ensemble.model_copy(
        update={
            "action": new_action,
            "suggested_size_usd": max(suggested_size, 0.0),
            "rationale": rationale,
        }
    )
    return updated, Actionability(
        buy_eligible=buy_eligible,
        sell_eligible=sell_eligible,
        reason=reason,
        size_dampened=size_dampened,
        size_factor=factor if size_dampened else 1.0,
        opportunity_score=score,
        liquidity_score=liq,
    )


__all__ = ["apply_actionability_gates"]
