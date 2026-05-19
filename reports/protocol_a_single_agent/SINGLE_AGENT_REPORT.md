# Protocol A — single-agent report

**Agent :** 46 (simulation single-agent)  
**Artifact :** `reports/research_runs_phase13/volume_shock_protocol_a_365d.json`

## Verdict global

**`weak_evidence_only`** — aucune promotion OOS. Hypothèse traitée comme **proxy volatilité / risque**, pas signal directionnel.

## Résultats par actif (variantes actives)

| Asset | Variante | Events | BH rej. | Placebos shift/shuffle | Hold-out | Verdict |
|-------|----------|--------|---------|------------------------|----------|---------|
| BTC | vol_z20_high | 18 | 3/8 | p=1.0 / p=1.0 | failed | weak evidence |
| BTC | vol_z60_high | 16 | 5/8 | p=1.0 / p=1.0 | failed | weak evidence |
| ETH | vol_z20_high | 23 | 2/8 | non passés | failed | weak evidence |
| ETH | vol_z60_high | 15 | 3/8 | non passés | failed | weak evidence |
| SOL | — | — | — | — | — | **blocked_data** |

Variantes `vol_z20_range_compression` et `vol_z20_low_abs_return` : **blocked** ou sous-puissantes (0–1 evt).

## Interprétation (honnête)

- Quelques rejets BH sur **return** et **realized_vol post_7** répliquent Phase 11 sur BTC.  
- Placebos alignés **post_7** ne confirment pas (p≈1) → pas de robustesse.  
- Hold-out G4 (50 % queue) **échoue** sur les cellules vol de référence → pas OOS.  
- Multi-actif **partiel** (pas de SOL) → pas de claim « universel crypto ».

## Prochaine action

Archiver comme contrôle méthodologique ; Phase 14 : protocole B ou C pour hypothèses data-heavy ; peupler cache SOL hors git si extension souhaitée.
