# Micro-live GO/NO-GO — Phase 28

**Verdict : NO-GO**

## Raisons

1. Phase 28 est **observation-only** — aucun chemin vers live n'est activé.
2. Phase 27 a produit 2 overlays `useful_overlay` (ETH 4h trend_following/ema_crossover + funding_basis) mais **0 validation_candidate**.
3. Compte PEDSL-CY : xStocks spot/perps API-blocked (inchangé).
4. Observation forward nécessite **2–4 semaines** minimum avant toute revue micro-live.
5. OI depth reste experimental (<500 rows gate Phase 27).

## Conditions pour revue Phase 29+

- ≥14 jours d'observation paper sans kill criteria déclenchés.
- Shadow comparison : block rate stable, pas d'upside manqué disproportionné.
- Equity overlay ≥ standalone −5 pp sur fenêtre glissante 30 barres 4h.
- Cache derivatives frais (funding + basis ETH 4h).

## Action

Continuer paper observation. Ne pas armer `micro_live_100eur` ni triple opt-in live.
