# Regime robustness — Phase 8 (Agent 18)

**Date (UTC) :** 2026-05-19  
**Module :** `src/research/regime_analysis.py`  
**Tests :** `tests/test_regime_analysis.py`  
**Pipeline :** recherche read-only (G2 — robustesse par régime)

---

## 1. Objectif

Ce rapport documente le harness **regime slicing** ajouté en Phase 8.
Il répond à la question G2 suivante (voir
[`docs/SIGNAL_REJECTION_POLICY.md`](../docs/SIGNAL_REJECTION_POLICY.md)) :

> Un effet event-study « supported » sous BH-FDR est-il **stable** quand
> on découpe par régime de marché (trend, volatilité, calendrier) ?

Le module **ne place aucun ordre**, **ne fetch rien**, et **n'importe pas**
`src.execution` / `src.risk` / `src.futures_kraken_cli`.

---

## 2. Vocabulaire des régimes

| Dimension | Labels | Règle (sans lookahead) |
|-----------|--------|-------------------------|
| **Trend** | `bull` / `bear` / `sideways` | Retour trailing `(close[i] - close[i-L]) / close[i-L]` vs seuils ±2 % (défaut `L=20`) |
| **Volatilité** | `high` / `low` | Stdev roulante des log-returns (`L=20`) comparée au quantile 50 % des stdev **strictement passées** |
| **Calendrier** | `weekend` / `weekday` | Samedi/Dimanche UTC vs lun–ven UTC |

Warm-up : trend → `None` pour `i < L` ; vol → `None` tant qu'aucune stdev passée n'existe.

---

## 3. API (stdlib only)

| Fonction | Rôle |
|----------|------|
| `assign_trend_regime(closes, …)` | Série de labels trend alignée sur les closes |
| `assign_volatility_regime(closes, …)` | Série high/low vol |
| `assign_calendar_regime(timestamps, …)` | Weekend vs weekday |
| `assign_calendar_regime_from_rows(rows, …)` | Extraction `timestamp` depuis OHLC dicts |
| `summarize_by_regime(values, regimes, …)` | Mean / median / stdev par bucket |
| `classify_regime_stability(summaries, …)` | Verdict `stable` / `unstable` / `insufficient_data` / `single_regime` |

Constantes exportées : `DEFAULT_TREND_LOOKBACK`, `DEFAULT_VOL_LOOKBACK`,
`DEFAULT_BULL_THRESHOLD`, `DEFAULT_BEAR_THRESHOLD`, `DEFAULT_MIN_REGIME_COUNT`,
`DEFAULT_MAX_SPREAD_RATIO`.

---

## 4. Workflow recommandé (manuel)

```text
1. Charger candles OHLC + résultats event study (retours par événement)
2. Aligner chaque événement sur l'index candle (forward as-of, comme event_study)
3. Lire le régime **au moment de l'événement** (pas post-event)
4. summarize_by_regime(forward_returns, regime_labels, min_count=5)
5. classify_regime_stability(summaries, min_per_regime=5, max_spread_ratio=0.5)
6. Si unstable ou insufficient_data → rejet G2 regime (documenter ici)
```

### Exemple PowerShell (pseudo-harness)

```powershell
.\.venv\Scripts\Activate.ps1
python -c "
from src.research.regime_analysis import (
    assign_trend_regime,
    assign_volatility_regime,
    assign_calendar_regime,
    summarize_by_regime,
    classify_regime_stability,
)

closes = [100 + i * 0.5 for i in range(120)]
trend = assign_trend_regime(closes)
vol = assign_volatility_regime(closes)
cal = assign_calendar_regime([1700000000 + i * 86400 for i in range(120)])

# Remplacer par les retours post-event réels une fois alignés
fake_returns = [0.01 if t == 'bull' else 0.002 for t in trend]
pairs = [(r, t) for r, t in zip(fake_returns, trend) if t]
summaries = summarize_by_regime([p[0] for p in pairs], [p[1] for p in pairs], min_count=5)
print(classify_regime_stability(summaries))
"
```

---

