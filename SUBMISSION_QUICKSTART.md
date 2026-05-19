# Submission Quickstart — Kraken Alpha Agent

> Audience : jury lablab (AI Agent Olympics — Kraken Trading Performance).  
> Format : 5-10 min de lecture max. Sections en français + en anglais.  
> Date : mai 2026. Hackathon window : **13 → 19 mai 2026 (UTC)**.

---

## 🇫🇷 Section française

### À quoi sert ce repo

`kraken-alpha-agent` est un agent de trading déterministe pour la **lablab AI
Agent Olympics – Kraken Trading Performance**. Le moteur lit les données de
marché xStocks via le Kraken CLI, calcule des features, classifie le régime,
combine 3 stratégies (momentum / breakout / mean-reversion) en ensemble
pondéré, applique une couche d'actionnabilité (BUY-only sur seuil, SELL
exit-only, no-short), puis passe par une porte de risque unique (caps
d'exposition, drawdown, cooldown, triple opt-in pour le live). Tout est tracé
en SQLite + JSONL pour audit.

### Comment l'agent fonctionne (1 paragraphe)

1. **Cycle 60 s** → polling Kraken CLI → features (returns 5/15/60min,
   volatilité, spread, distance high/low, volume) → régime
   (TRENDING / RANGING / HIGH_VOLATILITY / LOW_LIQUIDITY) → ensemble v2
   pondéré → actionnabilité (HOLD si seuil non atteint, no-short, exit-only) →
   risque (8 gates dont triple opt-in live + leverage cap 1.0x hardcodé) →
   exécution (`dry_run` par défaut, `paper` ou `live` sur opt-in explicite)
   → persistance SQLite + JSONL + dashboard FastAPI.
2. **Sur 13 xStocks rangées dynamiquement** par opportunity score, top-N=5
   par cycle, fenêtre BUY restreinte à `US_CORE` (sessions NYSE).

### Backtest en 60 secondes (copy-paste)

```powershell
git clone https://github.com/Damso74/kraken-alpha-agent.git
cd kraken-alpha-agent
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env

# Backtest hackathon-window (13 → 19 mai 2026, OHLC 1h x 168 candles)
python scripts/backtest_xstocks.py --top 8 --interval 60 --hours 168 --output-prefix data/backtest_hackathon_window

# Export vers le JSON web UI
python scripts/export_submission_backtest.py --input data/backtest_hackathon_window_latest.json --output web/public/data/backtest_xstocks_hackathon_window.json --snapshot-label hackathon_window

# Snapshot 30j baseline pour comparaison
python scripts/backtest_xstocks.py --top 8 --interval 60 --target-candles 720
python scripts/export_submission_backtest.py --output web/public/data/backtest_xstocks_30d.json --snapshot-label standard_30d
```

### Comment auditer le PnL live via la clé Kraken read-only

1. L'utilisateur fournit au jury (via DM lablab) une clé API Kraken **read-only**
   avec uniquement : `Query Funds`, `Query Open Orders & Trades`,
   `Query Closed Orders & Trades`. **Withdraw / Place Orders / Cancel Orders / Modify Settings = OFF.**
2. Le jury exécute (machine personnelle ou WSL) :

   ```bash
   kraken balance -o json
   kraken trades-history -o json
   kraken futures fills -o json   # si une clé Futures read-only est fournie
   ```

3. Le PnL net officiel = la somme des fills retournés par Kraken sur la
   fenêtre de soumission. Voir `docs/JURY_ACCESS_TEMPLATE.md` pour le
   protocole complet.

### Résultats clés

| Snapshot                                    | Période               | Net PnL    | Trades | Win rate | Max DD  |
|---------------------------------------------|-----------------------|------------|--------|----------|---------|
| **Hackathon window (primary)**              | 13 → 19 mai 2026 (UTC) | **+19.18 USD** | 10     | 80.0%    | 0.06%   |
| 30-day baseline                             | 16 avril → 15 mai 2026| +33.56 USD | 138    | 53.0%    | 1.68%   |
| Walk-forward OOS audit (xStocks 1h, 60d)    | mai 2026              | **0 configs survived OOS filter** (stricte : test_pnl > 0 ∧ winrate ≥ 50% ∧ trades ≥ 30) | – | – | – |

`+19.18 USD` représente +0.19 % sur 10 000 USD de capital de départ. Le
nombre de trades est faible (10) parce que xStocks ne tradent que ~80h/semaine
et que les BUY sont restreints à `US_CORE` (NYSE 9h30-16h ET) → le replay
sur 168 candles d'OHLC ne déclenche que ~1.5 jour d'activité réelle.
**Aucun curve-fit** : c'est le profil `aggressive_competition` non modifié,
identique au snapshot 30j.

### Pourquoi le PnL live est ~0 (transparence)

Le compte Kraken de l'utilisateur est sur l'entité **PEDSL-CY (Cyprus, EU)**.
Cette entité bloque structurellement xStocks au niveau compte :

- `kraken order buy AAPLx/USD --asset-class tokenized_asset` → `EGeneral:Permission denied`
- `kraken futures order buy PF_HOODXUSD --leverage 1` → `{"result":"success","status":"wouldNotReducePosition"}`
- Contrôle BTC Perp sur la même clé Futures → `status:"placed"` (preuve : la
  clé/IP/code sont sains, c'est venue-side et réglementaire)

Reproduit depuis FR/Lyon ET depuis le VPS US-NJ (140.82.12.75), même erreurs.
Citations Discord lablab d'autres participants confirmant le même blocage :
voir `docs/HACKATHON_DISCORD_CONTEXT.md`. Verdict : pas d'edge live exécutable
pour xStocks tant que le compte n'est pas migré vers une entité non-EU/EEA.

### Vidéo de démo

Voir [`docs/DEMO_VIDEO_SCRIPT.md`](./docs/DEMO_VIDEO_SCRIPT.md) (3-4 min,
storyboard 7 scènes, YouTube link inséré au moment de la soumission lablab).

### Cartographie du repo

```
kraken-alpha-agent/
├── src/                    # moteur déterministe (features, regime,
│                            # strategies, ensemble, actionability, risk,
│                            # execution, portfolio, storage)
├── scripts/                # CLI tools (backtest, ranking, dry_run_once,
│                            # run_agent_loop, paper_smoke_test, export
│                            # bundles)
├── tests/                  # 330+ tests pytest, ~5s
├── docs/                   # SUBMISSION.md, METHODOLOGY.md, JURY_ACCESS_TEMPLATE.md,
│                            # DEMO_VIDEO_SCRIPT.md, HACKATHON_DISCORD_CONTEXT.md, etc.
├── web/                    # dashboard Next.js 16 (Vercel) — read-only,
│                            # affiche les snapshots backtest
├── config.yaml             # profils (aggressive_competition, micro_live_100eur, …)
├── data/                   # gitignored — sqlite + jsonl + snapshots backtest
├── README.md               # entrée principale
├── SUBMISSION_QUICKSTART.md  # ce fichier
└── AGENTS.md               # learned-preferences pour les futurs runs
```

### Tests

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

Attendu : ~330+ passed, 0 failed, ~5 s wall-clock. Le test suite couvre la
parser whitelist, les risk gates, le wrapper futures, l'exit-action carve-out,
les flatten paths, les shorting blocks, le live triple opt-in.

### Rigueur méthodologique

Voir :

- [`docs/METHODOLOGY.md`](./docs/METHODOLOGY.md) — règles anti-curve-fit,
  filtre OOS strict, walk-forward train/test split.
- [`docs/STRATEGY_DISCOVERY_REPORT.md`](./docs/STRATEGY_DISCOVERY_REPORT.md) —
  verdict honest : 0 configs ont survécu au filtre out-of-sample, on garde la
  config par défaut et on documente le résultat négatif au lieu de chasser
  les métriques.

---

## 🇬🇧 English Section

### What this repo is

`kraken-alpha-agent` is a deterministic trading agent for the lablab
**AI Agent Olympics – Kraken Trading Performance** track. It reads xStocks
market data via the Kraken CLI, computes features, classifies the market
regime, blends 3 strategies (momentum / breakout / mean-reversion) in a
weighted ensemble, applies an actionability layer (BUY-only above threshold,
SELL exit-only, no-short), then routes through a single risk gate (exposure
caps, drawdown, cooldown, live triple opt-in). Every decision and order is
persisted to SQLite + JSONL for audit.

### How the agent works (one paragraph)

A 60-second cycle polls the Kraken CLI, builds features (5/15/60-min returns,
volatility, spread, high/low distance, volume), classifies the regime
(TRENDING / RANGING / HIGH_VOLATILITY / LOW_LIQUIDITY), runs the weighted
ensemble v2, downgrades unsafe intents to HOLD via the actionability layer
(BUY threshold, no-short, SELL exit-only), then passes through a single risk
manager (8 gates including the live triple opt-in and a hardcoded 1.0x
leverage cap). Execution mode is `dry_run` by default; `paper` and `live`
require explicit opt-in. The `aggressive_competition` profile trades the top-5
of 13 xStocks by opportunity score, with BUY entries restricted to `US_CORE`
(NYSE core hours).

### Backtest in 60 seconds (copy-paste)

```bash
git clone https://github.com/Damso74/kraken-alpha-agent.git
cd kraken-alpha-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env

# Hackathon-window backtest (May 13 → May 19, 2026, hourly OHLC × 168 candles)
python scripts/backtest_xstocks.py --top 8 --interval 60 --hours 168 \
    --output-prefix data/backtest_hackathon_window

# Export to the web UI JSON
python scripts/export_submission_backtest.py \
    --input data/backtest_hackathon_window_latest.json \
    --output web/public/data/backtest_xstocks_hackathon_window.json \
    --snapshot-label hackathon_window
```

### How to verify the live PnL via the read-only Kraken API key

1. The submitter shares a **read-only** Kraken API key with the jury via
   lablab DM. Permissions: `Query Funds`, `Query Open Orders & Trades`,
   `Query Closed Orders & Trades` ON. **Place Orders / Cancel / Withdraw /
   Modify Settings OFF.**
2. The jury runs (any machine with `kraken-cli` installed):

   ```bash
   kraken balance -o json
   kraken trades-history -o json
   kraken futures fills -o json   # if a Futures read-only key is also provided
   ```

3. Live PnL = the sum of fills returned by Kraken over the submission window.
   See `docs/JURY_ACCESS_TEMPLATE.md` for the full protocol.

### Key results

| Snapshot                          | Period                | Net PnL     | Trades | Win rate | Max DD |
|-----------------------------------|-----------------------|-------------|--------|----------|--------|
| **Hackathon window (primary)**    | 2026-05-13 → 05-19 UTC | **+19.18 USD** | 10     | 80.0%    | 0.06%  |
| 30-day baseline                   | 2026-04-16 → 05-15    | +33.56 USD  | 138    | 53.0%    | 1.68%  |
| Walk-forward OOS audit            | May 2026              | 0 configs survived strict OOS filter (test_pnl > 0 ∧ winrate ≥ 50% ∧ trades ≥ 30) | – | – | – |

The hackathon-window snapshot uses the unmodified `aggressive_competition`
profile (identical to the 30-day baseline). The low trade count (10) is a
direct consequence of xStocks trading ~80h/week and BUY entries being
restricted to `US_CORE` — only ~1.5 days of effective activity over the
168-hour replay. **No curve-fitting**: see `docs/METHODOLOGY.md` for the
anti-curve-fit policy.

### Why the live PnL is ~0 (transparency)

The submitter's Kraken account is on the **PEDSL-CY (Cyprus EU)** entity,
which structurally blocks xStocks at the account class layer:

- Spot: `kraken order buy AAPLx/USD --asset-class tokenized_asset` →
  `EGeneral:Permission denied`
- Futures: `kraken futures order buy PF_HOODXUSD --leverage 1` →
  `{"result":"success","status":"wouldNotReducePosition"}`
- Control BTC Perp on the same key → `status:"placed"` (proves the key, IP
  and code are healthy; the block is venue-side and regulatory).

Reproduced from both FR/Lyon and the US-NJ VPS (140.82.12.75) — same errors,
not IP/geo. Other lablab participants reported the same xStocks errors on
Discord (verbatim quotes in `docs/HACKATHON_DISCORD_CONTEXT.md`). Verdict: no
live xStocks PnL is achievable on this account until it is migrated to a
non-EU/EEA Kraken entity.

### Demo video

See [`docs/DEMO_VIDEO_SCRIPT.md`](./docs/DEMO_VIDEO_SCRIPT.md). YouTube link
will be inserted at submission time.

### Repo map

```
kraken-alpha-agent/
├── src/                    # deterministic engine (features, regime,
│                            # strategies, ensemble, actionability, risk,
│                            # execution, portfolio, storage)
├── scripts/                # CLI tools (backtest, ranking, dry_run_once,
│                            # run_agent_loop, paper_smoke_test, export
│                            # bundles)
├── tests/                  # 330+ pytest tests, ~5s
├── docs/                   # SUBMISSION.md, METHODOLOGY.md,
│                            # JURY_ACCESS_TEMPLATE.md, DEMO_VIDEO_SCRIPT.md,
│                            # HACKATHON_DISCORD_CONTEXT.md, etc.
├── web/                    # Next.js 16 dashboard (Vercel) — read-only,
│                            # displays the backtest snapshots
├── config.yaml             # profiles (aggressive_competition, micro_live_100eur, …)
├── data/                   # gitignored — sqlite + jsonl + backtest snapshots
├── README.md               # main entry point
├── SUBMISSION_QUICKSTART.md   # this file
└── AGENTS.md               # learned-preferences for future runs
```

### Tests

```bash
source .venv/bin/activate    # Windows: .\.venv\Scripts\Activate.ps1
python -m pytest -q
```

Expected: 330+ passed, 0 failed, ~5 s wall-clock.

### Methodology

- [`docs/METHODOLOGY.md`](./docs/METHODOLOGY.md) — anti-curve-fit policy,
  strict OOS filter, walk-forward train/test split.
- [`docs/STRATEGY_DISCOVERY_REPORT.md`](./docs/STRATEGY_DISCOVERY_REPORT.md) —
  honest verdict: 0 configs survived the out-of-sample filter; we keep the
  default config and document the negative result instead of chasing metrics.

---

**License:** MIT (see `pyproject.toml`). **Default mode:** `dry_run` — no
order can leave the process without an explicit triple opt-in
(`TRADING_MODE=live` + `LIVE_TRADING=true` + `ALLOW_LIVE_ORDERS=true`).
Hardcoded leverage cap = 1.0x. Shorting permanently disabled.
