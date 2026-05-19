# Sources de données — pipeline alpha alternatif

> Inventaire des APIs publiques consommées par
> `src/data/collectors/`, `src/crypto_ohlc_rest.py` et le demo
> Fear & Greed. Toutes ces sources sont **read-only** ; aucune ne
> peut placer d'ordre.

## Vue d'ensemble

| Source | Auth | Granularité | Cache par défaut | Module |
|--------|------|-------------|------------------|--------|
| DefiLlama stablecoins | Non | Journalier | `data/collector_cache/defillama.json` | `defillama.py` |
| DefiLlama chain TVL | Non | Journalier | idem (clé `chain_tvl_{chain}`) | `defillama.py` |
| Wikimedia pageviews | Non | Journalier | `data/collector_cache/wikimedia.json` | `wikimedia.py` |
| Etherscan gas oracle | Optionnelle (`ETHERSCAN_API_KEY`) | Snapshot | `data/collector_cache/etherscan_gas.json` | `etherscan.py` |
| Etherscan gas history | Dérivé local | Journalier (append) | `data/collector_cache/etherscan_gas_history.json` | script `event_study_eth_gas.py` |
| Statuspage incidents | Non | Par incident | `data/collector_cache/status_pages.json` | `status_pages.py` |
| Kraken REST OHLC | Non | 15 / 60 / 240 / 1440 min | Aucun cache dédié dans les scripts event study | `crypto_ohlc_rest.py` |
| OHLC daily long (event study) | Non | Journalier (1440 min) | `data/collector_cache/ohlc_daily_{TICKER}.json` | `binance_public.py` + `_event_study_common.py` |
| Binance public klines | Non | 1m … 1M (event study: `1d`) | Persist optionnel dans `ohlc_daily_{TICKER}.json` | `binance_public.py` |
| Fear & Greed (demo only) | Non | Journalier | `data/external_cache/fear_greed.json` | `external_signals.py` |

Conventions communes (`src/data/collectors/_common.py`) :

- Chaque row normalisée expose `timestamp` en **secondes Unix UTC** (int).
- Timeout HTTP par défaut : **20 s** (`DEFAULT_HTTP_TIMEOUT_SECONDS`).
- Racine cache : **`data/collector_cache/`** (gitignored).
- Les fetchers sont injectables pour les tests hermétiques (zéro réseau).

---

## DefiLlama

### Endpoints

| Usage | URL |
|-------|-----|
| Supply agrégée stablecoins | `https://stablecoins.llama.fi/stablecoincharts/all` |
| TVL par chaîne | `https://api.llama.fi/v2/historicalChainTvl/{chain}` |

Auth : **aucune**. API gratuite.

### Fonctions

- `fetch_stablecoin_supply(start_iso, end_iso, cache_path=…)` → rows
  `{timestamp, date, source="defillama_stablecoins", total_circulating_usd, total_mcap}`.
- `fetch_chain_tvl(chain, start_iso, end_iso, cache_path=…)` → rows
  `{timestamp, date, source="defillama_chain_tvl", chain, tvl_usd}`.

### Cache

- Fichier : `data/collector_cache/defillama.json` (via
  `default_defillama_cache_path()`).
- Structure : `{ "source": "defillama", "generated_at": "…Z", "entries": { "stablecoin_supply": [...], "chain_tvl_ethereum": [...] } }`.
- Politique : si le cache couvre déjà `[start, end]` jour par jour,
  **aucun appel réseau**. Sinon fetch complet + merge par timestamp.

### Limites connues

- Granularité **journalière** uniquement ; pas d'intra-day.
- Les timestamps sont normalisés à **minuit UTC** du jour d'échantillon.
- Pas de rate limit documentée dans le repo ; en pratique, préférer
  le cache (`--use-cache-only`) pour les runs répétés.

### Consommateur signal

[`src/signals/stablecoin_supply.py`](../src/signals/stablecoin_supply.py)
— z-score sur la variation 7j de `total_mcap`.

---

## Wikimedia Analytics

### Endpoint

```
https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/
  {project}/{access}/{agent}/{article}/daily/{start}/{end}
```

