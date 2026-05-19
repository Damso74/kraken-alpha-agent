# Protocol B — red team report

**Rôle :** Red team (indépendant du builder)

## Findings

1. **Même hypothèse que Protocol A** — OK (JSON identique).  
2. **Placebos** — FAIL : shift et shuffle p=1.0 malgré BH in-sample (même faille Phase 11/12).  
3. **Hold-out** — FAIL : référence `realized_vol/post_7` non significative sur partition test.  
4. **Multi-actif** — WARNING : SOL `blocked_data` ; seulement 2/3 actifs.  
5. **Confusion vol vs trading** — le builder a flirté avec « validation » ; effet porte surtout sur vol/drawdown, pas return tradable net de coûts.  
6. **Red team registry** — `volume_shock_*` → status **fail** dans `red_team_verdicts.json`.

## Verdict red team

**Rétrograder** toute proposition `candidate for OOS` → **`weak evidence`**.

## Required fix

Aucun fix de seuil. Si relance : committee Protocol C + cache SOL optionnel hors commit.
