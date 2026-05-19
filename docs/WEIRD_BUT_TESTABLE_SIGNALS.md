# Signaux « weird » mais testables — Phase 9

> Compagnon de [`HYPOTHESIS_BACKLOG_PHASE_9.md`](HYPOTHESIS_BACKLOG_PHASE_9.md).
> Ces hypothèses sont **volontairement excentriques** mais falsifiables via
> event study + placebo + BH-FDR — **sans prétendre à un edge tradeable**.
>
> Critères d'inclusion ici : feed public ou calendrier pur, coût d'impl
> faible, risque juridique **faible** (contrairement à la famille
> `P9-LG-*` du backlog principal).

## Philosophie

| Principe | Détail |
|----------|--------|
| Falsifiable vite | Harness existant : `scripts/_event_study_common.py` |
| Honnêteté | Verdict attendu : `not supported, move on` (succès méthodo) |
| Pas de causalité | Corrélation spatio-temporelle ≠ mécanisme |
| Weird ≠ illegal | Voir famille `P9-LG-*` pour les no-go |

## Top 10 — tests rapides recommandés

Ordre = coût marginal croissant avec l'infra actuelle du repo.

| Rang | ID | Nom | Pourquoi « quick » | Test recommandé | Placebo | Verdict cible |
|------|-----|-----|-------------------|-----------------|---------|---------------|
| 1 | P9-WX-083 | Pic pageviews « Recession » | Collector Wikimedia déjà là ; autre article | `event_study_wikipedia.py --article Recession` | 200 tirages aléatoires | weird but quick |
| 2 | P9-WX-088 | Google Trends « buy bitcoin » | Export CSV manuel → cache JSON one-shot | Event study custom rows | shift +30j | weird but quick |
| 3 | P9-CA-040 | Phase lunaire (calendrier pur) | Zéro feed ; dérivé timestamps OHLC | `event_study_calendar.py` flag custom ou script dérivé | vendredis aléatoires | weird but quick |
| 4 | P9-WX-087 | Jour de tirage loterie Powerball | Calendrier public US | Calendrier + OHLC BTC | shuffle dates | weird but quick |
| 5 | P9-AT-020 | Activité GitHub `bitcoin/bitcoin` | API GitHub REST commits/day (rate limit) | Z-score commits → events | random days | weird but quick |
| 6 | P9-WX-091 | Patch Tuesday Microsoft | Calendrier 2e mardi US | Calendrier pur | placebo mois | weird but quick |
| 7 | P9-WX-084 | Incident Steam (Statuspage) | Même pattern que `status_pages.py` | Nouveau venue `steam` si API existe | incidents placebo | weird but quick |
| 8 | P9-WX-089 | Saison meme-coins (dominance) | `external_signals` BTC dominance déjà là | Croiser dominance ↑ + alt vol | F&G placebo | weird but quick |
| 9 | P9-WX-090 | Mercure rétrograde (astro) | Calendrier éphémérides CSV | Events calendrier | shuffle | weird but quick |
| 10 | P9-WX-092 | Vélocité éditions Wikipedia BTC | API Wikimedia edits (si dispo) ou proxy pageviews Δ | Momentum Δviews | article placebo | weird but quick |

## Fiches détaillées (10)

### P9-WX-083 — Attention Wikipedia « Recession »

| Champ | Valeur |
|-------|--------|
| **Intuition** | Peur macro → recherche « Recession » → risk-off crypto court terme. |
| **Pourquoi ça pourrait marcher** | Proxy retail anxiety corrélé aux cycles 2022–2023. |
| **Pourquoi c'est sans doute bullshit** | Article ≠ trade flow ; 403 Wikimedia sans User-Agent (cf. leaderboard). |
| **Dataset** | Wikimedia pageviews journalier |
| **Source** | `wikimedia.py` |
| **Fréquence** | Journalier |
| **Horizon** | post_1 / post_3 / post_7 |
| **Type** | Attention / sentiment proxy |
| **Actifs** | BTC, ETH |
| **Difficulté données** | Faible (après fix UA) |
| **Difficulté impl** | Faible (clone `wiki_attention`) |
| **Risque sur-ajustement** | Élevé (choix article post-hoc) |
| **Risque juridique** | Faible (API publique) |
| **Test** | `event_study_wikipedia.py --article Recession --mode momentum` |
| **Placebo** | Bootstrap timestamps aléatoires (défaut harness) |
| **Raison de rejet attendue** | Non robuste cross-articles ; placebo reproduce hit-rate |
| **Priorité** | 62/100 |
| **Verdict** | weird but quick |

### P9-WX-088 — Google Trends « buy bitcoin »

