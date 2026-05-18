# Hackathon Discord — Contexte officiel et témoignages participants

> Document de référence pour la submission lablab. Il agrège les messages
> officiels des modérateurs lablab (Steve, Inaam) et les retours publics
> des autres participants à la *Kraken Challenge* (track AI Agent
> Olympics). Toutes les citations sont **verbatim**, copiées depuis le
> canal Discord public de l'événement.
>
> Ce fichier est référencé par `docs/SUBMISSION.md` et le script de la
> vidéo de démo (`docs/DEMO_VIDEO_SCRIPT.md`). Il prouve que les
> blocages observés sur notre compte PEDSL-CY (Cyprus EU) **ne sont pas
> un cas isolé** : plusieurs autres équipes butent sur les mêmes
> problèmes xStocks / shorting / disponibilité géographique.

## 1. Cadrage officiel (Steve, modérateur lablab)

### Annonce d'ouverture — 12/05/2026 00:28

> Welcome to the kraken channel
>
> Kraken is one of the most established cryptocurrency exchanges in the
> world, trusted by institutions and individual traders, and known for
> its deep liquidity and trading infrastructure.
>
> For this hackathon, participants will work with two Kraken products:
>   • Kraken CLI is an AI-native command-line interface for programmatic
>     trading. It handles exchange complexity such as authentication,
>     rate limiting, and order management so you can focus on your
>     agent's strategy logic.
>   • xStocks are 1:1 asset-backed tokenized U.S. equities and ETFs
>     that can be traded 24/7 on-chain.

### Tutoriel officiel — 14/05/2026 20:47

> @here
>
> Full Kraken tutorial & template for those that are participating in
> the Kraken Challange
>
> Find it here: https://lablab.ai/ai-tutorials/featherless-kraken-multi-model-financial-agent
>
> Github template here: https://github.com/Stephen-Kimoi/featherless-kraken-agent

### Date de début de la fenêtre de mesure — 16/05/2026 18:14

> Start day is hackathon start date

→ **Implication** : la fenêtre de 30 jours promise sur la landing page
court depuis le **13 mai 2026** (date officielle d'ouverture du
hackathon), même si la *deadline de submission* lablab est le
**20 mai 2026**.

### Mécanisme d'audit du PnL — 16/05/2026 10:00

> Hi @djkorou360
>
> You need to submit your read only kraken API key, which will show
> your trading history to Kraken judges.

→ **Implication directe pour notre submission** : la submission package
**doit inclure** une clé API Kraken read-only valide. C'est exactement
le protocole décrit dans `docs/JURY_ACCESS_TEMPLATE.md`.

## 2. Cadrage officiel (Inaam, modératrice lablab)

### Démonstration vidéo du PnL obligatoire — 15/05/2026 20:29

> you need to show that in your demo video

(en réponse à djkorou360 demandant comment les juges constatent le PnL)

→ **Implication pour `docs/DEMO_VIDEO_SCRIPT.md`** : la vidéo doit
**explicitement montrer le PnL Kraken** (terminal `kraken
trades-history`, capture Kraken Pro, ou capture du dashboard avec la
source `live`). Ce n'est pas une simple recommandation.

## 3. Témoignages publics d'autres participants

### djkorou360 — fil principal des blocages xStocks (15→18/05/2026)

> **14/05/2026 09:40 :** Is no one working on the kraken trading bot ? 😭

> **16/05/2026 11:34 :** Thank you for the clarification and the trading
> history will be of a 30 day period ? Can you confirm the starting
> date of the countdown please
>
> Also thanks for the tutorial I tried it out and it's pretty good
> added a few things like shorting function to it

> **16/05/2026 17:20 :** @Steve | lablab.ai @Inaam | lablab.ai is it
> not possible to short anything ?
> Is it designed as a spot market my shorting function is running into
> errors and the TSLAx/USD is also returning kraken cli errors I thought
> this would be possible to trade since it was mentioned on the
> hackathon page

> **16/05/2026 18:50 :** im unable to trade xstock stuff and also
> unable to short stuff
> is that disabled?

> **16/05/2026 21:29 :** @Steve | lablab.ai @Inaam | lablab.ai sorry
> for the constant questions can you please confirm whether shorting is
> disabled along with trading xstocks
>
> ```
> kraken paper sell ETH/USD 100 --yes
> Error: Validation error: Insufficient ETH balance. Available: 0.00000000, Required: 100.00000000
> ```
> unable to short
>
> ```
> kraken ticker AAPLx/USD
> Error: EQuery:Unknown asset pair
> ```
> along with invalid asset

> **18/05/2026 10:17 :** (en réponse à Jennycruzy « Does Kraken CLI
> support xStocks for paper trading ? ») **no**

### thisisaman408 — 14/05/2026 20:47

> We'd have to buy kraken api and it's not available in all the
> countries, hah

### Ammar Khalid — 17/05/2026 15:20

> For ai agent Hackathon milan do we need the real money to deposit on
> kraken xstocks or we can do paper trading?

→ Question restée sans réponse officielle au moment de la submission
(18/05/2026 matin).

### Jennycruzy [DeFi] — 18/05/2026 03:21

> Does Kraken CLI support xStocks for paper trading ?

