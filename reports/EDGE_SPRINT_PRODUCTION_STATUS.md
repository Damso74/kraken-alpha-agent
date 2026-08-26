# Edge sprint — état de production shadow

Date de référence : 2026-08-26 UTC

## Verdicts

| Hypothèse | État | Preuve ou prochain gate |
| --- | --- | --- |
| H-QH-001 quarter-hour | Rejetée | 742 trades, PnL net à 20 pb de -1 558,75 USD, win rate 43,94 %, placebo p=0,328934. |
| H-WOF-002 world order flow | Collecte forward-only | Les snapshots historiques officiels d'univers ne sont pas disponibles. Les snapshots causaux Binance et Kraken du 26 août ne peuvent gouverner qu'à partir du lundi 31 août 2026. Aucun verdict avant 30 semaines forward indépendantes ; un candidat exige en plus les gates cumulatives, dont 100 semaines éligibles et 30 semaines exposées. |
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

Le smoke watchdog de 60 secondes `20260826T185910.090273Z` a produit 34 698
messages marché normalisés, 34 896 lignes raw (1 300 384 octets compressés), un
heartbeat hashé de 34 896 événements, zéro gap, zéro credential et zéro ordre.
Cette phase pré-audit de capacité a ensuite été archivée sans suppression.

Un audit de capacité a ensuite mesuré 24,28 Gio/jour réservés sur le JSON non
compressé contre 1,75 Gio/jour réellement écrit. Le quota aurait été atteint en
4,12 jours. Avant le premier jour UTC complet, le budget a été corrigé pour
réserver les blocs gzip exacts et le plafond physique porté à 200 Gio, soit
environ 114 jours au débit observé pour un horizon maximal de 60 jours.

Le smoke physique final `20260826T191516.107215Z` est valide : 33 007 messages,
33 205 lignes raw, 898 949 octets gzip et 899 319 octets projetés globalement,
sans mismatch de hash, credential ni ordre. La production gelée active est la
session `20260826T191702.344218Z`, dont le heartbeat est alimenté toutes les cinq
secondes. La tâche utilise désormais explicitement `--storage-cap-gib 200`.

Cette première occurrence longue a ensuite subi un trou de marché supérieur à
cinq minutes puis un blocage d'ouverture TLS. Elle a été arrêtée, journalisée
dans `technical/ops/incidents.jsonl` et déplacée sans suppression vers
`data/collector_cache/archive/h_exe_stalled_connect_20260826T191702.344218Z_*`.
Le diagnostic a aussi révélé que la priorité Task Scheduler par défaut (`7`,
`BelowNormal`) pouvait bloquer Python jusque dans ses imports sous charge disque.
Les trois tâches utilisent maintenant la priorité normale `4`.

La session active finale est `20260826T193742.767936Z`. Elle a démarré en moins
de vingt secondes, dépassé 42 320 événements, et le contrôle planifié Python a
terminé avec le code `0` et `healthy=true`.

L'audit de bout en bout H-WOF a ensuite révélé que le premier journal ne
capturait pas encore les prix Kraken d'entrée et de sortie exigés par le
pré-enregistrement. Avant le début de la première semaine causale, le run
planifié a été complété par une finalisation hebdomadaire append-only : après
clôture, elle agrège les sept jours, exige les deux opens Kraken 1h exacts pour
chaque membre et écrit un outcome avec manifeste SHA-256. Le moniteur de quinze
minutes vérifie désormais le journal WOF complet, y compris les outcomes mûrs,
et non plus uniquement la fraîcheur des snapshots. Au contrôle du 26 août à
19:51 UTC, l'état réel est `bootstrap-pending`, sans erreur, avec zéro outcome
attendu. La première issue possible pour la semaine source du 31 août sera
finalisée au plus tôt lors du run du 15 septembre 2026.

La désinstallation est locale et réversible via
`scripts/uninstall_edge_forward_tasks.ps1`.

## Frontière d'autorisation

Cette production est une production de données et d'observation shadow. Aucun
résultat présent ne justifie une exploitation financière. Le code ne doit pas
passer en paper ou live avant les horizons temporels préenregistrés, le passage
de toutes les gates scientifiques et économiques, puis une autorisation humaine
séparée conformément aux règles live du dépôt.
