# Option D — Protocole d'activation live crypto Perps

> **STATUT (HEAD `40f211e` + cette branche, 2026-05-18 17:30 CEST) — DÉCONSEILLÉ.**
> Le walk-forward crypto exécuté ce jour (`data/walk_forward_crypto_results.json`)
> retourne **0 survivor sur 48 combos** (test PnL ∈ [-0.33$, +0.00$], 0 combo
> avec PnL OOS positif sur 90 jours, 5 paires). La stratégie déterministe
> n'a **aucun edge mesurable** sur la couche crypto Perps avec le stack
> actuel. Option D = **EV-négative** sur cet horizon. Le profil
> `live_crypto_aggressive_capped` n'a donc **pas** été créé (cf. Phase 3
> du protocole utilisateur). Le script d'activation refuse de se lancer
> tant que ce profil n'existe pas dans `config.yaml`. Voir §
> "Conditions d'activation" en bas pour la checklist binaire.

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

## Pourquoi le verdict actuel est EV-négatif

Sortie brute du walk-forward (`scripts/walk_forward_crypto.py`) sur
240-min × 90 jours, 5 paires (BTC, ETH, SOL, AVAX, LTC), profil
`micro_live_100eur_crypto`, 48 combinaisons :

| Métrique test set | min     | médiane | max     |
|-------------------|---------|---------|---------|
| `net_pnl_usd`     | −0.33$  | −0.17$  | −0.09$  |
| `win_rate`        | 38.66 % | 39.67 % | 40.50 % |
| `max_drawdown_pct`| 0.02 %  | 0.02 %  | 0.03 %  |
| `trades_count`    | 299     | 300     | 300     |

Le pattern est sans ambiguïté : la stratégie **génère beaucoup de fills**
(≈300 trades sur 30 jours OOS par configuration) mais le **win-rate
reste sous 50 %** dans toutes les combinaisons train et test, et le
PnL OOS est négatif dans 48/48 cas. Il n'existe pas de calibration
dans la grille qui transforme cet edge négatif en edge positif.

La conséquence directe est que sur les 24-30 h restantes avant la
deadline lablab, **toute activation live de l'option D a une espérance
de gain négative bornée à -$5** :

- **Best case** : `+0.00$` (rare ; nécessite que l'OOS performance
  inverse soudainement).
- **Expected case** : `−2.00 à −5.00$` (extrapolation de la PnL OOS
  médiane sur 24 h ramenée à l'envelope $30 → ~−$0.40/h → kill switch
  atteint entre +6 h et +12 h).
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
- `scripts/walk_forward_crypto.py` — driver walk-forward crypto.
- `src/crypto_ohlc_rest.py` — fetcher REST crypto (no CLI dependency).
- `data/walk_forward_crypto_results.json` — sortie brute du
  walk-forward (gitignored — artefact dérivé local).
- `AGENTS.md` — règles de safety et override "futures + leverage"
  (intransigeant 1x, exit-only SELL, no `Withdrawal` key, etc.).
