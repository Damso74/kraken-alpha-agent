# H-QH-001 — validation

- Statut : **not_supported**
- Symbole : **PF_XBTUSD**
- Trades : **742**
- PnL net à 20 bps : **-1558.75 USD**
- Win rate : **43.94 %**
- Borne bootstrap : **-0.002969415202370975**
- p placebo : **0.32893421315736854**
- Seuil familial : **0.01666667**
- Test final 2026 scellé : **true**

## Gates

- PASS — `min_300_trades`
- FAIL — `positive_pnl`
- FAIL — `positive_mean`
- FAIL — `win_rate_50pct`
- FAIL — `bootstrap_lower_bound_positive`
- FAIL — `beats_matched_off_quarter_placebo`
- FAIL — `positive_at_40bps`
- FAIL — `both_time_halves_positive`
- FAIL — `positive_without_best_month`
- PASS — `acceptable_concentration`
- PASS — `data_quality`

Sortie de recherche uniquement. Aucun ordre paper/live n'est autorisé.
