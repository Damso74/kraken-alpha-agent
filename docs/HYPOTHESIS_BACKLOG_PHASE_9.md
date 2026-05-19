# Backlog d'hypothèses alpha — Phase 9 (100 idées)

> **Docs only — aucun code.** Inventaire structuré pour le pipeline alpha
> alternatif read-only ([`ALTERNATIVE_ALPHA_PIPELINE.md`](ALTERNATIVE_ALPHA_PIPELINE.md)).
>
> **Aucune de ces entrées ne constitue une promesse de rentabilité, de PnL,
> ou de « signal tradeable ».** Les scores de priorité classent l'intérêt
> **méthodologique** (falsifiabilité, coût, alignement infra) — pas l'espérance
> de gain.

## Contexte repo (Phase 3 → 9)

| Fait documenté | Implication backlog |
|----------------|---------------------|
| Leaderboard Phase 3 : **0** signal live-ready | Verdicts par défaut = rejet ou backlog |
| `calendar_weekend_start` 730j → `not supported` | Famille calendrier : prudence extrême |
| `stablecoin_supply` 365j → **0 events** | Revoir seuils avant OOS |
| Wikipedia → **403** sans User-Agent | P9-AT-011 bloqué jusqu'à fix collector |
| ETH gas → **0 rows** history | P9-OC-041 bloqué jusqu'à seed cache |
| Compte PEDSL-CY : xStocks API **Permission denied** | Famille P9-XS-* = backlog gelé, pas live |
| `event_study_deribit_expiry` = calendrier pur | Pas de feed Deribit — pas de prétention options |

## Légende des champs

| Champ | Description |
|-------|-------------|
| `hypothesis_id` | Identifiant stable `P9-{famille}-{nnn}` |
| `name` | Nom court |
| `intuition` | Story en une phrase |
| `why_might_work` | Mécanisme plausible (pas une promesse) |
| `why_probably_bullshit` | Objection principale |
| `dataset` | Nature des rows |
| `source` | API / module / calendrier |
| `frequency` | Cadence des events |
| `horizon` | Fenêtres event study (`post_1/3/7`) |
| `signal_type` | Taxonomie interne |
| `assets` | Paires cibles Kraken REST |
| `data_difficulty` | 1–5 (1 = trivial) |
| `impl_difficulty` | 1–5 |
| `overfit_risk` | faible / moyen / élevé / extrême |
| `legal_risk` | faible / moyen / **no-go** |
| `recommended_test` | Script ou protocole |
| `placebo` | Contrôle falsification |
| `rejection_reason` | Motif attendu si échec |
| `priority_score` | 0–100 (méthodo, pas PnL) |
| `verdict` | `implement now` \| `later` \| `weird but quick` \| `kill` |

**Familles :** `SC` stablecoins · `AT` attention · `MS` microstructure · `CA` calendar ·
`OC` on-chain · `DV` derivatives · `MA` macro · `XS` xStocks gelé · `WX` weird · `LG` legal no-go

---

## Synthèse exécutive

| Métrique | Valeur |
|----------|--------|
| Entrées totales | 100 |
| `implement now` | 12 |
| `later` | 47 |
| `weird but quick` | 10 (détail : [`WEIRD_BUT_TESTABLE_SIGNALS.md`](WEIRD_BUT_TESTABLE_SIGNALS.md)) |
| `kill` | 31 (dont 8 legal no-go `P9-LG-*` ; voir § 10 kill immédiats) |

---

## Top 20 classées (priorité méthodologique)

| Rang | ID | Nom | Score | Verdict | Justification courte |
|------|-----|-----|-------|---------|----------------------|
| 1 | P9-AT-011 | Wikipedia BTC momentum | 78 | implement now | Script + signal existants ; bloqué 403 — fix UA = déblocage immédiat |
| 2 | P9-OC-041 | ETH gas congestion z-high | 76 | implement now | Signal + script existants ; seed `etherscan_gas_history.json` |
| 3 | P9-SC-001 | Supply stablecoins z-high 7j | 74 | implement now | Déjà run ; 0 events → baisser z ou allonger fenêtre **pré-enregistré** |
| 4 | P9-CA-032 | Ouverture session US (ET) | 72 | implement now | `calendar_effects.py` + `event_study_calendar.py` prêts |
| 5 | P9-MS-021 | Vol réalisée week-end BTC | 70 | implement now | OHLC seul ; weekend_start déjà testé négatif — variante vol |
| 6 | P9-AT-017 | Fear & Greed extrême peur | 68 | later | Demo `weak evidence` — pas promotion sans harness complet multi-actifs |
| 7 | P9-MS-028 | Funding rate perp extrême | 67 | later | Kraken Futures public ou collector dédié |
| 8 | P9-OC-042 | BTC mempool vsize z-high | 66 | later | Signal `btc_mempool.py` sans collector — feed à ajouter |
| 9 | P9-SC-002 | Supply stablecoins z-low | 65 | implement now | Symétrique SC-001 ; même infra |
| 10 | P9-CA-037 | 3e vendredi expiry (calendrier) | 64 | implement now | Script `deribit_expiry` — nullité calendaire |
| 11 | P9-MS-023 | Volume spike z-score journalier | 63 | implement now | Dérivé OHLC pur |
| 12 | P9-AT-012 | Wikipedia Ethereum | 62 | implement now | Même fix UA que BTC |
| 13 | P9-OC-048 | TVL Ethereum DefiLlama | 61 | later | `fetch_chain_tvl` existe ; signal à écrire |
| 14 | P9-DV-053 | Funding BTC flip signe | 60 | later | Données futures Kraken |
| 15 | P9-MA-065 | Proxy VIX risk-off | 59 | later | Import CSV macro |
| 16 | P9-WX-083 | Pageviews « Recession » | 58 | weird but quick | Voir doc weird |
| 17 | P9-MS-025 | Range HL / close proxy spread | 57 | implement now | OHLC ; intra-day lissé |
| 18 | P9-SC-006 | Net mint/burn stablecoins | 56 | later | Dérivé DefiLlama |
| 19 | P9-CA-034 | Fin de mois rebalancing | 55 | later | Calendrier pur |
| 20 | P9-DV-057 | Gamma pinning 3e vendredi | 54 | later | Extension calendrier ; pas de OI |

---

## 10 tests « weird » rapides

Voir fiches complètes : [`WEIRD_BUT_TESTABLE_SIGNALS.md`](WEIRD_BUT_TESTABLE_SIGNALS.md).

| ID | Nom | Score |
|----|-----|-------|
| P9-WX-083 | Wikipedia « Recession » | 62 |
| P9-WX-088 | Google Trends « buy bitcoin » | 48 |
| P9-CA-040 | Phase lunaire | 35 |
| P9-WX-087 | Jour tirage Powerball | 40 |
| P9-AT-020 | Commits GitHub bitcoin/bitcoin | 45 |
| P9-WX-091 | Patch Tuesday | 38 |
| P9-WX-084 | Incidents Steam | 42 |
| P9-WX-089 | Saison meme-coins (dominance) | 50 |
| P9-WX-090 | Mercure rétrograde | 30 |
| P9-WX-092 | Vélocité éditions Wikipedia | 55 |

---

## 10 « kill » immédiats (ne pas investir de cycles)

| ID | Nom | Raison kill |
|----|-----|-------------|
| P9-LG-093 | Volume marchés dark web | Source illégale / non reproductible / ToS |
| P9-LG-094 | Front-run wallets « insider » | Données non publiques ; équivalent délit d'initié |
| P9-LG-095 | Trading sur flux hacks exchange | Profite de crime ; compliance |
| P9-LG-096 | Flux sanctions contournement | Violation sanctions / AML |
| P9-LG-097 | Scraping Twitter/X sans API | Violation ToS plateforme |
| P9-LG-098 | Groupes Telegram payants « alpha » | Pas de licence ; souvent fraude |
| P9-LG-099 | Copy MEV sandwich | Ethique + latence impossible retail |
| P9-LG-100 | Front-run Statuspage pré-publication | Accès privilégié ; potentiellement illégal |
| P9-XS-076 | Arb spot tokenisé vs equity | **Permission denied** PEDSL-CY — pas d'exécution |
| P9-XS-077 | Perp xStocks funding trade | **wouldNotReducePosition** — ouverture impossible |

---

## Catalogue complet (100 entrées)

Format compact : chaque bloc liste tous les champs requis.

---

### Famille SC — Stablecoins (10)

#### P9-SC-001 — Expansion supply stablecoins (z-high 7j)

