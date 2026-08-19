# Phase 10 — Observation paper (design)

> ## ⚠ Design jamais implémenté — ne pas chercher ses artefacts
>
> **Statut au 2026-08-19 : `design_only`.** Ce document décrit une architecture
> qui n'a jamais été branchée. Concrètement :
>
> - `src/research/paper_simulator.py` n'est importé par **aucun** module de
>   production — seulement par `tests/`.
> - Les répertoires `data/paper_observation/` et `reports/paper_observation/`
>   (sans suffixe) **n'existent pas**, et les rapports hebdomadaires `WEEK_*.md`
>   décrits plus bas n'ont jamais été produits.
> - Les gates G1 à G4c décrits ici comme actifs ne sont appliqués par aucun code
>   en exécution.
>
> L'observation réellement construite est une **autre** implémentation, celle des
> phases 28 à 30 : `src/bot/overlay_observation_engine.py` →
> `reports/paper_observation_phase28/`. Elle non plus n'a jamais tourné en
> forward (1 barre au 2026-05-21, 0 depuis) et elle est désormais **archivée** —
> voir `reports/PHASE31_FINAL_VERDICT.md` et l'ADR-012 de `docs/DECISIONS.md`.
>
> Ce document est conservé comme trace de conception, pas comme documentation
> d'un système existant.

> Système **paper-only** pour observer un signal alternatif *après* les
> gates de recherche (G0–G4), sans ordre exchange, sans clé privée, sans
> profil live, sans import de `src.execution`, `src.risk` ou
> `src.futures_kraken_cli`. Ce document est un **design** — il ne branche
> rien au moteur de trading existant.

## TL;DR (1 paragraphe)

L'observation paper est la **couche 6** du pipeline alpha alternatif :
une fois qu'un signal a survécu placebo + Benjamini–Hochberg, robustesse,
expectancy nette post-frais, OOS et contrôles de concentration/régime,
on l'enregistre dans un **journal de signaux**, on simule des **positions
fictives** avec frais/spread/slippage pessimistes, et on produit un
**verdict hebdomadaire** (`observe` / `degrade` / `reject`). Aucun appel
Kraken write, aucun `TRADING_MODE=paper` du CLI, aucune modification de
`config.yaml`. Le module optionnel
[`src/research/paper_simulator.py`](../src/research/paper_simulator.py)
implémente uniquement l'arithmétique de coûts et les barres de verdict —
pas de réseau, pas de subprocess.

## Ce que « paper » signifie ici (et ce que ce n'est **pas**)

| Terme repo | Signification | Utilisé en Phase 10 ? |
|------------|---------------|------------------------|
| **Observation paper** (ce doc) | Simulation locale déterministe, journal JSONL, positions fictives | **Oui** — objet du design |
| `TRADING_MODE=paper` + `kraken paper *` | Moteur paper Kraken CLI (`src/execution.py`) | **Non** — hors scope, clés requises |
| `dry_run` / agent loop | Pipeline production xStocks/crypto | **Non** — interdit d'importer |

Confusion volontairement évitée : l'observation paper **n'est pas** un
pré-live sur venue. C'est une **forward observation read-only** alimentée
par OHLC public et timestamps de signaux déjà validés en recherche.

## Philosophie

| Principe | Implication |
|----------|-------------|
| **Paper = récompense méthodologique** | Seuls les signaux ayant passé G0–G4 entrent en observation ; le refus reste la norme |
| **Coûts pessimistes** | Barre alignée sur [`SIGNAL_REJECTION_POLICY.md`](SIGNAL_REJECTION_POLICY.md) : taker 40 bps/jambe, spread + slippage en sus |
| **Journal append-only** | Chaque décision porte un `reason_code` explicite — pas de rétro-ingénierie silencieuse |
| **Verdict hebdo honnête** | `reject` est un output valide ; `observe` ne signifie pas « promouvoir au live » |
| **Séparation stricte** | Aucun import execution / risk / futures ; aucune écriture dans `config.yaml` |

Ce design **ne garantit aucune rentabilité**. Il mesure si un edge
statistique *survit* à une exécution fictive conservatrice sur une
fenêtre forward courte.

---

## Position dans le pipeline

