# H-DV-001 — résultat de validation

- Statut : **insufficient_power**
- Nature : **proxy DVOL exploratoire, non-réplication**
- Trades validation : **11**
- PnL net validation : **161.60 USD**
- Win rate : **45.45 %**
- Test final 2026 scellé : **true**

## Gates

- FAIL — `min_30_trades`
- PASS — `positive_pnl`
- PASS — `positive_mean`
- FAIL — `win_rate_50pct`
- FAIL — `bootstrap_lower_bound_positive`
- FAIL — `beats_matched_placebo_bonferroni`
- PASS — `positive_at_100bps`
- FAIL — `positive_each_year`
- FAIL — `positive_leave_one_quarter_out`
- FAIL — `acceptable_quarter_concentration`
- PASS — `data_quality`

Ce rapport est une sortie de recherche. Il n'autorise ni paper trading,
ni live, ni ordre et ne constitue pas un conseil financier.
