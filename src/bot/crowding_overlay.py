"""Phase 26C — crowding filter overlay on existing low-frequency strategies."""

from __future__ import annotations

import bisect
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from src.data.collectors.binance_derivatives_public import (
    default_funding_cache_path,
    default_oi_cache_path,
    load_derivatives_cache,
)
from src.strategies.base import StrategySignal
from src.zscore import ZStatus as ZStatus  # re-export: API historique du module
from src.zscore import rolling_z, rolling_z_status

CrowdingFilter = Literal["allow", "reduce", "block"]

CROWDING_FILTERS: tuple[CrowdingFilter, ...] = ("allow", "reduce", "block")

# Binance publie le funding toutes les 8h (00:00 / 08:00 / 16:00 UTC).
FUNDING_INTERVAL_SECONDS = 8 * 3600
# Borne de fraicheur du forward-fill: on tolere une publication manquee
# (retard/trou de cache) mais pas davantage. Au-dela, la derniere valeur
# connue n'informe plus sur le crowding courant et, recopiee a l'infini,
# rendait la serie constante -> pstdev nul -> z-score exactement 0.0.
DEFAULT_FUNDING_MAX_STALENESS_S = 2 * FUNDING_INTERVAL_SECONDS
# openInterestHist a un pas natif de 4h ou 1d selon le timeframe: on l'infere
# depuis la serie, ce fallback ne sert que si l'inference est impossible.
DEFAULT_OI_MAX_STALENESS_S = 2 * 86400
# Tolerance de pas manquants avant de declarer une valeur perimee.
STALENESS_STEP_TOLERANCE = 2


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


def infer_series_step_seconds(series: Sequence[Mapping[str, Any]]) -> int | None:
    """Pas natif median d'une serie horodatee (None si indeterminable)."""
    ts = sorted({int(r["timestamp"]) for r in series})
    diffs = [b - a for a, b in zip(ts, ts[1:], strict=False) if b > a]
    if not diffs:
        return None
    return int(statistics.median(diffs))


def staleness_bound_for(
    series: Sequence[Mapping[str, Any]],
    *,
    default_s: float,
    tolerance: int = STALENESS_STEP_TOLERANCE,
) -> float:
    """Borne de fraicheur deduite du pas natif de la serie."""
    step = infer_series_step_seconds(series)
    if step is None or step <= 0:
        return default_s
    return float(step * tolerance)


def _align_series(
    candles: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    value_key: str,
    *,
    max_staleness_s: float | None = None,
) -> list[float | None]:
    """Forward-fill de ``series`` sur ``candles``, borne en fraicheur.

    Sans ``max_staleness_s`` le forward-fill est illimite: passe la fin du
    cache, la derniere valeur connue etait recopiee indefiniment (defaut #12).
    """
    if not series:
        return [None] * len(candles)
    ts_list = [int(r["timestamp"]) for r in series]
    vals = [float(r[value_key]) for r in series]
    out: list[float | None] = []
    for c in candles:
        cts = int(c["timestamp"])
        idx = bisect.bisect_right(ts_list, cts) - 1
        if idx < 0:
            out.append(None)
            continue
        if max_staleness_s is not None and (cts - ts_list[idx]) > max_staleness_s:
            out.append(None)
            continue
        out.append(vals[idx])
    return out


# Alias historiques: l'implementation vit desormais dans :mod:`src.zscore`
# (source unique, cf. le troisieme exemplaire trouve dans le collecteur basis).
_rolling_z_status = rolling_z_status
_rolling_z = rolling_z


def _status_of(z: float | None, declared: ZStatus | None) -> ZStatus:
    if declared is not None:
        return declared
    return "ok" if z is not None else "no_data"


def _degraded_reason(funding_status: ZStatus, oi_status: ZStatus) -> str | None:
    """Raison explicite quand un z-score existe mais n'est pas exploitable."""
    if funding_status == "flat" or oi_status == "flat":
        return f"flat_series funding={funding_status} oi={oi_status}"
    if funding_status != "ok" or oi_status != "ok":
        return f"partial_data funding={funding_status} oi={oi_status}"
    return None