```
  Hypothèse formulée
        │
        ▼
  [G0] Puissance & données          ← event study / collectors
        │
        ▼
  [G1] Placebo + BH-FDR             ← scripts event_study_*.py
        │
        ▼
  [G2] Robustesse & turnover
        │
        ▼
  [G3] Expectancy nette post-frais
        │
        ▼
  [G4] Out-of-sample
        │
        ▼
  [G4b] Concentration & régime      ← barres documentées ci-dessous
        │
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  PHASE 10 — OBSERVATION PAPER (ce document)                 │
  │  journal → positions fictives → coûts → verdict hebdomadaire │
  └─────────────────────────────────────────────────────────────┘
        │
        ▼
  [G5] Triple opt-in live           ← hors scope ; jamais auto-déclenché
```

Un signal **n'entre jamais** en observation paper tant que la case
« éligible » n'est pas cochée sur **tous** les critères de la section
suivante.

---

## Pré-requis d'entrée (gates cumulatifs)

Reprenant et **durcissant** [`SIGNAL_REJECTION_POLICY.md`](SIGNAL_REJECTION_POLICY.md)
pour le démarrage paper :

| Gate | Critère | Échec → `reason_code` |
|------|---------|------------------------|
| G0 | ≥ **5** événements alignés (≥ **10** pour `exchange_status`) | `ELIG_G0_FAIL_EVENTS` |
| G1a | ≥ 1 cellule `(metric, window)` rejette H0 sous **BH-FDR α=0,05** | `ELIG_G1_FAIL_BH` |
| G1b | P-value empirique placebo `< 0,05` sur la cellule de référence | `ELIG_G1_FAIL_PLACEBO` |
| G2a | Jackknife : retrait du plus gros événement ne inverse pas le signe du mean `post_7` ; chute `|mean|` ≤ **50 %** ; hit-rate reste ≥ **50 %** | `ELIG_G2_FAIL_ROBUSTNESS` |
| G2b | Ratio `events / candles` ≤ **0,30** ; ≤ **1** rotation complète/jour en moyenne | `ELIG_G2_FAIL_TURNOVER` |
| G3 | `mean_return_brut_post_7 − round_trip_taker ≥ 0` avec round-trip taker **0,80 %** (40+40 bps) | `ELIG_G3_FAIL_COST_DOMINANT` |
| G4 | Même signal + seuils sur hold-out / walk-forward : survie BH **ou** p empirique `< 0,05` sur le test seul | `ELIG_G4_FAIL_OOS` |
| G4b | Concentration : aucun événement ne contribue > **50 %** du PnL agrégé simulé ; aucun pair ne drive > **70 %** des trades | `ELIG_FAIL_CONCENTRATION` |
| G4c | Régime : effet de même signe dans ≥ **2** terciles de vol réalisée (split sur train) | `ELIG_FAIL_REGIME` |

**Passage** : tous les codes ci-dessus absents → `ELIG_PASS_ALL`.

> Les verdicts `weak evidence`, `not supported, move on` et `blocked`
> du leaderboard **interdisent** l'observation paper sans exception.

Implémentation de référence (pure fonction, sans I/O) :
[`check_paper_eligibility()`](../src/research/paper_simulator.py).

---

