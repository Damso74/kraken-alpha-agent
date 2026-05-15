"""Configuration loader.

Combines:
- environment variables (loaded via ``python-dotenv`` so ``.env`` works automatically)
- the YAML file pointed to by ``CONFIG_PATH`` (defaults to ``config.yaml``, falls
  back to ``config.example.yaml`` so the agent runs out of the box).

The YAML file may define a ``profile`` and a ``profiles:`` map. The active
profile is deep-merged on top of the base config so module code never needs
to know which profile is active — it just reads the merged structure.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(override=False)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class CompetitionConfig(BaseModel):
    name: str = "AI Agent Olympics - Kraken Trading Performance"
    alias_public: str = "Kraken Sentinel"
    agent_codename: str = "Kraken Alpha Agent"
    starting_equity_usd: float = 10_000.0


class TradingConfig(BaseModel):
    mode: str = "dry_run"
    base_currency: str = "USD"
    cycle_interval_seconds: int = 60
    max_decisions_per_minute: int = 4
    # Calibration knobs (see README "Calibration knobs").
    min_opportunity_score_buy: float = 0.18
    min_opportunity_score_sell: float = 0.18
    sell_exit_only: bool = True
    shorting_enabled: bool = False
    no_trade_if_negative_opportunity: bool = True
    liquidity_size_dampener: float = 0.5
    liquidity_size_factor: float = 0.5
    # Session guard for entries. SELL exits are always allowed regardless.
    # Empty list disables the guard (any session can trigger BUY).
    allowed_entry_sessions: list[str] = Field(
        default_factory=lambda: ["US_CORE"]
    )


class UniverseConfig(BaseModel):
    mode: str = "static"          # "static" | "dynamic"
    symbols: list[str] = Field(
        default_factory=lambda: [
            "NVDAx", "TSLAx", "AAPLx", "MSFTx", "AMZNx",
            "GOOGLx", "METAx", "SPYx", "QQQx", "MSTRx",
            "HOODx", "CRCLx", "GLDx",
        ]
    )
    quote: str = "USD"
    allow_outside_market_hours: bool = True
    max_spread_bps: int = 80
    min_trade_count: int = 10
    min_volume: float = 100.0
    top_n: int = 8
    ranking_cache_seconds: int = 60


class StrategyConfig(BaseModel):
    ensemble_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "momentum": 0.40,
            "breakout": 0.25,
            "mean_reversion": 0.20,
            "liquidity": 0.10,
            "volatility_penalty": 0.10,
            "spread_penalty": 0.05,
        }
    )
    thresholds: dict[str, float] = Field(
        default_factory=lambda: {"buy": 0.20, "sell": -0.20}
    )
    min_confidence_to_trade: float = 0.30


class RiskConfig(BaseModel):
    max_open_positions: int = 5
    max_position_notional_usd: float = 1500.0
    max_total_exposure_usd: float = 6000.0
    max_daily_drawdown_pct: float = 5.0
    max_spread_bps: int = 60
    cooldown_seconds_per_symbol: int = 90
    block_unknown_symbol: bool = True
    block_if_regime: list[str] = Field(
        default_factory=lambda: ["LOW_LIQUIDITY", "HIGH_VOLATILITY"]
    )
    stop_loss_pct: float = 1.5
    take_profit_pct: float = 2.5
    max_trades_per_hour: int = 20


class ExecutionConfig(BaseModel):
    default_order_type: str = "market"
    dry_run_size_usd: float = 250.0
    paper_size_usd: float = 250.0
    live_size_usd: float = 100.0
    require_validate_first: bool = True
    dead_mans_switch_seconds: int = 120
    # ``spot`` keeps the historical xStocks orderbook routing; ``futures``
    # pivots the live engine to Kraken Futures Perpetual xStocks (see
    # :mod:`src.futures_kraken_cli`). The default stays ``spot`` so existing
    # profiles never silently flip venues — only profiles that explicitly
    # set ``execution.engine: futures`` will route through the futures CLI.
    engine: Literal["spot", "futures"] = "spot"


class FuturesConfig(BaseModel):
    """Live-futures pivot configuration.

    The values below are read by both the risk gate and the execution layer.
    ``max_leverage`` is enforced *intransigeantly* by the risk gate: any
    config/env value above 1.0 is rejected at evaluation time, regardless of
    the source (config, env, override). The 1.0 ceiling makes the futures
    branch effectively equivalent to spot — no margin call surface — while
    keeping the same triple opt-in and the same exit-only SELL semantics.
    """

    enabled: bool = False
    max_leverage: float = 1.0
    max_funding_rate_pct_per_hour: float = 0.5
    dry_run_mode_uses_paper_engine: bool = True
    # Optional mapping override. When non-empty, replaces the hardcoded
    # ``SPOT_TO_FUTURES`` table in :mod:`src.futures_kraken_cli` at runtime
    # (useful for tests). Empty dict means "use the canonical table".
    symbol_mapping: dict[str, str] = Field(default_factory=dict)


class ExitRulesConfig(BaseModel):
    """Defaults consumed by :mod:`src.exit_rules`.

    Profile overrides for ``risk.stop_loss_pct`` / ``risk.take_profit_pct``
    take precedence over the top-level values here; the exit engine reads
    profile-level first and falls back to ``exit.*`` only when the profile
    is silent (see ``src/exit_rules.py``).
    """

    stop_loss_pct: float = 1.5
    take_profit_pct: float = 2.0
    momentum_exit_score: float = -0.03
    max_hold_minutes: float = 90.0
    stale_position_min_pnl_pct: float = 0.3
    flatten_before_close_minutes: float = 15.0


class LLMConfig(BaseModel):
    enabled: bool = False
    base_url: str = "https://api.featherless.ai/v1"
    model: str = ""
    timeout_seconds: int = 20
    allow_override: bool = False


class LoggingConfig(BaseModel):
    level: str = "INFO"
    mask_secrets: bool = True


class DashboardConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    refresh_seconds: int = 5


class YAMLConfig(BaseModel):
    competition: CompetitionConfig = Field(default_factory=CompetitionConfig)
    profile: str = "balanced"
    profile_description: str = ""
    trading: TradingConfig = Field(default_factory=TradingConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    futures: FuturesConfig = Field(default_factory=FuturesConfig)
    exit: ExitRulesConfig = Field(default_factory=ExitRulesConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)


class EnvSettings(BaseSettings):
    """Environment-driven settings (secrets + paths)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    trading_mode: str = "dry_run"
    live_trading: bool = False
    allow_live_orders: bool = False

    # Optional env-level overrides for the actionability knobs. ``None`` means
    # "use the YAML value"; an explicit value here wins. The env wins so an
    # operator can lock down a host without editing config files.
    shorting_enabled: Optional[bool] = None
    min_opportunity_score_buy: Optional[float] = None
    min_opportunity_score_sell: Optional[float] = None

    kraken_api_key: str = ""
    kraken_api_secret: str = ""

    # Dedicated Kraken Futures credentials. When set, they take precedence
    # over the spot keys for the futures engine (see
    # :mod:`src.futures_kraken_cli`). The user creates these separately on
    # https://futures.kraken.com — they are never required for the spot
    # engine and never written back by the agent.
    kraken_futures_api_key: str = ""
    kraken_futures_api_secret: str = ""

    featherless_api_key: str = ""
    featherless_base_url: str = "https://api.featherless.ai/v1"
    featherless_model: str = ""

    database_path: str = "data/agent.sqlite"
    decisions_log_path: str = "data/decisions.jsonl"
    trades_log_path: str = "data/trades.jsonl"
    pnl_log_path: str = "data/pnl.jsonl"
    config_path: str = "config.yaml"
    log_level: str = "INFO"