## 5. Critères de verdict (`classify_regime_stability`)

| Verdict | Condition | Action G2 |
|---------|-----------|-----------|
| `insufficient_data` | Aucun bucket avec `n >= min_per_regime` (défaut 5) | **Ne pas conclure** — élargir fenêtre ou fusionner régimes |
| `single_regime` | Un seul bucket éligible | **Ne pas conclure** — pas de comparaison cross-regime |
| `stable` | Même signe des means **et** `(max-min)/max(|mean|) <= 0.5` | Passer G2 regime (nécessaire, pas suffisant) |
| `unstable` | Signe opposé **ou** spread ratio > cap | **Rejet G2 regime** — effet driven par un sous-ensemble |

---

## 6. Matrice de robustesse (template)

Remplir une ligne par signal event-study **supported** sous BH-FDR.

| Signal | Dataset | Régime testé | Buckets (n) | Mean par bucket | Verdict stabilité | Décision |
|--------|---------|--------------|-------------|-----------------|-------------------|----------|
| `_example_signal_` | BTC 365d | trend | bull (12), bear (8), sideways (15) | +0.8 %, +0.6 %, +0.7 % | `stable` | Conserver pour G3 frais |
| `_example_signal_` | BTC 365d | vol | high (10), low (25) | +1.2 %, −0.3 % | `unstable` | **Rejet G2** — effet vol-dépendant |
| `_example_signal_` | BTC 365d | calendar | weekday (30), weekend (5) | +0.5 %, n<5 | `insufficient_data` | Élargir fenêtre |
| `calendar_weekend_start` | BTC 730d | calendar | weekday (—), weekend (103) | — | `single_regime` | Déjà rejeté Phase 3 |
| `demo_fear_greed_extreme_fear` | BTC 180d | trend | _à remplir_ | _à remplir_ | _pending_ | Demo only — pas promu |
| `stablecoin_supply_z_high` | BTC 365d | — | 0 events | — | `blocked` | Insufficient events |

---

## 7. Résultats Phase 8 (état initial)

| Métrique | Valeur |
|----------|--------|
| Module livré | `src/research/regime_analysis.py` |
| Tests | `tests/test_regime_analysis.py` (déterministes, sans réseau) |
| Dépendances | stdlib + `src.logger` uniquement |
| Lookahead | Interdit par construction (seuils vol = passé strict) |
| Signals « stable » cross-regime | **0** (matrice template — runs manuels requis) |

### Hypothèses pré-enregistrées (non exécutées automatiquement)

1. **Trend stability** — un signal F&G « supported » doit garder le même signe
   de mean post-7 en bull et bear ; sinon rejet G2.
2. **Vol stability** — rejet si l'effet n'existe qu'en `high` vol (pattern
   typique des spikes de news).
3. **Calendar stability** — rejet si l'effet est **weekend-only** avec
   `n_weekend < 5` (cf. politique ETH gas dans `SIGNAL_REJECTION_POLICY.md`).

---

## 8. Limites connues

- Les régimes trend/vol sont **heuristiques** (pas le classifieur live
  `src/regime.py` qui consomme des `Features` tick-level).
- Pas de correction FDR **à l'intérieur** des slices régime — chaque
  découpe est un test exploratoire ; documenter le cherry-picking risk.
- `max_spread_ratio=0.5` est un défaut conservateur ; ajuster *a priori*
  dans ce rapport avant de lancer les runs.
- Les retours event-study restent **bruts** (sans frais) ; G3 s'applique
  après un verdict `stable` ici.

---

## 9. Prochaines actions

1. Pour chaque JSON sous `reports/research_runs/` avec verdict ≠
   `not supported, move on`, aligner les retours par événement et remplir
   la matrice §6.
2. Archiver les signaux `unstable` avec la raison (`notes` de
   `RegimeStabilityResult`).
3. Ne **pas** brancher vers `config.yaml` — ce module reste recherche-only.

---

## 10. QA

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest tests/test_regime_analysis.py -q
```

Attendu : **100 % green**, aucun appel réseau.
