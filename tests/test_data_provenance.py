"""Collector cache provenance (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from src.data.collectors._provenance import (
    merge_provenance_into_report,
    provenance_from_cache_path,
    sha256_file,
)


def test_sha256_and_row_count(tmp_path: Path) -> None:
    cache = tmp_path / "feed.json"
    cache.write_text(json.dumps([{"a": 1}, {"a": 2}]), encoding="utf-8")
    digest = sha256_file(cache)
    assert digest is not None
    prov = provenance_from_cache_path(cache)
    assert prov.row_count == 2
    assert prov.sha256 == digest


def test_merge_provenance_into_report() -> None:
    prov = provenance_from_cache_path(Path("nope.json"))
    report = merge_provenance_into_report({"verdict": "kill"}, ohlc=prov)
    assert "data_provenance" in report
    assert report["data_provenance"]["ohlc"]["source"] == "cache"
