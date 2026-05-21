"""Phase 26B — derivatives crowding event studies (cache-only, no network)."""

from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

from src.data.collectors.binance_derivatives_public import (
    LIQUIDATIONS_BLOCKED_REASON,
    LIQUIDATIONS_STATUS,
    default_funding_cache_path,
    default_oi_cache_path,
    load_derivatives_cache,
)

SeriesStatus = Literal["available", "blocked_data"]

FORWARD_HORIZONS_HOURS: tuple[int, ...] = (4, 24, 72)


@dataclass(frozen=True)
class EventStudySpec:
    signal_id: str
    description: str
    requires_liquidations: bool = False


PHASE26_EVENT_SPECS: tuple[EventStudySpec, ...] = (
    EventStudySpec("funding_extreme", "Funding percentile extreme (crowding)"),
    EventStudySpec("funding_zscore", "Funding rolling z-score regime"),
    EventStudySpec("oi_expansion_flat_price", "OI up + price range flat (leverage build)"),
    EventStudySpec("oi_zscore_range_compress", "OI z-score high + compressed range"),
    EventStudySpec(
        "liquidation_spike",
        "Liquidation spike aftershock",
        requires_liquidations=True,
    ),
    EventStudySpec("funding_oi_disagreement", "Funding vs OI directional disagreement"),
)


@dataclass
class ForwardReturnStats:
    horizon_hours: int
    horizon_bars: int
    event_count: int
    mean_return_pct: float
    median_return_pct: float
    sign_rate: float
    baseline_mean_return_pct: float
    excess_mean_pct: float


@dataclass
class SignalEventStudyResult:
    signal_id: str
    status: SeriesStatus
    event_count: int
    blocked_reason: str | None = None
    forward_stats: list[ForwardReturnStats] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _interval_minutes(timeframe: str) -> int:
    tf = timeframe.strip().lower()
    if tf == "4h":
        return 240
    if tf == "1d":
        return 1440
    raise ValueError(f"unsupported timeframe: {timeframe}")


def _horizon_bars(hours: int, interval_minutes: int) -> int:
    bar_hours = interval_minutes / 60.0
    return max(1, int(round(hours / bar_hours)))


def _align_series_to_candles(
    candles: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    value_key: str,
) -> list[float | None]:
    """For each candle index, last known series value at or before candle ts."""
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


def _rolling_zscore(values: Sequence[float | None], window: int) -> list[float | None]:
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


def _percentile_rank(buf: list[float], value: float) -> float:
    if not buf:
        return 0.5
    below = sum(1 for x in buf if x <= value)
    return below / len(buf)


def _forward_return_pct(
    candles: Sequence[Mapping[str, Any]],
    index: int,
    horizon_bars: int,
) -> float | None:
    if index + horizon_bars >= len(candles):
        return None
    c0 = float(candles[index]["close"])
    c1 = float(candles[index + horizon_bars]["close"])
    if c0 <= 0:
        return None
    return (c1 / c0 - 1.0) * 100.0


def _max_dd_proxy_pct(candles: Sequence[Mapping[str, Any]], index: int, horizon_bars: int) -> float | None:
    if index + horizon_bars >= len(candles):
        return None
    peak = float(candles[index]["close"])
    max_dd = 0.0
    for j in range(index, index + horizon_bars + 1):
        c = float(candles[j]["close"])
        if c > peak:
            peak = c
        dd = (peak - c) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd * 100.0


def _realized_vol_proxy(
    candles: Sequence[Mapping[str, Any]],
    index: int,
    horizon_bars: int,
) -> float | None:
    rets: list[float] = []
    for j in range(index + 1, index + horizon_bars + 1):
        p0 = float(candles[j - 1]["close"])
        p1 = float(candles[j]["close"])
        if p0 > 0:
            rets.append(math.log(p1 / p0))
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets) * 100.0