| Champ | Valeur |
|-------|--------|
| **Intuition** | Pic de recherche retail précède volatilité, pas nécessairement direction. |
| **Pourquoi ça pourrait marcher** | Littérature marketing crypto sur attention retail. |
| **Pourquoi c'est sans doute bullshit** | Trends lissé, retards, Google change l'indexation. |
| **Dataset** | CSV Trends exporté manuellement |
| **Source** | Hors repo → cache `data/collector_cache/google_trends_buy_bitcoin.json` (à créer) |
| **Fréquence** | Hebdo ou journalier |
| **Horizon** | post_7 |
| **Type** | Attention |
| **Actifs** | BTC |
| **Difficulté données** | Moyenne (pas d'API officielle gratuite stable) |
| **Difficulté impl** | Moyenne (collector one-shot) |
| **Risque sur-ajustement** | Très élevé |
| **Risque juridique** | Faible si export manuel utilisateur |
| **Test** | Event study custom après normalisation rows |
| **Placebo** | `shift_events_in_time` +30j |
| **Raison de rejet attendue** | Effet disparait OOS ; retards variables |
| **Priorité** | 48/100 |
| **Verdict** | weird but quick |

### P9-CA-040 — Phase lunaire

| Champ | Valeur |
|-------|--------|
| **Intuition** | Folklore trader ; aucun mécanisme crédible. |
| **Pourquoi ça pourrait marcher** | Ne devrait pas — test de nullité du harness. |
| **Pourquoi c'est sans doute bullshit** | Multiple testing sur ~29 phases/jours. |
| **Dataset** | Éphémérides CSV (NASA/USNO) |
| **Source** | Calendrier externe statique |
| **Fréquence** | ~12–13 nouvelles lunes/an |
| **Horizon** | post_3 |
| **Type** | Calendrier / pseudo-macro |
| **Actifs** | BTC |
| **Difficulté données** | Faible |
| **Difficulté impl** | Faible |
| **Risque sur-ajustement** | Extrême |
| **Risque juridique** | Nul |
| **Test** | Events pleine lune vs nouvelle lune |
| **Placebo** | Jours aléatoires même saisonnalité |
| **Raison de rejet attendue** | BH ne survit pas ; contrôle sanity |
| **Priorité** | 35/100 |
| **Verdict** | weird but quick |

### P9-WX-087 — Jour tirage Powerball

| Champ | Valeur |
|-------|--------|
| **Intuition** | Distraction retail / liquidité marginale US le soir du tirage. |
| **Pourquoi ça pourrait marcher** | Micro-effet session US sur BTC USD. |
| **Pourquoi c'est sans doute bullshit** | N presque nul (~104 tirages / 2 ans). |
| **Dataset** | Calendrier loterie officiel |
| **Source** | Fichier statique |
| **Fréquence** | ~2–3× / semaine |
| **Horizon** | post_1 |
| **Type** | Calendrier comportemental |
| **Actifs** | BTC |
| **Difficulté données** | Faible |
| **Difficulté impl** | Faible |
| **Risque sur-ajustement** | Élevé |
| **Risque juridique** | Nul |
| **Test** | Event study calendrier |
| **Placebo** | Mercredis aléatoires |
| **Raison de rejet attendue** | < 5 events alignés sur fenêtre courte |
| **Priorité** | 40/100 |
| **Verdict** | weird but quick |

### P9-AT-020 — Commits GitHub bitcoin/bitcoin

| Champ | Valeur |
|-------|--------|
| **Intuition** | Activité dev core → narrative technique → vol. |
| **Pourquoi ça pourrait marcher** | Releases majeures corrélées à l'attention. |
| **Pourquoi c'est sans doute bullshit** | Commits ≠ prix ; bots et cherry-picking. |
| **Dataset** | GitHub REST commits/day |
| **Source** | `api.github.com` |
| **Fréquence** | Journalier |
| **Horizon** | post_3 / post_7 |
| **Type** | Attention dev |
| **Actifs** | BTC |
| **Difficulté données** | Moyenne (rate limit, UA) |
| **Difficulté impl** | Moyenne |
| **Risque sur-ajustement** | Moyen |
| **Risque juridique** | Faible (ToS GitHub respectés) |
| **Test** | Z-score commits → events |
| **Placebo** | Bootstrap jours |
| **Raison de rejet attendue** | Clusters sur releases isolées |
| **Priorité** | 45/100 |
| **Verdict** | weird but quick |

### P9-WX-091 — Patch Tuesday Microsoft

| Champ | Valeur |
|-------|--------|
| **Intuition** | IT downtime corporate → risk-off vague → crypto ? |
| **Pourquoi ça pourrait marcher** | Corrélation spurious macro tech. |
| **Pourquoi c'est sans doute bullshit** | Mécanisme inexistant pour BTC on-chain. |
| **Dataset** | Calendrier 2e mardi |
| **Source** | Statique |
| **Fréquence** | Mensuel |
| **Horizon** | post_1 |
| **Type** | Calendrier |
| **Actifs** | BTC, ETH |
| **Difficulté données** | Faible |
| **Difficulté impl** | Faible |
| **Risque sur-ajustement** | Moyen |
| **Risque juridique** | Nul |
| **Test** | `event_study_calendar.py` avec flag dérivé |
| **Placebo** | Mardis aléatoires |
| **Raison de rejet attendue** | Effet non reproductible hold-out |
| **Priorité** | 38/100 |
| **Verdict** | weird but quick |

### P9-WX-084 — Incidents Steam (Statuspage)

| Champ | Valeur |
|-------|--------|
| **Intuition** | Gaming down → jeunes traders distraits ? (très faible). |
| **Pourquoi ça pourrait marcher** | Proxy outage culture internet. |
| **Pourquoi c'est sans doute bullshit** | Aucun lien économique crédible. |
| **Dataset** | Statuspage incidents |
| **Source** | `status.steampowered.com` API v2 (à valider) |
| **Fréquence** | Sparse |
| **Horizon** | post_1 / post_3 |
| **Type** | Attention / outage |
| **Actifs** | BTC |
| **Difficulté données** | Faible |
| **Difficulté impl** | Faible (copie `status_pages.py`) |
| **Risque sur-ajustement** | Faible (peu d'events) |
| **Risque juridique** | Faible |
| **Test** | Event study incidents major |
| **Placebo** | Random timestamps |
| **Raison de rejet attendue** | < 5 incidents / an |
| **Priorité** | 42/100 |
| **Verdict** | weird but quick |

### P9-WX-089 — Saison meme-coins (dominance BTC)

| Champ | Valeur |
|-------|--------|
| **Intuition** | BTC dominance ↓ → rotation alt → vol BTC indirecte. |
| **Pourquoi ça pourrait marcher** | Régime risk-on/off documenté en bull markets. |
| **Pourquoi c'est sans doute bullshit** | Dominance déjà dans `external_signals` ; double comptage. |
| **Dataset** | BTC dominance % |
| **Source** | `external_signals` (CoinGecko ou équivalent) |
| **Fréquence** | Journalier |
| **Horizon** | post_7 |
| **Type** | Régime / attention |
| **Actifs** | BTC, alts basket |
| **Difficulté données** | Faible |
| **Difficulté impl** | Faible |
| **Risque sur-ajustement** | Élevé |
| **Risque juridique** | Faible |
| **Test** | Z-score dominance + event study |
| **Placebo** | F&G placebo |
| **Raison de rejet attendue** | Colinéarité avec F&G demo |
| **Priorité** | 50/100 |
| **Verdict** | weird but quick |

### P9-WX-090 — Mercure rétrograde

| Champ | Valeur |
|-------|--------|
| **Intuition** | Narratif astrologie retail ; test de nullité. |
| **Pourquoi ça pourrait marcher** | Ne devrait pas. |
| **Pourquoi c'est sans doute bullshit** | Astrologie. |
| **Dataset** | CSV éphémérides |
| **Source** | Calendrier statique |
| **Fréquence** | ~3× / an |
| **Horizon** | post_7 |
| **Type** | Calendrier |
| **Actifs** | BTC |
| **Difficulté données** | Faible |
| **Difficulté impl** | Faible |
| **Risque sur-ajustement** | Élevé |
| **Risque juridique** | Nul |
| **Test** | Events début rétrograde |
| **Placebo** | Fenêtres shiftées |
| **Raison de rejet attendue** | N faible ; folklore |
| **Priorité** | 30/100 |
| **Verdict** | weird but quick |

### P9-WX-092 — Vélocité éditions Wikipedia BTC

| Champ | Valeur |
|-------|--------|
| **Intuition** | Guerre d'éditions = controverse → vol. |
| **Pourquoi ça pourrait marcher** | Proxy conflit informationnel. |
| **Pourquoi c'est sans doute bullshit** | Bruit éditorial vs marché. |
| **Dataset** | Wikimedia edits ou Δ pageviews |
| **Source** | Wikimedia |
| **Fréquence** | Journalier |
| **Horizon** | post_3 |
| **Type** | Attention |
| **Actifs** | BTC |
| **Difficulté données** | Moyenne |
| **Difficulté impl** | Moyenne |
| **Risque sur-ajustement** | Élevé |
| **Risque juridique** | Faible |
| **Test** | Z-score Δviews |
| **Placebo** | Article Ethereum contrôle |
| **Raison de rejet attendue** | 403 sans UA ; non robuste cross-article |
| **Priorité** | 55/100 |
| **Verdict** | weird but quick |

## Références

- [`HYPOTHESIS_BACKLOG_PHASE_9.md`](HYPOTHESIS_BACKLOG_PHASE_9.md) — catalogue complet 100 entrées
- [`ALTERNATIVE_ALPHA_PIPELINE.md`](ALTERNATIVE_ALPHA_PIPELINE.md) — harness event study
- [`SIGNAL_REJECTION_POLICY.md`](SIGNAL_REJECTION_POLICY.md) — gates G0–G5
- [`reports/ALPHA_RESEARCH_LEADERBOARD.md`](../reports/ALPHA_RESEARCH_LEADERBOARD.md) — résultats Phase 3