Paramètres par défaut du collector : `project=en.wikipedia`,
`access=all-access`, `agent=all-agents`.

Auth : **aucune**.

### Variable d'environnement

| Variable | Obligatoire | Comportement |
|----------|-------------|--------------|
| `WIKIMEDIA_USER_AGENT` | Non | User-Agent HTTP envoyé sur chaque GET REST. Défaut projet : `KrakenAlphaAgent-Research/1.0 (read-only; contact@example.com)`. Sans User-Agent descriptif, l'API renvoie **HTTP 403**. |

Politique Wikimedia : [User-Agent policy](https://w.wiki/4wJS).

### Fonctions

- `fetch_pageviews(article, start_iso, end_iso, cache_path=…, project=…)`
  → rows `{timestamp, date, source="wikimedia_pageviews", project, article, views}`.
- `wikimedia_http_get_json(url)` — couche HTTP dédiée (User-Agent, timeout 20 s, retry léger sur 429/5xx).

### Cache

- Fichier : `data/collector_cache/wikimedia.json`.
- Clé cache : `pageviews_{project}_{article}` (espaces → underscores).
- Même logique « cache hit si couverture complète des jours » que DefiLlama.

### Limites connues

- Format de date Wikimedia : `YYYYMMDD00` (début) / `YYYYMMDD23` (fin).
- **403 Forbidden** si User-Agent absent ou générique ; corriger via
  `WIKIMEDIA_USER_AGENT` ou le défaut du module.
- Filtrage bots / changements de métrique côté Wikimedia → ruptures
  structurelles possibles (documenté dans le docstring du signal
  `wiki_attention`).
- Retry automatique (2 tentatives) sur 429/503 uniquement ; pas de hammering.

### Consommateur signal

[`src/signals/wiki_attention.py`](../src/signals/wiki_attention.py)
— le script `event_study_wikipedia.py` mappe `views` → `pageviews`.

---

## Etherscan (gas oracle)

### Endpoint

```
https://api.etherscan.io/api?module=gastracker&action=gasoracle
```

Paramètre optionnel : `apikey={ETHERSCAN_API_KEY}`.

### Variable d'environnement

| Variable | Obligatoire | Comportement |
|----------|-------------|--------------|
| `ETHERSCAN_API_KEY` | Non | Lue par `fetch_gas_oracle()` si `api_key` non passé. Sans clé : fetch best-effort ; en cas d'erreur HTTP → **séquence vide** (dégradation gracieuse CI/offline). Avec clé : erreur propagée. |

`.env.example` ne liste pas encore `ETHERSCAN_API_KEY` ; définir la
variable localement dans `.env` si besoin.

### Fonctions

- `fetch_gas_oracle(cache_path=…, api_key=…, max_cache_age_seconds=300)`
  → **une seule row** snapshot :
  `{timestamp, source="etherscan_gas_oracle", safe_gwei, propose_gwei, fast_gwei, has_api_key}`.

### Cache snapshot

- Fichier : `data/collector_cache/etherscan_gas.json`.
- TTL : **300 s** (5 min) via `fetched_at` + `snapshot`.
- Réutilisation : si le cache est frais, pas d'appel réseau.

### Cache historique (limitation majeure — snapshot only)

L'API gas oracle ne fournit **pas** d'historique temporel : une requête
renvoie les prix **courants** uniquement. Il n'y a pas, dans ce repo, de
source HTTP read-only simple pour backfiller des années de gas journalier
(sans scraping agressif ni inventer de données).

Pour `scripts/event_study_eth_gas.py` :

- Fichier append-only : `data/collector_cache/etherscan_gas_history.json`.
- Inventaire et commandes de refresh : [`data/collector_cache/README.md`](../data/collector_cache/README.md).

#### Schéma `etherscan_gas_history.json` (structure — pas de valeurs inventées)

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

Champs lus par le script :

| Champ | Type | Notes |
|-------|------|-------|
| `entries.daily` | `list[object]` | Obligatoire ; rows invalides ignorées |
| `timestamp` | `int` | Secondes Unix ; normalisé à 00:00 UTC du jour |
| `fast_gwei` | `float` | ≥ 0 ; seul prix utilisé par le z-score |

Le snapshot intermédiaire `etherscan_gas.json` a un schéma distinct :

```json
{
  "source": "etherscan",
  "generated_at": "<iso8601_z>",
  "fetched_at": "<unix_int>",
  "snapshot": {
    "timestamp": "<unix_int>",
    "source": "etherscan_gas_oracle",
    "safe_gwei": "<float>",
    "propose_gwei": "<float>",
    "fast_gwei": "<float>",
    "has_api_key": "<bool>"
  }
}
```

#### Minimum de rows

Le signal `eth_gas_congestion` calcule un z-score roulant sur
`lookback` observations (défaut CLI `--lookback 180`). Le script exige
**`lookback + 1`** rows journalières dans `entries.daily` avant de
produire des événements — soit **181 rows** avec les défauts.

Au premier clone, l'historique est vide : le script **échoue** tant
que le cache n'a pas été peuplé (runs quotidiens sans
`--use-cache-only`, ou seed manuel vérifiable).