| Champ | Valeur |
|-------|--------|
| Intuition | Liquidité fiat-on-chain ↑ → pression achat BTC |
| Pourquoi ça pourrait marcher | Couche collatérale du marché crypto |
| Pourquoi bullshit | Déjà testé 365j : **0 events** à z≥1,5 |
| Dataset | DefiLlama supply journalier |
| Source | `defillama.py` / `stablecoin_supply.py` |
| Fréquence | ~quelques events/an à seuil strict |
| Horizon | post_7 |
| Type | Flux liquidité |
| Actifs | BTC |
| Data diff / Impl diff | 1 / 1 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | `event_study_stablecoins.py --direction high --z-threshold 1.0` |
| Placebo | Bootstrap 200 (défaut) |
| Rejet attendu | Placebo = baseline ; seuil arbitraire |
| Priorité | **74** |
| Verdict | **implement now** |

#### P9-SC-002 — Contraction supply (z-low 7j)

| Champ | Valeur |
|-------|--------|
| Intuition | Retrait liquidité → risk-off |
| Pourquoi ça pourrait marcher | Symétrique SC-001 |
| Pourquoi bullshit | Même feed ; corrélation régime bear |
| Dataset | DefiLlama |
| Source | idem |
| Fréquence | Sparse |
| Horizon | post_7 |
| Type | Flux liquidité |
| Actifs | BTC, ETH |
| Data / Impl | 1 / 1 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | `--direction low` |
| Placebo | Bootstrap |
| Rejet | Non significatif BH |
| Priorité | 65 |
| Verdict | implement now |

#### P9-SC-003 — Dominance USDT dans supply totale

| Champ | Valeur |
|-------|--------|
| Intuition | Fuite vers USDT = risk-off |
| Pourquoi ça pourrait marcher | USDT = parking bear |
| Pourquoi bullshit | Définition dominance change selon DefiLlama |
| Dataset | DefiLlama (dérivé) |
| Source | `defillama.py` |
| Fréquence | Mensuel |
| Horizon | post_7 |
| Type | Régime |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Nouveau dérivé + event study |
| Placebo | shift +30j |
| Rejet | Colinearité supply totale |
| Priorité | 48 |
| Verdict | later |

#### P9-SC-004 — Stress dépeg USDC (proxy)

| Champ | Valeur |
|-------|--------|
| Intuition | Dépeg → panique marché |
| Pourquoi ça pourrait marcher | Mars 2023 SVB |
| Pourquoi bullshit | Events rares ; besoin prix USDC/USD |
| Dataset | Prix + supply |
| Source | DefiLlama + Kraken USDC/USD |
| Fréquence | Très sparse |
| Horizon | post_1 |
| Type | Stress |
| Actifs | BTC, ETH |
| Data / Impl | 4 / 3 |
| Sur-ajustement | faible (N petit) |
| Juridique | faible |
| Test | Seuil \|peg-1\| > 0,5 % |
| Placebo | jours aléatoires |
| Rejet | < 5 events |
| Priorité | 40 |
| Verdict | later |

#### P9-SC-005 — Accélération 2e dérivée supply 14j

| Champ | Valeur |
|-------|--------|
| Intuition | Choc de vélocité plus que niveau |
| Pourquoi ça pourrait marcher | Anticipation |
| Pourquoi bullshit | Bruit sur série lissée |
| Dataset | DefiLlama |
| Source | idem |
| Fréquence | Moyenne |
| Horizon | post_3 |
| Type | Flux |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Z-score Δ² supply |
| Placebo | Bootstrap |
| Rejet | Double diff = overfit |
| Priorité | 42 |
| Verdict | later |

#### P9-SC-006 — Net mint/burn journalier agrégé

| Champ | Valeur |
|-------|--------|
| Intuition | Mint net = entrée capitale |
| Pourquoi ça pourrait marcher | Flux marginal |
| Pourquoi bullshit | Révisions données DefiLlama |
| Dataset | DefiLlama |
| Source | idem |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | Flux |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score mint net |
| Placebo | random days |
| Rejet | Placebo indistinguable |
| Priorité | 56 |
| Verdict | later |

#### P9-SC-007 — Part stablecoins euro (EURC+etc.)

| Champ | Valeur |
|-------|--------|
| Intuition | Flux zone euro |
| Pourquoi ça pourrait marcher | Régulation MiCA |
| Pourquoi bullshit | Part encore minuscule |
| Dataset | DefiLlama |
| Source | idem |
| Fréquence | Mensuel |
| Horizon | post_7 |
| Type | Régime |
| Actifs | BTC, EUR pairs |
| Data / Impl | 3 / 3 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Ratio EUR stables |
| Placebo | shift |
| Rejet | N insuffisant |
| Priorité | 35 |
| Verdict | later |

#### P9-SC-008 — Spike supply algo-stables (historique)

| Champ | Valeur |
|-------|--------|
| Intuition | Rappel UST/LUNA — contagion |
| Pourquoi ça pourrait marcher | Events extrêmes |
| Pourquoi bullshit | Régime change ; peu d'events post-2022 |
| Dataset | DefiLlama historique |
| Source | idem |
| Fréquence | Très sparse |
| Horizon | post_3 |
| Type | Stress |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | faible |
| Juridique | faible |
| Test | Seuil inclusion algo |
| Placebo | — |
| Rejet | < 5 events |
| Priorité | 30 |
| Verdict | kill |

#### P9-SC-009 — Supply stables × vol BTC élevée

| Champ | Valeur |
|-------|--------|
| Intuition | Interaction régime |
| Pourquoi ça pourrait marcher | Conditioning |
| Pourquoi bullshit | Deux hypothèses = double test |
| Dataset | DefiLlama + OHLC |
| Source | Combiné |
| Fréquence | Variable |
| Horizon | post_7 |
| Type | Interaction |
| Actifs | BTC |
| Data / Impl | 2 / 3 |
| Sur-ajustement | extrême |
| Juridique | faible |
| Test | Events conjonction |
| Placebo | shuffle vol |
| Rejet | Multiple testing |
| Priorité | 28 |
| Verdict | kill |

#### P9-SC-010 — Rotation USDT → USDC

| Champ | Valeur |
|-------|--------|
| Intuition | Préférence régulée |
| Pourquoi ça pourrait marcher | Narratif compliance |
| Pourquoi bullshit | Données bruitées |
| Dataset | DefiLlama |
| Source | idem |
| Fréquence | Mensuel |
| Horizon | post_7 |
| Type | Rotation |
| Actifs | BTC |
| Data / Impl | 3 / 3 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Z-score ratio USDC/USDT |
| Placebo | Bootstrap |
| Rejet | Non reproductible OOS |
| Priorité | 38 |
| Verdict | later |

---

### Famille AT — Attention (10)

#### P9-AT-011 — Wikipedia BTC momentum pageviews

| Champ | Valeur |
|-------|--------|
| Intuition | Attention retail → vol / retour |
| Pourquoi ça pourrait marcher | Proxy sentiment |
| Pourquoi bullshit | **403** sans User-Agent (leaderboard) |
| Dataset | Wikimedia daily |
| Source | `wikimedia.py` / `wiki_attention.py` |
| Fréquence | ~10–30 events/an |
| Horizon | post_7 |
| Type | Attention |
| Actifs | BTC |
| Data / Impl | 2 / 1 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | `event_study_wikipedia.py --article Bitcoin` |
| Placebo | Bootstrap |
| Rejet | Non robuste cross-articles |
| Priorité | **78** |
| Verdict | **implement now** |

#### P9-AT-012 — Wikipedia Ethereum

| Champ | Valeur |
|-------|--------|
| Intuition | Idem AT-011 sur ETH |
| Pourquoi ça pourrait marcher | Écosystème distinct |
| Pourquoi bullshit | Même infra ; corrélation BTC |
| Dataset | Wikimedia |
| Source | idem |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | Attention |
| Actifs | ETH |
| Data / Impl | 2 / 1 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | `--article Ethereum --ticker ETH` |
| Placebo | Bootstrap |
| Rejet | Colinéarité BTC |
| Priorité | 62 |
| Verdict | implement now |

#### P9-AT-013 — Wikipedia Solana

| Champ | Valeur |
|-------|--------|
| Intuition | Alt L1 narrative |
| Pourquoi ça pourrait marcher | Retail alt season |
| Pourquoi bullshit | Article moins liquide |
| Dataset | Wikimedia |
| Source | idem |
| Fréquence | Variable |
| Horizon | post_7 |
| Type | Attention |
| Actifs | SOL |
| Data / Impl | 2 / 1 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | `--article Solana --ticker SOL` |
| Placebo | article placebo |
| Rejet | Faible puissance |
| Priorité | 50 |
| Verdict | later |

#### P9-AT-014 — Composite attention 3 articles crypto

