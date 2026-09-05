# Kraken Alpha Agent

Répondre en français. Travailler depuis le checkout courant, après vérification de sa branche et de son état Git ; les anciens chemins de projet, hôtes et branches ne décrivent pas nécessairement l'environnement actif. Préserver le travail préexistant. Suivre les plans explicites de l'utilisateur ; déléguer des sous-tâches indépendantes lorsque cela aide et vérifier leurs résultats.

## Périmètre et décisions actuelles

- Réaliser les corrections locales réversibles et contrôles nécessaires jusqu'au résultat demandé. Une optimisation d'instructions ne vaut pas reprise de stratégie, activation live, accès distant ou autorisation de push.
- Avant une reprise de recherche, de stratégie ou de l'observation, consulter la décision maintenue pour cette tâche : si le checkout contient `reports/PHASE31_FINAL_VERDICT.md`, commencer par ce verdict puis les instructions explicites plus récentes ; sinon retrouver la décision autorisée avant toute reprise. Les anciennes notes annoncent successivement observation active et archivée ; elles ne permettent pas de déterminer son état actuel ni de lever un gel. En l'absence d'une décision applicable, préparer le travail local autorisé et signaler le point restant à arbitrer avant toute reprise opérationnelle.
- Ne pas lever le gel historique de `master` ou y fusionner sans décision explicite. Les anciennes permissions de pousser une branche ou un backup privé ne sont pas des autorisations pour une nouvelle mission. Push, publication, déploiement, opération financière ou changement de compte exigent l'autorisation couvrant l'action courante.
- Aucun secret dans les logs, instructions ou rapports ; `.env` reste non suivi, seul `.env.example` est destiné au dépôt. Une ancienne acceptation de risque sur des clés n'autorise pas à les exposer, les réutiliser hors périmètre ou différer une rotation requise par la mission.

## Frontières du moteur

- `dry_run`/simulation par défaut. Aucune opération réelle n'est un test local. Avant toute activité live explicitement demandée, lire [les garde-fous live](docs/agent-guidance/live-safeguards.md) et vérifier autorisation, instruments, compte, profil, scopes, budget et conditions d'arrêt. Ne pas inférer la capacité actuelle d'un compte à partir d'une ancienne erreur API.
- Le triple opt-in `TRADING_MODE=live` + `LIVE_TRADING=true` + `ALLOW_LIVE_ORDERS=true` reste obligatoire, limité à la session et jamais persisté dans `.env` ; il ne remplace pas la confirmation humaine et les autres préconditions.
- Préserver le plafond `HARDCODED_MAX_LEVERAGE = 1.0`, le refus au risk gate et à la construction d'ordre. Ce plafond n'établit aucune équivalence au spot ni absence de risque de marge.
- SELL reste exit-only, sans ouverture short, avec position longue existante et `--reduce-only` sur le moteur futures. Une sortie `is_exit_action=True` doit pouvoir franchir les caps exposition/position sans desserrer `shorting=false`.
- Aucun appel `kraken futures transfer` ou `wallet-transfer`. Les clés Futures sont distinctes des clés Spot : `Trades` + `Positions` seulement ; `Withdrawal`, `Transfer` et `Funding` désactivés. Conserver les gates funding, flatten/hard-stop et le profil futures borné décrits dans la référence.

- Les rejets Futures peuvent porter HTTP 200 et `result=success` : conserver une whitelist stricte des statuts acceptés, `ok=False` pour les rejets et les erreurs explicites ; les statuts dictionnaire de `cancel-after` gardent leur sémantique. Respecter la précision de taille validée et les instruments réellement pris en charge.
- Toute session crypto Option D reste désarmée par défaut, exige `--i-understand-the-risks` et conserve son kill switch à −5 USD. Lire [les préconditions Option D](docs/OPTION_D_ACTIVATION.md) uniquement pour une demande correspondante explicitement autorisée.
## Résultats et publication

- `web/` est le dashboard de soumission : chiffres issus des vrais JSON `web/public/data/backtest_xstocks_*.json`. Ne jamais présenter les données statiques comme live/temps réel ; afficher honnêtement un PnL négatif. Les libellés et preuves exactes de la soumission sont conservés dans [la référence produit](docs/agent-guidance/research-history.md).
- Pour améliorer une stratégie, préserver l'évaluation walk-forward et un test hors échantillon strict : `test_pnl_usd >= 0`, `test_win_rate >= 50%`, `trades_count >= 30`. Le snapshot récent de 30 jours reste dans TEST, jamais dans train. Si aucun candidat ne passe, conserver la configuration et documenter le résultat dans [METHODOLOGY](docs/METHODOLOGY.md), sans chercher à embellir les métriques.
- Les agents chargés de l'UI restent hors des fichiers de trading. Lire [web/AGENTS.md](web/AGENTS.md) pour une tâche web ; une modification de JSON ou d'UI n'autorise pas sa publication.

## Repères et vérification

- CLI, scripts, observations et décisions historiques : [repères par sujet](docs/agent-guidance/research-history.md). Consulter `scripts/README.md` seulement si présent dans ce checkout ; les scripts existants restent sous `scripts/`. Ne lancer que les scripts nécessaires à une demande autorisée, après vérification de leur mode et de leurs effets.
- Pour du Python, utiliser le venv local existant après vérification ; sur Windows, son exécutable direct évite une dépendance à l'activation du shell. Adapter la syntaxe au shell et à l'hôte courants au lieu de réappliquer un ancien contournement réseau.
- Exécuter les tests affectés par le changement ; corriger les régressions introduites puis relancer ces contrôles. La suite `python -m pytest -q` est pertinente pour un changement transversal ou la préparation d'intégration ; une modification documentaire n'exige pas l'exécution du moteur. Vérifier la CI réelle avant d'en annoncer le statut ; les anciens nombres de tests ne sont pas des objectifs ou des preuves actuelles.

Livrer brièvement les fichiers concernés, contrôles `passed` / `failed` / `not run` et limites. Distinguer backtest, simulation, observation, ordre accepté et résultat réel ; aucune affirmation de performance ou d'exécution sans la preuve correspondante.