class Settings(BaseModel):
    env: EnvSettings
    config: YAMLConfig
    config_source: str = "defaults"
    available_profiles: list[str] = Field(default_factory=list)
    active_profile: str = "balanced"

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    def absolute_path(self, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p
        return (self.project_root / p).resolve()

    def all_live_flags_on(self) -> bool:
        return (
            self.env.trading_mode.lower() == "live"
            and self.env.live_trading is True
            and self.env.allow_live_orders is True
        )

    def llm_active(self) -> bool:
        return bool(self.env.featherless_api_key) and (
            self.config.llm.enabled or bool(self.env.featherless_api_key)
        )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file {path} did not produce a mapping at the root")
    return data


def _resolve_config_path(env_path: str) -> tuple[Path, str]:
    candidate = (PROJECT_ROOT / env_path).resolve()
    if candidate.exists():
        return candidate, "config.yaml"
    example = (PROJECT_ROOT / "config.example.yaml").resolve()
    if example.exists():
        return example, "config.example.yaml"
    return candidate, "defaults"


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursive shallow-mutate-free merge. ``overlay`` wins on key collisions."""
    out = dict(base)
    for key, val in overlay.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(val, dict)
        ):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_active_profile(
    raw_yaml: dict[str, Any], *, override: str | None = None
) -> tuple[dict[str, Any], str, list[str]]:
    """Return ``(merged_yaml, active_profile, available_profiles)``.

    Profile lookup order:
      1. explicit ``override`` argument (used by tests / scripts)
      2. ``KRAKEN_ALPHA_PROFILE`` environment variable
      3. ``profile:`` field in the YAML file
      4. ``"balanced"`` fallback

    Unknown profile names fall back to ``balanced`` and emit a warning string
    in ``available_profiles`` so callers can surface it without crashing.
    """
    profiles_map = raw_yaml.get("profiles") or {}
    available = sorted(profiles_map.keys())
    requested = (
        override
        or os.environ.get("KRAKEN_ALPHA_PROFILE")
        or raw_yaml.get("profile")
        or "balanced"
    )
    if requested not in profiles_map and profiles_map:
        # Fallback silently to the first available profile, preferring balanced.
        requested = "balanced" if "balanced" in profiles_map else available[0]

    base = {k: v for k, v in raw_yaml.items() if k != "profiles"}
    profile_overlay = profiles_map.get(requested, {}) if isinstance(profiles_map.get(requested, {}), dict) else {}
    merged = _deep_merge(base, profile_overlay)

    # Make sure the merged structure tells downstream code which profile is live.
    merged["profile"] = requested
    description = ""
    if isinstance(profile_overlay, dict):
        description = str(profile_overlay.get("description", ""))
    merged["profile_description"] = description
    # Profile overlays may legally include a "description" key that does not
    # belong on the YAMLConfig itself — keep it out of the strict model.
    if "strategy" in merged and isinstance(merged["strategy"], dict):
        merged["strategy"].pop("description", None)
    if "risk" in merged and isinstance(merged["risk"], dict):
        merged["risk"].pop("description", None)
    return merged, requested, available


def _apply_env_overrides(config: YAMLConfig, env: EnvSettings) -> YAMLConfig:
    """Env-level overrides for the calibration knobs.

    The numeric thresholds are merged so the actionability layer sees a
    single source of truth. ``shorting_enabled`` is **not** merged here —
    we keep env and YAML separate so the gate requires *both* to be true
    independently (defence in depth, see :mod:`src.actionability`).
    """
    trading = config.trading.model_copy()
    if env.min_opportunity_score_buy is not None:
        trading.min_opportunity_score_buy = float(env.min_opportunity_score_buy)
    if env.min_opportunity_score_sell is not None:
        trading.min_opportunity_score_sell = float(env.min_opportunity_score_sell)
    return config.model_copy(update={"trading": trading})


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = EnvSettings()
    cfg_path, source = _resolve_config_path(env.config_path)
    raw = _read_yaml(cfg_path) if cfg_path.exists() else {}
    merged, active, available = load_active_profile(raw)
    config = YAMLConfig(**merged)
    config = _apply_env_overrides(config, env)
    return Settings(
        env=env,
        config=config,
        config_source=source,
        available_profiles=available,
        active_profile=active,
    )


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def safe_env_snapshot() -> dict[str, Any]:
    """Snapshot suitable for the dashboard / audit bundle: never leaks secrets."""
    s = get_settings()
    e = s.env
    return {
        "trading_mode": e.trading_mode,
        "live_trading": e.live_trading,
        "allow_live_orders": e.allow_live_orders,
        "kraken_api_key_set": bool(e.kraken_api_key),
        "kraken_api_secret_set": bool(e.kraken_api_secret),
        "kraken_futures_api_key_set": bool(e.kraken_futures_api_key),
        "kraken_futures_api_secret_set": bool(e.kraken_futures_api_secret),
        "featherless_api_key_set": bool(e.featherless_api_key),
        "featherless_base_url": e.featherless_base_url,
        "featherless_model": e.featherless_model,
        "database_path": e.database_path,
        "config_path": e.config_path,
        "log_level": e.log_level,
        "active_profile": s.active_profile,
        "available_profiles": s.available_profiles,
    }


__all__ = [
    "Settings",
    "EnvSettings",
    "YAMLConfig",
    "get_settings",
    "reload_settings",
    "safe_env_snapshot",
    "load_active_profile",
    "PROJECT_ROOT",
]