def _detect_events(
    signal_id: str,
    candles: Sequence[Mapping[str, Any]],
    funding_aligned: list[float | None],
    oi_aligned: list[float | None],
    *,
    z_window: int = 60,
) -> tuple[list[int], list[str]]:
    notes: list[str] = []
    n = len(candles)
    events: list[int] = []
    fund_z = _rolling_zscore(funding_aligned, z_window)
    oi_z = _rolling_zscore(oi_aligned, z_window)

    if signal_id == "funding_extreme":
        buf: list[float] = []
        for i in range(n):
            v = funding_aligned[i]
            if v is None:
                continue
            buf.append(v)
            if len(buf) > z_window:
                buf.pop(0)
            if len(buf) < 30:
                continue
            pct = _percentile_rank(buf, v)
            if pct >= 0.90 or pct <= 0.10:
                events.append(i)
        notes.append("events=funding percentile <=10% or >=90%")
        return events, notes

    if signal_id == "funding_zscore":
        for i, z in enumerate(fund_z):
            if z is not None and abs(z) >= 2.0:
                events.append(i)
        notes.append("events=|funding z|>=2")
        return events, notes

    if signal_id == "oi_expansion_flat_price":
        for i in range(20, n - 1):
            oz = oi_z[i]
            if oz is None or oz < 1.0:
                continue
            window = candles[i - 5 : i + 1]
            closes = [float(c["close"]) for c in window]
            rng = (max(closes) - min(closes)) / (statistics.mean(closes) or 1.0)
            if rng < 0.01:
                events.append(i)
        notes.append("events=OI z>=1 and 5-bar range <1%")
        return events, notes

    if signal_id == "oi_zscore_range_compress":
        for i in range(20, n):
            oz = oi_z[i]
            if oz is None or oz < 1.5:
                continue
            hi = max(float(candles[i]["high"]) for c in candles[i - 10 : i + 1])
            lo = min(float(candles[i]["low"]) for c in candles[i - 10 : i + 1])
            mid = float(candles[i]["close"])
            if mid > 0 and (hi - lo) / mid < 0.02:
                events.append(i)
        notes.append("events=OI z>=1.5 and 10-bar range <2%")
        return events, notes

    if signal_id == "funding_oi_disagreement":
        for i in range(n):
            fz = fund_z[i]
            oz = oi_z[i]
            if fz is None or oz is None:
                continue
            if (fz > 1.0 and oz < -0.5) or (fz < -1.0 and oz > 0.5):
                events.append(i)
        notes.append("events=funding z and OI z opposite signs (strong)")
        return events, notes

    return events, notes


def run_signal_event_study(
    signal_id: str,
    candles: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    oi_rows: Sequence[Mapping[str, Any]],
    *,
    timeframe: str = "4h",
) -> SignalEventStudyResult:
    spec = next((s for s in PHASE26_EVENT_SPECS if s.signal_id == signal_id), None)
    if spec is None:
        return SignalEventStudyResult(signal_id, "blocked_data", 0, blocked_reason="unknown signal")

    if spec.requires_liquidations:
        return SignalEventStudyResult(
            signal_id,
            "blocked_data",
            0,
            blocked_reason=LIQUIDATIONS_BLOCKED_REASON,
            notes=[LIQUIDATIONS_STATUS],
        )

    if len(candles) < 120:
        return SignalEventStudyResult(
            signal_id,
            "blocked_data",
            0,
            blocked_reason="insufficient candles",
        )

    if not funding_rows and signal_id in (
        "funding_extreme",
        "funding_zscore",
        "funding_oi_disagreement",
    ):
        return SignalEventStudyResult(
            signal_id,
            "blocked_data",
            0,
            blocked_reason="funding cache missing",
        )

    if not oi_rows and signal_id.startswith("oi_"):
        return SignalEventStudyResult(
            signal_id,
            "blocked_data",
            0,
            blocked_reason="open interest cache missing",
        )

    interval = _interval_minutes(timeframe)
    fund_al = _align_series_to_candles(candles, funding_rows, "funding_rate")
    oi_al = _align_series_to_candles(candles, oi_rows, "open_interest")

    events, notes = _detect_events(signal_id, candles, fund_al, oi_al)
    if len(events) < 5:
        return SignalEventStudyResult(
            signal_id,
            "available",
            len(events),
            blocked_reason=None,
            notes=notes + ["too_few_events_for_stats"],
        )

    all_indices = list(range(50, len(candles) - max(_horizon_bars(h, interval) for h in FORWARD_HORIZONS_HOURS)))
    forward_stats: list[ForwardReturnStats] = []

    for hours in FORWARD_HORIZONS_HOURS:
        hb = _horizon_bars(hours, interval)
        ev_rets = [_forward_return_pct(candles, i, hb) for i in events]
        ev_rets = [r for r in ev_rets if r is not None]
        base_rets = [_forward_return_pct(candles, i, hb) for i in all_indices]
        base_rets = [r for r in base_rets if r is not None]
        if not ev_rets:
            continue
        ev_mean = statistics.mean(ev_rets)
        base_mean = statistics.mean(base_rets) if base_rets else 0.0
        forward_stats.append(
            ForwardReturnStats(
                horizon_hours=hours,
                horizon_bars=hb,
                event_count=len(ev_rets),
                mean_return_pct=round(ev_mean, 4),
                median_return_pct=round(statistics.median(ev_rets), 4),
                sign_rate=round(sum(1 for r in ev_rets if r > 0) / len(ev_rets), 4),
                baseline_mean_return_pct=round(base_mean, 4),
                excess_mean_pct=round(ev_mean - base_mean, 4),
            )
        )

    return SignalEventStudyResult(
        signal_id,
        "available",
        len(events),
        forward_stats=forward_stats,
        notes=notes,
    )


