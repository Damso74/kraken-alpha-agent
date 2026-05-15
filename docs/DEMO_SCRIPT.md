# Demo script — Kraken Alpha Agent

**Target duration: 90 seconds.** Shot live, on a clean repo clone, with the
Python virtualenv already activated and the dashboard running on
`http://127.0.0.1:8000`.

## Preflight checklist (run once before recording)

```powershell
.venv\Scripts\Activate.ps1
pytest                                # expect 96/96 green in ~2s
python scripts/rank_xstocks.py --top 8
python scripts/dry_run_once.py
python scripts/analyze_paper_run.py --since 24
uvicorn src.dashboard.app:app --reload
```

Then open in the browser, in tabs (in this order):

1. `http://127.0.0.1:8000/` — Overview, profile/PnL/paper banners,
   Actionability panel, top xStocks.
2. `http://127.0.0.1:8000/ranking` — raw JSON of the most recent ranking.
3. `http://127.0.0.1:8000/decisions` — decisions table.

Also keep one terminal visible (showing `python scripts/dry_run_once.py`
output) and one editor pane open on
`data/decisions.jsonl` so the final cut can land on a real audit line.

## Narration (English, ~150 words, ~85 seconds)

> This is **Kraken Alpha Agent**, an autonomous xStocks trading agent built
> for the **Kraken Trading Performance** track. The agent uses the Kraken
> CLI as its execution layer. It probes real xStocks market data through
> ticker, OHLC, orderbook and trades. Then it ranks each tokenized stock
> using momentum, liquidity, volume, trade count and spread. The dashboard
> shows the active profile, PnL source, paper status and latest ranked
> opportunities. The trading engine runs momentum, breakout and
> mean-reversion strategies. Their votes are combined into an opportunity
> score. The actionability layer checks signal strength, disables shorting
> by default, makes SELL exit-only, and dampens size when liquidity is low.
> In this run, the agent produced thirteen decisions and chose HOLD every
> time because the opportunities were not strong enough. This is intentional:
> autonomous but **not blind**. For safety, dry-run is the default. Live
> trading requires a triple opt-in. Every decision is persisted to SQLite
> and JSONL, and an audit bundle can be exported.

## Shot list (90s)

| ⏱  | Visual                                         | Spoken cue                                  |
|----|------------------------------------------------|---------------------------------------------|
| 0–8s   | Terminal: `python scripts/rank_xstocks.py --top 8` running. | "Kraken Alpha Agent… Kraken CLI as execution layer." |
| 8–18s  | Terminal: ranking table prints (`MSTRx`, `NVDAx`, …).        | "Ranks each tokenized stock using momentum, liquidity, volume, trade count and spread." |
| 18–30s | Dashboard `/` — profile banner, ranking table, BUY/EXIT/NO-TRADE panel. | "Dashboard shows the active profile, PnL source, paper status, latest opportunities." |
| 30–45s | Switch to `/decisions` page, then back to overview. | "Momentum, breakout, mean reversion — votes combined into an opportunity score." |
| 45–60s | Dashboard `/` — Actionability panel close-up. | "Actionability layer: signal strength, no shorting by default, SELL exit-only, size dampened when liquidity is low." |
| 60–72s | Terminal: `python scripts/dry_run_once.py` output (13 decisions, all HOLD). | "13 decisions, HOLD every time. Autonomous but not blind." |
| 72–84s | Editor: a single line of `data/decisions.jsonl`, then `python scripts/export_audit_bundle.py`. | "Dry-run is the default. Live trading requires a triple opt-in. Every decision audited." |
| 84–90s | Dashboard `/health` → JSON → cut to repo URL.  | "Submitted as Kraken Alpha Agent."          |

## Tips

- Record at 30 fps with a 16:9 capture; the terminal/dashboard split looks
  better than full-screen browser.
- Hide any sensitive env values from the recording (the dashboard masks
  them by design — verify `safe_env_snapshot()` returns booleans only).
- If WSL is not installed on the recording machine, the mock transport
  produces identical visuals — call that out in the description.

## Backup short pitch (15 seconds, social)

> Autonomous xStocks trading agent on the Kraken CLI. Ranks tokenized
> stocks by momentum, liquidity and spread, then routes signals through
> an actionability layer that refuses to short by default and dampens
> size when the book is thin. Dry-run by default, live trading gated by
> a triple opt-in. Full audit trail in SQLite + JSONL.
