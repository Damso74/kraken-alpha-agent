"""Phase 27 — funding + basis crowding overlay on Phase 23 strategies."""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from src.bot.crowding_overlay import (
    DEFAULT_FUNDING_MAX_STALENESS_S,
    ZStatus,
    _align_series,
    _rolling_z_status,
    _status_of,
    compare_baseline_vs_overlay,
    staleness_bound_for,
)
from src.data.collectors.binance_basis_public import (
    _coerce_z_status,
    default_basis_cache_path,
    load_basis_cache,
)
from src.data.collectors.binance_derivatives_public import (
    default_funding_cache_path,
    load_derivatives_cache,
)
from src.strategies.base import StrategySignal

BasisCrowdingFilter = Literal["allow", "reduce", "block"]

OverlayMode = Literal["funding_only", "funding_basis"]

# Le collecteur Phase 27 produit une ligne de basis par bougie (4h ou 1d):
# ce fallback ne sert que si le pas natif ne peut pas etre infere.
DEFAULT_BASIS_MAX_STALENESS_S = 2 * 86400


@dataclass(frozen=True)
class BasisCrowdingState:
    filter: BasisCrowdingFilter
    funding_z: float | None
    basis_z: float | None
    basis_compression: bool
    basis_extreme: bool
    reason: str


def _basis_degraded_reason(funding_status: ZStatus, basis_status: ZStatus) -> str | None:
    """Raison explicite quand un z existe mais n'est pas exploitable."""
    if funding_status == "flat" or basis_status == "flat":
        return f"flat_series funding={funding_status} basis={basis_status}"
    if funding_status != "ok" or basis_status != "ok":
        return f"partial_data funding={funding_status} basis={basis_status}"
    return None


def classify_basis_crowding(
    funding_z: float | None,
    basis_z: float | None,
    *,
    basis_compression: bool = False,
    basis_extreme: bool = False,
    funding_status: ZStatus | None = None,
    basis_status: ZStatus | None = None,
    block_funding_z: float = +2.0,
    block_basis_z: float = 2.0,
) -> BasisCrowdingState:
    """Funding + basis combo rules (Phase 27).

    Toutes les regles ci-dessous comparent ``fz`` a des seuils. Substituer
    0.0 a un funding absent (defaut #12) rendait ces branches inatteignables
    et faisait loguer "neutral" alors que la verite etait "no_data": le
    funding manquant sort donc explicitement en amont.
    """
    fs = _status_of(funding_z, funding_status)
    bs = _status_of(basis_z, basis_status)

    if funding_z is None and basis_z is None:
        return BasisCrowdingState(
            "allow", funding_z, basis_z, basis_compression, basis_extreme, "no_data"
        )

    if funding_z is None:
        # Le basis seul reste exploitable pour reduire, mais on ne pretend pas
        # connaitre l'etat de crowding funding.
        bz_only = basis_z if basis_z is not None else 0.0
        filt: BasisCrowdingFilter = (
            "reduce" if (basis_extreme or abs(bz_only) >= 1.5) else "allow"
        )
        bz_txt = f"{basis_z:.2f}" if basis_z is not None else "na"
        return BasisCrowdingState(
            filt,
            None,
            basis_z,
            basis_compression,
            basis_extreme,
            f"no_data_funding basis_only bz={bz_txt} funding={fs} basis={bs}",
        )

    fz = funding_z
    bz = basis_z if basis_z is not None else 0.0

    # funding high + basis high → block / reduce
    if fz >= block_funding_z and bz >= block_basis_z:
        return BasisCrowdingState(
            "block",
            funding_z,
            basis_z,
            basis_compression,
            basis_extreme,
            f"funding_basis_elevated fz={fz:.2f} bz={bz:.2f}",
        )

    # funding low + basis low → allow
    if abs(fz) < 0.5 and abs(bz) < 0.5:
        return BasisCrowdingState(
            "allow",
            funding_z,
            basis_z,
            basis_compression,
            basis_extreme,
            _basis_degraded_reason(fs, bs) or "funding_basis_neutral",
        )

    # funding high + basis contracting → reduce
    if fz >= 1.0 and basis_compression:
        return BasisCrowdingState(
            "reduce",
            funding_z,
            basis_z,
            basis_compression,
            basis_extreme,
            f"funding_high_basis_contracting fz={fz:.2f}",
        )

    # funding low + stable basis (documented: low carry + tight basis)
    if fz <= -0.5 and abs(bz) < 1.0 and not basis_extreme:
        return BasisCrowdingState(
            "allow",
            funding_z,
            basis_z,
            basis_compression,
            basis_extreme,
            "funding_low_basis_stable",
        )

    if basis_extreme and fz >= 0.5:
        return BasisCrowdingState(
            "reduce",
            funding_z,
            basis_z,
            basis_compression,
            basis_extreme,
            f"basis_extreme fz={fz:.2f} bz={bz:.2f}",
        )

    if abs(fz) >= 2.5:
        return BasisCrowdingState(
            "block",
            funding_z,
            basis_z,
            basis_compression,
            basis_extreme,
            f"extreme_funding fz={fz:.2f}",
        )

    if abs(fz) >= 1.5 or abs(bz) >= 1.5:
        return BasisCrowdingState(
            "reduce",
            funding_z,
            basis_z,
            basis_compression,
            basis_extreme,
            f"moderate_crowding fz={fz:.2f} bz={bz:.2f}",
        )

    return BasisCrowdingState(
        "allow",
        funding_z,
        basis_z,
        basis_compression,
        basis_extreme,
        _basis_degraded_reason(fs, bs) or "neutral",
    )


