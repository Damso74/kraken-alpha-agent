# lablab.ai — Texte de submission prêt à coller

> Ce document contient **les chaînes de caractères exactes** à copier
> dans chaque champ du formulaire de submission lablab pour l'événement
> *AI Agent Olympics — Kraken Challenge (Kraken Trading Performance)*.
> Deadline : **20 mai 2026**. Plateforme :
> <https://lablab.ai/event/ai-agent-olympics>.
>
> **À remplir manuellement par l'utilisateur après l'enregistrement de
> la vidéo** : le champ *Submission video URL* (le lien YouTube ou
> Vimeo de la vidéo de démo). Le reste est figé.

## Track / Catégorie

```
AI Agent Olympics → Kraken Challenge (Kraken Trading Performance)
```

## Project name

```
Kraken Alpha Agent
```

(Public alias : *Kraken Sentinel*. Utiliser **Kraken Alpha Agent**
comme nom officiel — c'est celui du repo GitHub et du déploiement
Vercel.)

## Tagline (≤ 140 caractères)

```
Autonomous, fully audited xStocks trading agent on Kraken CLI. Triple opt-in for live, 232/232 tests, public Vercel dashboard.
```

(*139 caractères avec les espaces.*)

## Short description (≤ 280 caractères)

```
Deterministic xStocks trading agent on Kraken CLI: ranked universe, momentum + breakout + mean-reversion ensemble, risk gates with triple live opt-in, SQLite + JSONL audit. Live xStocks blocked at the venue (PEDSL-CY, EU) — documented honestly with Discord evidence.
```

(*278 caractères avec les espaces.*)

## Long description (~ 1500 caractères)

```
Kraken Alpha Agent is an autonomous, transparent, auditable and safe-by-default trading agent for tokenized US equities (xStocks) on Kraken, built for the AI Agent Olympics — Kraken Challenge track on lablab.ai.

The agent polls real xStocks market data via Kraken CLI (`ticker`, `ohlc`, `orderbook`, `trades` with `--asset-class tokenized_asset`), engineers a small feature set per symbol (returns, realised vol, spread, distance from 1h high/low, volume), classifies the market regime, and runs three independent strategies — momentum, breakout, mean-reversion — blended in a liquidity-aware ensemble. An actionability layer downgrades unsafe intents to HOLD (BUY threshold, SELL exit-only, no-shorting default, liquidity dampener) before the risk manager applies allowlist, drawdown, exposure, cooldown and hourly trade caps. Live mode is gated by a triple opt-in (TRADING_MODE=live + LIVE_TRADING=true + ALLOW_LIVE_ORDERS=true). Every decision is persisted to SQLite plus JSONL for full audit; a FastAPI dashboard plus a Next.js Vercel landing page expose the engine to the jury.

Live xStocks PnL on this submission is 0 USD because the user's Kraken account is on PEDSL-CY (Cyprus EU), where both the spot xStocks orderbook AND the xStocks Perpetual Futures are venue-blocked at the account-class layer. The block is reproduced from two IPs and a BTC Perp control on the same key fills cleanly. Other lablab participants report the same xStocks errors publicly on Discord — full evidence in docs/HACKATHON_DISCORD_CONTEXT.md. A 30-day deterministic backtest (138 trades, +33.56 USD, 1.68% max drawdown) anchors the engine's expected behaviour.
```

(*≈ 1 460 caractères avec les espaces. Adapter à la limite exacte du
champ lablab — si le champ est plus court, garder le premier
paragraphe + la dernière phrase sur le block xStocks et le backtest.*)

## Tech stack

```
Python 3.11, FastAPI, Pydantic, SQLite, JSONL, Pytest, Kraken CLI 0.3.2, WSL Ubuntu, Next.js 16 (App Router), Tailwind CSS, Vercel, Vultr (Ubuntu 24.04 LTS), Featherless (OpenAI-compatible LLM explainer, optional).
```

## Tags / Keywords (≤ 10)

```
kraken-cli, xstocks, trading-agent, autonomous-agent, python, fastapi, nextjs, vercel, risk-management, ai-agent-olympics
```

## Team members

```
- Damso74 (sole author) — GitHub: https://github.com/Damso74
```

(*Adapter si l'utilisateur veut ajouter d'autres membres.*)

## Submission video URL

