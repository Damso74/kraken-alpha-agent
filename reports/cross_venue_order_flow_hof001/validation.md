# H-OF-001 — résultat de validation

- Statut : **insufficient_power**
- Nature : **proxy inter-places, non-réplication exacte**
- Semaines exposées : **9**
- PnL net : **504.01 USD**
- Win rate : **66.67 %**
- Test final 2026 scellé : **true**

## Gates

- FAIL — `min_30_trades`
- FAIL — `eligible_exposure_and_state_changes`
- PASS — `positive_pnl`
- PASS — `positive_mean`
- PASS — `win_rate_50pct`
- PASS — `annualized_weekly_sharpe_0_5`
- FAIL — `bootstrap_lower_bound_positive`
- FAIL — `beats_permutation_bonferroni`
- PASS — `positive_at_100bps`
- PASS — `positive_each_year`
- FAIL — `positive_leave_one_quarter_out`
- FAIL — `acceptable_quarter_concentration`
- PASS — `beats_both_single_venue_means`
- PASS — `beats_momentum_and_weekly_long_pnl`
- PASS — `data_quality`

Sortie de recherche uniquement : aucun paper trading, live ou ordre
n'est autorisé par ce résultat, qui n'est pas un conseil financier.
