# Red team — Phase 28 overlay observation

## Le daemon peut-il envoyer un ordre réel ?

**Non.**

- `run_overlay_observation_daemon_phase28.py` importe uniquement `overlay_observation_engine`, `daemon_loop`, `state_store`.
- Aucun import de `src.execution`, `futures_kraken_cli`, `run_agent_loop`.
- `--observation-only` est `True` par défaut ; les décisions vont dans `decisions.jsonl` / `shadow_comparison.jsonl`.
- Paper fills passent par `ExecutionSimulator` local (Phase 14 bot), pas Kraken CLI.
- Test `test_no_live_imports_in_daemon_script` verrouille l'absence de symboles live.

## Stale data ?

- OHLC : `is_stale_data()` si gap >3j entre bougies.
- Derivatives : si basis cache absent, status `funding_only` → kill config `stale_data=True`.
- Shadow rows enregistrent `funding_z` / `basis_z` pour audit post-hoc.

## Double daemon ?

- Lock file `.daemon.lock` par `state_dir` via `acquire_lock()`.
- Deux stratégies = deux state dirs distincts → locks indépendants.
- `--run-all-targets` acquiert/release lock séquentiellement par cible.

## Fuites clés API ?

- Cache-only default ; pas d'appel réseau dans le chemin observation.
- `state_store` explicite : no secrets.

## Risque résiduel

- Un opérateur pourrait lancer **en parallèle** le daemon Phase 19 (`run_paper_daemon.py`) sur le même asset — hors scope Phase 28 ; documenté comme anti-pattern.
- Supprimer `STOP_OBSERVATION` relance l'observation sans revue humaine — procédure documentée dans KILL_CRITERIA.