def classify_funding_only(
    funding_z: float | None,
    *,
    funding_status: ZStatus | None = None,
    block_z: float = 2.5,
    reduce_z: float = 1.5,
) -> BasisCrowdingState:
    """Funding-only overlay (no basis, no OI)."""
    fs = _status_of(funding_z, funding_status)
    if funding_z is None:
        return BasisCrowdingState(
            "allow", None, None, False, False, f"no_data_funding funding={fs}"
        )
    fz = funding_z
    if abs(fz) >= block_z:
        return BasisCrowdingState(
            "block", funding_z, None, False, False, f"funding_extreme fz={fz:.2f}"
        )
    if abs(fz) >= reduce_z:
        return BasisCrowdingState(
            "reduce", funding_z, None, False, False, f"funding_elevated fz={fz:.2f}"
        )
    if fs == "flat":
        # z=0.0 sur une serie plate: ce n'est pas un funding "neutre observe".
        return BasisCrowdingState(
            "allow", funding_z, None, False, False, "flat_series funding=flat"
        )
    return BasisCrowdingState("allow", funding_z, None, False, False, "funding_neutral")


def _align_optional_float_series(
    candles: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    value_key: str,
    *,
    max_staleness_s: float | None = None,
) -> list[float | None]:
    if not series:
        return [None] * len(candles)
    ts_list = [int(r["timestamp"]) for r in series]
    vals: list[float | None] = []
    for r in series:
        raw = r.get(value_key)
        if raw is None:
            vals.append(None)
        else:
            try:
                vals.append(float(raw))
            except (TypeError, ValueError):
                vals.append(None)
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


def _align_z_status_series(
    candles: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    value_key: str,
    *,
    max_staleness_s: float | None = None,
) -> list[ZStatus]:
    """Forward-fill du statut de z-score, ``no_data`` hors de portee/fraicheur."""
    if not series:
        return ["no_data"] * len(candles)
    ts_list = [int(r["timestamp"]) for r in series]
    vals: list[ZStatus] = []
    for r in series:
        z_raw = r.get("basis_zscore")
        try:
            z = float(z_raw) if z_raw is not None else None
        except (TypeError, ValueError):
            z = None
        # Les lignes sans ``basis_z_status`` (caches d'avant Phase 30, dicts
        # construits a la main) retombent sur ok/no_data selon la valeur.
        vals.append(_coerce_z_status(r.get(value_key), z))
    out: list[ZStatus] = []
    for c in candles:
        cts = int(c["timestamp"])
        idx = bisect.bisect_right(ts_list, cts) - 1
        if idx < 0:
            out.append("no_data")
            continue
        if max_staleness_s is not None and (cts - ts_list[idx]) > max_staleness_s:
            out.append("no_data")
            continue
        out.append(vals[idx])
    return out


def _align_bool_series(
    candles: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    value_key: str,
    *,
    max_staleness_s: float | None = None,
) -> list[bool | None]:
    if not series:
        return [None] * len(candles)
    ts_list = [int(r["timestamp"]) for r in series]
    vals = [bool(r[value_key]) for r in series]
    out: list[bool | None] = []
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