def classify_crowding(
    funding_z: float | None,
    oi_z: float | None,
    *,
    funding_status: ZStatus | None = None,
    oi_status: ZStatus | None = None,
    block_funding_z: float = 2.5,
    reduce_funding_z: float = 1.5,
    block_oi_z: float = 2.0,
) -> CrowdingState:
    """Map derivatives state → allow / reduce / block.

    ``funding_status`` / ``oi_status`` portent la distinction "absent" vs
    "nul" vs "serie plate"; en leur absence elle est deduite de la valeur.
    """
    fs = _status_of(funding_z, funding_status)
    os_ = _status_of(oi_z, oi_status)
    if funding_z is None and oi_z is None:
        return CrowdingState(
            "allow", funding_z, oi_z, f"no_derivatives_data funding={fs} oi={os_}"
        )

    # Asymetrie assumee avec ``classify_basis_crowding``, qui lui refuse toute
    # substitution: la difference tient a l'atteignabilite des branches.
    # Ici chaque regle exige |z| >= 1.2 sur au moins une serie, donc un 0.0
    # substitue ne peut jamais declencher block/reduce a lui seul ni satisfaire
    # la regle de desaccord (|fz| > 1.0 requis); la seule sortie "allow"
    # atteignable passe par ``_degraded_reason`` qui expose fs/os_. Dans
    # ``classify_basis_crowding`` au contraire, les branches "funding bas"
    # (fz <= -0.5, |fz| < 0.5) sont satisfaites *par* le 0.0 substitue et
    # affirmaient un calme funding jamais observe: la substitution y est donc
    # supprimee, pas ici.
    fz = funding_z if funding_z is not None else 0.0
    oz = oi_z if oi_z is not None else 0.0
    # ...restait mensongere dans la raison logguee: "fz=0.00" pour un funding
    # absent. On y ecrit "na".
    fz_txt = f"{funding_z:.2f}" if funding_z is not None else "na"
    oz_txt = f"{oi_z:.2f}" if oi_z is not None else "na"

    if abs(fz) >= block_funding_z or abs(oz) >= block_oi_z:
        return CrowdingState(
            "block",
            funding_z,
            oi_z,
            f"extreme_crowding fz={fz_txt} oz={oz_txt}",
        )

    if abs(fz) >= reduce_funding_z or abs(oz) >= 1.2:
        return CrowdingState(
            "reduce",
            funding_z,
            oi_z,
            f"elevated_crowding fz={fz_txt} oz={oz_txt}",
        )

    if (fz > 1.0 and oz < -0.5) or (fz < -1.0 and oz > 0.5):
        return CrowdingState(
            "block",
            funding_z,
            oi_z,
            "funding_oi_disagreement",
        )

    degraded = _degraded_reason(fs, os_)
    if degraded is not None:
        return CrowdingState("allow", funding_z, oi_z, degraded)
    return CrowdingState("allow", funding_z, oi_z, "neutral")


def precompute_crowding_states(
    candles: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    oi_rows: Sequence[Mapping[str, Any]],
    *,
    z_window: int = 60,
    funding_max_staleness_s: float | None = DEFAULT_FUNDING_MAX_STALENESS_S,
    oi_max_staleness_s: float | None = None,
) -> list[CrowdingState]:
    """Etats de crowding bougie par bougie, forward-fill borne en fraicheur.

    ``oi_max_staleness_s=None`` deduit la borne du pas natif de la serie OI
    (4h ou 1d selon le timeframe), ce que le module ne peut pas deviner.
    """
    oi_bound = (
        oi_max_staleness_s
        if oi_max_staleness_s is not None
        else staleness_bound_for(oi_rows, default_s=DEFAULT_OI_MAX_STALENESS_S)
    )
    fund = _align_series(
        candles, funding_rows, "funding_rate", max_staleness_s=funding_max_staleness_s
    )
    oi = _align_series(candles, oi_rows, "open_interest", max_staleness_s=oi_bound)
    fz = _rolling_z_status(fund, z_window)
    oz = _rolling_z_status(oi, z_window)
    return [
        classify_crowding(
            fz[i][0], oz[i][0], funding_status=fz[i][1], oi_status=oz[i][1]
        )
        for i in range(len(candles))
    ]


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
