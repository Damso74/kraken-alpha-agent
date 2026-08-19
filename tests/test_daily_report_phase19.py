"""Tests for daily report (Phase 19)."""

from __future__ import annotations

from src.bot.daily_report import build_daily_report, render_daily_report_md, write_daily_report
from src.bot.state_store import DaemonState, StateBundle, append_equity, save_state


def test_daily_report_generation(tmp_path) -> None:
    save_state(tmp_path, StateBundle(state=DaemonState(equity=1010.0)))
    append_equity(tmp_path, 1, 1000.0)
    append_equity(tmp_path, 2, 1010.0)
    data = build_daily_report(tmp_path)
    assert data.equity == 1010.0
    md = render_daily_report_md(data)
    assert "PAPER ONLY" in md
    out = write_daily_report(tmp_path, tmp_path / "live")
    assert out.is_file()