| Champ | Valeur |
|-------|--------|
| Intuition | Panier attention |
| Pourquoi ça pourrait marcher | Réduit bruit idiosyncratique |
| Pourquoi bullshit | Poids arbitraires |
| Dataset | Wikimedia multi |
| Source | idem |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | Attention |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | extrême |
| Juridique | faible |
| Test | Somme z-scores |
| Placebo | shuffle articles |
| Rejet | Overfit poids |
| Priorité | 45 |
| Verdict | later |

#### P9-AT-015 — Google Trends « Bitcoin »

| Champ | Valeur |
|-------|--------|
| Intuition | Retail search lead/lag |
| Pourquoi ça pourrait marcher | Littérature marketing |
| Pourquoi bullshit | Pas d'API stable gratuite |
| Dataset | CSV Trends |
| Source | Hors repo |
| Fréquence | Hebdo |
| Horizon | post_7 |
| Type | Attention |
| Actifs | BTC |
| Data / Impl | 3 / 3 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Import cache + event study |
| Placebo | shift +30j |
| Rejet | Retard variable |
| Priorité | 44 |
| Verdict | later |

#### P9-AT-016 — Mentions Reddit r/cryptocurrency

| Champ | Valeur |
|-------|--------|
| Intuition | Buzz social |
| Pourquoi ça pourrait marcher | Sentiment crowd |
| Pourquoi bullshit | API Reddit restreinte ; brigading |
| Dataset | Reddit API |
| Source | OAuth Reddit |
| Fréquence | Journalier |
| Horizon | post_3 |
| Type | Attention |
| Actifs | BTC |
| Data / Impl | 4 / 4 |
| Sur-ajustement | élevé |
| Juridique | moyen (ToS) |
| Test | — |
| Placebo | — |
| Rejet | ToS / coût |
| Priorité | 20 |
| Verdict | kill |

#### P9-AT-017 — Fear & Greed extrême peur

| Champ | Valeur |
|-------|--------|
| Intuition | Contrarian extrême peur |
| Pourquoi ça pourrait marcher | Behavioral finance |
| Pourquoi bullshit | Demo **weak evidence** ; pas harness prod |
| Dataset | alternative.me F&G |
| Source | `external_signals.py` |
| Fréquence | ~10 % jours |
| Horizon | post_7 |
| Type | Sentiment |
| Actifs | BTC |
| Data / Impl | 1 / 1 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | `demo_event_study.py` puis event study dédié |
| Placebo | Bootstrap |
| Rejet | Demo-only ; BH instable |
| Priorité | 68 |
| Verdict | later |

#### P9-AT-018 — Compteur headlines crypto (GDELT/NewsAPI)

| Champ | Valeur |
|-------|--------|
| Intuition | News flow → vol |
| Pourquoi ça pourrait marcher | Information arrival |
| Pourquoi bullshit | Coût API ; biais sélection |
| Dataset | News count |
| Source | NewsAPI payant |
| Fréquence | Journalier |
| Horizon | post_1 |
| Type | Attention |
| Actifs | BTC |
| Data / Impl | 4 / 4 |
| Sur-ajustement | élevé |
| Juridique | moyen |
| Test | — |
| Placebo | — |
| Rejet | Budget / ToS |
| Priorité | 25 |
| Verdict | kill |

#### P9-AT-019 — YouTube « bitcoin » search volume

| Champ | Valeur |
|-------|--------|
| Intuition | Retail video attention |
| Pourquoi ça pourrait marcher | Corrèle Trends |
| Pourquoi bullshit | Pas d'API publique simple |
| Dataset | Google Trends proxy |
| Source | CSV |
| Fréquence | Hebdo |
| Horizon | post_7 |
| Type | Attention |
| Actifs | BTC |
| Data / Impl | 3 / 3 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Cache manuel |
| Placebo | shift |
| Rejet | Duplicata AT-015 |
| Priorité | 32 |
| Verdict | later |

#### P9-AT-020 — Commits GitHub bitcoin/bitcoin

| Champ | Valeur |
|-------|--------|
| Intuition | Activité dev → narrative |
| Pourquoi ça pourrait marcher | Releases |
| Pourquoi bullshit | Bots commits |
| Dataset | GitHub REST |
| Source | api.github.com |
| Fréquence | Journalier |
| Horizon | post_3 |
| Type | Attention dev |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score commits |
| Placebo | random days |
| Rejet | Clusters release |
| Priorité | 45 |
| Verdict | weird but quick |

---

### Famille MS — Microstructure (10)

#### P9-MS-021 — Vol réalisée élevée week-end BTC

| Champ | Valeur |
|-------|--------|
| Intuition | Liquidité basse → vol |
| Pourquoi ça pourrait marcher | Microstructure 24/7 |
| Pourquoi bullshit | Weekend_start déjà **not supported** |
| Dataset | OHLC journalier |
| Source | `crypto_ohlc_rest.py` |
| Fréquence | Hebdo |
| Horizon | post_1 |
| Type | Microstructure |
| Actifs | BTC |
| Data / Impl | 1 / 1 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Events sat+sun vol z-high |
| Placebo | jours semaine |
| Rejet | Hold-out fail |
| Priorité | 70 |
| Verdict | implement now |

#### P9-MS-022 — Proxy spread (high-low)/close

| Champ | Valeur |
|-------|--------|
| Intuition | Spread ↑ → incertitude |
| Pourquoi ça pourrait marcher | Proxy classique |
| Pourquoi bullshit | Daily lisse intra-day |
| Dataset | OHLC |
| Source | Kraken REST |
| Fréquence | Journalier |
| Horizon | post_3 |
| Type | Microstructure |
| Actifs | BTC, ETH |
| Data / Impl | 1 / 1 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score HL spread |
| Placebo | Bootstrap |
| Rejet | Non significatif |
| Priorité | 52 |
| Verdict | implement now |

#### P9-MS-023 — Volume spike z-score

| Champ | Valeur |
|-------|--------|
| Intuition | Volume anormal → information |
| Pourquoi ça pourrait marcher | Volume-price literature |
| Pourquoi bullshit | Volume Kraken ≠ global |
| Dataset | OHLC volume |
| Source | Kraken REST |
| Fréquence | ~5–15 % jours |
| Horizon | post_3 |
| Type | Microstructure |
| Actifs | BTC |
| Data / Impl | 1 / 1 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score volume 30j |
| Placebo | Bootstrap |
| Rejet | > 30 % candles = rejet G2 |
| Priorité | 63 |
| Verdict | implement now |

#### P9-MS-024 — Close location value (CLV) extrême

| Champ | Valeur |
|-------|--------|
| Intuition | Pression acheteuse intra-bar |
| Pourquoi ça pourrait marcher | Proxy order flow |
| Pourquoi bullshit | Une barre/jour |
| Dataset | OHLC |
| Source | Kraken |
| Fréquence | Journalier |
| Horizon | post_1 |
| Type | Microstructure |
| Actifs | BTC |
| Data / Impl | 1 / 2 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | CLV z-high events |
| Placebo | shuffle |
| Rejet | Overfit |
| Priorité | 48 |
| Verdict | later |

#### P9-MS-025 — Range HL / close (spread proxy)

| Champ | Valeur |
|-------|--------|
| Intuition | Voir MS-022 variante |
| Pourquoi ça pourrait marcher | Idem |
| Pourquoi bullshit | Redondant MS-022 |
| Dataset | OHLC |
| Source | Kraken |
| Fréquence | Journalier |
| Horizon | post_3 |
| Type | Microstructure |
| Actifs | ETH |
| Data / Impl | 1 / 1 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | ETH ticker |
| Placebo | Bootstrap |
| Rejet | Redondance |
| Priorité | 57 |
| Verdict | implement now |

#### P9-MS-026 — Orderbook imbalance L2

| Champ | Valeur |
|-------|--------|
| Intuition | Pression bid/ask |
| Pourquoi ça pourrait marcher | Microstructure classique |
| Pourquoi bullshit | Besoin snapshots L2 ; pas dans collectors |
| Dataset | Order book |
| Source | Kraken public L2 |
| Fréquence | Intra-day |
| Horizon | post_1 (60m) |
| Type | Microstructure |
| Actifs | BTC |
| Data / Impl | 4 / 4 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Collector L2 + agrégat journalier |
| Placebo | shuffle |
| Rejet | Coût stockage |
| Priorité | 40 |
| Verdict | later |

#### P9-MS-027 — Trades aggressor imbalance