Exemple **SYNTHETIC** (schéma uniquement, pas pour la recherche) :
[`data/collector_cache/examples/etherscan_gas_history.example.json`](../data/collector_cache/examples/etherscan_gas_history.example.json).

En `--use-cache-only` sans rows : message exact
`blocked: missing historical gas cache` (exit 2).

#### Merge snapshot → history (`resolve_gas_history`)

Implémenté dans `src/data/collectors/etherscan.py`, appelé par
`scripts/event_study_eth_gas.py` :

1. **`load_gas_history`** — lit `entries.daily`, normalise chaque row
   (`timestamp` → minuit UTC, `fast_gwei` ≥ 0).
2. **Sans `--use-cache-only`** — **`fetch_gas_oracle`** +
   **`append_oracle_snapshot_to_history`** :
   - snapshot → `etherscan_gas.json` (TTL 5 min) ;
   - row journalière (jour civil UTC du `timestamp` de fetch) ;
   - **`merge_gas_history`** : union par `timestamp` (écrase le même jour) ;
   - **`persist_gas_history`** : réécrit le JSON history.
3. **Avec `--use-cache-only`** — skip réseau ; si history vide →
   `CollectorError("blocked: missing historical gas cache")`.
4. Si `len(history) < lookback + 1` → exit code 2 avec chemin absolu
   du fichier et lien vers `data/collector_cache/README.md`.

**Conséquence honnête** : un historique gas crédible ne peut pas être
bootstrapé en une seule requête API — seulement jour par jour via le
snapshot, ou import manuel de données tierces vérifiables.

### Limites connues

- Snapshot instantané, pas une série historique native.
- Tier gratuit Etherscan : quotas API non documentés dans ce repo ;
  le TTL 5 min sur le snapshot limite les appels répétés.
- Post-EIP-1559 / L2 : niveaux de gas non stationnaires (cf. signal
  `eth_gas_congestion`).

### Consommateur signal

[`src/signals/eth_gas_congestion.py`](../src/signals/eth_gas_congestion.py)
— z-score sur `fast_gwei`.

---

## Statuspage (Kraken, Coinbase)

### Endpoints

| Venue | URL |
|-------|-----|
| Kraken | `https://status.kraken.com/api/v2/incidents.json` |
| Coinbase | `https://status.coinbase.com/api/v2/incidents.json` |

Auth : **aucune**.

### Fonctions

- `fetch_status_incidents(venue, cache_path=…)` — `venue ∈ {kraken, coinbase}`.
- `fetch_all_status_incidents(cache_path=…)` — merge trié par timestamp.

Rows normalisées :

```text
{timestamp, source="statuspage_incidents", venue, incident_id, name,
 status, impact, started_at, updated_at}
```

`timestamp` = `updated_at` ou `created_at` (ISO-8601 → Unix UTC).

### Cache

- Fichier : `data/collector_cache/status_pages.json`.
- Clés : `incidents_kraken`, `incidents_coinbase`.
- Si le fichier existe et contient la clé, **retour immédiat** sans
  re-fetch (pas de TTL — cache stale jusqu'à refresh manuel ou
  suppression).

