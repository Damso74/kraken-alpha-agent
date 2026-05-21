"""Phase 28 — shadow comparison: standalone vs overlay vs benchmarks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.bot.basis_crowding_overlay import BasisCrowdingState
from src.strategies.base import StrategySignal


@dataclass(frozen=True)
class ShadowComparisonRecord:
    timestamp: int
    price: float
    raw_signal: str
    standalone_action: str
    overlay_decision: str
    overlay_reason: str
    funding_z: float | None
    basis_z: float | None
    standalone_would_trade: bool
    overlay_blocks: bool
    effective_action: str
    buy_and_hold_action: str
    cash_action: str = "hold"


def _action_label(sig: StrategySignal | None) -> str:
    if sig is None:
        return "hold"
    return str(sig.action)


def standalone_would_trade(sig: StrategySignal | None) -> bool:
    if sig is None:
        return False
    return sig.action in ("buy", "sell")


def overlay_blocks_trade(
    standalone: StrategySignal | None,
    overlay_state: BasisCrowdingState,
    overlay_sig: StrategySignal | None,
) -> bool:
    if not standalone_would_trade(standalone):
        return False
    if standalone and standalone.action == "buy":
        if overlay_state.filter == "block":
            return True
        if overlay_sig and overlay_sig.action == "hold" and overlay_state.filter == "block":
            return True
    if overlay_state.filter == "block" and standalone and standalone.action == "buy":
        return True
    return (
        overlay_state.filter == "block"
        and standalone is not None
        and standalone.action == "buy"
        and (overlay_sig is None or overlay_sig.action == "hold")
    )


def buy_and_hold_action(*, in_market: bool, bar_index: int, warmup: int) -> str:
    if bar_index < warmup:
        return "hold"
    if not in_market:
        return "buy"
    return "hold"


def build_shadow_record(
    *,
    timestamp: int,
    price: float,
    standalone_sig: StrategySignal | None,
    overlay_sig: StrategySignal | None,
    overlay_state: BasisCrowdingState,
    bar_index: int,
    warmup: int,
    buy_hold_in_market: bool,
) -> ShadowComparisonRecord:
    standalone_action = _action_label(standalone_sig)
    effective_action = _action_label(overlay_sig)
    would_trade = standalone_would_trade(standalone_sig)
    blocks = overlay_blocks_trade(standalone_sig, overlay_state, overlay_sig)
    return ShadowComparisonRecord(
        timestamp=timestamp,
        price=price,
        raw_signal=standalone_action,
        standalone_action=standalone_action,
        overlay_decision=overlay_state.filter,
        overlay_reason=overlay_state.reason,
        funding_z=overlay_state.funding_z,
        basis_z=overlay_state.basis_z,
        standalone_would_trade=would_trade,
        overlay_blocks=blocks,
        effective_action=effective_action,
        buy_and_hold_action=buy_and_hold_action(
            in_market=buy_hold_in_market,
            bar_index=bar_index,
            warmup=warmup,
        ),
        cash_action="hold",
    )


def append_shadow_comparison(state_dir: Path | str, record: ShadowComparisonRecord | Mapping[str, Any]) -> None:
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "shadow_comparison.jsonl"
    payload = asdict(record) if isinstance(record, ShadowComparisonRecord) else dict(record)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def load_shadow_comparisons(state_dir: Path | str) -> list[dict[str, Any]]:
    path = Path(state_dir) / "shadow_comparison.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summarize_shadow(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "blocks": 0,
            "reductions": 0,
            "standalone_trades": 0,
            "block_rate_on_signals": 0.0,
        }
    blocks = sum(1 for r in rows if r.get("overlay_blocks"))
    reductions = sum(1 for r in rows if r.get("overlay_decision") == "reduce")
    standalone_trades = sum(1 for r in rows if r.get("standalone_would_trade"))
    block_rate = blocks / standalone_trades if standalone_trades else 0.0
    return {
        "count": len(rows),
        "blocks": blocks,
        "reductions": reductions,
        "standalone_trades": standalone_trades,
        "block_rate_on_signals": round(block_rate, 4),
    }
