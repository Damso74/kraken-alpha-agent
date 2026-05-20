# Paper Daemon — Phase 19

**Date :** 2026-05-20

## Composants

- `src/bot/state_store.py` — persistence fichier
- `src/bot/daemon_loop.py` — boucle sûre + lock
- `src/bot/daily_report.py` — rapport quotidien
- `scripts/run_paper_daemon.py` — mode once/loop
- `scripts/generate_paper_daily_report.py`

## État persisté

`reports/paper_daemon_state/` (gitignored runtime state OK in reports for demo)

## Mode par défaut

`--mode once` — pas de boucle infinie sans flag explicite.
