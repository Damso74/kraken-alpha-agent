"""Phase 26C — crowding filter overlay on existing low-frequency strategies."""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from src.data.collectors.binance_derivatives_public import (
    default_funding_cache_path,
    default_oi_cache_path,
    load_derivatives_cache,
)
from src.strategies.base import StrategySignal

CrowdingFilter = Literal["allow", "reduce", "block"]

CROWDING_FILTERS: tuple[CrowdingFilter, ...] = ("allow", "reduce", "block")


@dataclass(frozen=True)
class CrowdingState:
    filter: CrowdingFilter
    funding_z: float | None
    oi_z: float | None
    reason: str


def _interval_minutes(timeframe: str) -> int:
    tf = timeframe.strip().lower()
    if tf == "4h":
        return 240
    if tf == "1d":
        return 1440
    raise ValueError(f"unsupported timeframe: {timeframe}")


def _align_series(
    candles: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    value_key: str,
) -> list[float | None]:
    if not series:
        return [None] * len(candles)
    ts_list = [int(r["timestamp"]) for r in series]
    vals = [float(r[value_key]) for r in series]
    out: list[float | None] = []
    for c in candles:
        cts = int(c["timestamp"])
        idx = bisect.bisect_right(ts_list, cts) - 1
        out.append(vals[idx] if idx >= 0 else None)
    return out


def _rolling_z(values: Sequence[float | None], window: int) -> list[float | None]:
    import statistics

    out: list[float | None] = []
    buf: list[float] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        buf.append(v)
        if len(buf) > window:
            buf.pop(0)
        if len(buf) < max(10, window // 2):
            out.append(None)
            continue
        mu = statistics.mean(buf)
        sd = statistics.pstdev(buf) or 1e-12
        out.append((v - mu) / sd)
    return out


def classify_crowding(
    funding_z: float | None,
    oi_z: float | None,
    *,
    block_funding_z: float = 2.5,
    reduce_funding_z: float = 1.5,
    block_oi_z: float = 2.0,
) -> CrowdingState:
    """Map derivatives state → allow / reduce / block."""
    if funding_z is None and oi_z is None:
        return CrowdingState("allow", funding_z, oi_z, "no_derivatives_data")

    fz = funding_z or 0.0
    oz = oi_z or 0.0

    if abs(fz) >= block_funding_z or abs(oz) >= block_oi_z:
        return CrowdingState(
            "block",
            funding_z,
            oi_z,
            f"extreme_crowding fz={fz:.2f} oz={oz:.2f}",
        )

    if abs(fz) >= reduce_funding_z or abs(oz) >= 1.2:
        return CrowdingState(
            "reduce",
            funding_z,
            oi_z,
            f"elevated_crowding fz={fz:.2f} oz={oz:.2f}",
        )

    if (fz > 1.0 and oz < -0.5) or (fz < -1.0 and oz > 0.5):
        return CrowdingState(
            "block",
            funding_z,
            oi_z,
            "funding_oi_disagreement",
        )

    return CrowdingState("allow", funding_z, oi_z, "neutral")


def precompute_crowding_states(
    candles: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    oi_rows: Sequence[Mapping[str, Any]],
    *,
    z_window: int = 60,
) -> list[CrowdingState]:
    fund = _align_series(candles, funding_rows, "funding_rate")
    oi = _align_series(candles, oi_rows, "open_interest")
    fz = _rolling_z(fund, z_window)
    oz = _rolling_z(oi, z_window)
    return [classify_crowding(fz[i], oz[i]) for i in range(len(candles))]


class CrowdingOverlayStrategy:
    """Wrap Phase 23 strategy — block or scale entries under crowding."""

    name = "crowding_overlay"

    def __init__(
        self,
        inner: object,
        timeframe: str,
        *,
        precomputed_states: Sequence[CrowdingState] | None = None,
        reduce_scale: float = 0.5,
    ) -> None:
        self._inner = inner
        self.timeframe = timeframe
        self.reduce_scale = reduce_scale
        inner_name = getattr(inner, "name", "strategy")
        self.name = f"{inner_name}+crowding_overlay"
        self._states: list[CrowdingState] | None = (
            list(precomputed_states) if precomputed_states is not None else None
        )

    def bind_derivatives(
        self,
        candles: Sequence[Any],
        funding_rows: Sequence[Mapping[str, Any]],
        oi_rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self._states = precompute_crowding_states(candles, funding_rows, oi_rows)

    def warmup_bars(self) -> int:
        return max(int(self._inner.warmup_bars()), 65)

    def _state_at(self, index: int) -> CrowdingState:
        if self._states is None or index >= len(self._states):
            return CrowdingState("allow", None, None, "unbound")
        return self._states[index]

    def on_bar(self, index, candles, portfolio, symbol) -> StrategySignal | None:
        state = self._state_at(index)
        if state.filter == "block":
            pos = portfolio.position(symbol)
            if pos.quantity > 1e-12:
                return StrategySignal("sell", 1.0, f"crowding_block_exit:{state.reason}")
            return StrategySignal("hold", 0.0, f"crowding_block:{state.reason}")

        sig = self._inner.on_bar(index, candles, portfolio, symbol)
        if sig is None or sig.action in ("hold", "sell"):
            return sig
        if state.filter == "reduce":
            scaled = float(sig.size_fraction) * self.reduce_scale
            return StrategySignal(
                sig.action,
                scaled,
                f"crowding_reduce:{state.reason}:{sig.reason}",
            )
        return sig


def load_derivatives_for_asset(
    asset: str,
    timeframe: str,
    cache_root: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    from pathlib import Path

    root = Path(cache_root)
    sym = asset.strip().upper().partition("/")[0]
    period = "4h" if timeframe == "4h" else "1d"
    f_rows, f_meta = load_derivatives_cache(default_funding_cache_path(sym, root))
    o_rows, o_meta = load_derivatives_cache(default_oi_cache_path(sym, period, root))
    if len(f_rows) < 50 or len(o_rows) < 50:
        return [], [], "blocked_data"
    return f_rows, o_rows, "available"


def compare_baseline_vs_overlay(
    baseline: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, Any]:
    """Risk-adjusted delta for tournament matrix."""
    dd_base = float(baseline.get("max_drawdown_pct", 0))
    dd_ov = float(overlay.get("max_drawdown_pct", 0))
    ret_base = float(baseline.get("total_return_pct", 0))
    ret_ov = float(overlay.get("total_return_pct", 0))
    dd_red = dd_base - dd_ov
    ret_delta = ret_ov - ret_base
    improved_risk = dd_red > 0.5 and ret_delta >= -2.0
    improved_alpha = ret_delta > 0.5 and dd_ov <= dd_base + 1.0
    return {
        "dd_reduction_pp": round(dd_red, 4),
        "return_delta_pct": round(ret_delta, 4),
        "improved_risk_only": improved_risk and not improved_alpha,
        "improved_alpha": improved_alpha,
    }
