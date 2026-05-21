"""Phase 30 — observation ops guard helpers (no secrets, no live I/O)."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

LEGACY_ASSETS = frozenset({"BTC"})
LEGACY_STRATEGIES = frozenset({"regime_router"})
LEGACY_TIMEFRAMES = frozenset({"1d"})

DEFAULT_EXPECTED_STRATEGIES: tuple[str, ...] = (
    "trend_following+funding_basis",
    "ema_crossover+funding_basis",
)


def should_skip_observation(stop_flag_path: Path | str) -> bool:
    """Return True when STOP_OBSERVATION flag is present."""
    return Path(stop_flag_path).is_file()


def check_state_legacy_warning(
    state: Mapping[str, object],
    *,
    expected_asset: str = "ETH",
    expected_timeframe: str = "4h",
    expected_strategies: Sequence[str] | None = None,
    target_label: str = "",
) -> list[str]:
    """Return human-readable warnings for stale state.json metadata."""
    warnings: list[str] = []
    prefix = f"{target_label}: " if target_label else ""

    asset = str(state.get("asset") or "").upper()
    timeframe = str(state.get("timeframe") or "")
    strategy = str(state.get("strategy") or "")

    exp_asset = expected_asset.upper()
    if asset and asset != exp_asset:
        warnings.append(f"{prefix}asset={asset!r} (expected {exp_asset})")
    elif asset in LEGACY_ASSETS:
        warnings.append(f"{prefix}asset={asset!r} (legacy)")

    if timeframe and timeframe != expected_timeframe:
        warnings.append(
            f"{prefix}timeframe={timeframe!r} (expected {expected_timeframe})"
        )
    elif timeframe in LEGACY_TIMEFRAMES:
        warnings.append(f"{prefix}timeframe={timeframe!r} (legacy)")

    valid_strategies = tuple(expected_strategies or DEFAULT_EXPECTED_STRATEGIES)
    if strategy in LEGACY_STRATEGIES:
        warnings.append(f"{prefix}strategy={strategy!r} (legacy regime_router)")
    elif strategy and valid_strategies and strategy not in valid_strategies:
        warnings.append(
            f"{prefix}strategy={strategy!r} (expected one of {list(valid_strategies)})"
        )

    return warnings


def check_all_target_state_warnings(
    state_dirs: Sequence[Path | str],
    *,
    expected_asset: str = "ETH",
    expected_timeframe: str = "4h",
) -> list[str]:
    """Load state.json from each target dir and collect legacy warnings."""
    import json

    all_warnings: list[str] = []
    for state_dir in state_dirs:
        path = Path(state_dir) / "state.json"
        label = Path(state_dir).name
        if not path.is_file():
            continue
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            all_warnings.append(f"{label}: failed to read state.json ({exc})")
            continue
        if not isinstance(state, dict):
            all_warnings.append(f"{label}: state.json is not an object")
            continue
        all_warnings.extend(
            check_state_legacy_warning(
                state,
                expected_asset=expected_asset,
                expected_timeframe=expected_timeframe,
                target_label=label,
            )
        )
    return all_warnings
