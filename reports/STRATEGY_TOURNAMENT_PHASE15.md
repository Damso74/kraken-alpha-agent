# Strategy tournament — Phase 15 (multi-timeframe V2)

## CLI

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/run_strategy_tournament.py `
  --assets BTC ETH `
  --timeframes 1d 4h 1h `
  --cash 1000 `
  --fees-bps 40 `
  --slippage-bps 5 `
  --output-dir reports/strategy_tournament_phase15 `
  --cache-only
```

`--timeframe` (singulier) reste supporté pour compatibilité Phase 14.

## Sorties

| Fichier | Contenu |
|---------|---------|
| `results.json` | Métriques + verdict + risk + candle_count par (asset, timeframe, strategy) |
| `results_matrix.csv` | Matrice asset × timeframe × strategy |
| `trades.csv` | Fills |
| `equity_curve.csv` | Courbe equity |
| `decisions.jsonl` | Journal signaux / risk |

## Presets (verrouillés)

| Timeframe | Clé preset | Trend fast/slow | Breakout lookback | MR lookback / hold |
|-----------|------------|-----------------|-------------------|---------------------|
| 1d | `phase15_1d` | 20 / 50 | 20 | 20 / 7 |
| 4h | `phase15_4h` | 24 / 72 | 24 | 28 / 42 |
| 1h | `phase15_1h` | 48 / 120 | 48 | 56 / 168 |

Détail complet : `src/strategies/presets.py`.

## Verdicts Phase 15

`blocked_data`, `insufficient_candles`, `insufficient_trades`, `blocked_risk`, `blocked_costs`, `kill`, `weak`, `paper_candidate`.

`micro_live_candidate` : **jamais** émis par `classify_strategy_verdict`.

Seuils trades minimum : 1d ≥ 5, 4h ≥ 10, 1h ≥ 20.

## Run 2026-05-19

**Commande :** ci-dessus (BTC + ETH, 1d/4h/1h, cache-only).

| Dimension | Résultat |
|-----------|----------|
| Runs totaux | 24 (2 assets × 3 TF × 4 strategies) |
| Données 1d BTC/ETH | `data_ok=true` |
| Données 4h / 1h | `blocked_data` (fichiers cache absents) |
| SOL | non inclus (cache daily absent) |
| `paper_candidate` | 0 |
| Verdicts dominants | `blocked_data` (16), `insufficient_trades` (5), `blocked_risk` (2), `blocked_costs` (1) |

## Interprétation

Le tournoi V2 est un **filtre honnête multi-échelle** : sans caches 4h/1h locaux, les runs intraday restent `blocked_data` plutôt que d’inventer des candles. Les runs 1d reflètent frais 40 bps + contraintes risk — aucune promotion live.
