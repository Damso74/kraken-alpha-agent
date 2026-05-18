# Script vidéo de démo — Kraken Alpha Agent

> **Cible** : 3 à 4 minutes, vidéo de submission lablab pour le track
> **AI Agent Olympics → Kraken Challenge (Kraken Trading
> Performance)**. La modératrice lablab **Inaam** a explicitement
> confirmé (Discord, 15/05/2026 20:29) : *« you need to show that [le
> PnL] in your demo video »*. Cette vidéo doit donc montrer le PnL
> réel sur Kraken (clé read-only), pas seulement le dashboard.
>
> Le script est rédigé en français (préférence utilisateur) ; le texte
> narré est en anglais pour matcher le public lablab international —
> les **didascalies** (italique + crochets) restent en français.

## Préflight — à exécuter une fois avant l'enregistrement

```powershell
# 1. Activer le venv et vérifier que tout est vert
.venv\Scripts\Activate.ps1
pytest                                          # attendu: 232/232 en ~5s

# 2. Snapshot du ranking et d'un cycle dry_run
python scripts/rank_xstocks.py --top 8
python scripts/dry_run_once.py

# 3. Lancer le dashboard FastAPI local (terminal dédié)
uvicorn src.dashboard.app:app --reload

# 4. Vérifier que le dashboard Vercel répond
#   https://kraken-alpha-agent-damso74s-projects.vercel.app
```

Onglets navigateur à pré-ouvrir, dans l'ordre :

1. **Dashboard Vercel** (la "vitrine" du projet, jury-friendly).
2. **GitHub repo** (page README, branch `master`).
3. **FastAPI dashboard local** `http://127.0.0.1:8000/` (preuve que
   le moteur tourne en local).
4. **Kraken Pro** — page *Trade history* (filtrée sur la fenêtre
   13-18 mai 2026) + page *API* (montre les permissions de la clé
   read-only à transmettre au jury).

Fenêtres terminal à pré-ouvrir :

