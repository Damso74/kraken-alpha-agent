# Cinq hypothèses Phase 11 — candidats d’implémentation

> **Docs only — aucun code.** Sélection pour la prochaine vague d’event studies
> read-only (Phase 11), après le backlog Phase 9 et les runs Phase 6 (leaderboard V2).
>
> **Aucune entrée ci-dessous ne constitue une promesse de rentabilité, de PnL,
> ou de signal « live-ready ».** Les verdicts attendus restent majoritairement
> `not supported, move on`, `weak evidence` ou `blocked` — c’est un succès
> méthodologique.

## Contexte Phase 6 (réalité à respecter)

Synthèse issue de [`reports/PHASE_3_VS_PHASE_6.md`](../reports/PHASE_3_VS_PHASE_6.md) et du
[`reports/ALPHA_RESEARCH_LEADERBOARD_V2.md`](../reports/ALPHA_RESEARCH_LEADERBOARD_V2.md) :

| Signal Phase 6 | Résultat | Conséquence Phase 11 |
|----------------|----------|----------------------|
| `wikipedia_btc_attention` | 16 events, **weak evidence**, BH 0/5 | Phase 11 : panier 8 pages crypto + placebos non-crypto (`--layout basket`) ; seuils z figés 1,5 / 2,0 |
| `wikipedia_crypto_basket` | Agent 27 (Phase 11 sprint) | `scripts/event_study_wikipedia.py --layout basket` → `reports/research_runs_phase11/` ; verdict ∈ {kill, blocked, weak evidence, candidate for further OOS testing} |
| `stablecoin_supply_z_high` (z≥1,5) | **0 events → blocked** | Seuil z=1,0 **uniquement** si pré-enregistré avant run principal |
| `calendar_weekend_start` | **not supported** (105 events, BH 0/5) | **Exclure** toute variante week-end UTC ; calendrier ≠ week-end |
| `eth_gas_congestion` | **blocked** (0 rows history) | Inclure seulement avec plan de seed `etherscan_gas_history.json` |
| `exchange_status_major_incident` | 2 events, weak | Sous-puissance — pas dans le top 5 |
| `demo_fear_greed_extreme_fear` | demo harness, weak | Pas de promotion sans harness event_study dédié multi-actifs |

Infrastructure commune Phase 6 : OHLC via `--ohlc-source binance-public`, placebos
`random-events bootstrap` (200 reps), FDR Benjamini–Hochberg α=0,05.

## Critères de sélection (rappel)

| Critère | Application |
|---------|-------------|
| Données accessibles | APIs publiques gratuites ou OHLC déjà câblé ; pas Glassnode / Deribit OI |
| Coût faible | Pas d’API payante ; cache JSON local |
| Turnover faible | Événements espacés (z élevé, calendrier mensuel, congestion sparse) |
| Event study falsifiable | Harness `scripts/event_study_*.py` + `_event_study_common.py` |
| Placebo clair | Bootstrap 200 ou jours placebo calendaires documentés |
| Risque juridique | Sources publiques ; pas scraping ToS / dark web / MEV |
| Pas de HFT | Résolution **journalière** uniquement |
| Pas de gros capital | Recherche read-only ; aucun ordre |

## Synthèse des 5 retenues

| Rang | ID | Nom court | Effort estimé | Nouveau code |
|------|-----|-----------|---------------|--------------|
| 1 | P9-CA-032 | Ouverture session US (ET) | **S** (0,5–1 j) | Non — script prêt |
| 2 | P9-MS-023 | Pic de volume journalier (z-high) | **M** (2–3 j) | **Fait** — `volume_shock.py` + `event_study_volume_shock.py` |
| 3 | P9-SC-001-PR | Supply stables z≥1,0 (pré-enregistré) | **S** (0,5 j) | Non — flag CLI existant |
| 4 | P9-OC-041 | Congestion gas ETH (fast gwei) | **M** (1–2 j) | Non — seed cache + run |
| 5 | P9-CA-037 | 3ᵉ vendredi expiry (calendrier) | **S** (0,5 j) | Non — script prêt |

**Exclus explicitement de ce top 5 :** `calendar_weekend_start` (rejet Phase 6),
`wikipedia_btc_attention` (déjà évalué, faible puissance), stablecoins z≥1,5 sans
pré-enregistrement, familles xStocks PEDSL, dérivés payants, HFT / L2 / legal no-go.

---

## 1. P9-CA-032 — Ouverture session US cash (ET)

