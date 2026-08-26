# H-EXE-001 — exploitation locale technique

Cette couche lance uniquement une collecte publique shadow bornée. Elle
n'installe aucun service, ne lit aucun secret et ne possède aucune commande
d'ordre.

## Exécution manuelle bornée

Depuis PowerShell, dans le worktree :

```powershell
.\.venv\Scripts\python.exe `
  scripts\run_execution_toxicity_ops_once.py `
  --duration-seconds 3580
```

Le superviseur crée une session horodatée immuable. Si le WebSocket tombe, il
recrée un collecteur vide : les séquences et le carnet précédents ne sont jamais
réutilisés, les probes en attente sont abandonnés, et de nouveaux snapshots book
et trade sont obligatoires. Une absence totale d'événement marché normalisé
pendant 15 secondes est traitée comme une rupture récupérable, même si la socket
TLS reste ouverte et continue d'émettre des trames de contrôle.

Les chemins runtime, ignorés par Git, sont :

- `data/collector_cache/kraken_execution_toxicity_hexe001/technical/sessions/` ;
- journal append-only `technical/sessions.jsonl` ;
- digests immuables `technical/ops/digests/` ;
- gates éventuels `technical/ops/technical_gates/`.

Le verrou `.ops-once.lock` empêche deux occurrences simultanées. Un verrou resté
après un arrêt brutal doit être examiné manuellement ; le programme ne le force
jamais ni ne tue un autre processus.

Le plafond de 200 Gio physiques est unique pour tout l'output root, toutes
sessions et tous types d'artefacts confondus. Les writers raw et observations
partagent le même budget pendant une occurrence ; l'occurrence suivante
recompte l'ensemble des fichiers déjà présents. Les lignes sont compressées en
blocs gzip bornés avant réservation, de sorte que le quota comptabilise les
octets réellement écrits. Aucun writer ne dispose de son propre quota
additionnel.

## Task Scheduler — installation locale

- périodicité : toutes les heures ;
- action : la commande ci-dessus avec `--duration-seconds 3580` ;
- fenêtre inter-run nominale : 20 secondes, soit 99,44 % de couverture avant
  les pertes réseau ;
- répertoire de démarrage : le worktree ;
- règle de chevauchement : ne pas démarrer une nouvelle instance ;
- exécution sous un compte utilisateur non administrateur ;
- le passage sur batterie ne tue pas une occurrence déjà lancée ;
- redémarrage après échec autorisé, sans élévation de privilèges.

Le dépôt fournit un installateur idempotent qui refuse d'écraser une tâche
existante sans option explicite :

```powershell
.\scripts\install_edge_forward_tasks.ps1
```

Il installe également la collecte quotidienne H-WOF-002 à 02:15 heure locale.
Une troisième tâche `KrakenEdge-Forward-Health` vérifie toutes les quinze
minutes les actions enregistrées, la fraîcheur du raw H-EXE et des snapshots
WOF, ainsi qu'une réserve disque minimale de 250 Gio. Elle produit des digests
JSON immuables sous `data/collector_cache/edge_forward_health/` et retourne un
code non nul fail-closed en cas d'anomalie. L'exécution planifiée vérifie les
données et le disque sans réinterroger Task Scheduler depuis son propre contexte
d'exécution ; une invocation manuelle du même script ajoute le contrôle exact
des actions enregistrées. Les tâches utilisent le venv propre au worktree et le
compte utilisateur courant avec un niveau d'exécution limité.

Le plan d'alimentation Windows n'est pas modifié. Sur cette machine, la veille
reste désactivée sur secteur mais intervient après dix minutes sur batterie ;
une telle veille suspend la collecte et la période correspondante ne peut pas
compter dans la couverture UTC de 99 %.

Chaque session H-EXE publie aussi un `progress.json` atomique toutes les cinq
secondes lorsqu'elle reçoit des événements normalisés. Ce fichier mutable est
une preuve d'activité opérationnelle uniquement ; il est exclu des données
scientifiques append-only puis hashé dans le résumé immuable à la fin du run.
La désinstallation réversible est :

```powershell
.\scripts\uninstall_edge_forward_tasks.ps1
```

Une occurrence est volontairement bornée afin qu'un ordonnanceur puisse la
relancer et contrôler son état. La couverture journalière minimale est 99 % ; un
jour sous ce seuil ne compte pas parmi les quatorze jours complets. La couverture
est la fusion des fenêtres de chaque connexion ; l'intervalle entre une rupture
et son nouveau snapshot n'est jamais compté comme observé.

## Healthcheck sans collecte

```powershell
C:\Code\perso\kraken-alpha-agent\.venv\Scripts\python.exe `
  scripts\run_execution_toxicity_ops_once.py --health-only
```

Le healthcheck recalcule les hashes courants, vérifie le journal et les résumés
immuables, fusionne les fenêtres par jour UTC et produit un digest. Il n'émet un
`technical_gate` que lorsque :

- quatorze jours UTC terminés dépassent 99 % de couverture ;
- toutes les sessions retenues sont valides ;
- aucun gap de séquence non résolu n'existe ;
- les hashes du pré-enregistrement, du collecteur, du superviseur, du moteur, des
  opérations et des deux runners correspondent exactement au code courant.

Un gate autorise seulement le démarrage manuel de la collecte de validation. Il
n'autorise aucun ordre, passage paper/live ni déploiement.