## Architecture logique

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Entrées (read-only)                                                     │
│  • JSON event study : reports/research_runs/<signal>_<window>.json       │
│  • OHLC journalier public : src/crypto_ohlc_rest (fetch hors simulateur) │
│  • Timestamps signal : src/signals/ (déjà produits par les scripts)    │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Eligibility gate                                                        │
│  check_paper_eligibility(EligibilityInput) → EligibilityReport           │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ eligible == True
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Signal journal (append-only JSONL)                                      │
│  data/paper_observation/<signal_id>/journal.jsonl                        │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Paper simulator (stdlib, déterministe)                                  │
│  src/research/paper_simulator.py                                         │
│  • PaperCostModel (maker/taker/spread/slippage)                          │
│  • simulate_round_trip() → PaperTradeResult                              │
│  • compute_weekly_verdict() → WeeklyVerdict                              │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Artefacts hebdomadaires                                                 │
│  reports/paper_observation/<signal_id>/WEEK_<ISO_week>.md                │
│  reports/paper_observation/<signal_id>/WEEK_<ISO_week>.json              │
└──────────────────────────────────────────────────────────────────────────┘
```

### Contrat de sécurité (identique à `src/research/`)

| Règle | Détail |
|-------|--------|
| Read-only venue | Aucun ordre, aucune clé Kraken |
| Stdlib dans le simulateur | Pas de pandas/numpy |
| Déterministe | Même entrée → même sortie ; pas de RNG dans le simulateur |
| Pas de mutation production | Interdit : `config.yaml`, profils `live_*`, agent loop |
| Imports interdits | `src.execution`, `src.risk`, `src.futures_kraken_cli`, `src.kraken_cli` |

---

## Journal de signaux

Fichier : `data/paper_observation/<signal_id>/journal.jsonl` (gitignored
sauf README d'exemple).

Chaque ligne est un objet JSON **immuable** une fois écrit :

```json
{
  "schema_version": 1,
  "ts_utc": 1715990400,
  "signal_id": "calendar_weekend_start",
  "event_type": "paper_open",
  "reason_code": "TRADE_OPEN_LONG",
  "pair": "BTC/USD",
  "direction": "long",
  "reference_price": 67500.0,
  "notional_usd": 100.0,
  "hold_days": 7,
  "cost_model": "taker_conservative",
  "metadata": {
    "source_event_ts": 1715904000,
    "event_study_window": "post_7",
    "eligibility_snapshot": "ELIG_PASS_ALL"
  }
}
```

### Types d'événements (`event_type`)

| `event_type` | Quand | Exemple `reason_code` |
|--------------|-------|------------------------|
| `eligibility_check` | À l'admission | `ELIG_PASS_ALL`, `ELIG_G3_FAIL_COST_DOMINANT` |
| `signal_fire` | Timestamp signal détecté (OHLC aligné) | `SIGNAL_ALIGNED` |
| `paper_open` | Ouverture position fictive | `TRADE_OPEN_LONG` |
| `paper_close` | Clôture au bout de `hold_days` | `TRADE_CLOSE_LONG` |
| `skip` | Signal ignoré (coût, overlap, cooldown) | `SKIP_EDGE_BELOW_COSTS`, `SKIP_OVERLAP` |
| `weekly_verdict` | Agrégat fin de semaine ISO | `WEEKLY_OBSERVE`, `WEEKLY_REJECT` |

### Règles d'écriture

1. **Append-only** — pas de `UPDATE` ; corrections = nouvelle ligne + référence `supersedes`.
2. **Un seul open par pair** — pas de pyramiding ; `SKIP_OVERLAP` si signal concurrent.
3. **Cooldown** — minimum **1 jour** entre deux opens sur le même `signal_id` (évite le sur-comptage calendrier).
4. **Hold fixe** — durée = fenêtre de référence de l'event study (`post_7` par défaut) ; pas de retuning en forward.

---

## Positions fictives

Une position paper est un enregistrement **en mémoire ou JSON snapshot** —
pas une ligne SQLite production, pas un appel `kraken paper`.

| Champ | Description |
|-------|-------------|
| `position_id` | UUID déterministe dérivé de `(signal_id, open_ts, pair)` |
| `pair` | Ex. `BTC/USD` (crypto REST public uniquement en Phase 10) |
| `direction` | `long` seulement (aligné `shorting=false` du moteur principal) |
| `entry_price` | Close OHLC du jour d'alignement |
| `exit_price` | Close OHLC à `open_ts + hold_days` |
| `notional_usd` | Fixe par session paper (défaut **100 USD** fictifs) |
| `gross_return` | `(exit − entry) / entry` |
| `net_return` | `gross_return − round_trip_cost_fraction` |
| `cost_drag` | `round_trip_cost_fraction` (fraction, pas bps) |
| `status` | `open` → `closed` |

Clôture : **market-on-close fictif** au candle de sortie — pas de
intraday, pas de stop-loss dynamique en v1 (simplicité > réalisme).

---

## Modèle de coûts

Aligné sur la politique de rejet G3, **plus pessimiste** que le
simulateur local `fee = size × 0.001` de `src/execution.py` (10 bps —
**ne pas réutiliser** pour valider un signal alternatif).

### Hypothèse par défaut (`PaperCostModel.taker_conservative`)

| Composante | Valeur | Application |
|------------|--------|-------------|
| Frais taker | **40 bps** / jambe | Entrée + sortie |
| Frais maker | **25 bps** / jambe | Scénario alternatif (non défaut) |
| Spread | **10 bps** / jambe | Demi-spread payé à chaque jambe |
| Slippage | **5 bps** / jambe | Fixe, pas de modèle de profondeur |

**Round-trip taker conservateur (défaut)** :

```text
cost = 2 × (40 + 10/2 + 5) bps = 2 × 50 bps = 1,00 % du notional
```

> La barre G3 utilise **0,80 %** (frais seuls). L'observation paper
> applique **1,00 %** pour la simulation forward — marge de sécurité
> explicite.

Fonction : `PaperCostModel.round_trip_cost_fraction(use_taker=True)`.

### Dominance des coûts

**Skip automatique** (`SKIP_EDGE_BELOW_COSTS`) si, au moment du signal :

```text
expected_edge_bps < round_trip_cost_bps
```

où `expected_edge_bps` = mean brut `post_7` de l'event study **figé à
l'admission** (pas recalculé en forward — évite le peeking).

---

## Codes raison (`reason_code`)

Espace de noms stable pour le journal et les rapports hebdo.

### Éligibilité

| Code | Signification |
|------|---------------|
| `ELIG_PASS_ALL` | Tous les gates G0–G4c passés |
| `ELIG_G0_FAIL_EVENTS` | Trop peu d'événements |
| `ELIG_G1_FAIL_BH` | Aucun rejet BH-FDR |
| `ELIG_G1_FAIL_PLACEBO` | Placebo non significatif |
| `ELIG_G2_FAIL_ROBUSTNESS` | Jackknife / hit-rate |
| `ELIG_G2_FAIL_TURNOVER` | Signal trop fréquent |
| `ELIG_G3_FAIL_COST_DOMINANT` | Edge brut ≤ frais taker 0,80 % |
| `ELIG_G4_FAIL_OOS` | Hold-out raté |
| `ELIG_FAIL_CONCENTRATION` | Un trade ou pair domine |
| `ELIG_FAIL_REGIME` | Effet absent sur ≥ 2 terciles vol |

### Trading fictif

| Code | Signification |
|------|---------------|
| `SIGNAL_ALIGNED` | Timestamp mappé sur candle daily |
| `TRADE_OPEN_LONG` | Position fictive ouverte |
| `TRADE_CLOSE_LONG` | Position fictive clôturée |
| `SKIP_EDGE_BELOW_COSTS` | Edge attendu < coûts |
| `SKIP_OVERLAP` | Position déjà ouverte |
| `SKIP_COOLDOWN` | Délai minimum non respecté |
| `SKIP_NOT_ELIGIBLE` | Signal retiré du set éligible |

### Verdict hebdomadaire

| Code | Signification |
|------|---------------|
| `WEEKLY_OBSERVE` | PnL net > 0, coûts non dominants, concentration OK |
| `WEEKLY_DEGRADE` | PnL net ≤ 0 mais ≥ −0,5 × coûts cumulés (edge fragile) |
| `WEEKLY_REJECT` | PnL net < −0,5 × coûts **ou** concentration **ou** < 2 trades clos |
| `WEEKLY_INSUFFICIENT_ACTIVITY` | Semaine sans clôture (pas de verdict force) |

---

## Verdict hebdomadaire

Produit chaque **lundi 00:00 UTC** (ou à la demande via script futur
`scripts/paper_observation_report.py` — **non implémenté** en Phase 10
design-only).

Entrée : liste des `PaperTradeResult` clôturés dans la semaine ISO +
métadonnées d'éligibilité.

Algorithme (`compute_weekly_verdict`) :

1. Si `n_closed < 2` → `WEEKLY_INSUFFICIENT_ACTIVITY` (pas de promotion).
2. Calculer `net_pnl_fraction` = somme des `net_return × weight` (poids
   égaux par trade en v1).
3. `cost_drag_ratio` = `sum(cost_drag) / max(|sum(gross_return)|, ε)`.
4. `max_trade_concentration` = part du trade le plus profitable (valeur
   absolue) dans le PnL net total.
5. Verdict :
   - **`WEEKLY_REJECT`** si `net_pnl_fraction < −0.5 × sum(cost_drag)`
     **ou** `max_trade_concentration > 0.50` **ou** un seul trade clos
     avec PnL net négatif > 2× coût.
   - **`WEEKLY_DEGRADE`** si `net_pnl_fraction ≤ 0` mais pas reject.
   - **`WEEKLY_OBSERVE`** si `net_pnl_fraction > 0` **et**
     `cost_drag_ratio < 0.80` **et** concentration OK.

### Interprétation (honnête)

| Verdict | Action |
|---------|--------|
| `WEEKLY_OBSERVE` | Continuer l'observation ; **ne pas** toucher au live |
| `WEEKLY_DEGRADE` | Continuer avec alerte ; revue manuelle des paramètres **a priori** |
| `WEEKLY_REJECT` | **Stop** observation pour ce `signal_id` ; archiver |
| `WEEKLY_INSUFFICIENT_ACTIVITY` | Attendre ; pas de conclusion |

**≥ 4 semaines consécutives `WEEKLY_OBSERVE`** seraient nécessaires
*avant toute discussion* de G5 (triple opt-in) — hors automatisme,
décision humaine documentée.

---

## État actuel du leaderboard (Phase 3 → Phase 10)

D'après [`ALPHA_RESEARCH_LEADERBOARD.md`](../reports/ALPHA_RESEARCH_LEADERBOARD.md)
— **aucun signal n'est éligible** à l'observation paper aujourd'hui :

| Signal | Verdict recherche | Éligible paper ? |
|--------|-------------------|------------------|
| `stablecoin_supply_z_high` | blocked / 0 events | Non — G0 |
| `calendar_weekend_start` | not supported | Non — G1 |
| `exchange_status_major_incident` | not supported (2 events) | Non — G0/G1 |
| `demo_fear_greed_extreme_fear` | weak evidence (demo) | Non — G1 + demo |
| `wikipedia_btc_attention` | blocked (403) | Non — données |
| `eth_gas_congestion` | blocked (API) | Non — données |

Comportement **sain** : Phase 10 est prête architecturalement, vide
opérationnellement.

---

## Artefacts et layout fichiers (proposé)

```text
data/paper_observation/
  README.md                          # git-tracked : explique le dossier gitignored
  <signal_id>/
    journal.jsonl                    # gitignored
    state_snapshot.json              # gitignored — positions ouvertes

