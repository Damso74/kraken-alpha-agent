# Phase 30.2 — Static dashboard

**Date :** 2026-05-21  
**Branche :** `phase30/observation-ops-ux`

## Output

`reports/paper_observation_phase28/dashboard.html`

HTML statique, CSS embarqué, **aucun JS externe ni CDN**.

## Inputs

- `reports/phase29_observation_metrics/summary.json`
- `decisions.jsonl`, `shadow_comparison.jsonl`, `equity_curve.csv` par cible
- `STOP_OBSERVATION`
- Dernier fichier `ops_logs/*.log`

## Sections

1. Status & last run  
2. STOP_OBSERVATION  
3. Data freshness  
4. Target cards (2)  
5. Equity comparison  
6. Overlay behavior  
7. Risk metrics  
8. Recent decisions table  
9. Kill criteria  
10. Next decision verdict  
11. Latest ops log tail  

## Commande

```powershell
python scripts/generate_observation_dashboard_phase30.py
```

Ouvrir localement dans le navigateur ou copier sur le VPS (pas de serveur web requis).
