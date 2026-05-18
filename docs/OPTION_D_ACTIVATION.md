# Option D — Protocole d'activation live crypto Perps

> **STATUT (Phase 2 update, 2026-05-18 19:55 CEST) — DÉCONSEILLÉ
> DÉFINITIF SUR 5 VARIANTES.** L'audit a été étendu à une **deuxième
> couche de recherche** (Bayesian Optuna + signaux externes) pour
> vérifier qu'un coin de l'espace param non-couvert par la grille
> déterministe ne renfermait pas un edge masqué. **Toutes les 5
> variantes retournent 0 survivor sur le filtre OOS strict** :
>
> | Variante                                  | Combos | Survivors | Best OOS PnL | Best OOS WR | Source |
> |-------------------------------------------|--------|-----------|--------------|-------------|--------|
> | Walk-forward 240-min déterministe         | 48     | **0**     | −0.09 USD    | 40.50 %     | `data/walk_forward_crypto_results.json`         |
> | Walk-forward 60-min déterministe          | 48     | **0**     | −0.21 USD    | 42.99 %     | `data/walk_forward_crypto_60min_results.json`   |
> | Walk-forward 15-min déterministe          | 48     | **0**     | −0.02 USD    | 51.85 %†    | `data/walk_forward_crypto_15min_results.json`   |
> | **Optuna 500 trials Bayesian (Phase 2a)** | 500    | **0**     | +0.251 USD‡  | 43.0 %      | `data/optuna_crypto_results.json`               |
> | **Walk-forward + signaux externes (Phase 2b)** | 180 | **0**     | +0.266 USD‡  | 42.7 %      | `data/walk_forward_with_signals_results.json`   |
>
> ‡ Phase 2 atteint un PnL OOS positif sur certaines configurations
> mais **butte systématiquement sur la barre WR ≥ 50 %**. Voir
> [`docs/STRATEGY_DISCOVERY_REPORT.md`](STRATEGY_DISCOVERY_REPORT.md)
> pour le détail (saturation de `min_confidence_to_trade` à 0.40,
> caveat BTC dominance historique manquante, p-hacking risk).
>
> †Le best test WR du 15-min passe la barre 48 % (51.85 %), mais ce
> candidat a un test PnL négatif (−0.04 USD) — le filtre PnL le rejette.
> Le best test PnL (−0.02 USD ; presque flat mais négatif) a un WR de
> 34.88 % et est rejeté par le filtre WR. Aucune calibration ne franchit
> simultanément les trois critères (PnL ≥ 0, WR ≥ 0.48, trades ≥ 60).
>
> Conséquence : **aucun profil `live_crypto_*_capped` ni
> `live_crypto_with_signals_capped` n'a été créé** dans `config.yaml`.
> Le script d'activation refuse de se lancer tant qu'aucun profil
> futures-engine survivor n'existe — cf. § "Conditions d'activation"
> pour la checklist binaire. Voir
> [`docs/STRATEGY_DISCOVERY_REPORT.md`](STRATEGY_DISCOVERY_REPORT.md)
> pour la procédure complète Phase 2 (Bayesian + signaux externes) et
> les caveats méthodologiques exhaustifs (p-hacking, fenêtre courte,
> BTC dom historique).

Cette doc reste publiée parce que l'infrastructure (kill switch +
monitoring + procédure) est entièrement câblée et **réutilisable**
dès qu'une stratégie tunée (ou une autre asset class) franchirait à
nouveau le filtre OOS. Le jour où un profil futures-engine survivor
est ajouté à `config.yaml`, ce document décrit exactement comment
l'activer.

## TL;DR

1. Tirer **uniquement** quand le walk-forward (ou un test équivalent)
   produit un *survivor* OOS avec `test_pnl_usd ≥ 0`, `test_win_rate ≥ 0.50`
   et `test_trades_count ≥ 30`.
2. Créer le profil `live_crypto_aggressive_capped` dans `config.yaml`
   avec les caps suivants (toujours) : `max_total_exposure_usd ≤ 30`,
   `max_position_notional_usd ≤ 10`, `max_open_positions ≤ 3`,
   `max_leverage = 1.0`, `shorting_enabled = false`,
   `block_if_regime` inclut `LOW_LIQUIDITY`.
