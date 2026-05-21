# Micro-live GO/NO-GO — Phase 29

**Verdict : NO-GO**

## Raisons

1. Phase 29 est **observation ops only** — aucun chemin live ajouté.
2. Forward window **T0** (< 1 jour de loop) — règle 2–4 semaines non satisfaite.
3. Phase 27 : 0 `validation_candidate` sur overlays ETH 4h.
4. Compte PEDSL-CY : xStocks spot/perps API-blocked (inchangé).
5. Décision Phase 29 : **`continue_observation`** — micro-live review **interdite**.

## Conditions pour revue future (Phase 31+, pas avant 14j)

- ≥14 jours observation paper sans kill criteria.
- Shadow : block rate stable, proxies missed upside / avoided drawdown documentés.
- ≥30 shadow rows, ≥5 trades paper par cible.
- Cache derivatives frais (funding + basis ETH 4h).
- Compte non-EU requis pour xStocks compétition (hors scope actuel).

## Action

Lancer loop 14j (utilisateur) via `reports/PHASE30_OBSERVATION_PLAYBOOK.md`. Ne pas armer `micro_live_100eur` ni triple opt-in live.
