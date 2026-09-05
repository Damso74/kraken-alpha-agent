# Garde-fous live Kraken

À lire seulement pour une demande touchant aux risques, à l'exécution ou à une activation live explicitement autorisée. Les limites ci-dessous sont conservées des instructions antérieures ; elles ne prouvent ni l'accès actuel du compte, ni la viabilité financière, ni une autorisation d'ordre. Ne pas lancer les commandes de cette référence dans le cadre d'une simple lecture ou optimisation documentaire. Une ancienne autorisation du 2026-05-15 n'est pas une autorisation de la mission courante. Vérifier compte/instruments, profil, scopes, budget et conditions d'arrêt avant une activité live ; toute nouvelle autorisation doit les couvrir.

## Séquence et arrêt

- Safe-by-default live sequence (never bypass): `scripts/validate_live_xstocks.py` -> shadow >=20 min -> `scripts/live_preflight.py --allow-live-env-check` -> manual confirmation -> `kraken order cancel-after 60` -> `scripts/run_agent_loop.py`. Friday EOD (CEST): 21:45 stop new BUYs, 21:45-21:55 flatten, 22:00 hard-stop. Micro-live NO-GO until 2–4 weeks clean forward paper observation (J+7/J+14/J+28 reviews).

Les horaires Friday EOD/CEST, fenêtres US_CORE et préconditions d'observation ci-dessus sont à confronter à la décision opérationnelle actuelle ; ne pas les considérer comme une activation automatique ni conclure que la période d'observation est accomplie.

## Limites de l'override futures historique

- `src.risk.HARDCODED_MAX_LEVERAGE = 1.0` : conserver le refus de toute demande >1x dans le risk gate et `src.futures_kraken_cli._build_order_args`. Cette limite ne justifie aucune assurance d'équivalence au spot ou d'absence de risque de marge.
  - SELL is exit-only on the futures engine: `execution._execute_futures` refuses any SELL without an open long and forces `--reduce-only` on the wire.
  - `flatten_before_close_exit` still fires 15 min before US_CORE close → no overnight funding accrual.
  - Funding-rate gate: BUY refused when `features.funding_rate_pct_per_hour > futures.max_funding_rate_pct_per_hour` (default 0.5%/h).
  - Triple opt-in (`TRADING_MODE=live` + `LIVE_TRADING=true` + `ALLOW_LIVE_ORDERS=true`) is unchanged and remains mandatory; never persisted to `.env`.
  - The `micro_live_100eur` profile is the only profile that pivots to `execution.engine: futures`; the active default (`aggressive_competition`) stays on `engine: spot` so existing tests and dry-runs are not perturbed.
  - The agent never calls `kraken futures transfer` / `wallet-transfer`. The Futures write API key MUST be created with `Trades` + `Positions` only and `Withdrawal` / `Transfer` / `Funding` disabled; the existing Spot key cannot be reused for futures.
  - Because `kraken futures order` has no `--validate` flag, there is no mainnet dry-run for futures: the first live futures order is necessarily a real wire-level order and must be sized minimal (1x, isolated, micro nominal). All pre-live validation runs through `kraken futures paper *` (which itself requires `kraken futures paper init` to have been run on the host once).

## Sémantique de sortie

- `src/risk.evaluate_risk(action="SELL", is_exit_action=True, ...)` MUST bypass exposure/position caps (exit-only; does not relax `shorting=false`).