### Intuition

Le passage à la session cash US pourrait concentrer flux et volatilité sur BTC,
sans prétendre à un edge tradeable.

### Dataset

| Champ | Valeur |
|-------|--------|
| Rows prix | OHLC journalier BTC (Binance public ou Kraken REST) |
| Rows événements | Timestamps dérivés des candles (pas de feed externe) |
| Fenêtre | 365–730 j recommandés |
| Horizon | `post_1`, `post_3`, `post_7` |

### Collector nécessaire

**Aucun** — événements construits depuis les timestamps OHLC uniquement
(`src/signals/calendar_effects.py` → `build_us_core_session_open_events`).

### Signal builder

Module existant : `src/signals/calendar_effects.py`  
Flag : `us_open` (définition session pré-enregistrée dans le module, fuseau `America/New_York`).

### Script à créer

**Aucun** — utiliser :

```text
python scripts/event_study_calendar.py \
  --calendar-flag us_open \
  --days 730 \
  --ohlc-source binance-public \
  --output-json reports/research_runs_v2/calendar_us_open_730d.json
```

### Test placebo

| Placebo | Protocole |
|---------|-----------|
| Primaire | Bootstrap `random-events` (200 reps, seed `20260519`) — défaut `_event_study_common.py` |
| Secondaire (recommandé) | Comparer à un flag calendrier placebo : jours ouvrés US **sans** fenêtre d’ouverture (à documenter dans le JSON `placebo_notes`) ou run séparé `--calendar-flag` sur mid-session si ajouté plus tard |

### Rejet attendu

- BH FDR : **0/5** (effet dilué par le marché 24/7).
- Verdict leaderboard : **`not supported, move on`** ou **`weak evidence`** si une cellule raw p<0,05 sans FDR.
- Risque : effet entièrement expliqué par le régime macro (corrélation S&P), non spécifique crypto.

### Effort estimé

**S — 0,5 à 1 jour** : run + entrée leaderboard + note dans `RUN_LOG` Phase 11.

---

## 2. P9-MS-023 — Pic de volume journalier (z-score élevé)

### Intuition

Un volume journalier anormalement élevé sur la paire de référence pourrait
coïncider avec arrivée d’information ; testable en event study sans order flow L2.

### Dataset

| Champ | Valeur |
|-------|--------|
| Rows prix | OHLC journalier `{timestamp, open, high, low, close, volume}` |
| Champ signal | `volume` (float, unité venue) |
| Fréquence events | ~5–15 % des jours si z≥2,0 ; plus sparse si z≥2,5 |
| Horizon | `post_1`, `post_3` (priorité) ; `post_7` optionnel |

### Collector nécessaire

**Aucun collector dédié** — réutiliser `fetch_daily_ohlc_from_args()`  
(`src/crypto_ohlc_rest.py`, source `binance-public` recommandée pour alignement Phase 6).

### Signal builder

**Implémenté (Phase 11)** : `src/signals/volume_shock.py`

| Fonction | Comportement |
|----------|--------------|
| `compute_volume_shock_features` | `volume_z_20`, `volume_z_60`, `range_compression_20`, `return_abs_z_20` |
| `build_volume_shock_events(..., variant=...)` | 4 variantes pré-enregistrées (z≥2.0 ; compression range z≤−1.0 ; \|ret\| z≤−1.0) |

Paramètres figés : `z_threshold=2.0`, lookbacks 20/60, ticker `BTC`.

### Script

**Implémenté** : `scripts/event_study_volume_shock.py` → JSON sous `reports/research_runs_phase11/`

| Élément | Détail |
|---------|--------|
| TAG | `volume_shock` |
| Args | `add_common_event_study_args` + `--variant` / `--run-all-variants` |
| Métriques | `return`, `realized_vol`, `max_drawdown` ; fenêtres `post_1/3/7` |
| Tests | `tests/test_signals_volume_shock.py` |

### Test placebo

| Placebo | Protocole |
|---------|-----------|
| Primaire | Bootstrap 200 tirages uniformes (`run_event_study_pipeline`) |
| Shift | `shift_events_in_time` +30j |
| Shuffle | `shuffle_labels` sur les retours post_3 par événement |
| Garde-fou G2 | Si >30 % des candles → verdict **`blocked`** |

### Rejet attendu

- Distribution post-event **indistinguable** du placebo sur `return` post_3/post_7.
- Verdict : **`not supported, move on`**.
- Objection documentée : volume Kraken/Binance ≠ volume global ; sur-ajustement du seuil z.