3. Exporter dans le shell courant (jamais dans `.env`) le triple opt-in
   + le profil + la clé Futures.
4. Lancer `scripts/live_crypto_with_killswitch.py --i-understand-the-risks`
   dans un terminal.
5. Lancer **en parallèle** `scripts/monitor_live_session.py` dans un
   second terminal pour la lecture humaine en continu.
6. Surveiller le journal `data/killswitch.log` ; stopper par `Ctrl+C`
   ou laisser le kill switch agir (auto-flatten dans tous les cas).

## Pourquoi le verdict actuel reste EV-négatif sur 3 résolutions

Trois sweeps walk-forward indépendants couvrent maintenant trois
échelles temporelles complémentaires, tous sur les 5 mêmes paires
(`BTC, ETH, SOL, AVAX, LTC`), profil `micro_live_100eur_crypto`,
48 combinaisons par sweep :

### 240-min × ~90 jours (~60d/30d split, source `walk_forward_crypto_results.json`)

| Métrique test set | min     | médiane | max     |
|-------------------|---------|---------|---------|
| `net_pnl_usd`     | −0.33$  | −0.17$  | −0.09$  |
| `win_rate`        | 38.66 % | 39.67 % | 40.50 % |
| `max_drawdown_pct`| 0.02 %  | 0.02 %  | 0.03 %  |
| `trades_count`    | 299     | 300     | 300     |

### 60-min × ~30 jours (~20d/10d split, source `walk_forward_crypto_60min_results.json`)

| Métrique test set | min     | médiane | max     |
|-------------------|---------|---------|---------|
| `net_pnl_usd`     | −0.90$  | −0.39$  | −0.21$  |
| `win_rate`        | 32.99 % | 40.95 % | 42.99 % |
| `max_drawdown_pct`| 1.08 %  | 1.66 %  | 3.03 %  |
| `trades_count`    | 242     | 247     | 247     |

Le 60-min **dégrade** la situation par rapport au 240-min : le best
test PnL passe de −0.09$ à −0.21$ et le best test WR plafonne à
42.99 % (toujours <50 %). La conclusion est plus marquée encore :
plus on raccourcit l'horizon, plus l'edge négatif est visible.

### 15-min × ~7.5 jours (~5d/2.5d split, source `walk_forward_crypto_15min_results.json`)

| Métrique test set | min     | médiane | max     |
|-------------------|---------|---------|---------|
| `net_pnl_usd`     | −0.36$  | −0.05$  | −0.02$  |
| `win_rate`        | 26.15 % | 37.88 % | 51.85 % |
| `max_drawdown_pct`| 0.12 %  | 0.24 %  | 1.80 %  |
| `trades_count`    | 187     | 237     | 240     |

Le 15-min est la résolution la plus permissive du brief (`WR ≥ 0.48`,
`trades ≥ 60`) parce que le scalping intra-day génère mécaniquement
plus de fills sur des micro-ranges. Malgré cette relaxation **0
configuration ne survit** : le best test PnL est −0.018$ (presque
flat mais toujours négatif) avec un WR de 34.88 % ; et le seul
candidat dont le WR dépasse 48 % (51.85 %) a un PnL négatif (−0.04$).
Aucune calibration ne franchit simultanément les trois barres.

### Synthèse multi-résolution

Le pattern est sans ambiguïté sur les **trois** résolutions testées :
la stratégie **génère beaucoup de fills** (≈190-300 trades sur la
fenêtre OOS par configuration selon la résolution) mais le **win-rate
reste presque toujours sous 50 %** dans les combinaisons train et
test, et le PnL OOS est **strictement négatif dans 144/144 cas**
(48 combos × 3 résolutions). Il n'existe pas de calibration dans la
grille — sur trois échelles temporelles indépendantes — qui transforme
cet edge négatif en edge positif.

