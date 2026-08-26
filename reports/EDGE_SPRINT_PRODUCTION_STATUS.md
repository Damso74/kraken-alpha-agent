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

Deux tâches Windows limitées au compte utilisateur courant sont installables
par `scripts/install_edge_forward_tasks.ps1` :

- `KrakenEdge-H-EXE-Technical`, une session publique de 3 580 secondes chaque
  heure, sans fonction d'ordre ;
- `KrakenEdge-H-WOF-Forward`, une collecte causale quotidienne à 02:15 heure
  locale.

La désinstallation est locale et réversible via
`scripts/uninstall_edge_forward_tasks.ps1`.

## Frontière d'autorisation

Cette production est une production de données et d'observation shadow. Aucun
résultat présent ne justifie une exploitation financière. Le code ne doit pas
passer en paper ou live avant les horizons temporels préenregistrés, le passage
de toutes les gates scientifiques et économiques, puis une autorisation humaine
séparée conformément aux règles live du dépôt.
