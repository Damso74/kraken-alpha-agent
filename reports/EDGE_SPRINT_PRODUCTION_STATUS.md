# Edge sprint — état de production shadow

Date de référence : 2026-08-26 UTC

## Verdicts

| Hypothèse | État | Preuve ou prochain gate |
| --- | --- | --- |
| H-QH-001 quarter-hour | Rejetée | 742 trades, PnL net à 20 pb de -1 558,75 USD, win rate 43,94 %, placebo p=0,328934. |
| H-WOF-002 world order flow | Collecte forward-only | Les snapshots historiques officiels d'univers ne sont pas disponibles. Les snapshots causaux Binance et Kraken du 26 août ne peuvent gouverner qu'à partir du lundi 31 août 2026. Verdict interdit avant 30 semaines forward indépendantes et passage de toutes les gates préenregistrées. |
| H-EXE-001 toxicité d'exécution | Production technique shadow | Flux publics Kraken Futures uniquement, zéro credential et zéro ordre. Gate technique interdit avant 14 jours UTC complets à plus de 99 % de couverture et sans gap non résolu. Validation économique ensuite : 30 à 60 jours et au moins 10 000 probes terminés. |

## Production locale

La cible retenue est le poste Windows local : environ 830 Gio libres au moment
du déploiement. Le VPS partagé `vps-ovh` n'est pas retenu car il est déjà à 88 %
d'occupation avec 21 conteneurs actifs. Le serveur Vultr historique n'est pas
utilisé faute d'accès SSH dédié non-root vérifié.

Deux tâches Windows limitées au compte utilisateur courant ont été installées
le 26 août 2026 par `scripts/install_edge_forward_tasks.ps1` :

- `KrakenEdge-H-EXE-Technical`, une session publique de 3 580 secondes chaque
  heure, sans fonction d'ordre ;
- `KrakenEdge-H-WOF-Forward`, une collecte causale quotidienne à 02:15 heure
  locale ;
- `KrakenEdge-Forward-Health`, un contrôle fail-closed toutes les quinze minutes
  de la configuration, de la fraîcheur des données et de la réserve disque.

Le premier lancement planifié H-WOF a terminé avec le code `0` en état
`bootstrap-pending`, après vérification des snapshots. La première session
longue H-EXE a révélé une socket TLS vivante sans événements marché. Les deux
canaries pré-correction ont été préservés sous
`data/collector_cache/archive/` et sont exclus de la phase technique.

L'amendement opérationnel impose désormais une reconnexion avec snapshots frais
après 15 secondes sans événement marché normalisé ; les trames de contrôle ne
réinitialisent pas ce watchdog. Un `progress.json` atomique matérialise en plus
la progression toutes les cinq secondes, indépendamment du buffering gzip.

Le smoke final de 60 secondes `20260826T185910.090273Z` a produit 34 698
messages marché normalisés, 34 896 lignes raw (1 300 384 octets compressés), un
heartbeat hashé de 34 896 événements, zéro gap, zéro credential et zéro ordre.
La production corrigée a redémarré dans la session
`20260826T190049.911965Z` ; son heartbeat comptait déjà 15 363 événements après
vingt secondes.

La désinstallation est locale et réversible via
`scripts/uninstall_edge_forward_tasks.ps1`.

## Frontière d'autorisation

Cette production est une production de données et d'observation shadow. Aucun
résultat présent ne justifie une exploitation financière. Le code ne doit pas
passer en paper ou live avant les horizons temporels préenregistrés, le passage
de toutes les gates scientifiques et économiques, puis une autorisation humaine
séparée conformément aux règles live du dépôt.
