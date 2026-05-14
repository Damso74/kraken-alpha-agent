"""Deterministic strategy votes."""

from .breakout import score as breakout_score
from .ensemble import combine
from .mean_reversion import score as mean_reversion_score
from .momentum import score as momentum_score

__all__ = [
    "momentum_score",
    "breakout_score",
    "mean_reversion_score",
    "combine",
]