def precompute_basis_crowding_states(
    candles: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    basis_rows: Sequence[Mapping[str, Any]],
    *,
    mode: OverlayMode = "funding_basis",
    z_window: int = 60,
    funding_max_staleness_s: float | None = DEFAULT_FUNDING_MAX_STALENESS_S,
    basis_max_staleness_s: float | None = None,
) -> list[BasisCrowdingState]:
    """Etats bougie par bougie, forward-fill borne en fraicheur (defaut #12).

    ``basis_max_staleness_s=None`` deduit la borne du pas natif de la serie
    de basis (une ligne par bougie chez le collecteur Phase 27).
    """
    basis_bound = (
        basis_max_staleness_s
        if basis_max_staleness_s is not None
        else staleness_bound_for(basis_rows, default_s=DEFAULT_BASIS_MAX_STALENESS_S)
    )
    fund = _align_series(
        candles, funding_rows, "funding_rate", max_staleness_s=funding_max_staleness_s
    )
    fz = _rolling_z_status(fund, z_window)

    if mode == "funding_only":
        return [
            classify_funding_only(fz[i][0], funding_status=fz[i][1])
            for i in range(len(candles))
        ]

    basis_z_aligned: list[float | None] = []
    basis_status: list[ZStatus] = []
    compression: list[bool] = []
    extreme: list[bool] = []
    if basis_rows:
        bz_series = _align_optional_float_series(
            candles, basis_rows, "basis_zscore", max_staleness_s=basis_bound
        )
        bs_series = _align_z_status_series(
            candles, basis_rows, "basis_z_status", max_staleness_s=basis_bound
        )
        comp_series = _align_bool_series(
            candles, basis_rows, "basis_compression", max_staleness_s=basis_bound
        )
        ext_series = _align_bool_series(
            candles, basis_rows, "basis_extreme", max_staleness_s=basis_bound
        )
        for i in range(len(candles)):
            basis_z_aligned.append(bz_series[i])
            basis_status.append(bs_series[i] if bz_series[i] is not None else "no_data")
            compression.append(bool(comp_series[i]) if comp_series[i] is not None else False)
            extreme.append(bool(ext_series[i]) if ext_series[i] is not None else False)
    else:
        basis_z_aligned = [None] * len(candles)
        basis_status = ["no_data"] * len(candles)
        compression = [False] * len(candles)
        extreme = [False] * len(candles)

    return [
        classify_basis_crowding(
            fz[i][0],
            basis_z_aligned[i],
            basis_compression=compression[i],
            basis_extreme=extreme[i],
            funding_status=fz[i][1],
            basis_status=basis_status[i],
        )
        for i in range(len(candles))
    ]


