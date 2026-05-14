"""Structured logger with automatic secret masking.

Any value that looks like an API key/secret is masked before reaching the
formatter so it can never leak to stdout, files, or the dashboard.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from logging import LogRecord
from typing import Iterable


# Environment variable names whose value must never appear in logs.
_SECRET_ENV_NAMES: tuple[str, ...] = (
    "KRAKEN_API_KEY",
    "KRAKEN_API_SECRET",
    "FEATHERLESS_API_KEY",
)


def _gather_secret_values() -> list[str]:
    out: list[str] = []
    for name in _SECRET_ENV_NAMES:
        val = os.environ.get(name)
        if val and len(val) >= 6:
            out.append(val)
    return out


# Patterns that match obvious credential formats even if the value is not in env.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([A-Za-z0-9/+_\-]{8,})"),
    re.compile(r"(?i)(api[_-]?secret\s*[=:]\s*)([A-Za-z0-9/+_\-]{8,})"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]{8,})"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([A-Za-z0-9._\-]{8,})"),
    re.compile(r"(?i)\b(KRAKEN_API_KEY|KRAKEN_API_SECRET|FEATHERLESS_API_KEY)=([^\s]+)"),
)


def mask_secrets(text: str, extra_values: Iterable[str] | None = None) -> str:
    if not text:
        return text
    out = text
    for value in _gather_secret_values():
        if value and value in out:
            out = out.replace(value, "***")
    if extra_values:
        for value in extra_values:
            if value and value in out:
                out = out.replace(value, "***")
    for pat in _PATTERNS:
        out = pat.sub(lambda m: f"{m.group(1)}***", out)
    return out


class _MaskingFormatter(logging.Formatter):
    def format(self, record: LogRecord) -> str:
        original = super().format(record)
        return mask_secrets(original)


_LEVEL_DEFAULT = "INFO"


def setup_logging(level: str | None = None) -> None:
    lvl = (level or os.environ.get("LOG_LEVEL", _LEVEL_DEFAULT)).upper()
    root = logging.getLogger()
    if getattr(root, "_kaa_configured", False):
        root.setLevel(lvl)
        return
    root.setLevel(lvl)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(lvl)
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    handler.setFormatter(_MaskingFormatter(fmt=fmt, datefmt="%Y-%m-%dT%H:%M:%S"))
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root._kaa_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
