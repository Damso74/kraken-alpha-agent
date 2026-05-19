# Réalisme économique — modèle de coûts recherche (Phase 7)

**Date (UTC) :** 2026-05-19  
**Modules :** `src/research/cost_model.py`, `src/research/tradeability.py`  
**Portée :** recherche read-only uniquement — **aucun** branchement live.

---

## Objectif

Les event studies (`src/research/event_study.py`) produisent des retours **bruts**.
Ce modèle soustrait des frais Kraken **pessimistes** et classe la
« tradeability » en verdicts explicites. Un rejet ici est un **succès**
de filtre, pas un échec du pipeline.

---

## Hypothèses de coûts (compte spot Kraken, petit notionnel)

| Composante | Valeur par défaut | Notes |
|------------|-------------------|-------|
| Maker | **0,25 %** par jambe | Scénario optimiste d'exécution |
| Taker | **0,40 %** par jambe | **Défaut** pour la barre G3 |
| Round-trip taker/taker | **0,80 %** | Achat + vente taker |
| Spread / slippage — majors | **0,05 % – 0,20 %** | Défaut pessimiste : **0,20 %** |
| Spread / slippage — alts | **0,20 % – 0,60 %** | Défaut pessimiste : **0,60 %** |

**Total pessimiste typique (major, taker/taker) :** 0,80 % + 0,20 % = **1,00 %**  
**Total pessimiste typique (alt, taker/taker) :** 0,80 % + 0,60 % = **1,40 %**

Ces chiffres sont **plus conservateurs** que le `fee = 0,001` (10 bps) parfois
utilisé dans la simulation paper locale (`src/execution.py`). Ne pas mélanger
les deux pour valider un signal alternatif.

---

## API (stdlib uniquement)

| Fonction | Rôle |
|----------|------|
| `estimate_round_trip_cost(...)` | Décompose frais + slippage → `RoundTripCost.total_pct` |
| `compute_net_event_return(gross, cost)` | `gross − cost` (fractions) |
| `classify_tradeability(gross, ...)` | Verdict + raison + flag `reject` |
| `reject_if_cost_dominated(gross, ...)` | Tuple `(reject, reason, verdict)` pour G3 |
| `summarize_cost_assumptions()` | Snapshot JSON des constantes |

---

## Verdicts de tradeability

| Verdict | Signification | Live ? |
|---------|---------------|--------|
| `economically impossible` | Brut < **0,50 %** par trade (suspect) ou incohérent | **Non** |
| `cost dominated` | Brut positif mais net ≤ 0 après coûts | **Non** |
| `research only` | Net positif mais marge fine ou gates G2/G4 incomplets | **Non** |
| `candidate for paper observation` | Net > coûts, N ≥ 5, BH + OOS documentés | **Non** (paper **observation** seulement) |

**Aucun verdict n'est « live-ready ».** Le triple opt-in (`TRADING_MODE`,
`LIVE_TRADING`, `ALLOW_LIVE_ORDERS`) reste obligatoire et hors scope.

---

## Seuils de rejet (alignés G3)

1. **Brut suspect :** `gross_mean < 0,005` (0,50 % par trade) → rejet automatique.
2. **Edge illusoire :** `gross_mean − round_trip_cost ≤ 0` → `cost dominated`.
3. **Promotion :** même `candidate for paper observation` n'autorise ni
   `config.yaml`, ni profil live, ni ordre réel.

---

## Exemple d'utilisation (recherche)

```python
from src.research.cost_model import estimate_round_trip_cost, compute_net_event_return
from src.research.tradeability import classify_tradeability, reject_if_cost_dominated

gross_mean = 0.012  # 1.2 % brut moyen post-event (post_7)
cost = estimate_round_trip_cost(liquidity_tier="major", pessimistic=True)
net = compute_net_event_return(gross_mean, cost)
assessment = classify_tradeability(
    gross_mean,
    n_events=12,
    bh_supported=True,
    oos_confirmed=False,
)
reject, reason, verdict = reject_if_cost_dominated(gross_mean)
```

---

## Références

- [`docs/SIGNAL_REJECTION_POLICY.md`](../docs/SIGNAL_REJECTION_POLICY.md) — gates G0–G5
- [`docs/ALTERNATIVE_ALPHA_PIPELINE.md`](../docs/ALTERNATIVE_ALPHA_PIPELINE.md) — architecture
- Tests : `tests/test_research_cost_model.py`, `tests/test_tradeability.py`
