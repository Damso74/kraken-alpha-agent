# Qualité — kraken-alpha-agent

---

## Tests

| Métrique | Valeur (2026-05-21) |
|----------|---------------------|
| Tests collectés | **894** |
| Fichiers test | 123 (`tests/test_*.py`) |
| Commande | `python -m pytest -q` |
| Durée locale | ~130 s (Windows, venv) |

**Note :** Le README historique citait « 232 tests » — chiffre obsolète avant l’expansion du pipeline recherche phases 16–30.

### Fixtures

- `tests/conftest.py` — env safe (clés vides, mode dry_run)
- `tests/conftest_bot.py` — fixtures bot/backtest

### Modules à couverture indirecte

Pas de tests unitaires dédiés aujourd’hui pour : `src/main.py`, `src/llm_explainer.py`, `src/pnl.py`, `src/dashboard/app.py`, `src/signals/btc_mempool.py`.

---

## Lint

```powershell
.\.venv\Scripts\Activate.ps1
ruff check src tests scripts
```

Config : `pyproject.toml` — Ruff, line-length 100, Python 3.11.

---

## CI

Workflow : `.github/workflows/ci.yml`

- Python 3.11
- `pip install -r requirements.txt`
- `KRAKEN_CLI_TRANSPORT=mock`
- `python -m pytest -q`

Pas de secrets GitHub requis. Pas d’appels Kraken.

---

## Politique secrets

| Règle | Détail |
|-------|--------|
| `.env` | Gitignored — jamais committer |
| `.env.example` | Placeholders vides uniquement |
| Logs | `src/logger.py` masque `KRAKEN_API_KEY`, `KRAKEN_API_SECRET`, `FEATHERLESS_API_KEY` |
| Audit export | `scripts/export_audit_bundle.py` redact secrets |
| Live | Triple opt-in : `TRADING_MODE=live` + `LIVE_TRADING=true` + `ALLOW_LIVE_ORDERS=true` |

**Gap connu (P2) :** les clés `KRAKEN_FUTURES_*` ne sont pas encore dans la liste de masquage logger — ne pas logger leurs valeurs manuellement.

---

## Fichiers protégés

Modifications interdites sans justification explicite :

- `config.yaml`
- `src/execution.py`, `src/risk.py`, `src/futures_kraken_cli.py`
- `web/`

---

## Makefile (raccourcis)

```powershell
make test      # pytest -q
make lint      # ruff check
make collect   # pytest --collect-only -q
```

Sur Windows sans `make` : utiliser les commandes pytest/ruff directement.

---

## Avant chaque commit

1. `python -m pytest -q` — doit rester vert
2. Vérifier qu’aucun secret n’est staged : `git diff --cached`
3. Ne pas committer `data/`, `.env`, rapports d’exécution locaux non demandés

---

## Anti-curve-fit (recherche)

Walk-forward avec filtre OOS strict :

- `test_pnl_usd >= 0`
- `test_win_rate >= 50%`
- `trades_count >= 30`

Si zéro config survive → conserver config actuelle, documenter dans `docs/METHODOLOGY.md`.

Voir `AGENTS.md` et `docs/DECISIONS.md`.
