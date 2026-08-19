# Qualité — kraken-alpha-agent

> **Audit du 2026-08-19.** Ce document contenait plusieurs affirmations fausses,
> corrigées ici : le nombre de tests, la description de la CI (qui n'avait
> **jamais** exécuté un seul test), la liste des modules non couverts (fausse
> dans les deux sens), et un « gap connu » de masquage de secrets **déjà corrigé
> depuis `cd20a15`**. Voir `reports/PHASE31_FINAL_VERDICT.md`.

---

## Tests

| Métrique | Valeur (2026-08-19) |
|----------|---------------------|
| Tests collectés | **1058** |
| Fichiers test | 126 (`tests/test_*.py`) |
| Commande | `python -m pytest -q` |
| Durée locale | ~3 min (Windows, venv, Python 3.14) |
| Couverture mesurée | **aucune** — voir « Trou connu » ci-dessous |

Le README historique citait « 232 tests » (périmètre hackathon, branche
`master`), puis « 894 » (chiffre figé au 2026-05-21). L'audit de clôture du
2026-08-19 en a ajouté 149, tous liés à un défaut confirmé.

### Fixtures

- `tests/conftest.py` — env safe (clés vides, mode dry_run, transport `mock`)
- `tests/conftest_bot.py` — fixtures bot/backtest

### Modules sans test dédié

Vérifié par `grep` sur `tests/` le 2026-08-19 :

`src/portfolio.py` · `src/market_data.py` · `src/pnl.py` · `src/utils.py` ·
`src/llm_explainer.py` · `src/signals/_stats.py` · `src/signals/options_expiry.py` ·
`src/signals/btc_mempool.py` · `src/data/collectors/_common.py`

`src/portfolio.py` (`record_fill`) et `src/market_data.py` sont sur le chemin
critique exécution/risque : ce sont les deux plus coûteux de la liste.

`src/main.py` et `src/dashboard/app.py`, que ce document listait auparavant
comme non couverts, **le sont** (`tests/test_session_guard.py`,
`tests/test_backtest.py`).

### Trou connu — pas de mesure de couverture

Ni `pytest-cov` ni `coverage` ne sont installés ni configurés. « 1058 tests » ne
dit rien de ce qui est réellement exercé : impossible de savoir quelles branches
de `src/risk.py`, `src/execution.py` ou `src/live_killswitch.py` sont couvertes.
Non corrigé — voir le verdict final pour l'arbitrage.

---

## Lint

```bash
ruff check src tests scripts
```

Config : `pyproject.toml` — line-length 100, target py311, `select = ["E","F","I","B","UP"]`.

`per-file-ignores` : `E402` sur `scripts/*.py`, dont le bootstrap `sys.path`
impose des imports hors tête de fichier.

État au 2026-08-19 : 840 erreurs à l'ouverture de l'audit, 910 corrections
mécaniques appliquées (`--fix`), le reliquat traité au cas par cas. Plusieurs de
ces erreurs signalaient de **vrais défauts** — la boucle no-op de
`overlay_observation_engine.py` était un `B018` ignoré depuis trois mois.

---

## CI

Workflow : `.github/workflows/ci.yml` — Python 3.11, ubuntu-latest.

| Étape | Rôle |
|-------|------|
| `pip install -r requirements.txt` | ruff y est déclaré (il ne l'était pas) |
| `ruff check src tests scripts` | gate lint |
| `bash -n scripts/*.sh` + `shellcheck -S error` | les scripts d'ops n'avaient ni test ni lint |
| `pytest --collect-only -q` | sanity de collecte |
| `pytest -q` | `KRAKEN_CLI_TRANSPORT=mock`, `TRADING_MODE=dry_run` |
| `git diff --exit-code` | **aucun test ne doit réécrire un fichier suivi** |

Pas de secrets GitHub requis. Aucun appel Kraken.

**Historique.** Avant le 2026-08-19 la CI n'avait jamais dépassé l'étape lint :
`ruff` n'était déclaré que dans l'extra `[dev]` de `pyproject.toml` alors que le
workflow installe `requirements.txt`, d'où un `exit 127` (`ruff: command not
found`) sur les deux seuls runs de la branche (`26225708783`, `26225503049`).
Tous les steps suivants étaient `skipped`. Aucun badge, aucune protection de
branche : la situation n'était pas « un gate cassé » mais « aucun gate ».

Le dernier step, `git diff --exit-code`, existe parce que
`scripts/audit_data_backbone_phase24.py` écrivait son rapport dans un chemin repo
en dur : chaque `pytest` remplaçait un rapport de recherche versionné par la
sortie d'une fixture.

---

## Politique secrets

| Règle | Détail |
|-------|--------|
| `.env` | Gitignored — jamais committé |
| `.env.example` | Placeholders vides uniquement |
| Logs | `src/logger.py` masque les préfixes env `KRAKEN_*` (donc `KRAKEN_FUTURES_*`), `FEATHERLESS_*`, `VULTR_*`, les suffixes `*_KEY` / `*_SECRET` / `*_TOKEN`, les en-têtes `Authorization`, les clés privées PEM et les blobs base64 ; `sanitize_payload()` pour les structures JSON |
| Audit export | `scripts/export_audit_bundle.py` rédacte les secrets |
| Live | Triple opt-in : `TRADING_MODE=live` + `LIVE_TRADING=true` + `ALLOW_LIVE_ORDERS=true` |

Aucun secret n'a été trouvé dans l'arbre ni dans l'historique git (audit du
2026-08-19, dépôt public).

---

## Fichiers protégés

Modifications interdites sans justification explicite :

- `config.yaml`
- `src/execution.py`, `src/risk.py`, `src/futures_kraken_cli.py`
- `web/`

**À noter :** `src/bot/*` est entré dans le graphe d'import de l'agent live
(`src/main.py` → `src/strategies/__init__.py` → `src/strategies/breakout.py` →
`src/bot/__init__.py`) sans figurer dans cette liste. Le couplage est latent —
aucun effet de bord à l'import, et le chemin live n'appelle aucun code
`src/bot` — mais il existe.

---

## Makefile (raccourcis)

```bash
make test      # pytest -q
make lint      # ruff check
make collect   # pytest --collect-only -q
```

Sur Windows sans `make` : utiliser les commandes pytest/ruff directement.

---

## Avant chaque commit

1. `python -m pytest -q` — doit rester vert
2. `ruff check src tests scripts` — doit rester vert
3. `git diff --exit-code` après les tests — aucun fichier suivi réécrit
4. Vérifier qu'aucun secret n'est staged : `git diff --cached`
5. Ne pas committer `data/`, `.env`, ni les rapports d'exécution locaux

---

## Anti-curve-fit (recherche)

Filtre OOS strict du walk-forward :

- `test_pnl_usd >= 0`
- `test_win_rate >= 50%`
- `trades_count >= 30`

**Limite documentée :** le second critère était inapplicable dans tout le moteur
bot des phases 21-30, `win_rate_pct` y étant calculé depuis une liste de PnL par
trade qui ne portait pas l'information (`trade_count = 55`, `total_return =
+4,24 %`, `win_rate = 0,0`). Voir `reports/PHASE31_FINAL_VERDICT.md`.

Si zéro configuration survit → conserver la configuration actuelle et le
documenter dans `docs/METHODOLOGY.md`.

Voir `AGENTS.md` et `docs/DECISIONS.md`.
