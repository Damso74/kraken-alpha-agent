# H-WOF-002 — exploitation forward-only

Ce runbook concerne uniquement la collecte publique et l'observation. Il
n'active ni paper trading, ni live, ni ordre.

## Univers Kraken public et borné

Le CLI capture automatiquement l'endpoint public officiel Kraken
`/0/public/AssetPairs?assetVersion=1`, sans clé. Il conserve uniquement :

- les paires Spot `currency`, `lot=unit`, `status=online` ;
- les quotes USD, puis USDT, puis USDC par ordre de priorité ;
- les actifs crypto, hors fiat, stablecoins et xStocks ;
- une seule paire long-only par actif.

Si plus de 80 actifs survivent, les 80 premiers tickers en ordre lexical sont
retenus : règle déterministe, causale et indépendante des rendements. Moins de
30 actifs provoque un refus. Le fichier quotidien et son manifeste contiennent
l'URL officielle, `assetVersion=1`, l'horodatage, la sélection complète et les
SHA-256.

Capture manuelle possible pour initialiser le journal :

```powershell
.\.venv\Scripts\python.exe `
  scripts\collect_world_order_flow_forward.py snapshot-kraken
```

## Bootstrap

Capturer un premier snapshot sans tenter de reconstruire le passé :

```powershell
.\.venv\Scripts\python.exe `
  scripts\collect_world_order_flow_forward.py snapshot

.\.venv\Scripts\python.exe `
  scripts\collect_world_order_flow_forward.py snapshot-kraken
```

Le snapshot capturé pendant une semaine ne gouverne jamais rétroactivement
cette semaine. Il pourra servir à partir du lundi suivant. Avant cela, un refus
`bootstrap incomplete` est normal et protège contre le biais rétrospectif.

## Collecte quotidienne

Après la clôture UTC de la journée précédente :

```powershell
.\.venv\Scripts\python.exe `
  scripts\collect_world_order_flow_forward.py collect `
  --minimum-assets 30 --maximum-assets 80
```

Chaque exécution :

1. capture au plus un snapshot Binance `exchangeInfo` par jour UTC ;
2. capture au plus un snapshot Kraken `AssetPairs` public par jour UTC ;
3. choisit les deux snapshots antérieurs au lundi de la journée cible ;
4. intersecte les univers et télécharge seulement les klines publiques 1d closes ;
5. écrit `days/YYYY-MM-DD.json` atomiquement ;
6. ajoute un enregistrement hashé à `manifest.jsonl`.

La tâche planifiée utilise `collect-scheduled`. Cette variante conserve les
mêmes refus fail-closed, mais considère l'attente causale de la première semaine
comme un bootstrap sain après capture et vérification des deux snapshots. Toute
autre erreur conserve un code de sortie non nul.

Une répétition produit un cache hit sans réseau. Une interruption après
l'écriture du fichier quotidien est récupérée en ajoutant le manifeste attendu,
sans réécrire les données. Aucun téléchargement `aggTrades` n'est effectué.

## Vérification hors réseau

```powershell
.\.venv\Scripts\python.exe `
  scripts\collect_world_order_flow_forward.py collect `
  --cache-only

.\.venv\Scripts\python.exe `
  scripts\collect_world_order_flow_forward.py healthcheck

.\.venv\Scripts\python.exe `
  scripts\collect_world_order_flow_forward.py digest
```

`healthcheck` vérifie les snapshots, les chemins canoniques, tous les SHA-256,
la provenance, les doublons, la chronologie et le retard. `digest` retourne un
résumé stable adapté à une alerte ou une tâche planifiée. Code retour : `0` si
sain, `2` si incomplet, en retard ou corrompu.

Le CLI interdit `--as-of-date` avec une capture réseau : cette option est
réservée aux vérifications cache-only afin d'empêcher un faux backfill causal.
