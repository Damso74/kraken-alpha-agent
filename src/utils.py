"""Tiny helpers shared across modules."""

from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def pct(numer: float, denom: float, default: float = 0.0) -> float:
    if not denom:
        return default
    return numer / denom


def fmt_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"
