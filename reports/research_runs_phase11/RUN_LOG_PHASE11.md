# Research runs Phase 11 — RUN_LOG

**Date (UTC):** 2026-05-19  
**Agent:** 29 — Volume shock signal (P9-MS-023)  
**Branch:** `posthackathon/research-lab-phase-3-10`  
**Environment:** Windows 11, PowerShell, `.\.venv\Scripts\Activate.ps1`, `$env:PYTHONIOENCODING='utf-8'`

No `config.yaml` or live profile changes.

---

## P9-MS-023 — Volume shock (all pre-registered variants)

```powershell
python scripts/event_study_volume_shock.py --days 365 --ohlc-source cache --use-cache-only --run-all-variants
```

| Field | Value |
|-------|-------|
| Exit code | **2** (blocked variants present) |
| OHLC | **371** daily candles (`data/collector_cache/ohlc_daily_BTC.json`) |
| Placebos | Bootstrap 200 + shift +30d + shuffle labels (return post_3) |
| Métriques | `return`, `realized_vol`, `max_drawdown` ; fenêtres `post_1/3/7` |

### Variant `vol_z20_high`

| Field | Value |
|-------|-------|
| Events | **18** (4.9 % des candles — OK G2) |
| BH @ FDR 0.05 | **3/8** cellules rejettent H0 |
| Meilleur signal brut | return post_7 mean ≈ −4.35 %, p≈0.01 |
| Shift +30j (return post_3) | p = **1.0** — effet non robuste au décalage |
| Shuffle labels (return post_3) | p = **1.0** |
| Script verdict | `supported` (BH seul) |
| **Research verdict** | **weak evidence** — jamais tradable ; placebos shift/shuffle échouent |

### Variant `vol_z60_high`

| Field | Value |
|-------|-------|
| Events | **16** (4.3 %) |
| BH @ FDR 0.05 | **5/8** |
| Shift / shuffle post_3 | p = **1.0** / **1.0** |
| **Research verdict** | **weak evidence** |

### Variant `vol_z20_range_compression`

| Field | Value |
|-------|-------|
| Events | **0** (volume z≥2 **et** range_compression_20 ≤ −1.0 simultanés) |
| **Research verdict** | **blocked** |

### Variant `vol_z20_low_abs_return`

| Field | Value |
|-------|-------|
| Events | **0** (volume z≥2 **et** return_abs_z_20 ≤ −1.0 simultanés) |
| **Research verdict** | **blocked** |

**Artifact:** `reports/research_runs_phase11/volume_shock_all_365d.json`

**Synthèse Phase 11 :** les chocs de volume journaliers BTC montrent des cellules BH « significatives » sur post_7 (retour négatif moyen), mais les placebos shift +30j et shuffle annulent l’interprétation causale → **weak evidence** au mieux, **blocked** pour les variantes squeeze/quiet. **Aucune promotion OOS / live.**

---

## Code livré

| Path | Rôle |
|------|------|
| `src/signals/volume_shock.py` | Features + 4 variantes d’événements pré-enregistrées |
| `scripts/event_study_volume_shock.py` | Harness event study + placebos étendus |
| `tests/test_signals_volume_shock.py` | Tests unitaires (sans réseau) |
| `docs/NEXT_5_HYPOTHESES.md` | P9-MS-023 marqué implémenté |

---

## Agent 28 — Calendar micro-baselines (5 effets pré-enregistrés)

**Agent:** 28 · **Suite:** calendrier Phase 11 (daily OHLC, pas de grille horaire)

| Effect ID | Definition (fixed) |
|-----------|-------------------|
| `us_market_open_window` | Mon–Fri calendar days, America/New_York |
| `sunday_us_evening` | Sunday calendar day, America/New_York |
| `monday_asia_open` | Monday calendar day, Asia/Tokyo |
| `third_friday` | Third Friday UTC (options expiry proxy) |
| `month_end` | Last UTC calendar day with a candle each month |

**Placebos:** random bootstrap (200 reps), random same-weekday (return/post_7),
shifted calendar +14..+60d (return/post_7).

**Metrics:** `return`, `realized_vol`, `volume_ratio` · overlay `tradeability.py`.

```powershell
python scripts/event_study_calendar.py `
  --micro-baselines `
  --days 730 `
  --ohlc-source cache `
  --use-cache-only `
  --output-json reports/research_runs_phase11/calendar_micro_baselines.json
```

| Effect | Events | BH reject | Net return (post_7) | Verdict |
|--------|--------|-----------|---------------------|---------|
| `us_market_open_window` | 526 | 2/8 | −0.66% | **weak evidence** |
| `sunday_us_evening` | 105 | 0/8 | −0.75% | **weak evidence** |
| `monday_asia_open` | 105 | 2/8 | −0.75% | **weak evidence** |
| `third_friday` | 25 | 0/8 | sous coûts | **weak evidence** |
| `month_end` | 25 | 0/8 | sous coûts | **weak evidence** |

**Run:** 736 daily candles (cache BTC) · seed `20260519` · FDR α=0.05.

**Conservative read:** aucun effet en `candidate for further OOS testing only`.
BH rejette des cellules `volume_ratio` sur `us_market_open_window` et `monday_asia_open`,
mais l’overlay économique (turnover > 30% ou gross < 0,5%) bloque toute promotion.
Retours forward restent sous le seuil suspect et net négatif après coûts pessimistes.

**Artifact:** `reports/research_runs_phase11/calendar_micro_baselines.json`

### Code livré (Agent 28)

| Path | Rôle |
|------|------|
| `src/signals/calendar_effects.py` | 5 builders pré-enregistrés + placebos same-weekday |
| `scripts/event_study_calendar.py` | Mode `--micro-baselines` + overlay économique |
| `tests/test_signals_calendar_effects.py` | Tests unitaires (sans réseau) |
