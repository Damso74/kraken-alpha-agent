"""Configuration loader.

Combines:
- environment variables (loaded via `python-dotenv` so `.env` works automatically)
- the YAML file pointed to by `CONFIG_PATH` (defaults to `config.yaml`, falls
  back to `config.example.yaml` so the agent runs out of the box).

The merged result is exposed through `get_settings()` (cached) so any module
can call it without re-parsing.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

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


class UniverseConfig(BaseModel):
    symbols: list[str] = Field(
        default_factory=lambda: [
            "NVDAx", "TSLAx", "AAPLx", "MSFTx", "AMZNx",
            "GOOGLx", "METAx", "SPYx", "QQQx", "MSTRx",
            "HOODx", "CRCLx", "GLDx",
        ]
    )
    quote: str = "USD"
    allow_outside_market_hours: bool = True


class StrategyConfig(BaseModel):
    ensemble_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "momentum": 0.40,
            "breakout": 0.25,
            "mean_reversion": 0.20,
            "volatility_penalty": 0.10,
            "spread_penalty": 0.05,
        }
    )
    thresholds: dict[str, float] = Field(
        default_factory=lambda: {"buy": 0.35, "sell": -0.35}
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


class ExecutionConfig(BaseModel):
    default_order_type: str = "market"
    dry_run_size_usd: float = 250.0
    paper_size_usd: float = 250.0
    live_size_usd: float = 100.0
    require_validate_first: bool = True
    dead_mans_switch_seconds: int = 120


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
    trading: TradingConfig = Field(default_factory=TradingConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
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

    kraken_api_key: str = ""
    kraken_api_secret: str = ""

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = EnvSettings()
    cfg_path, source = _resolve_config_path(env.config_path)
    raw = _read_yaml(cfg_path) if cfg_path.exists() else {}
    config = YAMLConfig(**raw)
    return Settings(env=env, config=config, config_source=source)


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def safe_env_snapshot() -> dict[str, Any]:
    """Snapshot suitable for the dashboard / audit bundle: never leaks secrets."""
    s = get_settings().env
    return {
        "trading_mode": s.trading_mode,
        "live_trading": s.live_trading,
        "allow_live_orders": s.allow_live_orders,
        "kraken_api_key_set": bool(s.kraken_api_key),
        "kraken_api_secret_set": bool(s.kraken_api_secret),
        "featherless_api_key_set": bool(s.featherless_api_key),
        "featherless_base_url": s.featherless_base_url,
        "featherless_model": s.featherless_model,
        "database_path": s.database_path,
        "config_path": s.config_path,
        "log_level": s.log_level,
    }


__all__ = [
    "Settings",
    "EnvSettings",
    "YAMLConfig",
    "get_settings",
    "reload_settings",
    "safe_env_snapshot",
    "PROJECT_ROOT",
]