→ Réponse non-officielle (djkorou360 — 18/05/2026 10:17) : « no ».

## 4. Timeline consolidée des blocages reportés publiquement

| Date (CEST) | Participant | Blocage | Citation / sortie verbatim |
|---|---|---|---|
| 14/05 20:47 | thisisaman408 | Disponibilité géographique de l'API Kraken | « not available in all the countries » |
| 16/05 17:20 | djkorou360 | xStocks CLI errors + shorting impossible | « TSLAx/USD is also returning kraken cli errors » |
| 16/05 21:29 | djkorou360 | Short paper bloqué (ETH/USD) | `Insufficient ETH balance. Available: 0.00000000` |
| 16/05 21:29 | djkorou360 | xStocks ticker rejeté | `EQuery:Unknown asset pair` sur `AAPLx/USD` |
| 17/05 15:20 | Ammar Khalid | Confusion paper vs live, dépôt réel exigé ? | Question publique sans réponse officielle |
| 18/05 03:21 | Jennycruzy | Support paper xStocks confirmé ? | Question publique sans réponse officielle |
| 18/05 10:17 | djkorou360 | Synthèse implicite | « no » (paper xStocks non supporté) |

## 5. Ce que ça confirme pour la submission

1. **xStocks est un blocage transverse**, pas spécifique à PEDSL-CY :
   - **djkorou360** reproduit `EQuery:Unknown asset pair` sur
     `kraken ticker AAPLx/USD`. C'est exactement la même famille
     d'erreur que celle observée sur notre paper (`kraken 0.3.2 paper
     buy/sell` ne supporte pas `--asset-class tokenized_asset` — voir
     `AGENTS.md`, ligne sur le paper engine).
   - **thisisaman408** signale publiquement que l'API n'est pas
     disponible dans tous les pays — exactement le pattern PEDSL-CY que
     nous avons documenté (`EGeneral:Permission denied` sur le spot
     xStocks et `wouldNotReducePosition` sur les Perps xStocks pour les
     comptes EU/EEA, voir `docs/SUBMISSION.md` §« Live result on this
     account »).

2. **Aucune réponse officielle** des modérateurs lablab sur le support
   paper xStocks (questions ouvertes de Ammar, Jennycruzy, djkorou360
   restées sans clarification au 18/05 10:30 CEST). Le hackathon a été
   ouvert sans que la couche paper Kraken supporte la classe
   `tokenized_asset` côté CLI.

3. **La règle de l'audit est claire** :
   - **Read-only API key** Kraken obligatoire dans la submission
     (Steve, 16/05 10:00).
   - **Démonstration du PnL dans la vidéo** obligatoire (Inaam,
     15/05 20:29).
   - Mesure sur **30 jours depuis le 13 mai** mais submission fermée
     le 20 mai → la fenêtre opérationnelle effective est de **5 à 7
     jours**, pas 30, pour la quasi-totalité des équipes EU/EEA.

4. **Notre décision d'arrêter le live trading** (option A — finaliser
   la submission avec le PnL existant ≈ −0.55 USD du diagnostic
   crypto) est **cohérente avec la situation publique** :
   - Aucun chemin API-driven n'existe pour exécuter du xStocks sur
     PEDSL-CY (ni spot, ni futures, prouvé contre un contrôle BTC Perp
     OK sur la même clé / IP / compte).
   - Brûler 2 jours de taker fees sur du crypto perp avec une stratégie
     calibrée xStocks (ce qui produit le ratio −1.5 USD/h observé) ne
     contribue pas à la note xStocks et fait perdre de l'argent réel.
   - L'audit jury read-only restera lisible et reproductible (22 fills
     crypto + 0 fill xStocks documenté venue-bloqué).

## 6. Sources et liens

- Discord lablab — channel `#kraken-challenge` (canal hackathon AI
  Agent Olympics).
- lablab landing page : <https://lablab.ai/event/ai-agent-olympics>
  (track *Kraken Challenge*).
- Tutoriel officiel Featherless × Kraken :
  <https://lablab.ai/ai-tutorials/featherless-kraken-multi-model-financial-agent>
- Template GitHub officiel :
  <https://github.com/Stephen-Kimoi/featherless-kraken-agent>
- Notre repo : <https://github.com/Damso74/kraken-alpha-agent>
- Notre dashboard public :
  <https://kraken-alpha-agent-damso74s-projects.vercel.app>
- Diagnostic complet du blocage PEDSL-CY : `docs/SUBMISSION.md`,
  section *« Live result on this account (PEDSL-CY block) »*.

## 7. Avertissement d'intégrité

Aucun message Discord cité ici n'a été reformulé ou paraphrasé : ce
sont des copies caractère pour caractère du canal public. Les seules
modifications visibles sont :

- Reformatage Markdown (gras, blockquotes) pour la lisibilité.
- Suppression d'emoji Discord propriétaires illisibles hors plateforme
  (badge `:man_mage:` du modérateur, badge `Icône de rôle, Moderator`).
- Pas de troncature au sein des citations : chaque message est cité en
  intégralité.

Toute distorsion factuelle dans ce document constituerait un fait
vérifiable contre nous lors de l'audit du jury — d'où le choix
volontaire du verbatim.