| Champ | Valeur |
|-------|--------|
| Intuition | Flux agresseur |
| Pourquoi ça pourrait marcher | Toxic flow |
| Pourquoi bullshit | API trades paginée lourde |
| Dataset | Trades publics |
| Source | Kraken REST trades |
| Fréquence | Haute |
| Horizon | post_1 |
| Type | Microstructure |
| Actifs | BTC |
| Data / Impl | 5 / 5 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | — |
| Placebo | — |
| Rejet | Hors scope Phase 9 |
| Priorité | 30 |
| Verdict | kill |

#### P9-MS-028 — Funding rate perp extrême

| Champ | Valeur |
|-------|--------|
| Intuition | Crowding longs → mean reversion |
| Pourquoi ça pourrait marcher | Futures literature |
| Pourquoi bullshit | Funding ≠ spot exécution actuelle |
| Dataset | Funding history |
| Source | Kraken Futures API |
| Fréquence | 8h |
| Horizon | post_3 |
| Type | Microstructure / perp |
| Actifs | BTC perp |
| Data / Impl | 3 / 3 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score funding |
| Placebo | shift |
| Rejet | Frais perp G3 |
| Priorité | 67 |
| Verdict | later |

#### P9-MS-029 — Liquidation cascade proxy (OI+ funding)

| Champ | Valeur |
|-------|--------|
| Intuition | Flush leverage |
| Pourquoi ça pourrait marcher | Events 2021 |
| Pourquoi bullshit | Données OI externes |
| Dataset | OI + funding |
| Source | Coinglass etc. |
| Fréquence | Sparse |
| Horizon | post_1 |
| Type | Microstructure |
| Actifs | BTC |
| Data / Impl | 4 / 4 |
| Sur-ajustement | moyen |
| Juridique | moyen (ToS tiers) |
| Test | — |
| Placebo | — |
| Rejet | Pas de feed gratuit fiable |
| Priorité | 28 |
| Verdict | kill |

#### P9-MS-030 — Vol-of-vol spike

| Champ | Valeur |
|-------|--------|
| Intuition | Incertitude sur vol |
| Pourquoi ça pourrait marcher | Régime change |
| Pourquoi bullshit | Estimation instable daily |
| Dataset | OHLC |
| Source | Kraken |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | Vol régime |
| Actifs | BTC |
| Data / Impl | 1 / 2 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Z-score vol of vol |
| Placebo | Bootstrap |
| Rejet | Non tradeable sans règle |
| Priorité | 46 |
| Verdict | later |

---

### Famille CA — Calendrier (10)

#### P9-CA-031 — Début week-end UTC (Saturday)

| Champ | Valeur |
|-------|--------|
| Intuition | Liquidité week-end |
| Pourquoi ça pourrait marcher | Pattern 24/7 |
| Pourquoi bullshit | **Déjà testé 730j : not supported** |
| Dataset | OHLC |
| Source | `calendar_effects.py` |
| Fréquence | Hebdo |
| Horizon | post_7 |
| Type | Calendrier |
| Actifs | BTC |
| Data / Impl | 1 / 1 |
| Sur-ajustement | extrême |
| Juridique | faible |
| Test | `event_study_calendar.py --calendar-flag weekend_start` |
| Placebo | Bootstrap |
| Rejet | Archive (leaderboard) |
| Priorité | 25 |
| Verdict | kill |

#### P9-CA-032 — Ouverture session US cash (ET)

| Champ | Valeur |
|-------|--------|
| Intuition | Flux TradFi → crypto |
| Pourquoi ça pourrait marcher | Corrélation S&P |
| Pourquoi bullshit | Crypto 24/7 dilue l'open |
| Dataset | OHLC |
| Source | `build_us_open_events` |
| Fréquence | Journalier (jours ouvrés US) |
| Horizon | post_1 |
| Type | Calendrier |
| Actifs | BTC |
| Data / Impl | 1 / 1 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | `--calendar-flag us_open` |
| Placebo | jours ouvrés placebo |
| Rejet | Hold-out |
| Priorité | 72 |
| Verdict | implement now |

#### P9-CA-033 — Ouverture Tokyo

| Champ | Valeur |
|-------|--------|
| Intuition | Session Asie |
| Pourquoi ça pourrait marcher | Flux JPY |
| Pourquoi bullshit | Définition session arbitraire |
| Dataset | OHLC |
| Source | `calendar_effects.py` |
| Fréquence | Journalier |
| Horizon | post_1 |
| Type | Calendrier |
| Actifs | BTC |
| Data / Impl | 1 / 1 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | `--calendar-flag asia_open` |
| Placebo | Bootstrap |
| Rejet | Multiple sessions |
| Priorité | 58 |
| Verdict | implement now |

#### P9-CA-034 — Fin de mois (last 2 days)

| Champ | Valeur |
|-------|--------|
| Intuition | Rebalancing institutionnel |
| Pourquoi ça pourrait marcher | Flows mensuels |
| Pourquoi bullshit | Crypto pas encore indexé massivement |
| Dataset | OHLC |
| Source | Calendrier dérivé |
| Fréquence | Mensuel |
| Horizon | post_3 |
| Type | Calendrier |
| Actifs | BTC |
| Data / Impl | 1 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Flag month_end |
| Placebo | mid-month days |
| Rejet | Saisonnalité faible |
| Priorité | 55 |
| Verdict | later |

#### P9-CA-035 — Jour FOMC (calendrier Fed)

| Champ | Valeur |
|-------|--------|
| Intuition | Annonce taux → risk |
| Pourquoi ça pourrait marcher | Macro surprise |
| Pourquoi bullshit | Heure annonce vs daily candle |
| Dataset | Calendrier Fed CSV |
| Source | Fichier statique |
| Fréquence | ~8/an |
| Horizon | post_1 |
| Type | Calendrier macro |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Events FOMC |
| Placebo | mercredis random |
| Rejet | N faible |
| Priorité | 52 |
| Verdict | later |

#### P9-CA-036 — Jour CPI US

| Champ | Valeur |
|-------|--------|
| Intuition | Inflation surprise |
| Pourquoi ça pourrait marcher | Macro |
| Pourquoi bullshit | Idem FOMC résolution |
| Dataset | Calendrier BLS |
| Source | CSV |
| Fréquence | Mensuel |
| Horizon | post_1 |
| Type | Calendrier macro |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | CPI days |
| Placebo | shift |
| Rejet | Volatilité event-day |
| Priorité | 50 |
| Verdict | later |

#### P9-CA-037 — 3e vendredi expiry (calendrier pur)

| Champ | Valeur |
|-------|--------|
| Intuition | Gamma/options pin |
| Pourquoi ça pourrait marcher | Literature equity |
| Pourquoi bullshit | **Pas de feed Deribit** — calendrier seul |
| Dataset | OHLC |
| Source | `options_expiry.py` |
| Fréquence | Mensuel |
| Horizon | post_3 |
| Type | Calendrier / dérivés |
| Actifs | BTC |
| Data / Impl | 1 / 1 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | `event_study_deribit_expiry.py` |
| Placebo | vendredis non-3e |
| Rejet | Non significatif vs placebo |
| Priorité | 64 |
| Verdict | implement now |

#### P9-CA-038 — Fin de trimestre

| Champ | Valeur |
|-------|--------|
| Intuition | Window dressing |
| Pourquoi ça pourrait marcher | TradFi |
| Pourquoi bullshit | Crypto faible lien |
| Dataset | Calendrier |
| Source | Dérivé OHLC |
| Fréquence | Trimestriel |
| Horizon | post_7 |
| Type | Calendrier |
| Actifs | BTC |
| Data / Impl | 1 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Last 5 days Q |
| Placebo | random |
| Rejet | N faible |
| Priorité | 42 |
| Verdict | later |

#### P9-CA-039 — Décembre tax-loss harvesting

| Champ | Valeur |
|-------|--------|
| Intuition | Ventes fiscales |
| Pourquoi ça pourrait marcher | Seasonality equity |
| Pourquoi bullshit | Crypto fiscalité hétérogène |
| Dataset | Calendrier |
| Source | Dérivé |
| Fréquence | Annuel |
| Horizon | post_7 |
| Type | Calendrier |
| Actifs | BTC |
| Data / Impl | 1 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Dec last 10d |
| Placebo | autres mois |
| Rejet | Un seul régime/an |
| Priorité | 38 |
| Verdict | later |

#### P9-CA-040 — Phase lunaire

| Champ | Valeur |
|-------|--------|
| Intuition | Nullité / folklore |
| Pourquoi ça pourrait marcher | Ne devrait pas |
| Pourquoi bullshit | Astrologie |
| Dataset | Éphémérides |
| Source | CSV NASA |
| Fréquence | ~12/an |
| Horizon | post_3 |
| Type | Calendrier |
| Actifs | BTC |
| Data / Impl | 1 / 1 |
| Sur-ajustement | extrême |
| Juridique | faible |
| Test | Pleine lune |
| Placebo | random |
| Rejet | Sanity null |
| Priorité | 35 |
| Verdict | weird but quick |