```
TO_FILL_AFTER_RECORDING — YouTube unlisted link (or Vimeo), see docs/DEMO_VIDEO_SCRIPT.md for the storyboard.
```

(*À remplir manuellement après l'enregistrement et l'upload de la
vidéo. Format recommandé : YouTube unlisted ou Vimeo. Durée cible :
3-4 min.*)

## GitHub URL

```
https://github.com/Damso74/kraken-alpha-agent
```

## Demo URL (live deployment)

```
https://kraken-alpha-agent-damso74s-projects.vercel.app
```

## Read-only API key handover note (à inclure si un champ "comments / notes for judges" existe)

```
The Kraken read-only API key (Spot + Futures) and the audit-window timestamps will be sent to the Kraken/lablab jury via direct message on the lablab platform, per the protocol in docs/JURY_ACCESS_TEMPLATE.md.

Permissions on that key: Query Funds, Query Open/Closed Orders & Trades, Query Ledger Entries, Query Positions (Futures), Query Fills (Futures). Place Orders / Cancel Orders / Withdraw / Transfer are DISABLED. The key is rotated immediately after the jury confirms the audit is complete.

Expected audit content (13/05 → 18/05/2026 window):
- ZERO xStocks fills (spot AND Perps blocked at venue layer on PEDSL-CY)
- ~22 crypto Perps fills (LTC / ETH / SOL / AVAX / XBT) from a 19-minute diagnostic session, ≈ −0.55 USD aggregate PnL — documented as out-of-track in docs/SUBMISSION.md.
- Local SQLite + JSONL audit logs available on request.
```

## Inspirations / Built with

```
- Kraken CLI (krakenfx/kraken-cli) — primary execution layer
- Featherless AI tutorial template (Stephen-Kimoi/featherless-kraken-agent) — reference architecture
- lablab.ai AI Agent Olympics community — Discord channel #kraken-challenge for venue-block reproduction
```

## Hackathon-specific fields (à vérifier sur la page lablab au moment de soumettre)

| Champ probable | Valeur à coller |
|---|---|
| Event / Hackathon | `AI Agent Olympics` |
| Track | `Kraken Challenge (Kraken Trading Performance)` |
| Open-source ? | `Yes — MIT license` |
| Live URL / Deployment ? | `https://kraken-alpha-agent-damso74s-projects.vercel.app` |
| Source code URL ? | `https://github.com/Damso74/kraken-alpha-agent` |
| Pitch deck ? | `N/A — see docs/SUBMISSION.md` |
| Region restrictions ? | `EU/EEA Kraken accounts cannot trade xStocks (spot or Perps) at the venue layer — documented in docs/HACKATHON_DISCORD_CONTEXT.md` |

## Checklist finale avant de cliquer "Submit"

- [ ] Vidéo enregistrée (3-4 min, scénario : `docs/DEMO_VIDEO_SCRIPT.md`).
- [ ] Vidéo uploadée sur YouTube (unlisted) ou Vimeo.
- [ ] URL de la vidéo collée dans le champ *Submission video URL*.
- [ ] Repo GitHub public (vérifier sur
      <https://github.com/Damso74/kraken-alpha-agent>).
- [ ] Vercel deployment reachable
      (<https://kraken-alpha-agent-damso74s-projects.vercel.app>).
- [ ] Clé API Kraken read-only **créée dans Kraken Pro** avec les
      permissions listées dans `docs/JURY_ACCESS_TEMPLATE.md`.
- [ ] Clé API Kraken read-only **envoyée au jury via lablab DM**
      (jamais sur Discord public, jamais dans Git).
- [ ] Commit final poussé sur `master`
      (`git log --oneline -1` vérifié).
- [ ] `pytest` toujours green localement (**232 / 232**).

## Notes pour l'utilisateur

- Le champ *Submission video URL* est le seul à modifier après cette
  préparation — tous les autres sont stables.
- Si lablab impose une limite de caractères plus stricte que prévu
  sur un champ donné, raccourcir en priorité la *Long description*
  (garder le premier paragraphe + la phrase finale sur le block
  PEDSL-CY) — c'est le champ le plus élastique.
- Ne pas paster d'emojis dans les champs lablab (compatibilité
  unicode imparfaite sur certains navigateurs jury).
- Conserver une copie locale de ce fichier pendant la submission —
  c'est la *source de vérité* pour le texte effectivement soumis.
