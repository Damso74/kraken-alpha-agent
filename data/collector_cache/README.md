# Collector cache — `data/collector_cache/`

Répertoire **gitignored** pour les feeds read-only du pipeline alpha
alternatif (`src/data/collectors/` + scripts `event_study_*.py`).

Les fichiers n'existent pas dans le clone frais : chaque script les
crée au premier run réseau ou échoue explicitement en
`--use-cache-only`.

Voir aussi [`docs/DATA_SOURCES.md`](../../docs/DATA_SOURCES.md) pour
les schémas détaillés et les limites API.

---

## Reconstruire les caches depuis les manifests

**Outil : [`scripts/reseed_collector_cache.py`](../../scripts/reseed_collector_cache.py).**

Les résultats des phases 21 à 30 ont été produits avec des caches qui
ne sont pas dans le dépôt. Les **manifests versionnés** sous `reports/`
décrivent en revanche exactement ce qui manque (actif, timeframe,
nombre de barres, bornes temporelles, `sha256`) :

| Manifest | Séries décrites |
|----------|-----------------|
| `reports/data_manifests_phase21/ohlcv_backbone_manifest.json` | OHLCV 1d / 4h / 1h — avec `sha256` |
| `reports/phase24_data_backbone/data_quality.json` | OHLCV 1d / 4h — avec `sha256` |
| `reports/data_manifests_phase26/derivatives_readiness.json` | funding, open interest 4h / 1d |
| `reports/data_manifests_phase27/basis_readiness.json` | basis 4h |
| `reports/data_manifests_phase27/derivatives_depth.json` | profondeur OI + rappel funding / basis |

Ces manifests portent des **chemins absolus de la machine d'origine**
(`C:\Users\credo\...`) : l'outil ne garde que le nom de fichier et le
réécrit sous `--cache-root` (défaut `data/collector_cache/`).

```powershell
# 1. Inventaire hors ligne : que manque-t-il ? (aucun réseau, aucune écriture)
python scripts/reseed_collector_cache.py --dry-run

# 2. Reconstruction réelle (appelle les collectors publics Binance)
python scripts/reseed_collector_cache.py

# Un seul actif / un seul manifest
python scripts/reseed_collector_cache.py --only BTC
python scripts/reseed_collector_cache.py --manifest reports/data_manifests_phase21/ohlcv_backbone_manifest.json

# Rapport machine
python scripts/reseed_collector_cache.py --dry-run --json
```

### Statuts et codes de sortie

| Statut | Signification |
|--------|---------------|
| `match` | Fichier présent, `sha256` identique au manifest |
| `mismatch` | Fichier présent mais **différent** — jamais écrasé sans `--force` |
| `absent` | Fichier manquant (dry-run, ou reconstruction impossible) |
| `rebuilt` | Fetch effectué et cache écrit |
| `skipped` | Série jamais collectée à l'origine (voir plus bas) |
| `error` | Échec fetch / parse / écriture (rapporté, le lot continue) |

Sortie **0** = rien d'anormal, **1** = erreur, **2** = divergence ou
cache toujours absent.

### Le `sha256` ne peut pas matcher après reconstruction

Les caches embarquent leur propre horodatage (`generated_at` /
`fetched_at`) et sont fetchés sur une fenêtre qui se termine
**aujourd'hui**. Un re-fetch ne reproduit donc **jamais** le fichier
octet pour octet : un `sha256` différent après `rebuilt` est **attendu**,
pas un bug. Le `sha256` du manifest répond à une seule question : *« ai-je
exactement le fichier d'origine ? »*. Pour juger un cache reconstruit,
comparer plutôt `row_count` / bornes temporelles rapportés par l'outil
à ceux du manifest.

### Ce qui n'est pas reconstructible

| Série | Raison |
|-------|--------|
| `liquidations` | Aucune source publique historique (`/fapi/v1/allForceOrders` = fenêtre glissante courte) |
| funding / OI / basis **SOL** | `blocked_data` dans les manifests d'origine : ces caches n'ont jamais existé |
| `oi_{ASSET}_{période}.json` | Binance `openInterestHist` ≈ **30 j glissants** : on peut refaire *un* cache de 30 j, **pas** celui de mai 2026. Les résultats phases 26/27 dépendant de l'OI ne sont donc **pas** reproductibles à l'identique |

### Garde-fous