class BasisCrowdingOverlayStrategy:
    """Wrap Phase 23 strategy with funding-only or funding+basis overlay."""

    name = "basis_crowding_overlay"

    def __init__(
        self,
        inner: object,
        timeframe: str,
        *,
        mode: OverlayMode = "funding_basis",
        precomputed_states: Sequence[BasisCrowdingState] | None = None,
        reduce_scale: float = 0.5,
    ) -> None:
        self._inner = inner
        self.timeframe = timeframe
        self.mode = mode
        self.reduce_scale = reduce_scale
        inner_name = getattr(inner, "name", "strategy")
        suffix = "funding_basis" if mode == "funding_basis" else "funding_only"
        self.name = f"{inner_name}+{suffix}_overlay"
        self._states: list[BasisCrowdingState] | None = (
            list(precomputed_states) if precomputed_states is not None else None
        )

    def bind_derivatives(
        self,
        candles: Sequence[Any],
        funding_rows: Sequence[Mapping[str, Any]],
        basis_rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self._states = precompute_basis_crowding_states(
            candles,
            funding_rows,
            basis_rows or [],
            mode=self.mode,
        )

    def warmup_bars(self) -> int:
        return max(int(self._inner.warmup_bars()), 65)

    def _state_at(self, index: int) -> BasisCrowdingState:
        if self._states is None or index >= len(self._states):
            return BasisCrowdingState("allow", None, None, False, False, "unbound")
        return self._states[index]

    def on_bar(self, index, candles, portfolio, symbol) -> StrategySignal | None:
        state = self._state_at(index)
        if state.filter == "block":
            pos = portfolio.position(symbol)
            if pos.quantity > 1e-12:
                return StrategySignal(
                    "sell", 1.0, f"basis_crowding_block_exit:{state.reason}"
                )
            return StrategySignal("hold", 0.0, f"basis_crowding_block:{state.reason}")

        sig = self._inner.on_bar(index, candles, portfolio, symbol)
        if sig is None or sig.action in ("hold", "sell"):
            return sig
        if state.filter == "reduce":
            scaled = float(sig.size_fraction) * self.reduce_scale
            return StrategySignal(
                sig.action,
                scaled,
                f"basis_crowding_reduce:{state.reason}:{sig.reason}",
            )
        return sig


def load_basis_overlay_inputs(
    asset: str,
    timeframe: str,
    cache_root: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    from pathlib import Path

    root = Path(cache_root)
    sym = asset.strip().upper().partition("/")[0]
    f_rows, f_meta = load_derivatives_cache(default_funding_cache_path(sym, root))
    b_rows, b_meta = load_basis_cache(default_basis_cache_path(sym, timeframe, root))
    if len(f_rows) < 50:
        return [], [], "blocked_data"
    if len(b_rows) < 50:
        return f_rows, [], "funding_only"
    return f_rows, b_rows, "available"


EthAutopsyVerdict = Literal["useful_overlay", "decorative", "kill_overlay"]


def classify_eth_overlay_autopsy_verdict(
    baseline: Mapping[str, Any],
    overlay: Mapping[str, Any],
    *,
    missed_upside_pct: float = 0.0,
) -> EthAutopsyVerdict:
    """Phase 27D verdict for ETH 4h crowding/basis overlay autopsy."""
    if not baseline.get("data_ok") or not overlay.get("data_ok"):
        return "decorative"
    dd_base = float(baseline.get("max_drawdown_pct", 0))
    dd_ov = float(overlay.get("max_drawdown_pct", 0))
    ret_base = float(baseline.get("total_return_pct", 0))
    ret_ov = float(overlay.get("total_return_pct", 0))
    dd_red = dd_base - dd_ov
    ret_delta = ret_ov - ret_base

    if ret_delta < -5.0 and dd_red < 1.0:
        return "kill_overlay"
    if dd_red >= 2.0 and ret_delta >= -2.0 and missed_upside_pct < 8.0:
        return "useful_overlay"
    if dd_red >= 1.0 and ret_delta >= -3.0:
        return "useful_overlay"
    return "decorative"


def compare_overlay_modes(
    baseline: Mapping[str, Any],
    funding_only: Mapping[str, Any],
    funding_basis: Mapping[str, Any],
) -> dict[str, Any]:
    """Tournament delta: baseline vs funding-only vs funding+basis."""
    fo = compare_baseline_vs_overlay(baseline, funding_only)
    fb = compare_baseline_vs_overlay(baseline, funding_basis)
    fo_vs_fb = compare_baseline_vs_overlay(funding_only, funding_basis)
    best = "baseline"
    if fb.get("improved_alpha") or (
        fb.get("improved_risk_only") and not fo.get("improved_risk_only")
    ):
        best = "funding_basis"
    elif fo.get("improved_alpha") or fo.get("improved_risk_only"):
        best = "funding_only"
    return {
        "funding_only_vs_baseline": fo,
        "funding_basis_vs_baseline": fb,
        "funding_basis_vs_funding_only": fo_vs_fb,
        "best_mode": best,
    }


def classify_phase27_tournament_verdict(
    baseline: Mapping[str, Any],
    funding_only: Mapping[str, Any],
    funding_basis: Mapping[str, Any],
) -> str:
    """Phase 27 tournament verdict (no validation_candidate without OI depth)."""
    cmp = compare_overlay_modes(baseline, funding_only, funding_basis)
    best = cmp["best_mode"]
    if best == "baseline":
        fo_ret = float(funding_only.get("total_return_pct", 0))
        base_ret = float(baseline.get("total_return_pct", 0))
        if fo_ret < base_ret - 3.0:
            return "kill"
        return "weak"
    target = funding_basis if best == "funding_basis" else funding_only
    sub = cmp["funding_basis_vs_baseline"] if best == "funding_basis" else cmp["funding_only_vs_baseline"]
    if sub.get("improved_alpha"):
        return "overlay_only"
    if sub.get("improved_risk_only"):
        return "overlay_only"
    if float(target.get("total_return_pct", 0)) < float(baseline.get("total_return_pct", 0)) - 3.0:
        return "kill"
    return "weak"