La conséquence directe est que sur les heures restantes avant la
deadline lablab, **toute activation live de l'option D a une espérance
de gain négative bornée à -$5** :

- **Best case** : `+0.00$` (rare ; nécessite que l'OOS performance
  inverse soudainement, scénario non observé sur aucun horizon).
- **Expected case** : `−2.00 à −5.00$` (extrapolation de la PnL OOS
  médiane sur 24 h ramenée à l'envelope $30 → ~−$0.40 à −$0.50/h →
  kill switch atteint entre +5 h et +12 h).
- **Worst case** : `−5.00$` (kill switch, garanti par construction du
  superviseur).

Le coût attendu pour 0 chance raisonnable de podium = **GO/NO-GO
clairement NO-GO** pour la submission.

## Architecture du superviseur

```
┌──────────────────────────────────────────────────────────────────┐
│ scripts/live_crypto_with_killswitch.py                           │
│                                                                  │
│  ┌─────────────────────────┐         ┌─────────────────────────┐ │
│  │ 1) Preflight            │         │ 4) PnL poller (thread)  │ │
│  │  - --i-understand…      │  ──────►│  every poll_interval s  │ │
│  │  - TRADING_MODE=live    │         │  kraken futures accounts│ │
│  │  - LIVE_TRADING=true    │         │  → realized + unrealized│ │
│  │  - ALLOW_LIVE_ORDERS=t  │         │  → cumulative_pnl_usd   │ │
│  │  - KRAKEN_FUTURES_API…  │         │                         │ │
│  │  - profile exists &     │         │  if pnl ≤ -5 USD →      │ │
│  │    engine=futures &     │         │     trigger flatten     │ │
│  │    cap ≤ 30 USD         │         │                         │ │
│  └──────────┬──────────────┘         └──────────┬──────────────┘ │
│             │                                   │                │
│             ▼                                   ▼                │
│  ┌─────────────────────────┐         ┌─────────────────────────┐ │
│  │ 2) Spawn subprocess     │         │ 5) Flatten              │ │
│  │  python scripts/        │ ◄───────│  - cancel-after 1       │ │
│  │  run_agent_loop.py      │ SIGTERM │  - reduce-only SELL on  │ │
│  │                         │         │    every open long       │ │
│  └─────────────────────────┘         │  - kill subprocess      │ │
│             │                         │  - append killswitch.log │ │
│             │                         │  - exit 1               │ │
│             ▼                         └─────────────────────────┘ │
│  ┌─────────────────────────┐                                     │
│  │ 3) signal handlers       │                                    │
│  │  SIGINT/SIGTERM → stop  │                                     │
│  │    and flatten anyway   │                                     │
│  └─────────────────────────┘                                     │
└──────────────────────────────────────────────────────────────────┘
```

Logique exacte côté décision : `src/live_killswitch.py` (`KillSwitchOrchestrator`).
Tous les side effects (poll, cancel, flatten, kill subprocess, clock)
sont **injectables**, ce qui rend les 11 tests `tests/test_live_killswitch.py`
hermétiques (aucun appel réseau, aucun subprocess réel).

## Pré-requis avant activation

Tout ce qui suit doit être vrai. Si **un seul** point manque, ne tire pas.

1. Le profil `live_crypto_aggressive_capped` existe dans `config.yaml`.
   - Vérification : `python -c "from src.config import get_settings; print(sorted(get_settings().available_profiles))"`
2. Le profil est en `execution.engine: futures` et `risk.max_total_exposure_usd ≤ 30`.
3. Le walk-forward le plus récent (`data/walk_forward_crypto_results.json`)
   contient un *winner* avec `test_pnl_usd ≥ 0`, `test_win_rate ≥ 50%`,
   `test_trades_count ≥ 30`.
4. Confirmation côté Discord / channel hackathon que le timing est OK
   (US_PREMARKET ou US_CORE pour des actifs corrélés, ou tout moment
   pour les crypto 24/7).
5. Clé Kraken Futures **WRITE** créée avec **uniquement** `Trades` +
   `Positions` (jamais `Withdrawal`/`Transfer`/`Funding`).
