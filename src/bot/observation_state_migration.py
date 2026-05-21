"""Phase 30.1 — normalize legacy observation state.json metadata (no history loss)."""

from __future__ import annotations

from typing import Any, Mapping

from src.bot.observation_ops_guards import (
    LEGACY_ASSETS,
    LEGACY_STRATEGIES,
    LEGACY_TIMEFRAMES,
)

CURRENT_SCHEMA_VERSION = 1

TARGET_METADATA: dict[str, dict[str, str]] = {
    "trend_following_baseline": {
        "asset": "ETH",
        "timeframe": "4h",
        "strategy": "trend_following+funding_basis",
        "overlay": "funding_basis",
    },
    "ema_crossover_baseline": {
        "asset": "ETH",
        "timeframe": "4h",
        "strategy": "ema_crossover+funding_basis",
        "overlay": "funding_basis",
    },
}


def expected_metadata(target_id: str) -> dict[str, str] | None:
    return TARGET_METADATA.get(target_id)


def is_legacy_observation_state(
    state: Mapping[str, Any],
    target_id: str,
) -> bool:
    """Return True when state.json metadata does not match Phase 28 ETH 4h targets."""
    meta = expected_metadata(target_id)
    if meta is None:
        return False

    asset = str(state.get("asset") or "").upper()
    timeframe = str(state.get("timeframe") or "")
    strategy = str(state.get("strategy") or "")

    if asset in LEGACY_ASSETS or (asset and asset != meta["asset"]):
        return True
    if timeframe in LEGACY_TIMEFRAMES or (timeframe and timeframe != meta["timeframe"]):
        return True
    if strategy in LEGACY_STRATEGIES or (strategy and strategy != meta["strategy"]):
        return True
    if str(state.get("overlay") or "") != meta["overlay"]:
        return True
    if int(state.get("state_schema_version") or 0) < CURRENT_SCHEMA_VERSION:
        return True
    return False


def migrate_observation_state(state: dict[str, Any], target_id: str) -> dict[str, Any]:
    """Normalize metadata fields; preserve trades/decisions/equity history on disk."""
    meta = expected_metadata(target_id)
    if meta is None:
        return dict(state)

    result = dict(state)
    changed = False

    if str(result.get("asset") or "").upper() != meta["asset"]:
        result["asset"] = meta["asset"]
        changed = True
    if str(result.get("timeframe") or "") != meta["timeframe"]:
        result["timeframe"] = meta["timeframe"]
        changed = True
    if str(result.get("strategy") or "") != meta["strategy"]:
        result["strategy"] = meta["strategy"]
        changed = True
    if str(result.get("overlay") or "") != meta["overlay"]:
        result["overlay"] = meta["overlay"]
        changed = True

    if int(result.get("state_schema_version") or 0) != CURRENT_SCHEMA_VERSION:
        result["state_schema_version"] = CURRENT_SCHEMA_VERSION
        if changed:
            result["migrated_from_legacy"] = True
        elif "migrated_from_legacy" not in result:
            result["migrated_from_legacy"] = False

    return result
