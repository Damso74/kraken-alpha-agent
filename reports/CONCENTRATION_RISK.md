# Concentration risk — Phase 8 (Agent 19)

**Date (UTC) :** 2026-05-19  
**Module :** `src/research/concentration.py`  
**Tests :** `tests/test_concentration.py`

---

## Objectif

Mesurer si un résultat agrégé d’event study (mean forward return, PnL proxy,
hit-rate) est **porté** par un petit nombre d’événements ou par un mois
calendaire. Un signal « supported » sous BH-FDR qui échoue ici ne passe pas
la barre G2 (robustesse) de [`docs/SIGNAL_REJECTION_POLICY.md`](../docs/SIGNAL_REJECTION_POLICY.md).

---

## Seuils canoniques

| Règle | Seuil | Constante |
|-------|-------|-----------|
| Un seul événement | part **> 20 %** du total absolu | `SINGLE_EVENT_HIGH_RISK_SHARE = 0.20` |
| Top 3 événements | part combinée **> 50 %** | `TOP_N_HIGH_RISK_SHARE = 0.50`, `TOP_N_DEFAULT = 3` |
| Un mois calendaire | part **> 40 %** | `MONTH_HIGH_RISK_SHARE = 0.40` |
| Puissance | **< 5** événements | `DEFAULT_MIN_EVENTS = 5` (aligné G0) |

Les parts utilisent `sum(abs(contribution_i))` au dénominateur pour que des
gains/pertes opposés ne masquent pas une dominance par magnitude.

Comparaisons **strictes** (`>`), pas `>=` : exactement 20 % / 50 % / 40 %
n’est pas classé « high risk ».

---

## API

| Fonction | Rôle |
|----------|------|
| `max_single_event_contribution` | Part max d’un événement |
| `top_n_events_contribution` | Part cumulée des *n* plus grands (défaut 3) |
| `max_month_contribution` | Part max par mois `YYYY-MM` |
| `event_count_sufficiency` | `n_events >= min_events` |
| `classify_concentration_risk` | Verdict agrégé + raisons textuelles |

### Verdicts (`classify_concentration_risk`)

| Verdict | Condition |
|---------|-----------|
| `insufficient_evidence` | `len(contributions) < min_events` |
| `high_concentration_risk` | Au moins un seuil de concentration dépassé |
| `acceptable` | Assez d’événements et aucun seuil dépassé |

---

## Exemple d’usage (recherche read-only)

```python
from src.research.concentration import classify_concentration_risk

# per_event_returns : une valeur par événement aligné (ex. post_7)
# event_months : "YYYY-MM" parallèle, ou event_timestamps unix UTC
verdict = classify_concentration_risk(
    per_event_returns,
    event_months=event_months,
)
if verdict.verdict != "acceptable":
    # Documenter le rejet G2 — ne pas promouvoir vers config / live
    print(verdict.verdict, verdict.reasons)
```

---

## Intégration pipeline

```
Event study (G1) → supported ?
        │
        ▼
classify_concentration_risk (G2b)  ← ce module
        │
        ├─ insufficient_evidence → aligné G0 weak evidence
        ├─ high_concentration_risk → rejet manuel G2
        └─ acceptable → poursuivre G3 (frais) / G4 (OOS)
```

Les scripts `event_study_*.py` n’appellent pas encore ce module ; l’intégration
reste manuelle ou scriptée dans les notebooks de recherche.

---

## Contrat technique

- Stdlib uniquement (`math`, `dataclasses`, `datetime` pour les mois).
- Déterministe, sans réseau.
- Aucun import de `src.execution`, `src.risk`, `src.futures_kraken_cli`.

---

## Références

- Politique : [`docs/SIGNAL_REJECTION_POLICY.md`](../docs/SIGNAL_REJECTION_POLICY.md) (section G2b)
- Jackknife leave-one-out (complément manuel) : même doc, section G2