---

### Famille OC — On-chain (12)

#### P9-OC-041 — ETH gas fast gwei z-high

| Champ | Valeur |
|-------|--------|
| Intuition | Congestion → risk-off ETH/BTC |
| Pourquoi ça pourrait marcher | Coût utilisation réseau |
| Pourquoi bullshit | **0 rows history** ; snapshot only |
| Dataset | Etherscan gas daily |
| Source | `etherscan.py` / `eth_gas_congestion.py` |
| Fréquence | Sparse |
| Horizon | post_7 |
| Type | On-chain |
| Actifs | ETH, BTC |
| Data / Impl | 2 / 1 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | `event_study_eth_gas.py` + seed history |
| Placebo | Bootstrap |
| Rejet | Cluster week-end only |
| Priorité | **76** |
| Verdict | **implement now** |

#### P9-OC-042 — BTC mempool vsize z-high

| Champ | Valeur |
|-------|--------|
| Intuition | Congestion Bitcoin |
| Pourquoi ça pourrait marcher | Frais + urgence settlement |
| Pourquoi bullshit | **Pas de collector mempool** |
| Dataset | Mempool.space API |
| Source | À créer |
| Fréquence | Journalier |
| Horizon | post_3 |
| Type | On-chain |
| Actifs | BTC |
| Data / Impl | 3 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | `btc_mempool.py` + collector |
| Placebo | Bootstrap |
| Rejet | News/halving clusters |
| Priorité | 66 |
| Verdict | later |

#### P9-OC-043 — Exchange netflow BTC (Glassnode)

| Champ | Valeur |
|-------|--------|
| Intuition | Entrées exchange → vente |
| Pourquoi ça pourrait marcher | Supply on exchange |
| Pourquoi bullshit | API payante |
| Dataset | Netflow |
| Source | Glassnode |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | On-chain |
| Actifs | BTC |
| Data / Impl | 5 / 3 |
| Sur-ajustement | moyen |
| Juridique | moyen (licence) |
| Test | — |
| Placebo | — |
| Rejet | Budget |
| Priorité | 22 |
| Verdict | kill |

#### P9-OC-044 — Adresses actives z-high

| Champ | Valeur |
|-------|--------|
| Intuition | Adoption / activité |
| Pourquoi ça pourrait marcher | Network effect |
| Pourquoi bullshit | Définition « active » change |
| Dataset | On-chain metrics |
| Source | Coin Metrics / Glassnode |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | On-chain |
| Actifs | BTC |
| Data / Impl | 4 / 3 |
| Sur-ajustement | élevé |
| Juridique | moyen |
| Test | — |
| Placebo | — |
| Rejet | Coût |
| Priorité | 24 |
| Verdict | kill |

#### P9-OC-045 — Whale transactions > 1000 BTC

| Champ | Valeur |
|-------|--------|
| Intuition | Whales move price |
| Pourquoi ça pourrait marcher | Impact blocks |
| Pourquoi bullshit | Wallet labeling incertain |
| Dataset | Whale alerts |
| Source | Whale Alert API |
| Fréquence | Sparse |
| Horizon | post_1 |
| Type | On-chain |
| Actifs | BTC |
| Data / Impl | 4 / 3 |
| Sur-ajustement | moyen |
| Juridique | moyen |
| Test | — |
| Placebo | — |
| Rejet | ToS / coût |
| Priorité | 26 |
| Verdict | kill |

#### P9-OC-046 — ETH burned (EIP-1559) daily spike

| Champ | Valeur |
|-------|--------|
| Intuition | Supply shock |
| Pourquoi ça pourrait marcher | Burn mécanique |
| Pourquoi bullshit | Besoin série burn |
| Dataset | Ultrasound.money API |
| Source | Public API |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | On-chain |
| Actifs | ETH |
| Data / Impl | 3 / 3 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score burn |
| Placebo | shift |
| Rejet | Régime post-merge |
| Priorité | 48 |
| Verdict | later |

#### P9-OC-047 — Migration TVL L1 → L2

| Champ | Valeur |
|-------|--------|
| Intuition | Activity shift |
| Pourquoi ça pourrait marcher | Fees L1 ↓ |
| Pourquoi bullshit | Agrégats DefiLlama révisés |
| Dataset | TVL L2/L1 ratio |
| Source | DefiLlama |
| Fréquence | Hebdo |
| Horizon | post_7 |
| Type | On-chain |
| Actifs | ETH |
| Data / Impl | 3 / 3 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Ratio z-score |
| Placebo | Bootstrap |
| Rejet | Non causal |
| Priorité | 40 |
| Verdict | later |

#### P9-OC-048 — TVL Ethereum DefiLlama z-high

| Champ | Valeur |
|-------|--------|
| Intuition | DeFi risk-on |
| Pourquoi ça pourrait marcher | TVL corrélé bull |
| Pourquoi bullshit | `fetch_chain_tvl` existe ; pas de signal |
| Dataset | chain TVL |
| Source | `defillama.py` |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | On-chain |
| Actifs | ETH, BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Nouveau signal + event study |
| Placebo | Bootstrap |
| Rejet | Colinéarité prix |
| Priorité | 61 |
| Verdict | later |

#### P9-OC-049 — Stablecoin bridge net vers L2

| Champ | Valeur |
|-------|--------|
| Intuition | Liquidité L2 |
| Pourquoi ça pourrait marcher | Usage L2 |
| Pourquoi bullshit | Données bridges fragmentées |
| Dataset | Bridges |
| Source | DefiLlama bridges |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | On-chain |
| Actifs | ETH |
| Data / Impl | 4 / 4 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | — |
| Placebo | — |
| Rejet | Impl lourde |
| Priorité | 32 |
| Verdict | later |

#### P9-OC-050 — Miner outflow z-high

| Champ | Valeur |
|-------|--------|
| Intuition | Miners vendent |
| Pourquoi ça pourrait marcher | Pression supply |
| Pourquoi bullshit | Labeling pools |
| Dataset | Miner flows |
| Source | Glassnode |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | On-chain |
| Actifs | BTC |
| Data / Impl | 5 / 3 |
| Sur-ajustement | moyen |
| Juridique | moyen |
| Test | — |
| Placebo | — |
| Rejet | Payant |
| Priorité | 20 |
| Verdict | kill |

#### P9-OC-051 — Hash rate drop > 5 % 7j

| Champ | Valeur |
|-------|--------|
| Intuition | Sécurité / miner stress |
| Pourquoi ça pourrait marcher | Chine ban 2021 |
| Pourquoi bullshit | Hash rate lag ; API |
| Dataset | Hashrate |
| Source | blockchain.com API |
| Fréquence | Hebdo |
| Horizon | post_7 |
| Type | On-chain |
| Actifs | BTC |
| Data / Impl | 3 / 3 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score hashrate |
| Placebo | shift |
| Rejet | Régime change hardware |
| Priorité | 36 |
| Verdict | later |

#### P9-OC-052 — Volume NFT floor (proxy risk-on)

| Champ | Valeur |
|-------|--------|
| Intuition | NFT = baromètre retail |
| Pourquoi ça pourrait marcher | Bull 2021 |
| Pourquoi bullshit | Lien BTC faible post-2022 |
| Dataset | NFT volume |
| Source | OpenSea / Dune |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | On-chain / attention |
| Actifs | BTC |
| Data / Impl | 4 / 4 |
| Sur-ajustement | élevé |
| Juridique | moyen |
| Test | — |
| Placebo | — |
| Rejet | Hors focus |
| Priorité | 18 |
| Verdict | kill |

---

### Famille DV — Dérivés (10)

#### P9-DV-053 — Funding BTC changement de signe

| Champ | Valeur |
|-------|--------|
| Intuition | Régime flip crowding |
| Pourquoi ça pourrait marcher | Perp microstructure |
| Pourquoi bullshit | Exécution spot par défaut |
| Dataset | Funding 8h |
| Source | Kraken Futures |
| Fréquence | Sparse |
| Horizon | post_3 |
| Type | Dérivés |
| Actifs | BTC |
| Data / Impl | 3 / 3 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Events sign flip |
| Placebo | random |
| Rejet | G3 frais perp |
| Priorité | 60 |
| Verdict | later |

#### P9-DV-054 — Basis perp-spot compression