reports/paper_observation/
  <signal_id>/
    WEEK_2026-W20.md                 # rapport lisible jury
    WEEK_2026-W20.json               # machine-readable

src/research/
  paper_simulator.py                 # arithmétique pure (optionnel, implémenté)

scripts/                             # FUTUR — hors scope design-only
  paper_observation_run.py           # boucle forward + fetch OHLC
  paper_observation_report.py        # agrège JSONL → verdict hebdo
```

Tout sous `data/paper_observation/` (sauf README) reste **gitignored**.

---

## Script CLI futur (non implémenté)

Esquisse pour une phase ultérieure — **ne pas exécuter** tant que le
design n'est pas revu :

```powershell
# Admission (one-shot, read-only inputs)
python scripts/paper_observation_admit.py `
  --event-study-json reports/research_runs/calendar_730d.json `
  --oos-json reports/research_runs/calendar_730d_oos.json

# Forward tick (cron hebdo / manuel)
python scripts/paper_observation_run.py `
  --signal-id calendar_weekend_start `
  --use-cache-only

# Rapport
python scripts/paper_observation_report.py `
  --signal-id calendar_weekend_start `
  --week 2026-W20
```

Flags obligatoires du futur harness :

- `--use-cache-only` par défaut **True** (pas de HTTP surprise).
- `--notional-usd 100` — montant fictif.
- `--dry-run` — n'écrit pas le journal (inspection stdout).
- **Aucun** `--live`, **aucun** `--place-order`.

---

## Tests (module optionnel)

[`tests/test_paper_simulator.py`](../tests/test_paper_simulator.py) couvre :

- Round-trip taker = **1,00 %** avec le modèle par défaut.
- `check_paper_eligibility` accepte/refuse selon les gates.
- `compute_weekly_verdict` — cas `observe`, `degrade`, `reject`,
  `insufficient_activity`.
- Déterminisme : deux appels identiques → même sortie.

Lancer :

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest tests/test_paper_simulator.py -q
```

