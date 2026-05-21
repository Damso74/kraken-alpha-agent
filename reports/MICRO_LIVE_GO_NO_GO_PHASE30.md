# Micro-live GO/NO-GO — Phase 30

**Verdict : NO-GO**

## Raisons

1. Phase 30 est **observation ops cron only** — aucun chemin live ajouté.
2. Forward window encore **T0 / début cron** — règle 2–4 semaines non satisfaite.
3. Phase 27 : 0 `validation_candidate` sur overlays ETH 4h.
4. Compte PEDSL-CY : xStocks spot/perps API-blocked (inchangé).
5. Décision Phase 30 : **`ready_for_vps_cron`** — micro-live review **interdite**.

## Conditions pour revue future (Phase 31+, pas avant 14j cron)

- ≥14 jours observation paper sans kill criteria (cron 4h VPS).
- Shadow : block rate stable, proxies missed upside / avoided drawdown documentés.
- ≥30 shadow rows, ≥5 trades paper par cible.
- Cache derivatives frais (funding + basis ETH 4h).
- Compte non-EU requis pour xStocks compétition (hors scope actuel).

## Action

Installer cron VPS via `reports/PHASE30_VPS_CRON_SETUP.md`. Ne pas armer `micro_live_100eur` ni triple opt-in live.