6. Clé Kraken Futures **READ-ONLY** créée séparément pour le monitor
   (idéalement dans un fichier `data/jury_readonly_credentials.md`
   gitignored, jamais commité).
7. La méthodologie de `docs/METHODOLOGY.md` est comprise par
   l'opérateur (raison d'être du walk-forward, signification des
   chiffres OOS).

## Commande exacte à lancer (PowerShell)

```powershell
# Terminal #1 — superviseur kill switch
.\.venv\Scripts\Activate.ps1

$env:TRADING_MODE = "live"
$env:LIVE_TRADING = "true"
$env:ALLOW_LIVE_ORDERS = "true"
$env:KRAKEN_ALPHA_PROFILE = "live_crypto_aggressive_capped"
$env:KRAKEN_FUTURES_API_KEY = "<write key Futures, Trades+Positions only>"
$env:KRAKEN_FUTURES_API_SECRET = "<secret correspondant>"
$env:KRAKEN_CLI_TRANSPORT = "auto"   # détection wsl/native automatique

# Test à blanc : seulement le preflight, aucun ordre, aucun subprocess
python scripts/live_crypto_with_killswitch.py --i-understand-the-risks --dry-validate

# Si exit 0 → activation réelle :
python scripts/live_crypto_with_killswitch.py `
    --i-understand-the-risks `
    --threshold-usd -5.0 `
    --poll-interval-seconds 10 `
    --max-duration-hours 6 `
    --flatten-cest-hour 21 `
    --flatten-cest-minute 55
```

```powershell
# Terminal #2 — monitor temps réel (read-only)
.\.venv\Scripts\Activate.ps1

$env:KRAKEN_FUTURES_API_KEY = "<read-only Futures key>"
$env:KRAKEN_FUTURES_API_SECRET = "<read-only secret>"
$env:KRAKEN_CLI_TRANSPORT = "auto"

python scripts/monitor_live_session.py `
    --refresh-seconds 5 `
    --threshold-usd -5.0 `
    --cest-cutoff-hour 21 `
    --cest-cutoff-minute 55
```

## Comment stopper

| Façon                                          | Comportement                                                                                     |
|------------------------------------------------|--------------------------------------------------------------------------------------------------|
| `Ctrl+C` dans le terminal #1                   | `SIGINT` capturé, orchestrateur stoppe ; cancel-all + flatten lancés ; subprocess tué ; exit 0. |
| `kill <pid>` (SIGTERM) du process superviseur  | Mêmes side effects que `Ctrl+C`.                                                                 |
| Kill switch automatique (cumul ≤ −$5)          | cancel-all + flatten + kill subprocess + exit 1.                                                 |
| CEST 21:55                                     | cancel-all + flatten + kill subprocess + exit 1.                                                 |
| `--max-duration-hours` atteint                 | cancel-all + flatten + kill subprocess + exit 1.                                                 |
| `>= 5` snapshots Kraken consécutifs qui foirent| cancel-all + flatten conservatoire (le poller est aveugle, on ne prend pas de risque) + exit 1. |

Dans **tous** les cas, le journal `data/killswitch.log` contient une
ligne JSON par évènement (baseline, snapshots, trigger, flatten). Une
post-session typique fait `Get-Content data/killswitch.log | ConvertFrom-Json`
pour la timeline complète.

## Post-mortem

Une fois la session terminée, dans n'importe quel ordre :

1. **Récupérer la timeline du superviseur** :
   ```powershell
   Get-Content data/killswitch.log | ConvertFrom-Json | Format-Table at_iso, kind, cumulative_pnl_usd, note
   ```
2. **Récupérer les trades live audités** (read-only key) :
   ```powershell
   kraken futures fills -o json > "data/post_mortem_fills_$(Get-Date -Format yyyy-MM-dd-HHmm).json"
   kraken futures positions -o json > "data/post_mortem_positions_$(Get-Date -Format yyyy-MM-dd-HHmm).json"
   kraken futures accounts -o json > "data/post_mortem_accounts_$(Get-Date -Format yyyy-MM-dd-HHmm).json"
   ```