---

## Ce que Phase 10 n'autorise **pas**

- Modifier `config.yaml` ou créer un profil `live_*` / `micro_live_*`.
- Appeler `kraken paper buy/sell`, `kraken order`, ou tout endpoint authentifié.
- Importer `src.execution`, `src.risk`, `src.futures_kraken_cli`.
- Présenter un verdict `WEEKLY_OBSERVE` comme preuve de PnL live futur.
- Contourner G4 OOS en « testant en paper live » sur venue.
- Réutiliser le fee 10 bps du simulateur xStocks paper pour valider un signal alternatif.

---

## Références croisées

- [`ALTERNATIVE_ALPHA_PIPELINE.md`](ALTERNATIVE_ALPHA_PIPELINE.md) — couche 1–5
- [`SIGNAL_REJECTION_POLICY.md`](SIGNAL_REJECTION_POLICY.md) — gates G0–G5
- [`METHODOLOGY.md`](METHODOLOGY.md) — discipline OOS walk-forward
- [`ALPHA_RESEARCH_LEADERBOARD.md`](../reports/ALPHA_RESEARCH_LEADERBOARD.md) — état Phase 3
- Code : [`src/research/paper_simulator.py`](../src/research/paper_simulator.py),
  [`scripts/_event_study_common.py`](../scripts/_event_study_common.py)