- **T1** : éditeur sur `data/decisions.jsonl` (preuve d'audit row-level).
- **T2** : terminal PowerShell, prêt à enchaîner
  `pytest`, `python scripts/dry_run_once.py`, et
  `wsl -- bash -lc "kraken trades-history -o json | head -40"`.
- **T3** : éditeur sur `docs/HACKATHON_DISCORD_CONTEXT.md` (preuve
  écrite du blocage transverse).

## Storyboard (3 min 45 s cible — total flexible 3:30 à 4:00)

### Scène 1 — Accroche (0:00 → 0:15) — 15 s

- **À l'écran** : dashboard Vercel
  (<https://kraken-alpha-agent-damso74s-projects.vercel.app>) en plein
  écran. Curseur survole la carte « 30-day backtest +33.56 USD ».
- **Narration (EN, ~38 mots)** :
  > "Kraken Alpha Agent — an autonomous, fully audited xStocks
  > trading agent for the lablab Kraken Challenge. Two hundred and
  > thirty-two tests green, a live Vercel dashboard, a thirty-day
  > backtest with a hundred and thirty-eight trades. Let me show you
  > what's under the hood — and the honest blocker that capped our
  > live PnL."

### Scène 2 — Architecture en 30 s (0:15 → 0:45) — 30 s

- **À l'écran** : section *System architecture* du dashboard Vercel
  (le SVG livré dans le commit `3386dc5`) → puis bascule rapide sur
  l'arbre `src/` dans VS Code.
- **Narration (EN, ~70 mots)** :
  > "The agent reads real Kraken xStocks market data — ticker, OHLC,
  > orderbook, trades — engineers features, classifies the market
  > regime, and runs three independent strategies: momentum,
  > breakout, mean-reversion. Their votes are blended in a
  > liquidity-aware ensemble. An actionability layer downgrades
  > unsafe intents to HOLD. Then a single risk gate enforces
  > drawdown, exposure, cooldown, and the live triple opt-in. Every
  > decision is persisted to SQLite plus JSONL."
- **Cue éditeur** : highlight `src/strategies/ensemble.py` puis
  `src/risk.py` (1 seconde chacun).

### Scène 3 — Tests + dry_run en live (0:45 → 1:15) — 30 s

- **À l'écran** : terminal T2. Enchaîner :

  ```powershell
  pytest -q
  # attendu: 232 passed
  python scripts/dry_run_once.py
  ```

- **Narration (EN, ~65 mots)** :
  > "Two hundred and thirty-two tests cover the parser whitelist,
  > the risk gates, the futures wrapper, the exit-action exposure
  > carve-out, every flatten path, every shorting block. The
  > deterministic mock CLI means the suite runs in five seconds on
  > any machine. One `dry_run_once` here on screen — full cycle, no
  > order leaves the process — gives you the exact decision log
  > format the audit pipeline persists."
- **Cue éditeur (1 s overlay)** : montrer un row de
  `data/decisions.jsonl` à l'écran.

### Scène 4 — Backtest 30 jours (1:15 → 1:45) — 30 s

- **À l'écran** : carte *30-day backtest* du dashboard Vercel.
  Curseur survole le top 3 par symbole (`CRCLx`, `HOODx`,
  `NVDAx`). Bascule sur les onglets *15d / 30m* et *7d / 15m* pour
  montrer les trois résolutions.
- **Narration (EN, ~65 mots)** :
  > "Because the live xStocks venue is blocked on this account —
  > more on that in a second — the engine is audited on a
  > deterministic backtest. Thirty days, sixty-minute bars, nine
  > ranked xStocks: a hundred and thirty-eight trades, fifty-three
  > percent win rate, plus thirty-three dollars net PnL, max
  > drawdown one point seven percent. CRCLx and HOODx carry the
  > book — exactly the symbols our ranking pass surfaces."

### Scène 5 — Le moment honnêteté (1:45 → 2:30) — **45 s — clé**

> **Pourquoi cette scène existe** : Inaam a confirmé que le PnL doit
> être montré dans la vidéo. Notre PnL live xStocks = 0 (venue
> bloqué). On le dit, on le prouve, on le contextualise — c'est ce
> qui fait la différence entre une submission opaque et une
> submission auditée.

- **À l'écran (segments)** :
  1. **(1:45 → 1:58)** Kraken Pro → *Trade page* sur
     `/app/trade/AAPLx-usd` qui silencieusement redirige sur
     `BTC/USD` (preuve UI directe du blocage).
  2. **(1:58 → 2:08)** Terminal T2 — sortie réelle :

     ```
     kraken order buy AAPLx/USD 0.01 --asset-class tokenized_asset --type market
     Error: EGeneral:Permission denied
     ```

     puis :

     ```
     kraken futures order buy PF_HOODXUSD 1 --type market --leverage 1
     {"result":"success","status":"wouldNotReducePosition"}
     ```

  3. **(2:08 → 2:20)** Bascule sur
     `docs/HACKATHON_DISCORD_CONTEXT.md` — scroller sur les
     citations verbatim de `djkorou360` et `thisisaman408`
     (« TSLAx/USD is also returning kraken cli errors »,
     « Kraken API not available in all countries »).
  4. **(2:20 → 2:30)** Terminal T2 :

     ```powershell
     wsl -- bash -lc "kraken trades-history -o json | head -40"
     ```

     Montrer les 22 fills crypto (LTC / ETH / SOL / AVAX / BTC).

- **Narration (EN, ~110 mots, débit posé)** :
  > "Now the honest part. My Kraken account is on PEDSL-CY — Cyprus
  > EU. The spot xStocks orderbook returns 'Permission denied' on
  > buy *and* on sell of an owned token, even from two distinct IPs.
  > The xStocks Perps futures return 'wouldNotReducePosition' on
  > every open order — while a BTC Perp control on the same key
  > fills cleanly. I'm not the only one: on the lablab Discord,
  > djkorou360 reports the exact same xStocks ticker error,
  > thisisaman408 says outright that the API is not available in all
  > countries. So my live xStocks PnL is zero, by venue, not by bug.
  > The minus fifty-five cents you see in trade history are
  > twenty-two crypto fills — a controlled diagnostic that the rest
  > of the engine works end to end on a real Kraken venue."

### Scène 6 — Audit & repro (2:30 → 3:15) — 45 s

- **À l'écran** :
  1. Kraken Pro → page *API* avec les permissions de la clé
     read-only qui sera transmise au jury (Query Funds, Query Open
     & Closed Orders & Trades activés ; Place Orders / Withdraw
     DÉSACTIVÉS). **Flouter** la valeur de la clé.
  2. `docs/JURY_ACCESS_TEMPLATE.md` — scroll sur la table des
     permissions et sur la séquence
     `kraken balance / trades-history / futures fills`.
  3. `docs/SUBMISSION.md` — section *Submission checklist*.

- **Narration (EN, ~95 mots)** :
  > "The submission packet is jury-auditable end to end. The
  > read-only Kraken API key — Query Funds, Query Orders & Trades,
  > everything else disabled — is shared with the jury via lablab
  > DM and never committed. Three commands give the jury access to
  > the full account state: `kraken balance`, `kraken
  > trades-history`, `kraken futures fills`. Local audit logs in
  > SQLite plus JSONL plus a secret-redacted export bundle make
  > every decision, every order, every cancel cross-checkable. The
  > full submission narrative — repo, dashboard, Discord evidence,
  > backtest — is one click away from the README."

### Scène 7 — Take-home (3:15 → 3:45) — 30 s

- **À l'écran** : dashboard Vercel — vue d'ensemble avec les KPI
  cards. Curseur termine sur l'URL GitHub.
- **Narration (EN, ~70 mots)** :
  > "Take-home: an engine that's correct end to end, audited with
  > two hundred and thirty-two tests, with a deterministic
  > thirty-day backtest and a transparent live PnL line. The
  > xStocks block is a hackathon-wide regulatory issue documented in
  > the Discord. If you give me one unrestricted week of live
  > xStocks trading on a non-EU account, the roadmap is in the
  > submission doc — but every safeguard described here, including
  > the triple opt-in and the leverage cap, ships in production
  > already. Thanks, Kraken. Thanks, lablab."

## Conseils de tournage

- **Format** : 1920×1080, 30 fps, capture full-screen avec scaling
  100 % côté Windows (sinon le texte des terminaux paraît floue
  après compression Discord/YouTube).
- **Audio** : enregistrement séparé (Audacity ou même téléphone) à
  −12 dBFS moyen. Couper les blancs entre scènes en montage.
- **Censure visuelle** : sur tout screenshot Kraken Pro montrant
  un identifiant de clé API, un wallet ou une balance précise,
  appliquer un floutage rectangulaire en post-prod. Le seul
  identifiant à laisser visible est le **last-4** du UUID de
  compte (utile pour le jury et déjà documenté dans
  `JURY_ACCESS_TEMPLATE.md`).
- **Variantes courtes** :
  - 90 s "social cut" : scènes 1 + 4 + 5 + 7 uniquement.
  - 15 s "teaser" : narration de la backup pitch dans `DEMO_SCRIPT.md`.

## Take-home summary à imprimer sous la vidéo (description YouTube/lablab)

```
Kraken Alpha Agent — Kraken Challenge submission (AI Agent Olympics, lablab.ai)

→ Repo: https://github.com/Damso74/kraken-alpha-agent
→ Dashboard: https://kraken-alpha-agent-damso74s-projects.vercel.app
→ Backtest: 30 days, 138 trades, +33.56 USD, 1.68% max DD
→ Live xStocks PnL: 0 USD (venue-blocked on PEDSL-CY — see docs/HACKATHON_DISCORD_CONTEXT.md)
→ Live crypto diagnostic: -0.55 USD on 22 fills (engine end-to-end validation, out-of-track)
→ Read-only Kraken API key delivered via lablab DM (see docs/JURY_ACCESS_TEMPLATE.md)

Tests: 232/232 green. Default mode: dry_run. Triple opt-in required for live.
```

## Notes pour l'enregistrement final

- Faire **deux prises minimum** de la scène 5 ("honesty moment") : la
  diction y compte autant que le contenu.
- Tester l'enchaînement Discord → terminal → Kraken Pro à vide
  **avant** de lancer l'audio — c'est là que tout dérape en pratique.
- Si Kraken Pro met du temps à charger la page *Trade history*,
  pré-charger l'onglet et figer la fenêtre 30 secondes avant le go
  (le rate-limit n'est pas un sujet ici car la clé est read-only).
- Garder une copie locale de la vidéo en `.mkv` (lossless) en plus du
  rendu compressé `.mp4` qui sera uploadé.
