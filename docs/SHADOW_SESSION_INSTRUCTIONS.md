# Shadow xStocks dry-run sur VPS — manuel d'exploitation

> Pendant la fenêtre hackathon (lablab — AI Agent Olympics — Kraken Trading
> Performance), une session "shadow live" tourne sur le **VPS Vultr Linux**
> en `dry_run` strict pour ~36-40 heures. Elle pollue les vrais marchés
> xStocks avec les signaux du bot, simule l'exécution localement,
> et produit un export JSON pour la submission. **Aucun ordre réel n'est
> jamais envoyé à Kraken.**
>
> Cible : couvrir May 18 ~21:30 CEST → May 20 ~12:00 CEST (deadline lablab).

VPS de référence (cf. `docs/VPS_RUNBOOK.md` et `.env` non-versionné) :

- **IP** : `140.82.12.75` (Vultr `ewr`, Ubuntu 24.04 LTS)
- **Utilisateur** : `root`
- **Repo** : `/root/kraken-alpha-agent`
- **Clef SSH locale** : `~/.ssh/kraken_vps_ed25519`
- **Tmux session name** : `kraken-shadow`
- **Réseau local** : ton FAI bloque TCP/22 — passe sur **hotspot mobile**
  pour tout `ssh` / `scp` (cf. AGENTS.md).

## TL;DR — 3 commandes pour démarrer + monitorer + exporter

À coller depuis **PowerShell local** (laptop), sur **hotspot mobile** :

```powershell
# 1) DEPLOIEMENT + LANCEMENT (lance la session 36-40h sur le VPS dans tmux)
ssh -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 'cd /root/kraken-alpha-agent && git pull origin master && bash -c "tmux has-session -t kraken-shadow 2>/dev/null && tmux kill-session -t kraken-shadow; tmux new-session -d -s kraken-shadow \"bash scripts/run_vps_shadow_xstocks.sh\"" && sleep 2 && tmux ls'

# 2) MONITORING live (depuis n importe ou)
ssh -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 'tail -f /root/kraken-alpha-agent/data/shadow_session.log'

# 3) EXPORT POUR SUBMISSION (à lancer mardi soir / mercredi matin, après stop)
# Voir Section 5 ci-dessous (pull DB + export local + commit).
```

## Pourquoi un shadow run sur VPS ?

Le compte Kraken est sur **PEDSL-CY (Cyprus EU)**. Conséquence vérifiée à
la main le 2026-05-15 :

- **Spot xStocks** : tout `kraken order buy/sell TICKERx/USD --asset-class
  tokenized_asset` retourne `EGeneral:Permission denied`, même un SELL
  d'un token déjà détenu.
- **Futures xStocks Perps** : tout `kraken futures order buy PF_<TICKER>XUSD`
  retourne `status:wouldNotReducePosition`. Confirmé sur HOODx, AAPLx,
  isolated 1x.
- **Crypto Perps de contrôle** : `kraken futures order buy PF_XBTUSD 0.0001`
  remplit immédiatement (`status:placed`), prouvant que la clé/route est
  fonctionnelle. Le blocage est strictement au niveau de la classe de
  compte sur les xStocks.

**Pourquoi le VPS plutôt que la machine Windows locale** :

- Pas de mise en veille Windows, pas de Windows Update qui redémarre.
- Réseau VPS stable, IP allow-listed côté Kraken.
- Kraken CLI 0.3.2 tourne **nativement** sur le VPS (pas de wrapper WSL).
- `tmux` détache la session du terminal qui l'a lancée → on peut couper
  le SSH sans tuer la session.
- Le bot est déjà déployé là-bas, c'est l'environnement de référence.

## Garanties dry_run (defense-in-depth)

Quatre barrières indépendantes empêchent un ordre réel de partir :

1. **Profil verrouillé** : `shadow_xstocks_36h` dans `config.yaml` impose
   `execution.engine: spot`, `trading.mode: dry_run`,
   `futures.enabled: false`.
2. **Variables d'environnement forcées** par `scripts/run_vps_shadow_xstocks.sh`
   au démarrage du tmux : `TRADING_MODE=dry_run`, `LIVE_TRADING=false`,
   `ALLOW_LIVE_ORDERS=false`. Le triple-opt-in du gate live est cassé
   dans 3 directions, **régulièrement** quel que soit le contenu de `.env`.