### Limites connues

- Événements **sparse** : souvent `< 10` incidents majeurs sur 180j.
- Le signal `exchange_status` mappe `venue` → `provider` ; pas de
  champ `component` granulaire dans le collector (défaut `"trading"`).
- Impact tiers : `minor`, `major`, `critical` (filtre script défaut :
  `major`).

### Consommateur signal

[`src/signals/exchange_status.py`](../src/signals/exchange_status.py).

---

## Kraken REST OHLC (public)

### Endpoint

```
https://api.kraken.com/0/public/OHLC
```

Paramètres : `pair`, `interval` (minutes), `since` (optionnel, Unix s).

Auth : **aucune**. Module :
[`src/crypto_ohlc_rest.py`](../src/crypto_ohlc_rest.py).

Constante code : `KRAKEN_REST_OHLC_CAP_PER_CALL = 720`.

### Cap ~720 candles par appel

Kraken renvoie **au plus ~720 candles par requête REST**, que l'on
paginate ou non. Le paramètre `since` avance le curseur **forward**
(`result.last`) mais **ne permet pas** de remonter au-delà du mur
historique natif que Kraken conserve pour chaque intervalle.

| Intervalle (min) | Profondeur max observée ~ | Fenêtre calendaire ~ |
|------------------|---------------------------|----------------------|
| 15 | ~720 candles | ~7,5 jours |
| 60 | ~720 candles | ~30 jours |
| 240 | ~720 candles | ~90 jours |
| 1440 (journalier) | ~720 candles | ~24 mois |

Pagination (`fetch_crypto_ohlc_paginated`) :

- Assemble plusieurs pages jusqu'à `target_candles` ou mur de profondeur.
- Plafond défensif : **`max_pages=10`** (~7 200 candles théoriques si
  chaque page est pleine — en pratique le mur natif stoppe avant).
- Pause **`0.4 s`** entre pages ; timeout HTTP **20 s** par appel.

### Quand utiliser quel intervalle

| Besoin | Recommandation |
|--------|----------------|
| Event studies (`event_study_*.py`, fenêtre 180 j) | **`interval=1440`** via `fetch_daily_ohlc()` — couvre 180 j+ sans cache disque |
| Walk-forward crypto 60 min (~30 j) | `interval=60`, `target_candles=720` — cache sous `data/ohlc_cache/crypto/` |
| Historique > ~24 mois (daily) ou > ~90 j (4 h) | Kraken REST seul **insuffisant** ; exporter/cache externe ou accepter la fenêtre Kraken |
| xStocks tokenisées | CLI `kraken ohlc --asset-class tokenized_asset` (module séparé `kraken_ohlc_paginated`) — hors scope collectors |

Les scripts event study **ne persistent pas** les OHLC Kraken dans
`data/collector_cache/` par défaut ; chaque run re-frappe Kraken REST
(sauf `--ohlc-source cache` ou `binance-public` avec cache chaud).
Le walk-forward crypto utilise un cache dédié
(`data/ohlc_cache/`, cf. `METHODOLOGY.md` et
`scripts/walk_forward_crypto.py --refresh-cache`).

### `--ohlc-source` (event studies)

Flag commun sur les scripts `event_study_*.py` (via
`scripts/_event_study_common.add_common_event_study_args`) :

| Valeur CLI | Comportement |
|------------|--------------|
| `kraken` (défaut) | Kraken REST journalier, cap ~720 candles |
| `cache` | Lecture seule `data/collector_cache/ohlc_daily_{TICKER}.json` |
| `binance-public` | Binance `/api/v3/klines` intervalle `1d`, pagination 1000 ; persiste le cache si absent/incomplet |

Avec `--use-cache-only` :

- feeds signaux : réseau bloqué (inchangé) ;
- OHLC `kraken` : bascule sur le cache `ohlc_daily_{TICKER}.json` ;
- OHLC `binance-public` : cache requis, pas de fetch ;
- OHLC `cache` : toujours disque seul.

Helper recommandé : `fetch_daily_ohlc_from_args(args)`.

### Fonctions

