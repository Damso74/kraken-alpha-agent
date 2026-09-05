# Repères Kraken par sujet

Référence conditionnelle issue des instructions relevées le 2026-09-05, comprenant des notes de mai 2026 et un audit daté du 2026-08-19. Lire uniquement la section utile. Les statuts de compte, blocages API, profils actifs, cron, hôtes, résultats de recherche et tests sont des observations historiques non revalidées. Ils ne définissent pas le statut opérationnel actuel et n'autorisent aucune opération. Les chemins ci-dessous sont relatifs à la racine du dépôt ; ne pas ouvrir de fichier de credentials dans un rapport d'agent.

## Soumission et interface

- Submission page honesty rule (recurring): the `web/` dashboard must display ONLY real backtest numbers from `web/public/data/backtest_xstocks_*.json`; never label static data as "live" or "real-time" (badge "READY FOR DEMO" and "Agent Online" are OK, "Live trading" / "Live xStocks fills" are NOT); the "What Blocked xStocks" section must quote verbatim API error strings (`EGeneral:Permission denied`, `wouldNotReducePosition`) as wire-level evidence; if the backtest produces a negative PnL, show the negative number honestly.
- `web/` is Next.js submission dashboard (static JSON from `web/public/data/` only, Vercel auto-deploy on `master` push). Core trading files off-limits to UI subagents. Submission scripts: `backtest_xstocks.py`, `export_submission_backtest.py`, `walk_forward_xstocks.py`, `export_audit_bundle.py`. Docs in `docs/` (SUBMISSION, METHODOLOGY, JURY_ACCESS, etc.).

## CLI et mécanismes observés — vérifier la version et le code

- Kraken CLI 0.3.2 runs in WSL Ubuntu from Windows (`KRAKEN_CLI_TRANSPORT` override); native on Linux VPS (`auto` → `$PATH` binary).
- xStocks pairs use slash form `TICKERx/USD`; read commands need `--asset-class tokenized_asset`. `kraken paper buy/sell` rejects xStocks (no `--asset-class`); agent loop simulates via `src/execution._simulate_paper_fill`.
- Des observations historiques ont retourné `EGeneral:Permission denied` sur Spot et `wouldNotReducePosition` sur des BUY Futures. Ces erreurs sont des preuves de rejet pour ces observations, pas une description du compte courant ni une autorisation de changement de compte.
- Kraken sépare les clés Spot/Futures ; les clés Futures en écriture restent limitées à `Trades` + `Positions`. Les clés de lecture destinées à un audit restent hors Git, sans droits d'ordre, de retrait ni de modification. Vérifier les instruments réellement pris en charge et leur mapping dans `src/futures_kraken_cli.py`.
- **Futures CLI**: literal `order` required (`kraken futures order buy/sell`); no `--validate`; paper uses `kraken futures paper *`. Size to 2 decimals; `run_futures_cli` whitelists success statuses only (`placed`, `filled`, etc.) — Kraken returns HTTP 200 on rejections.
- Mode par défaut `dry_run` ; triple opt-in live obligatoire. Les profils `aggressive_competition` et `micro_live_100eur` sont des repères à vérifier dans la configuration courante ; les flags live restent limités à la session.

## Recherche et observation — historique, pas un état actif confirmé

- Bot research pipeline (`src/bot/`, phases 16–30 on feature branches, not merged to `master`): Binance public caches gitignored in `data/collector_cache/` (BTC/ETH/SOL 1d/4h/1h + derivatives funding/basis). Exhaustive backtests: **0 paper_candidate**; price-only OHLCV exhausted after Phase 25 autopsy (no raw edge at zero fees; risk manager minor blocker; **4h best TF**; regime router = overlay not alpha). Derivatives funding+basis useful as risk overlay only; **ETH 4h funding+basis overlay** on `trend_following`/`ema_crossover` baselines is the active research track.
- Forward paper observation ops: `scripts/ops_run_observation_once_phase30.sh` / `.ps1` refreshes public caches then runs `run_overlay_observation_daemon_phase28.py --mode once`; state under `reports/paper_observation_phase28/`; static cockpit at `reports/paper_observation_phase28/dashboard.html` (NOT `web/`); metrics in `reports/phase29_observation_metrics/summary.json`; VPS **cron every 4h** preferred over infinite loop; `STOP_OBSERVATION` flag halts runs; `--cache-only` without refresh observes stale cache only.

## Audit du 2026-08-19

- Tests : **1058** collectés (`python -m pytest -q`), 126 fichiers, ~3 min
- CI : `.github/workflows/ci.yml` — ruff + shellcheck + pytest + `git diff --exit-code`.
  **Elle n'avait jamais exécuté un seul test avant le 2026-08-19** (`ruff` absent de
  `requirements.txt` → `exit 127` au step lint). Voir ADR-013.
- Verdict de la recherche : **`reports/PHASE31_FINAL_VERDICT.md`** — 0 signal tradable,
  observation forward archivée. Lire ce document avant toute reprise.
- Rapports d'audit antérieurs : `reports/PHASE1_AUDIT_REPORT.md`,
  `reports/REPOSITORY_AUDIT_FINAL.md` (le score « 72/100 → 78/100 » qui figurait ici
  n'était étayé par aucune mesure : ni couverture, ni CI verte)
- Index des scripts : `scripts/README.md` si présent dans le checkout ; ne pas importer un ancien arbre de recherche pour une simple correction documentaire.

## Contexte ancien à ne pas transformer en autorisation

- Les notes antérieures gelaient le développement stratégie jusqu'à la fin d'observation, puis signalaient l'observation archivée. Consulter le verdict et la décision applicable avant une reprise ; ce document ne tranche pas leur actualité.
- Des notes antérieures permettaient des pushes de branches/backup privés et acceptaient temporairement un risque lié à des clés. Ces permissions historiques ne valent pas autorisation actuelle.
- L'ancien chemin utilisateur et les contournements SSH/réseau dépendaient d'un hôte précédent. Utiliser le checkout et les accès explicitement autorisés pour la tâche.