3. **Court-circuit dans `src/execution.execute()`** : la branche `dry_run`
   retourne un `ExecutionResult(status="dry_run_logged")` AVANT tout
   appel CLI mutant.
4. **Tripwire `_assert_not_dry_run`** dans `src/execution.py` : juste
   avant chaque appel mutant (`kraken_cli.place_order`,
   `kraken_cli.validate_live_order`, `futures_kraken_cli.place_paper_order`,
   `futures_kraken_cli.place_live_order`, `futures_kraken_cli.validate_via_paper`),
   un `assert` lève `DryRunMutationError` si un refactor laisse passer
   un appel `mode == "dry_run"`. Tests dédiés : `tests/test_dry_run_safety.py`.

Les seuls appels Kraken autorisés pendant la session sont **read-only**
(`kraken ticker / ohlc / orderbook / trades / balance`). Les fills
simulés sont écrits dans :

- `data/agent.sqlite` (table `orders`, `mode='dry_run'`,
  `status='dry_run_logged'`)
- `data/decisions.jsonl`, `data/trades.jsonl` (mirroirs JSONL)
- `data/pnl.jsonl` + `pnl_snapshots`

## 1. Démarrer la session sur le VPS

> **NOTE** : l'agent Cursor n'a **pas pu** démarrer la session lui-même
> car `TCP/22` est bloqué depuis ce réseau (cf. AGENTS.md "Local network
> blocks outbound TCP/22 by default"). **Il faut basculer sur hotspot
> mobile** et lancer la commande ci-dessous depuis ta machine.

### Étape 1.1 — Push master local → GitHub

Depuis PowerShell local (la branche est à jour, juste pour confirmer) :

```powershell
git status        # doit etre clean ou ne contenir que les fichiers attendus
git push origin master
```

### Étape 1.2 — Pull + tmux launch sur le VPS

Toujours depuis PowerShell local (sur **hotspot mobile**) :

```powershell
ssh -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 @"
set -e
cd /root/kraken-alpha-agent
git fetch --all
git checkout master
git pull origin master
chmod +x scripts/run_vps_shadow_xstocks.sh
# kill any leftover session, then start a fresh detached tmux
if tmux has-session -t kraken-shadow 2>/dev/null; then
    tmux kill-session -t kraken-shadow
fi
tmux new-session -d -s kraken-shadow 'bash scripts/run_vps_shadow_xstocks.sh'
sleep 3
echo '--- tmux ls ---'
tmux ls
echo '--- last 30 lines of shadow_session.log ---'
tail -30 /root/kraken-alpha-agent/data/shadow_session.log || true
"@
```

Tu devrais voir :

```
--- tmux ls ---
kraken-shadow: 1 windows (created ...) [...]
--- last 30 lines of shadow_session.log ---
============================================================
SHADOW XSTOCKS DRY-RUN - DO NOT SHUT DOWN
...
```

### Étape 1.3 — Vérification 5 minutes après

```powershell
ssh -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 @"
echo '--- tmux state ---'
tmux ls
echo '--- last 50 lines of shadow_session.log ---'
tail -50 /root/kraken-alpha-agent/data/shadow_session.log
echo '--- recent cycles ---'
cd /root/kraken-alpha-agent
.venv/bin/python -c \"
import sqlite3, json
con = sqlite3.connect('file:data/agent.sqlite?mode=ro', uri=True)
cur = con.cursor()
print('cycles by mode (last 30 min):')
for row in cur.execute(\\\"select mode, count(*) from cycles where started_at >= datetime('now','-30 minutes') group by 1\\\"):
    print(' ', row)
print('orders by status/mode (last 30 min):')
for row in cur.execute(\\\"select status, mode, count(*) from orders where at >= datetime('now','-30 minutes') group by 1,2\\\"):
    print(' ', row)
\"
"@
```

Critères d'acceptation :

- `tmux ls` doit lister `kraken-shadow: 1 windows`
- `shadow_session.log` doit afficher au moins 1 ligne `cycle=cyc_XXXX
  mode=dynamic profile=shadow_xstocks_36h universe(5)=...`
- `orders by status/mode` doit montrer **uniquement** `dry_run` ou
  `blocked`/`skipped`. **Aucune** ligne `live` ou `paper` ne doit apparaître
  pour cette session.

## 2. Monitorer pendant la session

### Option A — Live tail du log (le plus simple)

```powershell
ssh -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 'tail -f /root/kraken-alpha-agent/data/shadow_session.log'
```

Ctrl+C dans cette fenêtre **n'arrête pas la session** (tu coupes juste
le tail).