### Effort estimé

**M — 2 à 3 jours** : signal + script + tests unitaires + un run 365d + leaderboard.

---

## 3. P9-SC-001-PR — Expansion supply stablecoins (z≥1,0, pré-enregistré)

### Intuition

Reprendre P9-SC-001 avec un seuil abaissé **avant** le run artifact principal,
pour sortir du statut `blocked` (0 events à z≥1,5 en Phase 6).

> **Note méthodo :** le probe z=1,0 du `RUN_LOG_V2` (12 events, BH 1/5 sur une
> cellule) est **exploratoire** — ne pas le promouvoir sans ce pré-enregistrement
> et un artifact dédié Phase 11.

### Dataset

| Champ | Valeur |
|-------|--------|
| Rows supply | DefiLlama stablecoin supply journalier (`total_mcap`, `timestamp`) |
| Rows prix | OHLC BTC (Binance public) |
| Fenêtre | 365 j (aligné Phase 6) |
| Horizon | `post_7` (hypothèse d’origine backlog) |

### Collector nécessaire

Existant : `src/data/collectors/defillama.py` → `fetch_stablecoin_supply()`  
Cache : `data/collector_cache/defillama.json`

### Signal builder

Existant : `src/signals/stablecoin_supply.py` → `build_stablecoin_supply_events()`  
Paramètres figés Phase 11 : `direction=high`, `z_threshold=1.0`, `lookback=180` (défaut script).

### Script à créer

**Aucun** — utiliser :

```text
python scripts/event_study_stablecoins.py \
  --days 365 \
  --z-threshold 1.0 \
  --ohlc-source binance-public \
  --output-json reports/research_runs_v2/stablecoins_z10_365d.json
```

Documenter dans le JSON : `preregistration_id: P9-SC-001-PR`, seuil 1.0, date de gel.

### Test placebo

| Placebo | Protocole |
|---------|-----------|
| Primaire | Bootstrap 200 (défaut harness) |
| Interprétation | Si BH rejette une cellule mais placebo p ≈ baseline → **`weak evidence`** max |

### Rejet attendu

- Placebo indistinguable malgré 12 events (probe Phase 6).
- Verdict probable : **`weak evidence`** ou **`not supported, move on`** après FDR.
- Objection : seuil arbitraire ; colinéarité régime bull 2020–21 ; pas de validation OOS.

### Effort estimé

**S — 0,5 jour** : note de pré-enregistrement + run + leaderboard (pas de nouveau module).

---

## 4. P9-OC-041 — Congestion gas Ethereum (fast gwei z-high)

### Intuition

Une congestion réseau ETH (gas élevé) pourrait coïncider avec stress ou rotation
risk-on/off sur ETH/BTC — testable en daily, sans exécution on-chain.

### Dataset

| Champ | Valeur |
|-------|--------|
| Rows gas | `{timestamp, fast_gwei}` journalier |
| Rows prix | OHLC ETH (ticker défaut script) |
| Prérequis | **≥181** rows dans `etherscan_gas_history.json` |
| Horizon | `post_7` (backlog) ; cellules standard 5 |

### Collector nécessaire

| Composant | Module / fichier |
|-----------|------------------|
| Snapshot | `src/data/collectors/etherscan.py` → `fetch_gas_oracle()` |
| Historique append | `data/collector_cache/etherscan_gas_history.json` |
| Clé API | `ETHERSCAN_API_KEY` (optionnelle mais recommandée) |

**Plan seed Phase 11 (obligatoire avant run `--use-cache-only`) :**

1. Boucle quotidienne 181+ jours **ou** import CSV contrôlé dans le format cache documenté [`DATA_SOURCES.md`](DATA_SOURCES.md).
2. Vérifier `len(daily) >= 181` avant event study.

### Signal builder

Existant : `src/signals/eth_gas_congestion.py` → `build_eth_gas_congestion_events()`  
Défauts : `z_threshold=1.5`, `lookback=180`.

### Script à créer

**Aucun** — utiliser :

```text
python scripts/event_study_eth_gas.py \
  --days 365 \
  --ohlc-source binance-public \
  --output-json reports/research_runs_v2/eth_gas_365d.json
```

(Premiers runs sans cache complet : append snapshot ; ne pas fabriquer de données.)

### Test placebo

| Placebo | Protocole |
|---------|-----------|
| Primaire | Bootstrap 200 sur timestamps alignés |
| Rejet infra | Si `<181` rows → **`blocked`** (règle Phase 6 inchangée) |

