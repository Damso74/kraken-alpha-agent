"""Cache provenance metadata for research collectors (no network)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class DataProvenance:
    """Describe where a research feed came from (cache file or live fetch)."""

    source: str
    path: str | None
    sha256: str | None
    row_count: int | None
    generated_at: str | None
    schema_version: str = "phase12-v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def safe_git_commit() -> str | None:
    """Best-effort ``git rev-parse HEAD`` without raising."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def ohlc_cache_row_count(path: Path) -> int | None:
    """Row count for ``ohlc_daily_{TICKER}.json`` nested ``entries.candles`` layout."""
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(doc, list):
        return len(doc)
    if isinstance(doc, Mapping):
        entries = doc.get("entries")
        if isinstance(entries, Mapping):
            candles = entries.get("candles")
            if isinstance(candles, list):
                return len(candles)
        for key in ("rows", "candles", "data"):
            val = doc.get(key)
            if isinstance(val, list):
                return len(val)
    return None


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_from_cache_path(
    path: Path,
    *,
    source: str = "cache",
    row_count: int | None = None,
) -> DataProvenance:
    """Build provenance for an on-disk JSON cache."""
    resolved = path.resolve()
    if row_count is None and resolved.is_file():
        row_count = ohlc_cache_row_count(resolved)

    mtime = None
    if resolved.is_file():
        mtime = datetime.fromtimestamp(
            resolved.stat().st_mtime, tz=timezone.utc
        ).isoformat()

    return DataProvenance(
        source=source,
        path=str(resolved),
        sha256=sha256_file(resolved),
        row_count=row_count,
        generated_at=mtime,
    )


def merge_provenance_into_report(
    report: dict[str, Any],
    *,
    ohlc: DataProvenance | None = None,
    signal: DataProvenance | None = None,
) -> dict[str, Any]:
    """Attach ``data_provenance`` block without mutating nested study cells."""
    block: dict[str, Any] = {}
    if ohlc is not None:
        block["ohlc"] = ohlc.to_dict()
    if signal is not None:
        block["signal_feed"] = signal.to_dict()
    if block:
        report = dict(report)
        report["data_provenance"] = block
    return report
