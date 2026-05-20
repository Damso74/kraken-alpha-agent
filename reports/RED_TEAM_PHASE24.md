# Red team — Phase 24

## 9 questions

1. **Live / micro-live touched?** Non — cache-only scripts, pas de triple opt-in.
2. **Fichiers interdits modifiés?** Non — `execution.py`, `risk.py`, `futures_kraken_cli.py`, `web/`, `config.yaml` intacts.
3. **Données réseau fetchées?** Non — audit et WF lisent uniquement `data/collector_cache/`.
4. **Historique complet utilisé quand data_ok?** Oui — pas de `--max-bars` dans le script WF Phase 24.
5. **Delta vs Phase 23 cap 500 bars?** 6 entrées ont plus de 500 barres disponibles.
6. **`paper_candidate` émis?** 0 (doit rester 0).
7. **`validation_candidate` crédible?** 1 — chaque cas exige ≥2 holdouts > B&H, DD < B&H, trades ≥8.
8. **Overlays pour sauver un candidat?** Non — WF principal overlay=off; overlay-only flag bloque validation.
9. **Micro-live GO?** Non — compte PEDSL-CY / pas de candidat paper.

## Verdict red team

Phase 24 reste défensive et documentaire. Zéro candidat = succès si motivé.

