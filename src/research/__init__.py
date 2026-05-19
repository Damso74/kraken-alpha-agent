"""Research harness for the post-hackathon strategy-discovery pipeline.

This package hosts the *truth-finding* tooling that lives outside the
live trading path. Nothing in :mod:`src.research` is allowed to import
:mod:`src.execution`, :mod:`src.futures_kraken_cli`, :mod:`src.risk` or
anything else that can mutate venue state — the contract is identical
to :mod:`src.external_signals` and is enforced by code review.

Current modules
---------------
- :mod:`src.research.event_study` — symmetric / asymmetric window event
  studies on top of any ``{timestamp, open, high, low, close, volume}``
  candle sequence. Stdlib-only so it ships everywhere the existing
  backtester does.
- :mod:`src.research.placebo` — placebo / falsification harness
  (temporal shift, random event sampling, label shuffle, Bonferroni
  and Benjamini–Hochberg multiple-testing corrections, empirical
  percentile rank). Built to kill bad hypotheses cheaply, *before*
  they reach the walk-forward step.

These two modules are the bare minimum to make the existing
``src.external_signals`` feeds (Fear & Greed, BTC dominance, realised
volatility regime) actionable in a research workflow without growing
the live trading surface by a single line.

Design constraints
------------------
- **No pandas, no numpy.** The whole project is stdlib + httpx + pydantic
  + fastapi + optuna (see ``requirements.txt``); adding heavyweight
  numerical libraries here would inflate the dependency footprint of
  the live trading container, which is unacceptable.
- **Pure functions where possible.** Helpers take primitive inputs
  (lists, dicts, frozen dataclasses) and return frozen dataclasses so
  the same call is reproducible and trivially testable.
- **No network I/O.** Network feeds live in :mod:`src.external_signals`
  and the upcoming ``src.data.collectors`` package — research code
  consumes them and never fetches them itself.
"""

from __future__ import annotations

__all__: list[str] = []