### Option B — Attache tmux (pour voir le terminal du loop)

```powershell
ssh -t -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 'tmux attach -t kraken-shadow'
```

**IMPORTANT** : pour détacher sans tuer, `Ctrl+B` puis `D`. **NE PAS**
faire Ctrl+C — ça arrête la session.

### Option C — Snapshot via le moniteur Python (read-only)

Récupère un snapshot de stats sur le VPS sans ouvrir de tail :

```powershell
ssh -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 @"
cd /root/kraken-alpha-agent
.venv/bin/python scripts/monitor_shadow_session.py --once
"@
```

Le moniteur lit `data/shadow_session.json` et `data/agent.sqlite` en
read-only et affiche : uptime, cycles depuis le démarrage, décisions,
trades simulés, fees, PnL simulé, positions ouvertes, dernière erreur,
distance jusqu'au cutoff (May 20 12:00 CEST).

## 3. Comment NE PAS arrêter la session par erreur

Pièges classiques :

- `tmux kill-session -t kraken-shadow` = **mort immédiate** de la
  session. À n'utiliser **qu'après** Ctrl+C dans la session.
- Reboot du VPS = mort de tmux et de la session. Pas de reboot pendant
  les 36-40h.
- `apt upgrade` qui redémarre un service Python = à éviter, lance plutôt
  `apt-get update && apt-get upgrade -y --no-install-recommends` après
  l'export final.
- Couper le SSH pendant que tu es **attaché** à tmux ne tue pas la
  session (c'est tout l'intérêt de tmux). Tu peux fermer ton laptop, la
  session continue.

## 4. Comment arrêter proprement

À faire mardi soir / mercredi matin avant l'export pour la submission :

```powershell
# Etape 1: send Ctrl+C dans le tmux pour arreter le run_agent_loop python
ssh -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 'tmux send-keys -t kraken-shadow C-c'

# Attendre ~60s que le cycle en cours finisse
Start-Sleep -Seconds 75

# Etape 2: tuer la session tmux (le launcher a deja termine sur exit_code=0)
ssh -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 'tmux kill-session -t kraken-shadow'

# Verifier
ssh -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 'tmux ls 2>&1 | head -5; tail -20 /root/kraken-alpha-agent/data/shadow_session.log'
```

Tu dois voir `[<timestamp>] launcher exit. restart_count=N` dans le log
et `no server running on /tmp/tmux-XXX/default` (ou message équivalent)
pour `tmux ls`.

## 5. Exporter la session pour la submission

Une fois la session arrêtée :

### Étape 5.1 — Pull la DB et le log depuis le VPS

```powershell
# Snapshot de la DB live (en read-only via VACUUM INTO pour eviter d ecrire)
ssh -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75 @"
cd /root/kraken-alpha-agent
mkdir -p export
sqlite3 data/agent.sqlite \"VACUUM INTO 'export/agent_shadow_session.sqlite';\"
cp data/shadow_session.log export/shadow_session.log
cp data/shadow_session.json export/shadow_session.json
ls -la export/
"@

# scp le snapshot vers la machine locale
scp -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75:/root/kraken-alpha-agent/export/agent_shadow_session.sqlite data/agent_shadow_session.sqlite
scp -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75:/root/kraken-alpha-agent/export/shadow_session.log data/shadow_session.log
scp -i $HOME\.ssh\kraken_vps_ed25519 root@140.82.12.75:/root/kraken-alpha-agent/export/shadow_session.json data/shadow_session.json
```

