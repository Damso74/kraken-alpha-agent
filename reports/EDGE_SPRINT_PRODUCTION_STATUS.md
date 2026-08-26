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

La session `20260826T193742.767936Z` a démontré le redémarrage en moins de vingt
secondes et dépassé 42 320 événements ; elle appartient désormais à la preuve
pré-gel conservée dans les archives, pas à l'horizon technique courant.

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

La chaîne de décision WOF est également matérialisée avant le premier jour
causal. Chaque jour et outcome scelle les hashes du pré-enregistrement, du
collecteur, du harnais d'analyse et de l'évaluateur. Le moniteur crée un
baseline cache-only pour chaque couple journal/sources, puis exige sa
reproduction exacte dans un processus ultérieur. Un reçu CI séparé doit être
lié aux mêmes hashes. Le contrôle réel à 20:11 UTC a reproduit exactement le
journal vide de bootstrap, mais retourne correctement `collecting`, `NO-GO`,
zéro semaine éligible et aucune autorisation paper/live.

Le premier reçu CI WOF ne liait que les sources scientifiques à Ruff et pytest.
Avant la première semaine causale, ce gate a été durci pour sceller les 385
fichiers suivis du périmètre CI et exiger également `bash -n`, ShellCheck,
`git diff --exit-code` et un worktree sans fichier non suivi. Le reçu courant
WOF est `beb70f71166d9187a36f19d45b6779379e6e903334b0e3a0f383d795ac23d88c` ;
le scope commun est
`98cee88ef3981b37876b129ac498dd12894c27abe4f753ca41f9f7455f45643e`.
Le moniteur réel lit `ci_verified=true` et `reproduction_verified=true`, sans
que ces preuves puissent contourner l'horizon : le verdict reste `collecting`,
`NO-GO` avec zéro semaine.

Avant le premier jour UTC complet H-EXE, le gate 8 a été rendu falsifiable : les
deux moitiés temporelles, chaque retrait d'un jour et chaque retrait d'un probe
doivent conserver au moins 5 bps en primaire et sous stress. L'évaluateur final
vérifie ensuite les manifests de validation, les couvertures journalières, les
hashes, les invariants de sécurité, le rejeu raw exact et un reçu CI lié aux
mêmes sources. Un `connection_id` monotone est scellé dans chaque événement raw
afin de reproduire les abandons de probes lors des reconnexions.

Les données collectées avant cette définition puis avant l'évaluateur complet
ont été préservées, sans suppression, sous
`archive/h_exe_pre_gate8_definition_20260826T203006Z` et
`archive/h_exe_pre_frozen_evaluator_20260826T205009Z`. La période technique
alors gelée est repartie avec la session `20260826T205010.286268Z`. Son premier
fichier raw porte bien `connection_id=1`. L'attestation associée au jeu de
sources `9d7e12c77399eeb6ace6930e37d31e00cb440f383c46e7ba8985e8b6c084266c`
a passé Ruff sur `src tests scripts` et les 1 175 tests sous transport mock,
`TRADING_MODE=dry_run` et les deux verrous live à `false`.

Le contrôle de production effectué après ce redémarrage retourne `healthy=true`
et zéro erreur, avec environ 783 Gio libres. H-EXE reste
`technical_gate_pending`, `NO-GO`; H-WOF reste `collecting`, `NO-GO`, avec ses
preuves de reproduction et CI valides. Aucun de ces états n'autorise le paper ou
le live.

L'audit du reçu CI a ensuite démontré qu'un changement de test ou de script non
scientifique pouvait laisser un ancien reçu apparemment valide. Avant le premier
jour UTC complet, l'attestation commune H-EXE/H-WOF a donc été liée aux 385
fichiers suivis et au workflow complet. L'état précédent a été préservé sous
`archive/h_exe_pre_full_ci_scope_20260826T211811Z` et
`archive/h_wof_pre_full_ci_scope_20260826T211811Z`. H-EXE repart définitivement
avec la session `20260826T211815.791884Z` et le reçu
`28aba9fa3f8cbe170d9864c89c99ceec53ebfcc2db643540ad9ccfe2bb751542`.
H-WOF a recapturé les deux snapshots du 26 août avec les nouveaux hashes. Deux
processus de contrôle successifs ont établi puis reproduit exactement son
baseline ; l'état global reste `healthy=true`, zéro credential, zéro ordre.

Un contrôle supplémentaire a détecté que la relance manuelle de cette session
n'avait pas déplacé le déclencheur initial à `:38`. L'occurrence suivante aurait
été ignorée pendant le run, créant ensuite environ 49 minutes sans collecte. La
définition Task Scheduler antérieure a été sauvegardée sous
`archive/task_scheduler_realign_20260826T210149Z`, puis le déclencheur a été
réaligné sans interrompre le processus : fin nominale à 23:49:50 locale,
prochaine occurrence à 23:50:10, soit 20 secondes de marge. Le healthcheck
manuel échoue désormais explicitement sur tout chevauchement ou trou supérieur
à 60 secondes.

La désinstallation est locale et réversible via
`scripts/uninstall_edge_forward_tasks.ps1`.

## Frontière d'autorisation

Cette production est une production de données et d'observation shadow. Aucun
résultat présent ne justifie une exploitation financière. Le code ne doit pas
passer en paper ou live avant les horizons temporels préenregistrés, le passage
de toutes les gates scientifiques et économiques, puis une autorisation humaine
séparée conformément aux règles live du dépôt.