def run_all_derivatives_event_studies(
    asset: str,
    candles: Sequence[Mapping[str, Any]],
    *,
    timeframe: str = "4h",
    cache_root: Any = None,
) -> dict[str, Any]:
    from pathlib import Path

    root = Path(cache_root) if cache_root is not None else default_funding_cache_path("BTC").parent
    sym = asset.strip().upper().partition("/")[0]
    period = "4h" if timeframe == "4h" else "1d"

    f_rows, _ = load_derivatives_cache(default_funding_cache_path(sym, root))
    o_rows, _ = load_derivatives_cache(default_oi_cache_path(sym, period, root))

    results: list[dict[str, Any]] = []
    for spec in PHASE26_EVENT_SPECS:
        r = run_signal_event_study(
            spec.signal_id,
            candles,
            f_rows,
            o_rows,
            timeframe=timeframe,
        )
        results.append(
            {
                "signal_id": r.signal_id,
                "status": r.status,
                "event_count": r.event_count,
                "blocked_reason": r.blocked_reason,
                "forward_stats": [
                    {
                        "horizon_hours": fs.horizon_hours,
                        "horizon_bars": fs.horizon_bars,
                        "event_count": fs.event_count,
                        "mean_return_pct": fs.mean_return_pct,
                        "median_return_pct": fs.median_return_pct,
                        "sign_rate": fs.sign_rate,
                        "baseline_mean_return_pct": fs.baseline_mean_return_pct,
                        "excess_mean_pct": fs.excess_mean_pct,
                    }
                    for fs in r.forward_stats
                ],
                "notes": r.notes,
            }
        )

    non_trivial = [
        r
        for r in results
        if r["status"] == "available"
        and r.get("forward_stats")
        and any(abs(fs["excess_mean_pct"]) >= 0.15 for fs in r["forward_stats"])
    ]

    return {
        "asset": sym,
        "timeframe": timeframe,
        "funding_rows": len(f_rows),
        "oi_rows": len(o_rows),
        "liquidations_status": LIQUIDATIONS_STATUS,
        "results": results,
        "non_trivial_signals": len(non_trivial),
        "proceed_to_overlay": len(non_trivial) > 0,
    }


def classify_event_study_verdict(summary: Mapping[str, Any]) -> str:
    """Honest verdict for a single asset/timeframe bundle."""
    if int(summary.get("funding_rows", 0)) < 100 or int(summary.get("oi_rows", 0)) < 100:
        return "blocked_data"
    if int(summary.get("non_trivial_signals", 0)) == 0:
        return "weak"
    if int(summary.get("non_trivial_signals", 0)) >= 2:
        return "overlay_only"
    return "weak"