### Étape 5.2 — Run l'exporteur en local

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/export_shadow_session_for_submission.py `
    --db data/agent_shadow_session.sqlite `
    --metadata data/shadow_session.json `
    --update-docs --print-summary
```

L'exporteur :

- Lit `data/shadow_session.json` pour retrouver le `started_at`.
- Lit la DB filtrée par timestamp.
- FIFO-pair les ordres BUY → SELL.
- Génère `web/public/data/shadow_session.json` avec `mode:
  "live_shadow_dry_run"`, métriques, equity curve, trades, errors.
- Splice le bloc `<!-- BEGIN:shadow-session --> ... <!-- END:shadow-session -->`
  dans `README.md` et `docs/SUBMISSION.md`.
- Affiche un résumé ASCII pour la vidéo démo.

### Étape 5.3 — Commit + push pour Vercel auto-redeploy

```powershell
git add web/public/data/shadow_session.json README.md docs/SUBMISSION.md
git commit -m "feat(shadow): live dry-run shadow session results (hackathon window)"
git push origin master
# Vercel redeploye automatiquement la dashboard en ~1min
```

## 6. Si la session crashe pendant la nuit

- Le launcher (`scripts/run_vps_shadow_xstocks.sh`) détecte un exit
  Python non-zéro et relance avec backoff exponentiel `5s → 10s → 20s
  → 40s → ...` capé à 5 min. Tu n'as **rien** à faire.
- Le compteur `restart_count` apparaît dans le log final quand tu fais
  Ctrl+C : il vaut 0 si la session n'a jamais crashé.
- Si tmux meurt (kernel panic, OOM killer, reboot non-prévu) : tu dois
  relancer manuellement (Section 1.2).
- Tous les logs sont dans `/root/kraken-alpha-agent/data/shadow_session.log`.
  L'export agrège l'ensemble depuis le `started_at` initial.

## 7. Fallback Windows local

Au cas où le VPS deviendrait inaccessible (DDoS, panne réseau, etc.),
un launcher PowerShell équivalent existe en local :
`scripts/launch_shadow_xstocks.ps1`. Il fait la même chose mais sur
Windows 11. Caveats : sleep mode, Windows Update, fragilité réseau.
**À n'utiliser qu'en dernier recours**.

## 8. Caveats à mentionner dans la submission

- **xStocks 24/5** : ~80h/semaine de trading. La fenêtre May 18-20 inclut
  lundi soir → mardi → mercredi matin = la plupart du temps en US_CORE.
  Le profil `shadow_xstocks_36h` n'autorise les BUY que pendant US_CORE
  (`allowed_entry_sessions: ["US_CORE"]`).
- **Read-only data** : tous les tickers viennent de `kraken ticker /
  ohlc / orderbook / trades` natif sur le VPS. Aucun calcul off-Kraken.
  C'est ce qui rend la session "live" même en `dry_run`.
- **Pas de slippage simulé** : les fills dry_run utilisent
  `features.last_price` (pas le mid book). Documenté dans
  `docs/METHODOLOGY.md`, appliqué uniformément aux backtests pour
  rester cohérent.
- **Pas d'audit Kraken-side** : puisque rien n'est envoyé, l'audit
  `kraken trades` du jury sera vide pour cette fenêtre. C'est cohérent
  avec le narratif "PEDSL-CY blocked → simulated execution".

## Cheat sheet — fichiers clés

| Path | Rôle |
|---|---|
| `scripts/run_vps_shadow_xstocks.sh` | launcher VPS (tmux, restart-on-crash, force dry_run) |
| `scripts/launch_shadow_xstocks.ps1` | launcher Windows local (fallback) |
| `scripts/monitor_shadow_session.py` | moniteur read-only (local ou via SSH) |
| `scripts/export_shadow_session_for_submission.py` | export final pour submission |
| `data/shadow_session.json` | metadata du run (gitignored) |
| `data/shadow_session.log` | log brut du loop (gitignored) |
| `data/agent.sqlite` | DB persistante (gitignored) |
| `web/public/data/shadow_session.json` | export final (committé) |
| `config.yaml` profil `shadow_xstocks_36h` | profil verrouillé dry_run |
| `tests/test_dry_run_safety.py` | tests du tripwire `_assert_not_dry_run` |
