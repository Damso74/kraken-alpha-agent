# Phase 16 — Next steps

**Date :** 2026-05-19

## Recommandation : Phase 17 (pas lancée)

Phase 16 validée côté code/tests. Prochaine étape suggérée :

1. **Peupler caches 4h/1h** localement (hors git) pour tournoi multi-TF complet — extension `binance_public` ou script fetch manuel.
2. **Phase 17** — selon plan parent (non exécutée dans cette session).
3. Re-run tournoi : `--timeframes 1d 4h 1h` une fois caches disponibles.
4. Walk-forward OOS si tuning demandé (anti-curve-fit policy AGENTS.md).

## Blockers restants

| Blocker | Impact |
|---------|--------|
| Caches 4h/1h absents | Runs intraday → `blocked_data` |
| SOL daily absent | Asset SOL exclu du tournoi local |
| 0 paper_candidate sur daily | Attendu sans post-hoc tuning |

## Non-goals (respectés)

- Pas de live trading
- Pas de merge master
- Pas de deploy Vercel
- Pas de micro_live_candidate (Phase 20)