| Champ | Valeur |
|-------|--------|
| Intuition | Arbitrageurs serrés |
| Pourquoi ça pourrait marcher | Carry trade |
| Pourquoi bullshit | Besoin spot+perp sync |
| Dataset | Basis |
| Source | Kraken |
| Fréquence | Journalier |
| Horizon | post_3 |
| Type | Dérivés |
| Actifs | BTC |
| Data / Impl | 4 / 4 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score basis |
| Placebo | shift |
| Rejet | Impl lourde |
| Priorité | 44 |
| Verdict | later |

#### P9-DV-055 — Skew put/call Deribit

| Champ | Valeur |
|-------|--------|
| Intuition | Demande protection |
| Pourquoi ça pourrait marcher | Options literature |
| Pourquoi bullshit | **Pas de collector Deribit** |
| Dataset | Options IV skew |
| Source | Deribit API |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | Dérivés |
| Actifs | BTC |
| Data / Impl | 5 / 5 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | — |
| Placebo | — |
| Rejet | Scope Phase 9 |
| Priorité | 25 |
| Verdict | kill |

#### P9-DV-056 — Open interest spike 24h

| Champ | Valeur |
|-------|--------|
| Intuition | Leverage build-up |
| Pourquoi ça pourrait marcher | Flush risk |
| Pourquoi bullshit | OI data tier payant |
| Dataset | OI |
| Source | Coinglass |
| Fréquence | Journalier |
| Horizon | post_1 |
| Type | Dérivés |
| Actifs | BTC |
| Data / Impl | 4 / 3 |
| Sur-ajustement | moyen |
| Juridique | moyen |
| Test | — |
| Placebo | — |
| Rejet | Coût |
| Priorité | 28 |
| Verdict | kill |

#### P9-DV-057 — Gamma pinning 3e vendredi

| Champ | Valeur |
|-------|--------|
| Intuition | Pin strike |
| Pourquoi ça pourrait marcher | Equity effect |
| Pourquoi bullshit | Sans OI = CA-037 duplicate |
| Dataset | OHLC |
| Source | Calendrier |
| Fréquence | Mensuel |
| Horizon | post_1 |
| Type | Dérivés |
| Actifs | BTC |
| Data / Impl | 1 / 2 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Extension CA-037 |
| Placebo | vendredis |
| Rejet | Pas de gamma sans OI |
| Priorité | 54 |
| Verdict | later |

#### P9-DV-058 — Heatmap liquidations

| Champ | Valeur |
|-------|--------|
| Intuition | Cascade liquidations |
| Pourquoi ça pourrait marcher | 2020–2021 events |
| Pourquoi bullshit | Données opaques |
| Dataset | Liquidations |
| Source | Tiers |
| Fréquence | Intra-day |
| Horizon | post_1 |
| Type | Dérivés |
| Actifs | BTC |
| Data / Impl | 5 / 5 |
| Sur-ajustement | moyen |
| Juridique | moyen |
| Test | — |
| Placebo | — |
| Rejet | Hors scope |
| Priorité | 22 |
| Verdict | kill |

#### P9-DV-059 — Shift smile IV (risk reversal)

| Champ | Valeur |
|-------|--------|
| Intuition | Skew regime |
| Pourquoi ça pourrait marcher | Fear gauge |
| Pourquoi bullshit | Pas Deribit feed |
| Dataset | IV surface |
| Source | Deribit |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | Dérivés |
| Actifs | BTC |
| Data / Impl | 5 / 5 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | — |
| Placebo | — |
| Rejet | Coût |
| Priorité | 20 |
| Verdict | kill |

#### P9-DV-060 — Backwardation term structure

| Champ | Valeur |
|-------|--------|
| Intuition | Stress spot |
| Pourquoi ça pourrait marcher | Commodity futures |
| Pourquoi bullshit | Kraken futures limited |
| Dataset | Term structure |
| Source | Kraken |
| Fréquence | Hebdo |
| Horizon | post_7 |
| Type | Dérivés |
| Actifs | BTC |
| Data / Impl | 4 / 4 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | — |
| Placebo | — |
| Rejet | Impl |
| Priorité | 30 |
| Verdict | later |

#### P9-DV-061 — Funding ETH vs BTC spread

| Champ | Valeur |
|-------|--------|
| Intuition | Rotation narrative |
| Pourquoi ça pourrait marcher | Relative crowding |
| Pourquoi bullshit | Deux perps corrélés |
| Dataset | Funding both |
| Source | Kraken Futures |
| Fréquence | 8h |
| Horizon | post_3 |
| Type | Dérivés |
| Actifs | ETH, BTC |
| Data / Impl | 3 / 3 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score spread |
| Placebo | shuffle |
| Rejet | Colinéarité |
| Priorité | 46 |
| Verdict | later |

#### P9-DV-062 — DVOL spike (vol implicite)

| Champ | Valeur |
|-------|--------|
| Intuition | Peur optionnelle |
| Pourquoi ça pourrait marcher | VIX crypto |
| Pourquoi bullshit | Deribit index |
| Dataset | DVOL |
| Source | Deribit |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | Dérivés |
| Actifs | BTC |
| Data / Impl | 4 / 4 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | — |
| Placebo | — |
| Rejet | Pas de feed |
| Priorité | 32 |
| Verdict | kill |

---

### Famille MA — Macro (10)

#### P9-MA-063 — Dollar index DXY proxy up

| Champ | Valeur |
|-------|--------|
| Intuition | DXY ↑ → risk-off crypto |
| Pourquoi ça pourrait marcher | Corrélation 2022 |
| Pourquoi bullshit | Import macro daily |
| Dataset | DXY |
| Source | FRED CSV |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | Macro |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score DXY ret |
| Placebo | shift |
| Rejet | Régime dependent |
| Priorité | 50 |
| Verdict | later |

#### P9-MA-064 — Gold up / BTC down divergence

| Champ | Valeur |
|-------|--------|
| Intuition | Rotation safe haven |
| Pourquoi ça pourrait marcher | Macro hedge |
| Pourquoi bullshit | « Digital gold » narrative change |
| Dataset | XAU + BTC |
| Source | FRED + Kraken |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | Macro |
| Actifs | BTC |
| Data / Impl | 3 / 3 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Spread ret z |
| Placebo | shuffle |
| Rejet | Overfit |
| Priorité | 42 |
| Verdict | later |

#### P9-MA-065 — VIX spike > 30

| Champ | Valeur |
|-------|--------|
| Intuition | Risk-off global |
| Pourquoi ça pourrait marcher | Corrélation equity-crypto |
| Pourquoi bullshit | VIX ≠ crypto vol |
| Dataset | VIX |
| Source | FRED |
| Fréquence | Sparse |
| Horizon | post_3 |
| Type | Macro |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Events VIX>30 |
| Placebo | random |
| Rejet | N events |
| Priorité | 59 |
| Verdict | later |

#### P9-MA-066 — US10Y yield +25bp 5j

| Champ | Valeur |
|-------|--------|
| Intuition | Rates ↑ → risk assets down |
| Pourquoi ça pourrait marcher | 2022 hiking |
| Pourquoi bullshit | Lag / Fed priced in |
| Dataset | US10Y yields |
| Source | FRED CSV |
| Fréquence | Sparse |
| Horizon | post_7 |
| Type | Macro |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Shock yields |
| Placebo | shift |
| Rejet | Colinearité macro |
| Priorité | 52 |
| Verdict | later |

#### P9-MA-067 — Jour NFP

| Champ | Valeur |
|-------|--------|
| Intuition | Employment surprise |
| Pourquoi ça pourrait marcher | Macro vol |
| Pourquoi bullshit | Daily candle masque 8h30 ET |
| Dataset | Calendrier NFP |
| Source | CSV BLS |
| Fréquence | Mensuel |
| Horizon | post_1 |
| Type | Macro |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | NFP days |
| Placebo | vendredis |
| Rejet | Résolution |
| Priorité | 48 |
| Verdict | later |

#### P9-MA-068 — China PMI < 50

| Champ | Valeur |
|-------|--------|
| Intuition | China slowdown |
| Pourquoi ça pourrait marcher | Mining + risk |
| Pourquoi bullshit | PMI mensuel ; crypto découplé |
| Dataset | PMI |
| Source | CSV |
| Fréquence | Mensuel |
| Horizon | post_7 |
| Type | Macro |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | PMI events |
| Placebo | random month |
| Rejet | N faible |
| Priorité | 40 |
| Verdict | later |

#### P9-MA-069 — Choc prix pétrole +10 % 3j

| Champ | Valeur |
|-------|--------|
| Intuition | Inflation fear |
| Pourquoi ça pourrait marcher | Macro 2022 |
| Pourquoi bullshit | Lien indirect |
| Dataset | WTI |
| Source | FRED |
| Fréquence | Sparse |
| Horizon | post_3 |
| Type | Macro |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Oil shock |
| Placebo | shift |
| Rejet | Peu d'events |
| Priorité | 38 |
| Verdict | later |