3. **Cross-check** : aggréger réalisé + non-réalisé via `_aggregate_pnl`
   dans `scripts/monitor_live_session.py` et confirmer que le total
   matche le dernier `cumulative_pnl_usd` du `killswitch.log`. Tout
   delta > $0.05 = bug du poller (à logger).
4. **Audit bundle** : régénérer le bundle masqué pour le jury :
   ```powershell
   python scripts/export_audit_bundle.py --include-killswitch-log
   ```
5. **Rotation** : faire tourner la clé Futures WRITE immédiatement
   après la session (la clé n'est utile que pendant la fenêtre live ;
   AGENTS.md le rappelle déjà comme dette post-hackathon).

## Conditions d'activation (checklist binaire)

L'opérateur **doit** cocher chacun de ces points dans l'ordre avant de
lancer la commande. Un seul non-coché → **NO-GO**.

- [ ] J'ai lu `docs/METHODOLOGY.md` et je comprends pourquoi le filtre
      OOS est strict (≥ 0 PnL, ≥ 50 % WR, ≥ 30 trades).
- [ ] `data/walk_forward_crypto_results.json` contient un *winner*
      (champ `winner` non-null) **généré moins de 24 h avant l'activation**.
- [ ] Le profil `live_crypto_aggressive_capped` existe dans
      `config.yaml` avec exactement les caps documentés ci-dessus
      (vérifié à la main, pas seulement par le preflight).
- [ ] La clé Kraken Futures WRITE utilisée a uniquement les permissions
      `Trades` + `Positions` (jamais `Withdrawal`/`Transfer`/`Funding`).
- [ ] La clé Kraken Futures READ-ONLY existe et est disponible pour le
      monitor (sinon le monitor refusera de démarrer).
- [ ] Le triple opt-in (`TRADING_MODE=live`, `LIVE_TRADING=true`,
      `ALLOW_LIVE_ORDERS=true`) est exporté **dans le shell courant
      uniquement**, **jamais** dans `.env`.
- [ ] `pytest -q` est vert (les ≥ 256 tests doivent passer ; un test
      cassé pourrait masquer une régression du kill switch).
- [ ] `python scripts/live_crypto_with_killswitch.py --i-understand-the-risks --dry-validate`
      renvoie exit 0.
- [ ] Le terminal #2 (monitor) est ouvert et raffraichit toutes les 5 s
      avec une baseline visible (`distance to kill switch ≈ +$5.00`).
- [ ] Je suis disponible à la console pendant **toute** la durée
      programmée (`--max-duration-hours`) — pas de "lance et fais autre
      chose pendant 24 h".
- [ ] Je sais que `Ctrl+C` est le bouton rouge et qu'il flatte de toute
      façon (pas de "j'arrête de regarder, ça continue").
- [ ] **Verdict EV actuel** : si la doc dit toujours **EV-négative
      DÉCONSEILLÉ** en tête, je n'active pas. Période.

## Référence croisée

- `src/live_killswitch.py` — orchestrateur pur testé (11 tests).
- `scripts/live_crypto_with_killswitch.py` — câblage production.
- `scripts/monitor_live_session.py` — read-only dashboard.
- `scripts/walk_forward_crypto.py` — driver walk-forward crypto avec
  presets `default` (240-min × 90d), `60min` (60-min × 30d) et
  `15min` (15-min × 7.5d). Voir `--grid-preset --help` pour les détails.
- `src/crypto_ohlc_rest.py` — fetcher REST crypto (no CLI dependency).
- `data/walk_forward_crypto_results.json` — sortie 240-min (gitignored).
- `data/walk_forward_crypto_60min_results.json` — sortie 60-min
  (gitignored ; 0/48 survivors, voir verdict ci-dessus).
- `data/walk_forward_crypto_15min_results.json` — sortie 15-min
  (gitignored ; 0/48 survivors, voir verdict ci-dessus).
- `AGENTS.md` — règles de safety et override "futures + leverage"
  (intransigeant 1x, exit-only SELL, no `Withdrawal` key, etc.).
