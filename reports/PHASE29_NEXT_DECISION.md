# Phase 29 — Next decision

**Date :** 2026-05-21  
**Branche :** `phase29/observation-ops`

## Décision

### **`continue_observation`**

| Gate | Status |
|------|--------|
| STOP_OBSERVATION absent | OK |
| Kill criteria non déclenchés | OK |
| observation_only=true | OK |
| Sanity pipeline PASS | OK |
| Fichiers sensibles unchanged | OK |
| Micro-live | **NO-GO** (règle 2–4 semaines forward) |

Aucun `fix_required` : le skip `duplicate_candle` au re-run once est comportement attendu.

## Contexte T0

- 1 decision / 1 shadow row par cible (premier cycle Phase 28 déjà exécuté).
- Block rate 0%, equity overlay replay cache : TF 1112 USD, EMA 966 USD vs starting 1000 USD.
- Fenêtre forward insuffisante pour juger missed upside / avoided drawdown — **normal**.

## Options explicites (non retenues)

| Option | Raison |
|--------|--------|
| `fix_required` | Non — STOP absent, pipeline OK |
| `kill_overlay` | Non — kill criteria OK |
| `extend_observation` | Implicite dans continue (loop 14–28j) |
| `micro_live_review_forbidden` | **Oui** — <14j forward, PEDSL-CY blocked, 0 validation_candidate |

---

## Phase 30/31 playbook (préparé, non lancé)

### Loop 14 jours — commandes utilisateur

**Daemon observation (les deux cibles, 4h interval) :**

```powershell
cd c:\Users\credo\Documents\Code_Informatique\Projets-en-cours\kraken-alpha-agent
.\.venv\Scripts\Activate.ps1

python scripts/run_overlay_observation_daemon_phase28.py `
  --run-all-targets --mode loop --interval-seconds 14400 `
  --allow-infinite-loop --cache-only
```

Arrêt propre : `Ctrl+C` (lock libéré). Ne pas supprimer `STOP_OBSERVATION` sans revue.

**Rapport daily (cron manuel ou Task Scheduler) :**

```powershell
python scripts/generate_overlay_observation_report_phase28.py --all-targets
python scripts/aggregate_observation_metrics_phase29.py
```

**Rapport weekly (dimanche ou lundi) :**

```powershell
python scripts/generate_overlay_observation_report_phase28.py --weekly --all-targets
python scripts/aggregate_observation_metrics_phase29.py
```

### Tableaux décision review

#### 7 jours (~42 barres 4h)

| Métrique | Seuil continue | Seuil fix/kill |
|----------|----------------|----------------|
| STOP_OBSERVATION | absent | présent → stop |
| Block rate (30 barres) | ≤ 60% | > 60% → kill |
| Trades paper | ≥ 5 si ≥30 shadow rows | < 5 → kill |
| Incoherent blocks | < 3 | ≥ 3 → kill |
| Equity gap vs standalone | ≥ −5 pp | < −5 pp → kill |
| Stale derivatives | 0 persistant | funding_only persistant → kill |

#### 14 jours (~84 barres 4h)

| Métrique | Continue | Review micro-live |
|----------|----------|-------------------|
| Shadow rows | ≥ 30 | ≥ 60 |
| Missed upside vs avoided DD | documenté | ratio favorable overlay |
| Kill criteria | 0 trigger | any → kill_overlay |
| Micro-live | **NO-GO** | revue **interdite** avant 14j |

#### 28 jours (~168 barres 4h)

| Métrique | Continue obs | Kill overlay | Micro-live |
|----------|--------------|--------------|------------|
| Block rate stable | oui | non | n/a |
| Equity overlay ≥ standalone −5pp | oui | non | prereq only |
| PEDSL-CY xStocks API | blocked | blocked | **NO-GO** |
| validation_candidate historique | 0 | n/a | required |

### Kill criteria rappel

Voir `reports/paper_observation_phase28/KILL_CRITERIA.md` :

- Block rate > 60% sur 30 barres
- < 5 trades après ≥30 shadow rows
- ≥ 3 blocks incohérents (z < 1.5)
- Underperformance rolling < −5 pp
- Stale basis en mode funding_basis
- Flag manuel STOP_OBSERVATION

## Prochaine phase

- **Phase 30** : lancer loop 14j (utilisateur) — voir `reports/PHASE30_OBSERVATION_PLAYBOOK.md`
- **Phase 31** : review 7/14j — voir `reports/PHASE31_REVIEW_CHECKLIST.md`