#### P9-MA-070 — Stress eurodollar (FRA-OIS proxy)

| Champ | Valeur |
|-------|--------|
| Intuition | Funding stress |
| Pourquoi ça pourrait marcher | 2008 / 2020 |
| Pourquoi bullshit | Série complexe |
| Dataset | Credit |
| Source | FRED |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | Macro |
| Actifs | BTC |
| Data / Impl | 4 / 3 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Z-score spread |
| Placebo | Bootstrap |
| Rejet | Impl lourde |
| Priorité | 35 |
| Verdict | later |

#### P9-MA-071 — HY spread widen 50bp 10j

| Champ | Valeur |
|-------|--------|
| Intuition | Credit risk-off |
| Pourquoi ça pourrait marcher | Cross-asset |
| Pourquoi bullshit | Lag |
| Dataset | HY OAS |
| Source | FRED |
| Fréquence | Hebdo |
| Horizon | post_7 |
| Type | Macro |
| Actifs | BTC |
| Data / Impl | 3 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Spread events |
| Placebo | shift |
| Rejet | Non significatif |
| Priorité | 44 |
| Verdict | later |

#### P9-MA-072 — Jour discours Fed chair

| Champ | Valeur |
|-------|--------|
| Intuition | Forward guidance |
| Pourquoi ça pourrait marcher | Vol macro |
| Pourquoi bullshit | Calendrier incomplet |
| Dataset | Calendrier Fed |
| Source | CSV manuel |
| Fréquence | Sparse |
| Horizon | post_1 |
| Type | Macro |
| Actifs | BTC |
| Data / Impl | 3 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Speech days |
| Placebo | random |
| Rejet | < 5 events |
| Priorité | 36 |
| Verdict | later |

---

### Famille XS — xStocks gelé (10)

> **Compte PEDSL-CY :** spot xStocks `EGeneral:Permission denied` ;
> perps xStocks `wouldNotReducePosition`. Ces hypothèses restent en
> **backlog recherche** (backtest CLI read-only possible) — **jamais
> live** tant que migration entité non-PEDSL.

#### P9-XS-073 — Gap week-end AAPLx

| Champ | Valeur |
|-------|--------|
| Intuition | Equity gap pattern |
| Pourquoi ça pourrait marcher | Marché fermé WE |
| Pourquoi bullshit | ~80h/week trading ; gaps xStocks spécifiques |
| Dataset | OHLC xStocks CLI |
| Source | `kraken ohlc --asset-class tokenized_asset` |
| Fréquence | Hebdo |
| Horizon | post_1 |
| Type | xStocks / calendrier |
| Actifs | AAPLx/USD |
| Data / Impl | 2 / 2 |
| Sur-ajustement | élevé |
| Juridique | faible (read-only) |
| Test | `backtest_xstocks.py` |
| Placebo | random Mondays |
| Rejet | OOS walk-forward 0/48 |
| Priorité | 45 |
| Verdict | later |

#### P9-XS-074 — Vol à l'open US cash

| Champ | Valeur |
|-------|--------|
| Intuition | Open TradFi |
| Pourquoi ça pourrait marcher | Overlap liquidity |
| Pourquoi bullshit | Tokenized hours ≠ NYSE |
| Dataset | OHLC xStocks |
| Source | Kraken CLI |
| Fréquence | Journalier |
| Horizon | post_1 |
| Type | xStocks |
| Actifs | TSLAx/USD |
| Data / Impl | 2 / 2 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Event study xStocks |
| Placebo | shift |
| Rejet | Données courtes |
| Priorité | 42 |
| Verdict | later |

#### P9-XS-075 — Saison earnings tokenized MAG7

| Champ | Valeur |
|-------|--------|
| Intuition | Earnings vol |
| Pourquoi ça pourrait marcher | Equity events |
| Pourquoi bullshit | Calendrier earnings manuel |
| Dataset | Calendrier + OHLC |
| Source | CSV earnings |
| Fréquence | Trimestriel |
| Horizon | post_3 |
| Type | xStocks |
| Actifs | AAPLx, NVDAx |
| Data / Impl | 4 / 3 |
| Sur-ajustement | extrême |
| Juridique | faible |
| Test | Backtest autour earnings |
| Placebo | random |
| Rejet | Overfit dates |
| Priorité | 38 |
| Verdict | later |

#### P9-XS-076 — Arb spot tokenisé vs equity spot

| Champ | Valeur |
|-------|--------|
| Intuition | Basis arb |
| Pourquoi ça pourrait marcher | Mispricing |
| Pourquoi bullshit | **Permission denied** — pas d'exécution |
| Dataset | Deux prix |
| Source | Kraken + equity feed |
| Fréquence | Intra-day |
| Horizon | post_1 |
| Type | xStocks arb |
| Actifs | AAPLx |
| Data / Impl | 5 / 5 |
| Sur-ajustement | moyen |
| Juridique | moyen |
| Test | — |
| Placebo | — |
| Rejet | **NO-GO exécution** |
| Priorité | **5** |
| Verdict | **kill** |

#### P9-XS-077 — Trade funding perp xStocks

| Champ | Valeur |
|-------|--------|
| Intuition | Perp carry |
| Pourquoi ça pourrait marcher | Futures |
| Pourquoi bullshit | **wouldNotReducePosition** |
| Dataset | Funding PF_* |
| Source | Kraken Futures |
| Fréquence | 8h |
| Horizon | post_3 |
| Type | xStocks perp |
| Actifs | PF_AAPLXUSD |
| Data / Impl | 3 / 3 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | — |
| Placebo | — |
| Rejet | **Ouverture impossible PEDSL** |
| Priorité | **5** |
| Verdict | **kill** |

#### P9-XS-078 — Interaction règle vendredi 21h45 CEST

| Champ | Valeur |
|-------|--------|
| Intuition | Flatten avant close US |
| Pourquoi ça pourrait marcher | Règle agent |
| Pourquoi bullshit | Règle interne ≠ alpha |
| Dataset | Logs agent |
| Source | SQLite |
| Fréquence | Hebdo |
| Horizon | post_1 |
| Type | xStocks / règle |
| Actifs | xStocks basket |
| Data / Impl | 2 / 2 |
| Sur-ajustement | faible |
| Juridique | faible |
| Test | Sim rule impact |
| Placebo | — |
| Rejet | Pas une hypothèse marché |
| Priorité | 30 |
| Verdict | kill |

#### P9-XS-079 — Corrélation MAG7 tokenized basket

| Champ | Valeur |
|-------|--------|
| Intuition | Factor MAG7 |
| Pourquoi ça pourrait marcher | Equity factor |
| Pourquoi bullshit | 10 perps seulement |
| Dataset | OHLC multi |
| Source | Kraken CLI |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | xStocks |
| Actifs | Basket xStocks |
| Data / Impl | 3 / 3 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | PCA basket |
| Placebo | shuffle |
| Rejet | Walk-forward fail |
| Priorité | 40 |
| Verdict | later |

#### P9-XS-080 — Rotation SPYx vs QQQx

| Champ | Valeur |
|-------|--------|
| Intuition | Growth vs broad |
| Pourquoi ça pourrait marcher | Macro regime |
| Pourquoi bullshit | 2 paires |
| Dataset | OHLC |
| Source | Kraken |
| Fréquence | Hebdo |
| Horizon | post_7 |
| Type | xStocks |
| Actifs | SPYx, QQQx |
| Data / Impl | 2 / 2 |
| Sur-ajustement | élevé |
| Juridique | faible |
| Test | Spread ret |
| Placebo | shift |
| Rejet | N faible |
| Priorité | 38 |
| Verdict | later |

#### P9-XS-081 — GLDx safe haven vs BTC

| Champ | Valeur |
|-------|--------|
| Intuition | Or tokenisé vs BTC |
| Pourquoi ça pourrait marcher | Haven rotation |
| Pourquoi bullshit | GLDx volume faible |
| Dataset | OHLC |
| Source | Kraken |
| Fréquence | Journalier |
| Horizon | post_7 |
| Type | xStocks |
| Actifs | GLDx, BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | moyen |
| Juridique | faible |
| Test | Spread study |
| Placebo | Bootstrap |
| Rejet | Liquidité |
| Priorité | 36 |
| Verdict | later |

#### P9-XS-082 — Walk-forward OOS xStocks backlog