- `fetch_crypto_ohlc_paginated(pair, interval_min, target_candles, since=…)`
  — pagination forward avec `sleep_between_pages=0.4` s entre pages.
- `normalize_crypto_pair(ticker)` — ex. `BTC` → `XBTUSD`.

Tickers mappés explicitement : BTC/XBT, ETH, SOL, AVAX, LTC, XRP,
DOGE, LINK, ADA, DOT ; autres tickers pass-through `TICKERUSD`.

### Rate limiting (comportement code)

- Timeout HTTP : **20 s** par appel.
- `max_pages=10` (plafond défensif).
- Pause **0,4 s** entre pages réussies.
- Pas de clé API → tier anonyme Kraken ; éviter les backfills
  agressifs en boucle.

---

## Binance public klines (OHLC long)

### Endpoint

```
https://api.binance.com/api/v3/klines
```

Paramètres event study : `symbol=BTCUSDT`, `interval=1d`, `startTime` /
`endTime` (ms), `limit=1000`.

Auth : **aucune**. Module :
[`src/data/collectors/binance_public.py`](../src/data/collectors/binance_public.py).

### Mapping tickers

Même table que Kraken REST pour les majors :
BTC/XBT → `BTCUSDT`, ETH → `ETHUSDT`, etc. Autres tickers :
`{TICKER}USDT`.

### Cache OHLC journalier (`data/collector_cache/`)

Fichier : `ohlc_daily_{TICKER}.json` (ex. `ohlc_daily_BTC.json`).

Schéma :

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

Peuplement :

```powershell
python scripts/event_study_stablecoins.py --ohlc-source binance-public --days 365
python scripts/event_study_stablecoins.py --ohlc-source cache --use-cache-only
```

**Ne pas committer** de gros fichiers OHLC : le répertoire est gitignored.

### Fonctions

- `fetch_binance_daily_klines(ticker, days, fetcher=…)` — pagination read-only.
- `fetch_ohlc_daily_with_cache(…)` — Binance fetch + persist cache.
- `fetch_ohlc_daily_cache_only(…)` — disque seul.
- `default_ohlc_daily_cache_path(ticker)` — chemin `ohlc_daily_{TICKER}.json`.

### Limites connues

- Binance spot USDT ≠ Kraken USD : spreads et gaps possibles ; usage
  **research-only** pour fenêtres > 720 jours Kraken.
- Rate limit anonyme non codée ; pause **0,2 s** entre pages.
- Geo-blocking Binance possible selon juridiction ; fallback = cache manuel.

---

## Fear & Greed (demo uniquement)

Hors package `collectors`, mais utilisé par `demo_event_study.py`.

| | |
|---|---|
| URL | `https://api.alternative.me/fng/?limit=N` |
| Auth | Aucune |
| Cache | `data/external_cache/fear_greed.json` |
| Module | [`src/external_signals.fetch_fear_greed`](../src/external_signals.py) |

Non branché aux scripts `event_study_*.py` de production alternative
— seulement la démo pedagogique du harness placebo + BH.

---

## Signaux sans feed externe

Ces signaux lisent uniquement les timestamps OHLC Kraken :

| Signal | Module | Donnée |
|--------|--------|--------|
| Calendrier (weekend, US open, Asia open) | `calendar_effects.py` | OHLC |
| Expiry options (3e vendredi UTC) | `options_expiry.py` | OHLC (calendrier pur) |
| BTC mempool congestion | `btc_mempool.py` | Requiert `mempool_vsize` (pas de collector mempool dans `src/data/collectors/` à ce jour — signal prêt, feed absent) |

---

## Deribit / expiry options — pas de collector

**Statut : expérimental / cache-only au sens « aucune API Deribit ».**

| | |
|---|---|
| Collector | **Absent** — aucun module `src/data/collectors/deribit*.py` |
| Script | [`scripts/event_study_deribit_expiry.py`](../scripts/event_study_deribit_expiry.py) |
| Signal | [`src/signals/options_expiry.py`](../src/signals/options_expiry.py) — calcule le **3e vendredi UTC** à partir des timestamps OHLC |
| Feed externe | **Aucun** — pas d'open interest, pas de prix d'options Deribit |
| Cache requis | **Aucun** dans `data/collector_cache/` |