- Un cache existant qui diffère du manifest n'est **jamais** écrasé
  silencieusement (`--force` requis, explicite).
- L'écriture est **refusée** partout dans le dépôt hors
  `data/collector_cache/` — en particulier dans `reports/`.
- Écriture atomique (fichier temporaire `*.reseed-tmp` puis remplacement) :
  aucun cache partiel en cas d'échec réseau.
- Le fetcher HTTP est injectable :
  `tests/test_reseed_collector_cache.py` couvre l'outil de bout en bout
  **sans réseau**.

---

## Inventaire

| Fichier | Source API | Granularité | Script(s) qui le consomment | Rafraîchir |
|---------|------------|-------------|----------------------------|------------|
| `defillama.json` | [DefiLlama stablecoins](https://stablecoins.llama.fi/stablecoincharts/all) | Journalier | `scripts/event_study_stablecoins.py` | `python scripts/event_study_stablecoins.py --days 180` (sans `--use-cache-only`) |
| `wikimedia.json` | [Wikimedia pageviews REST](https://wikimedia.org/api/rest_v1/) | Journalier | `scripts/event_study_wikipedia.py` | `python scripts/event_study_wikipedia.py --article Bitcoin --days 180` (requiert User-Agent : défaut module ou `WIKIMEDIA_USER_AGENT`) |
| `etherscan_gas.json` | [Etherscan gas oracle](https://api.etherscan.io/api?module=gastracker&action=gasoracle) | Snapshot (TTL 5 min) | `scripts/event_study_eth_gas.py` (fetch intermédiaire) | Automatique quand `event_study_eth_gas.py` tourne sans `--use-cache-only` ; clé optionnelle `ETHERSCAN_API_KEY` |
| `etherscan_gas_history.json` | **Dérivé local** (append depuis le snapshot) | Journalier | `scripts/event_study_eth_gas.py` | Voir section [Gas ETH](#gas-eth-etherscan_gas_historyjson) ci-dessous |
| `status_pages.json` | [Kraken Status](https://status.kraken.com/api/v2/incidents.json), [Coinbase Status](https://status.coinbase.com/api/v2/incidents.json) | Par incident | `scripts/event_study_exchange_status.py` | `python scripts/event_study_exchange_status.py --venue all` |
| `ohlc_daily_{TICKER}.json` | Kraken REST, Binance klines, ou import manuel | Journalier (1440 min) | Tous les `event_study_*.py` avec `--ohlc-source cache` ou `binance-public` | Voir section [OHLC journalier](#ohlc-journalier--ohlc_daily_tickerjson) |

### Hors de ce dossier (référence)

| Fichier | Emplacement | Usage |
|---------|-------------|-------|
| Fear & Greed | `data/external_cache/fear_greed.json` | `scripts/demo_event_study.py` uniquement |
| OHLC crypto walk-forward | `data/ohlc_cache/crypto/` | `scripts/walk_forward_crypto.py`, Optuna — pas les event studies |

---

## Gas ETH — `etherscan_gas_history.json`

### Limitation (Etherscan = snapshot only)

L'API **gas oracle** Etherscan (`module=gastracker&action=gasoracle`) ne
fournit **qu'un instantané** (`fast_gwei` courant). Aucun endpoint public
simple dans ce repo ne sert une série historique officielle.

L'historique journalier est un fichier **append-only** local, maintenu par
`resolve_gas_history()` dans `src/data/collectors/etherscan.py` et
`scripts/event_study_eth_gas.py` (merge du snapshot du jour).

Exemple de schéma **SYNTHETIC** (tests uniquement) :
[`examples/etherscan_gas_history.example.json`](examples/etherscan_gas_history.example.json).

### Schéma attendu (structure uniquement — ne pas inventer de séries)

```json
{
  "source": "etherscan_gas_history",
  "entries": {
    "daily": [
      {
        "timestamp": "<unix_utc_midnight_int>",
        "fast_gwei": "<float_gwei>",
        "source": "etherscan_gas_history"
      }
    ]
  }
}
```

- `timestamp` : secondes Unix UTC, normalisé à **00:00:00 UTC** du jour.
- `fast_gwei` : champ utilisé par le signal `eth_gas_congestion` (≥ 0).
- Les clés `safe_gwei` / `propose_gwei` du snapshot ne sont **pas**
  requises dans l'historique.

### Minimum de lignes

Le z-score roulant exige **`lookback + 1`** observations journalières :

| `--lookback` | Minimum de rows `daily` |
|--------------|-------------------------|
| 180 (défaut) | **181** |
| 90 | 91 |

Le script échoue avec un message explicite si le seuil n'est pas atteint.

### Merge snapshot → history (comportement du script)

1. Charge `etherscan_gas_history.json` (liste vide si absent).
2. **Sans** `--use-cache-only` :
   - appelle `fetch_gas_oracle()` → écrit/met à jour `etherscan_gas.json` ;
   - extrait `fast_gwei` + `timestamp` du snapshot ;
   - normalise le timestamp à minuit UTC du jour civil ;
   - fusionne par timestamp (dernière valeur gagne pour un même jour) ;
   - persiste le fichier history.
3. **Avec** `--use-cache-only` : aucun appel réseau ; le history doit
   déjà contenir assez de rows. Si le fichier est absent ou vide → exit **2**
   avec `blocked: missing historical gas cache`.

### Peupler l'historique

```powershell
# Append la journée courante (répéter quotidiennement sur ~181 jours)
python scripts/event_study_eth_gas.py

# CI / offline — history pré-peuplé requis
python scripts/event_study_eth_gas.py --use-cache-only
```

**Ne pas** fabriquer de valeurs historiques fictives pour contourner
le minimum : le signal n'a de sens qu'avec un historique réel ou
seedé manuellement à partir de données vérifiables.

---

## Mode `--use-cache-only`

Tous les `event_study_*.py` (sauf calendrier / expiry) acceptent ce flag.
En cas de cache manquant ou incomplet, le script imprime le chemin exact
et renvoie vers ce README.

Les scripts calendrier (`event_study_calendar.py`,
`event_study_deribit_expiry.py`) n'utilisent **aucun** fichier ici —
seulement les OHLC Kraken REST.

---

## OHLC journalier — `ohlc_daily_{TICKER}.json`

### Pourquoi

Kraken REST OHLC est plafonné à **~720 candles par appel**. Pour des
event studies > ~24 mois (daily) ou du offline CI, utiliser
`--ohlc-source cache` ou `--ohlc-source binance-public` (voir
[`docs/DATA_SOURCES.md`](../../docs/DATA_SOURCES.md)).

### Schéma attendu (structure uniquement — ne pas inventer de séries)

```json
{
  "source": "ohlc_daily_cache",
  "generated_at": "<iso8601_z>",
  "ticker": "BTC",
  "interval_minutes": 1440,
  "entries": {
    "candles": [
      {
        "timestamp": "<unix_utc_midnight_int>",
        "open": "<float>",
        "high": "<float>",
        "low": "<float>",
        "close": "<float>",
        "vwap": "<float>",
        "volume": "<float>"
      }
    ]
  }
}
```

- `timestamp` : secondes Unix UTC, normalisé à **00:00:00 UTC** du jour.
- Champs requis par candle : `open`, `high`, `low`, `close`, `volume`.
- `vwap` : optionnel à l'import ; dérivé de `(high+low+close)/3` si absent.

### Minimum de lignes

Le script exige au moins **`max(--days, 30)`** candles dans la fenêtre
(défaut 180 j → ≥ 180 rows). Le cache incomplet lève
`CollectorError` avec le chemin absolu du fichier.

### Peupler le cache

```powershell
# Binance public → écrit data/collector_cache/ohlc_daily_BTC.json
python scripts/event_study_stablecoins.py --ohlc-source binance-public --days 365

# Import manuel : placer le JSON au bon chemin, puis
python scripts/event_study_stablecoins.py --ohlc-source cache --use-cache-only
```

**Ne pas** committer de gros fichiers OHLC : ce répertoire est gitignored.

---

## Kraken OHLC (défaut sans cache)

Les event studies tirent les candles **par défaut** via
`src/crypto_ohlc_rest.py` (`--ohlc-source kraken`, intervalle 1440 min).
Cap **~720 candles par appel REST** ; voir [`docs/DATA_SOURCES.md`](../../docs/DATA_SOURCES.md)
§ Kraken REST OHLC pour les profondeurs par intervalle.

Pour une fenêtre longue ou du offline, préférer `--ohlc-source cache`
(`ohlc_daily_{TICKER}.json` ci-dessus) ou `--ohlc-source binance-public`.

Le cache walk-forward séparé reste sous `data/ohlc_cache/`.