| Champ | Valeur |
|-------|--------|
| Intuition | Retrouver config OOS |
| Pourquoi ça pourrait marcher | — |
| Pourquoi bullshit | **0/48 survivors** documenté |
| Dataset | walk_forward_results |
| Source | `METHODOLOGY.md` |
| Fréquence | — |
| Horizon | — |
| Type | Meta |
| Actifs | xStocks |
| Data / Impl | 1 / 1 |
| Sur-ajustement | N/A |
| Juridique | faible |
| Test | Ne pas re-tuner in-sample |
| Placebo | — |
| Rejet | Anti-curve-fit policy |
| Priorité | 15 |
| Verdict | kill |

---

### Famille WX — Weird testable (10)

> Fiches détaillées : [`WEIRD_BUT_TESTABLE_SIGNALS.md`](WEIRD_BUT_TESTABLE_SIGNALS.md)

| ID | Nom | Priorité | Verdict |
|----|-----|----------|---------|
| P9-WX-083 | Wikipedia « Recession » | 62 | weird but quick |
| P9-WX-084 | Incidents Steam | 42 | weird but quick |
| P9-WX-085 | Spotify outage | 28 | kill |
| P9-WX-086 | Volume paris sportifs | 15 | kill |
| P9-WX-087 | Jour Powerball | 40 | weird but quick |
| P9-WX-088 | Google Trends buy bitcoin | 48 | weird but quick |
| P9-WX-089 | Saison meme dominance | 50 | weird but quick |
| P9-WX-090 | Mercure rétrograde | 30 | weird but quick |
| P9-WX-091 | Patch Tuesday | 38 | weird but quick |
| P9-WX-092 | Vélocité edits Wikipedia | 55 | weird but quick |

#### P9-WX-085 — Spotify outage (kill)

| Champ | Valeur |
|-------|--------|
| Intuition | Streaming down → ??? |
| Pourquoi ça pourrait marcher | Aucun mécanisme |
| Pourquoi bullshit | Spurious |
| Dataset | Statuspage |
| Source | Spotify status |
| Fréquence | Rare |
| Horizon | post_1 |
| Type | Weird |
| Actifs | BTC |
| Data / Impl | 2 / 2 |
| Sur-ajustement | faible |
| Juridique | faible |
| Test | — |
| Placebo | — |
| Rejet | Priorité trop basse |
| Priorité | 28 |
| Verdict | kill |

#### P9-WX-086 — Volume paris sportifs (kill)

| Champ | Valeur |
|-------|--------|
| Intuition | Gambling vs crypto |
| Pourquoi ça pourrait marcher | Retail overlap |
| Pourquoi bullshit | Données opaques ; régulation |
| Dataset | — |
| Source | — |
| Fréquence | — |
| Horizon | — |
| Type | Weird |
| Actifs | BTC |
| Data / Impl | 5 / 5 |
| Sur-ajustement | extrême |
| Juridique | **moyen** |
| Test | — |
| Placebo | — |
| Rejet | Pas falsifiable cheaply |
| Priorité | 15 |
| Verdict | kill |

---

### Famille LG — Legal / éthique no-go (8)

> **Ne pas implémenter.** Documentées pour éviter la dérive « idées
> trouvées sur Twitter ».

#### P9-LG-093 — Volume marchés dark web

| Champ | Valeur |
|-------|--------|
| Intuition | Criminal activity proxy |
| Pourquoi ça pourrait marcher | — |
| Pourquoi bullshit | Source illégale / non vérifiable |
| Dataset | — |
| Source | Tor markets |
| Fréquence | — |
| Horizon | — |
| Type | **legal no-go** |
| Actifs | — |
| Data / Impl | 5 / 5 |
| Sur-ajustement | N/A |
| Juridique | **no-go** |
| Test | **interdit** |
| Placebo | — |
| Rejet | Criminalité / compliance |
| Priorité | 0 |
| Verdict | **kill** |

#### P9-LG-094 — Front-run wallets insider

| Champ | Valeur |
|-------|--------|
| Intuition | Copier insiders |
| Pourquoi ça pourrait marcher | — |
| Pourquoi bullshit | Initié / données privilégiées |
| Dataset | — |
| Source | — |
| Fréquence | — |
| Horizon | — |
| Type | **legal no-go** |
| Actifs | — |
| Data / Impl | 5 / 5 |
| Sur-ajustement | N/A |
| Juridique | **no-go** |
| Test | **interdit** |
| Placebo | — |
| Rejet | Délit d'initié (EU Market Abuse) |
| Priorité | 0 |
| Verdict | **kill** |

#### P9-LG-095 — Trader sur wallets hacks

| Champ | Valeur |
|-------|--------|
| Intuition | Victimes vendent |
| Pourquoi ça pourrait marcher | — |
| Pourquoi bullshit | Profite du crime |
| Dataset | — |
| Source | — |
| Type | **legal no-go** |
| Juridique | **no-go** |
| Test | **interdit** |
| Rejet | AML / éthique |
| Priorité | 0 |
| Verdict | **kill** |

#### P9-LG-096 — Flux sanctions evasion

| Champ | Valeur |
|-------|--------|
| Intuition | — |
| Pourquoi bullshit | Sanctions OFAC/EU |
| Type | **legal no-go** |
| Juridique | **no-go** |
| Test | **interdit** |
| Rejet | Violation sanctions |
| Priorité | 0 |
| Verdict | **kill** |

#### P9-LG-097 — Scraping Twitter sans API

| Champ | Valeur |
|-------|--------|
| Intuition | Sentiment social |
| Pourquoi bullshit | Violation ToS X |
| Type | **legal no-go** |
| Juridique | **no-go** |
| Test | **interdit** |
| Rejet | ToS + CGU |
| Priorité | 0 |
| Verdict | **kill** |

#### P9-LG-098 — Groupes Telegram payants

| Champ | Valeur |
|-------|--------|
| Intuition | « Alpha » payant |
| Pourquoi bullshit | Fraude fréquente |
| Type | **legal no-go** |
| Juridique | **no-go** |
| Test | **interdit** |
| Rejet | Pas de licence MiFID |
| Priorité | 0 |
| Verdict | **kill** |

#### P9-LG-099 — Copy trading MEV sandwich

| Champ | Valeur |
|-------|--------|
| Intuition | Copier bots MEV |
| Pourquoi bullshit | Latence + éthique |
| Type | **legal no-go** |
| Juridique | **no-go** |
| Test | **interdit** |
| Rejet | Manipulation marché |
| Priorité | 0 |
| Verdict | **kill** |

#### P9-LG-100 — Front-run Statuspage privilégié

| Champ | Valeur |
|-------|--------|
| Intuition | Trade avant annonce publique |
| Pourquoi bullshit | Accès privilégié |
| Type | **legal no-go** |
| Juridique | **no-go** |
| Test | **interdit** |
| Rejet | Abus de marché potentiel |
| Priorité | 0 |
| Verdict | **kill** |

---

## Matrice familles × verdicts

| Famille | n | implement now | later | weird but quick | kill |
|---------|---|---------------|-------|-----------------|------|
| SC | 10 | 2 | 6 | 0 | 2 |
| AT | 10 | 2 | 5 | 1 | 2 |
| MS | 10 | 4 | 4 | 0 | 2 |
| CA | 10 | 3 | 5 | 1 | 1 |
| OC | 12 | 1 | 6 | 0 | 5 |
| DV | 10 | 0 | 5 | 0 | 5 |
| MA | 10 | 0 | 10 | 0 | 0 |
| XS | 10 | 0 | 6 | 0 | 4 |
| WX | 10 | 0 | 0 | 8 | 2 |
| LG | 8 | 0 | 0 | 0 | 8 |

---

## Prochaines actions Phase 9 (ordre suggéré)

1. Fix User-Agent Wikimedia → re-run P9-AT-011 / 012.
2. Seed `etherscan_gas_history.json` → re-run P9-OC-041.
3. Re-run P9-SC-001 avec `--z-threshold 1.0` (hypothèse pré-enregistrée).
4. Lancer P9-CA-032, P9-CA-033, P9-CA-037 (infra prête).
5. Mettre à jour leaderboard : `python reports/_build_leaderboard.py`.

---

## Références

- [`ALTERNATIVE_ALPHA_PIPELINE.md`](ALTERNATIVE_ALPHA_PIPELINE.md)
- [`SIGNAL_REJECTION_POLICY.md`](SIGNAL_REJECTION_POLICY.md)
- [`DATA_SOURCES.md`](DATA_SOURCES.md)
- [`WEIRD_BUT_TESTABLE_SIGNALS.md`](WEIRD_BUT_TESTABLE_SIGNALS.md)
- [`reports/ALPHA_RESEARCH_LEADERBOARD.md`](../reports/ALPHA_RESEARCH_LEADERBOARD.md)
- [`AGENTS.md`](../AGENTS.md) — contraintes PEDSL-CY xStocks