### Rejet attendu

- Reste **`blocked`** si seed non fait.
- Si history OK : clusters week-end / NFT mint season → effet non causal ; **`weak evidence`** ou **`not supported`**.
- Objection : oracle = snapshot historique incomplet sans backfill API officiel.

### Effort estimé

**M — 1 à 2 jours** (majorité : seed cache honnête + runs ; code déjà présent).

---

## 5. P9-CA-037 — 3ᵉ vendredi / expiry mensuelle (calendrier pur)

### Intuition

Effet calendaire type « expiry » (literature equity) testé comme **nullité
structurelle** sur crypto — **sans** prétendre à des données options Deribit.

### Dataset

| Champ | Valeur |
|-------|--------|
| Rows prix | OHLC journalier BTC |
| Rows événements | 3ᵉ vendredi de chaque mois (dérivé timestamps OHLC) |
| Fréquence | ~12 events/an |
| Horizon | `post_1`, `post_3` |

### Collector nécessaire

**Aucun** — `src/signals/options_expiry.py` → `build_monthly_options_expiry_events()`.

### Signal builder

Module existant : `src/signals/options_expiry.py` (calendrier pur, pas d’OI).

### Script à créer

**Aucun** — utiliser :

```text
python scripts/event_study_deribit_expiry.py \
  --days 730 \
  --ohlc-source binance-public \
  --output-json reports/research_runs_v2/deribit_expiry_730d.json
```

(Le nom du script est historique ; **aucun feed Deribit** n’est requis.)

### Test placebo

| Placebo | Protocole |
|---------|-----------|
| Primaire | Bootstrap 200 (défaut) |
| Secondaire | Run comparatif documenté : vendredis **non** 3ᵉ du mois (à ajouter comme note ou flag futur `placebo_friday`) |

### Rejet attendu

- **`not supported, move on`** — pas de gamma sans OI ; effet equity non transférable.
- BH 0/5 attendu ; sert de **contrôle positif méthodologique** (hypothèse faible a priori).

### Effort estimé

**S — 0,5 jour** : run 730d + leaderboard.

---

## Ordre d’exécution Phase 11 suggéré

1. **P9-CA-032** et **P9-CA-037** — valider la chaîne calendrier sans dépendance externe.
2. **P9-SC-001-PR** — après écriture d’une ligne de pré-enregistrement (seuil 1.0) dans le run log.
3. **P9-MS-023** — seul lot nécessitant nouveau code applicatif.
4. **P9-OC-041** — en parallèle du seed gas si long ; ne pas bloquer les items 1–3.

Clôture : `python reports/_build_leaderboard.py --v2` et mise à jour
`reports/research_runs_v2/RUN_LOG_V2.md`.

## Hypothèses backlog « implement now » volontairement reportées

| ID | Raison du report |
|----|------------------|
| P9-AT-011 / 012 | Wikipedia BTC déjà Phase 6 (weak) ; ETH = doublon attention sans gain méthodo immédiat |
| P9-MS-021 | Variante week-end → famille **calendar_weekend** rejetée |
| P9-MS-025 / 022 | Redondant avec MS-023 pour une seule place microstructure OHLC |
| P9-OC-042 | Mempool BTC : collector **à créer** (effort > budget top 5) |
| P9-OC-048 | TVL ETH : bon candidat Phase 12 (signal + script neufs) |
| P9-MS-028 | Funding perp : turnover 8h + surface futures hors scope spot read-only |

## Références

- [`HYPOTHESIS_BACKLOG_PHASE_9.md`](HYPOTHESIS_BACKLOG_PHASE_9.md) — catalogue 100 idées
- [`reports/PHASE_3_VS_PHASE_6.md`](../reports/PHASE_3_VS_PHASE_6.md)
- [`reports/ALPHA_RESEARCH_LEADERBOARD_V2.md`](../reports/ALPHA_RESEARCH_LEADERBOARD_V2.md)
- [`reports/research_runs_v2/RUN_LOG_V2.md`](../reports/research_runs_v2/RUN_LOG_V2.md)
- [`ALTERNATIVE_ALPHA_PIPELINE.md`](ALTERNATIVE_ALPHA_PIPELINE.md)
- [`DATA_SOURCES.md`](DATA_SOURCES.md)
- [`SIGNAL_REJECTION_POLICY.md`](SIGNAL_REJECTION_POLICY.md)