Le nom « deribit » dans le script est **historique / motivation
hypothétique** (effet gamma autour des expiries listées). Le harness
mesure seulement si les vendredis d'expiry calendaire corrèlent avec
retour/vol forward sur les candles Kraken — **pas** une réplication
d'un flux Deribit.

**Ne pas présenter ce script comme « ready » ou branché à Deribit.**
Verdict attendu : test de nullité calendaire, pas une alpha options
validée.

---

## Mode offline / CI

Flag commun : **`--use-cache-only`** sur les scripts event study.

| Source | Comportement sans réseau |
|--------|--------------------------|
| DefiLlama / Wikimedia | Échec si cache incomplet pour `[start, end]` |
| Statuspage | OK si `status_pages.json` peuplé |
| Etherscan snapshot | Ignoré en `--use-cache-only` ; history cache requis |
| Kraken OHLC | Réseau sauf `--ohlc-source cache` ou `--use-cache-only` (lit `ohlc_daily_{TICKER}.json`) |
| Binance OHLC | `--ohlc-source binance-public` fetch + cache ; `--use-cache-only` exige cache chaud |
| Fear & Greed (demo) | Échec si cache F&G incomplet |

---

## Variables d'environnement — récapitulatif

| Variable | Sources concernées | Notes |
|----------|-------------------|-------|
| `ETHERSCAN_API_KEY` | Etherscan gas oracle | Optionnelle ; améliore fiabilité tier gratuit |
| `TRADING_MODE`, `LIVE_TRADING`, `ALLOW_LIVE_ORDERS` | **Aucune** dans ce pipeline | Triple opt-in live — irrelevant ici |

Aucune clé Kraken n'est requise pour collectors + OHLC public + event studies.

---

## Backlog Phase 9 (feeds non encore implémentés)

> Inventaire hypothèses : [`HYPOTHESIS_BACKLOG_PHASE_9.md`](HYPOTHESIS_BACKLOG_PHASE_9.md).
> **Aucun collector ci-dessous n'existe dans `src/data/collectors/` à ce jour** — ne pas
> présenter comme « ready ».

| Feed envisagé | Usage backlog | Statut |
|---------------|---------------|--------|
| Mempool.space (BTC vsize) | P9-OC-042 — signal `btc_mempool.py` prêt | **Absent** |
| Google Trends CSV | P9-AT-015, P9-WX-088 | **Absent** (import manuel) |
| FRED macro (DXY, VIX, yields) | P9-MA-* | **Absent** |
| Kraken Futures funding / OI | P9-DV-*, P9-MS-028 | **Absent** |
| Deribit options (IV, OI, DVOL) | P9-DV-055, 059, 062 | **Absent** — distinct de `options_expiry` (calendrier pur) |
| GitHub commits REST | P9-AT-020 | **Absent** |
| Glassnode / Whale Alert | P9-OC-043, 045, 050 | **Hors scope** (payant / licence) |

Signaux **weird** testables sans nouveau collector majeur :
[`WEIRD_BUT_TESTABLE_SIGNALS.md`](WEIRD_BUT_TESTABLE_SIGNALS.md).

---

## Références

- [`ALTERNATIVE_ALPHA_PIPELINE.md`](ALTERNATIVE_ALPHA_PIPELINE.md) — flux complet
- [`HYPOTHESIS_BACKLOG_PHASE_9.md`](HYPOTHESIS_BACKLOG_PHASE_9.md) — 100 hypothèses Phase 9
- [`WEIRD_BUT_TESTABLE_SIGNALS.md`](WEIRD_BUT_TESTABLE_SIGNALS.md) — sous-ensemble weird
- [`data/collector_cache/README.md`](../data/collector_cache/README.md) — chemins cache, refresh, schéma gas history
- [`SIGNAL_REJECTION_POLICY.md`](SIGNAL_REJECTION_POLICY.md) — quand ignorer un feed malgré des chiffres « intéressants »
- Tests hermétiques : `tests/test_collectors_*.py`
